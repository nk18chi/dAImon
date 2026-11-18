"""The catalog: dAImon's catalog/ plus each pack's daemons/, the installed list,
ejected copies in daemons/, `daimon add` / `remove`, `daimon init`'s choice, and
the migration of an install from before the catalog."""

import io
import os
import sys
import tempfile
import textwrap
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT))
import config  # noqa: E402
import migrate  # noqa: E402
from daimon import catalog, init  # noqa: E402


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip("\n"))
    return path


def make_daemon(folder: Path, slug: str, inputs: str = 'q = "base"') -> Path:
    write(
        folder / "daemon.toml",
        f'[daemon]\nschedule = {{ interval = 600 }}\ncommand = "/{slug}"\n[inputs]\n{inputs}\n',
    )
    write(folder / "skill" / "SKILL.md", f"---\nname: {slug}\ndescription: {slug} does it\n---\n")
    return folder


class CatalogBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.root, self.pack, self.home = base / "install", base / "team", base / "home"
        for slug in ("alpha", "beta", "gamma"):
            make_daemon(self.root / "catalog" / slug, slug)
        make_daemon(self.pack / "daemons" / "report", "report")
        self.conf = self.home / ".config" / "daimon" / "daimon.toml"
        self.write_config("")
        env = {"DAIMON_CONFIG": str(self.conf), "HOME": str(self.home)}
        self.env = patch.dict(os.environ, env)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def write_config(self, daemons: str):
        write(
            self.conf,
            f'# mine\n[core]\ninstall_root = "{self.root}"\nstate_dir = "{self.root}/state"\n\n'
            f"[daemons]\n{daemons}\n\n"
            f'[packs]\n# the team\npaths = ["{self.pack}"]\n',
        )

    def cfg(self):
        return config.Config.load()

    def daemons_key(self, key: str):
        return tomllib.loads(self.conf.read_text())["daemons"].get(key)


class ResolutionTest(CatalogBase):
    def test_catalog_lists_every_slug_with_its_source(self):
        cat = self.cfg().catalog()
        self.assertEqual(list(cat), ["alpha", "beta", "gamma", "report"])
        self.assertEqual(cat["alpha"]["source"], "dAImon")
        self.assertEqual(cat["report"]["source"], "team")
        self.assertEqual(cat["report"]["path"], self.pack / "daemons" / "report")

    def test_no_installed_key_means_every_catalog_daemon_minus_disabled(self):
        self.write_config('disabled = ["beta"]')
        cfg = self.cfg()
        self.assertIsNone(cfg.installed_list)
        self.assertEqual(cfg.installed(), ["alpha", "gamma", "report"])
        self.assertEqual(list(cfg.discover()), ["alpha", "gamma", "report"])

    def test_installed_key_is_the_active_set(self):
        self.write_config('installed = ["report", "alpha"]')
        self.assertEqual(list(self.cfg().discover()), ["alpha", "report"])

    def test_an_empty_installed_list_runs_nothing_and_is_valid(self):
        self.write_config("installed = []")
        cfg = self.cfg()
        self.assertEqual(cfg.discover(), {})
        self.assertEqual(config.validate(cfg), [])

    def test_ejected_copies_are_active_and_take_precedence(self):
        self.write_config('installed = ["alpha"]')
        mine = make_daemon(self.root / "daemons" / "beta", "beta", 'q = "mine"')
        private = make_daemon(self.root / "daemons" / "solo.local", "solo")
        cfg = self.cfg()
        self.assertEqual(list(cfg.discover()), ["alpha", "beta", "solo"])
        self.assertEqual(cfg.daemon_dir("beta"), mine)
        self.assertEqual(cfg.daemon_dir("solo"), private)
        self.assertEqual(cfg.daemon("beta")["inputs"]["q"], "mine")
        self.assertEqual(config.validate(cfg), [])

    def test_disabled_beats_installed_and_ejected(self):
        make_daemon(self.root / "daemons" / "beta", "beta")
        self.write_config('installed = ["alpha"]\ndisabled = ["alpha", "beta"]')
        self.assertEqual(self.cfg().discover(), {})

    def test_a_folder_left_behind_without_daemon_toml_is_not_a_daemon(self):
        write(self.root / "daemons" / "alpha" / "daemon.local.toml", '[inputs]\nq = "old"\n')
        cfg = self.cfg()
        self.assertEqual(cfg.ejected_locations(), {})
        self.assertEqual(cfg.daemon_dir("alpha"), self.root / "catalog" / "alpha")

    def test_update_window_reads_settings_left_in_the_old_daemon_folder(self):
        # After the git merge, before `daimon migrate`: the gitignored
        # daemons/alpha/daemon.local.toml is still there and still counts.
        write(self.root / "daemons" / "alpha" / "daemon.local.toml", '[inputs]\nq = "old"\n')
        self.assertEqual(self.cfg().daemon("alpha")["inputs"]["q"], "old")
        write(self.home / ".config" / "daimon" / "daemons" / "alpha.toml", '[inputs]\nq = "new"\n')
        self.assertEqual(self.cfg().daemon("alpha")["inputs"]["q"], "new")


class ValidationTest(CatalogBase):
    def errors(self) -> list[str]:
        return config.validate(self.cfg())

    def test_an_installed_slug_no_catalog_has_is_an_error(self):
        self.write_config('installed = ["alpha", "ghost"]')
        self.assertTrue(any("installed: ghost is in no catalog" in e for e in self.errors()))

    def test_a_slug_in_two_catalogs_is_an_error(self):
        make_daemon(self.pack / "daemons" / "alpha", "alpha")
        self.assertTrue(any(e.startswith("alpha: defined twice") for e in self.errors()))

    def test_an_ejected_copy_settles_a_duplicate(self):
        make_daemon(self.pack / "daemons" / "alpha", "alpha")
        make_daemon(self.root / "daemons" / "alpha", "alpha")
        self.assertEqual(self.errors(), [])

    def test_disabled_must_name_a_known_daemon(self):
        self.write_config('disabled = ["ghost"]')
        self.assertIn("[daemons].disabled references unknown daemon: ghost", self.errors())


class SlackCommandsDirsTest(CatalogBase):
    def setUp(self):
        super().setUp()
        make_daemon(
            self.root / "catalog" / "cmds",
            "cmds",
            'commands_dir = "catalog/cmds/commands"\nlocal_commands_dir = ""\npack_commands_dirs = []',
        )

    def test_local_runbooks_default_to_the_personal_dir(self):
        inputs = self.cfg().daemon("cmds")["inputs"]
        self.assertEqual(inputs["local_commands_dir"], str(self.conf.parent / "commands"))
        self.assertEqual(inputs["pack_commands_dirs"], [])

    def test_unmigrated_runbooks_in_the_old_folder_are_still_read(self):
        old = write(self.root / "daemons" / "slack-commands" / "commands.local" / "x.md", "x")
        inputs = self.cfg().daemon("cmds")["inputs"]
        self.assertEqual(inputs["pack_commands_dirs"], [str(old.parent)])


class AddRemoveTest(CatalogBase):
    def run_cmd(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with (
            patch.object(catalog, "_sync", return_value=True),
            redirect_stdout(out),
            redirect_stderr(out),
        ):
            rc = catalog.main(list(argv))
        return rc, out.getvalue()

    def test_add_appends_to_installed_keeping_comments_and_settings(self):
        self.write_config('installed = ["alpha"]')
        rc, out = self.run_cmd("add", "report", "alpha")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.daemons_key("installed"), ["alpha", "report"])
        text = self.conf.read_text()
        self.assertIn("# mine", text)
        self.assertIn("# the team", text)
        self.assertIn("register with `daimon tui` → r", out)

    def test_add_without_installed_key_starts_from_the_legacy_set(self):
        self.write_config('disabled = ["beta", "gamma"]')
        self.run_cmd("add", "gamma")
        self.assertEqual(self.daemons_key("installed"), ["alpha", "report", "gamma"])
        self.assertEqual(self.daemons_key("disabled"), ["beta"])

    def test_add_scaffolds_personal_settings_from_the_example(self):
        self.write_config("installed = []")
        write(self.root / "catalog" / "beta" / "daemon.local.toml.example", "[inputs]\nq = 'ex'\n")
        personal = self.home / ".config" / "daimon" / "daemons" / "beta.toml"
        self.run_cmd("add", "beta")
        self.assertEqual(personal.read_text(), "[inputs]\nq = 'ex'\n")
        personal.write_text("# edited\n")
        self.run_cmd("add", "beta")
        self.assertEqual(personal.read_text(), "# edited\n")

    def test_add_rejects_a_slug_no_catalog_has(self):
        self.write_config("installed = []")
        rc, out = self.run_cmd("add", "ghost")
        self.assertEqual(rc, 1)
        self.assertIn("ghost", out)
        self.assertEqual(self.daemons_key("installed"), [])

    def plist(self, slug: str) -> Path:
        return write(self.home / "Library" / "LaunchAgents" / f"com.daimon.{slug}.plist", "x")

    def test_remove_unregisters_an_unloaded_daemon_and_keeps_personal_settings(self):
        self.write_config('installed = ["alpha", "beta"]')
        plist = self.plist("alpha")
        personal = write(self.home / ".config" / "daimon" / "daemons" / "alpha.toml", "# me\n")
        not_loaded = catalog.subprocess.CompletedProcess([], 113, "", "")
        with patch.object(catalog, "_launchctl", return_value=not_loaded) as lc:
            rc, _ = self.run_cmd("remove", "alpha")
        self.assertEqual(rc, 0)
        self.assertFalse(plist.exists())
        self.assertTrue(personal.exists())
        self.assertEqual(self.daemons_key("installed"), ["beta"])
        self.assertNotIn("bootout", [c.args[0] for c in lc.call_args_list])

    def test_remove_of_a_loaded_daemon_needs_confirmation(self):
        self.write_config('installed = ["alpha"]')
        plist = self.plist("alpha")
        loaded = catalog.subprocess.CompletedProcess([], 0, "state = waiting", "")
        with patch.object(catalog, "_launchctl", return_value=loaded) as lc:
            rc, out = self.run_cmd("remove", "alpha")  # stdin is not a terminal
            self.assertEqual(rc, 1)
            self.assertIn("--yes", out)
            self.assertTrue(plist.exists())
            self.assertEqual(self.daemons_key("installed"), ["alpha"])
            rc, _ = self.run_cmd("remove", "--yes", "alpha")
        self.assertEqual(rc, 0)
        self.assertFalse(plist.exists())
        self.assertIn(
            ("bootout", f"gui/{os.getuid()}/com.daimon.alpha"),
            [c.args for c in lc.call_args_list],
        )
        self.assertEqual(self.daemons_key("installed"), [])

    def test_catalog_lists_source_and_state(self):
        self.write_config('installed = ["alpha"]\ndisabled = ["alpha"]')
        make_daemon(self.root / "daemons" / "gamma", "gamma")
        rows = {r[0]: r[1:] for r in catalog.rows(self.cfg())}
        self.assertEqual(rows["alpha"], ("dAImon", "installed, disabled", "alpha does it"))
        self.assertEqual(rows["gamma"], ("dAImon", "ejected", "gamma does it"))
        self.assertEqual(rows["report"], ("team", "-", "report does it"))
        rc, out = self.run_cmd("list")
        self.assertEqual(rc, 0)
        self.assertIn("report", out)


class InitChoosesFromTheCatalogTest(CatalogBase):
    def run_init(self, argv: list[str], stdin=None) -> str:
        out = io.StringIO()
        with (
            patch.object(init, "INSTALL_ROOT", self.root),
            patch.object(init, "_import_config", return_value=config),
            patch.object(init.sys, "stdin", stdin or io.StringIO()),
            redirect_stdout(out),
        ):
            self.assertEqual(init.main(argv), 0)
        return out.getvalue()

    def test_slugs_given_become_installed_and_leave_disabled(self):
        self.write_config('installed = ["alpha"]\ndisabled = ["report", "beta"]')
        self.run_init(["report", "gamma"])
        self.assertEqual(self.daemons_key("installed"), ["report", "gamma"])
        self.assertEqual(self.daemons_key("disabled"), ["beta"])
        self.assertIn("# the team", self.conf.read_text())

    def test_non_interactive_without_slugs_keeps_installed(self):
        self.write_config('installed = ["beta"]')
        self.run_init([])
        self.assertEqual(self.daemons_key("installed"), ["beta"])

    def test_interactive_multi_select(self):
        self.write_config('installed = ["alpha"]')
        tty = io.StringIO()
        tty.isatty = lambda: True  # type: ignore[method-assign]
        with patch("builtins.input", side_effect=["2 report", ""]):
            out = self.run_init([], tty)
        self.assertIn("● alpha", out)
        self.assertEqual(self.daemons_key("installed"), ["beta", "report"])


class MigrateLegacyTreeTest(CatalogBase):
    """An install from before the catalog, right after the git merge that moved
    daemons/ to catalog/: no `installed` key, gitignored files left behind."""

    def setUp(self):
        super().setUp()
        self.write_config('disabled = ["gamma"]')
        self.old = self.root / "daemons"
        write(self.old / "alpha" / "daemon.local.toml", '# mine\n[inputs]\nq = "legacy"\n')
        write(self.old / "beta" / "daemon.local.toml", "# moved to /x by daimon migrate\n")
        write(self.old / "beta" / "__pycache__" / "m.pyc", "")
        write(self.old / "slack-commands" / "commands.local" / "deploy.md", "deploy")
        write(self.old / "keep" / "notes.txt", "mine")
        make_daemon(self.old / "secret.local", "secret")

    def effective(self) -> dict:
        cfg = self.cfg()
        return {s: (cfg.daemon(s), config.render_skill(cfg, s)) for s in cfg.discover()}

    def test_migration_writes_todays_active_set_and_changes_nothing_that_runs(self):
        before = self.effective()
        self.assertEqual(list(before), ["alpha", "beta", "secret", "report"])
        lines = migrate.migrate(self.cfg())
        self.assertEqual(self.daemons_key("installed"), ["alpha", "beta", "report"])
        self.assertEqual(self.daemons_key("disabled"), ["gamma"])
        self.assertTrue(any(line.startswith("installed ") for line in lines), lines)
        self.assertEqual(self.effective(), before)
        self.assertIn("# mine", (self.conf.parent / "daemons" / "alpha.toml").read_text())

    def test_leftovers_are_tidied_and_real_content_kept(self):
        migrate.migrate(self.cfg())
        self.assertFalse((self.old / "alpha").exists())
        self.assertFalse((self.old / "beta").exists())
        self.assertFalse((self.old / "slack-commands").exists())
        self.assertEqual((self.old / "keep" / "notes.txt").read_text(), "mine")
        self.assertTrue((self.old / "secret.local" / "daemon.toml").exists())
        self.assertEqual((self.conf.parent / "commands" / "deploy.md").read_text(), "deploy")

    def test_a_differing_runbook_is_left_in_place(self):
        write(self.conf.parent / "commands" / "deploy.md", "other")
        lines = migrate.migrate(self.cfg())
        self.assertTrue(any(line.startswith("skip") and "deploy.md" in line for line in lines))
        self.assertTrue((self.old / "slack-commands" / "commands.local" / "deploy.md").exists())

    def test_second_run_is_a_no_op(self):
        migrate.migrate(self.cfg())
        snapshot = self.conf.read_text()
        self.assertEqual(migrate.migrate(self.cfg()), [])
        self.assertEqual(self.conf.read_text(), snapshot)

    def test_an_existing_installed_key_is_never_rewritten(self):
        self.write_config("installed = []")
        migrate.migrate(self.cfg())
        self.assertEqual(self.daemons_key("installed"), [])


if __name__ == "__main__":
    unittest.main()
