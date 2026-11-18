"""Personal settings live in the personal dir (beside daimon.toml), not the repo:
layering with the legacy in-repo *.local.toml files, writes, `daimon migrate`, and
`daimon init` scaffolding."""

import io
import os
import sys
import tempfile
import textwrap
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import config  # noqa: E402
import migrate  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from daimon import init  # noqa: E402


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip("\n"))


def make_daemon(folder: Path, slug: str, extra: str = ""):
    write(
        folder / "daemon.toml",
        f"""
        [daemon]
        sources = ["sc"]
        schedule = {{ interval = 600 }}
        command = "/{slug}"
        {extra}
        [inputs]
        q = "base"
        """,
    )
    write(folder / "skill" / "SKILL.md", f"---\nname: {slug}\n---\nq={{{{inputs.q}}}}\n")


class PersonalSettingsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.root = base / "install"
        self.pack = base / "team"
        self.home = base / "home"
        make_daemon(self.root / "catalog" / "alpha", "alpha")
        make_daemon(self.root / "daemons" / "secret.local", "secret")
        make_daemon(self.pack / "daemons" / "report", "report")
        write(
            self.root / "profiles" / "sc" / "profile.toml",
            '[profile]\ntool = "sc"\n[defaults]\nowner = "nobody"\nteam = "t"\n',
        )
        write(self.pack / "profiles" / "sc.toml", '[defaults]\nteam = "pack-team"\n')
        self.conf = self.home / "daimon.toml"
        write(
            self.conf,
            f'[core]\ninstall_root = "{self.root}"\nstate_dir = "{base}/state"\n'
            f'[packs]\npaths = ["{self.pack}"]\n'
            '[daemons]\ninstalled = ["alpha", "report"]\n',
        )
        os.environ["DAIMON_CONFIG"] = str(self.conf)

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("DAIMON_CONFIG", None)

    def legacy(self, slug_dir: str) -> Path:
        return self.root / "catalog" / slug_dir / "daemon.local.toml"

    def personal(self, slug: str) -> Path:
        return self.home / "daemons" / f"{slug}.toml"


class LayeringTest(PersonalSettingsBase):
    def test_paths_live_beside_the_global_config(self):
        cfg = config.Config.load()
        self.assertEqual(cfg.daemon_local_path("alpha"), self.personal("alpha"))
        self.assertEqual(cfg.profile_local_path("sc"), self.home / "profiles" / "sc.toml")
        self.assertEqual(
            cfg.legacy_daemon_local_paths("alpha"),
            [self.root / "daemons" / "alpha" / "daemon.local.toml", self.legacy("alpha")],
        )

    def test_personal_file_wins_over_legacy_which_wins_over_pack(self):
        write(self.pack / "overrides" / "alpha.toml", '[inputs]\nq = "team"\nr = "team"\ns = 1\n')
        write(self.legacy("alpha"), '[inputs]\nq = "legacy"\nr = "legacy"\n')
        write(self.personal("alpha"), '[inputs]\nq = "new"\n')
        inputs = config.Config.load().daemon("alpha")["inputs"]
        self.assertEqual((inputs["q"], inputs["r"], inputs["s"]), ("new", "legacy", 1))

    def test_profile_layers_end_with_the_personal_file(self):
        write(self.root / "profiles" / "sc" / "profile.local.toml", '[defaults]\nowner = "old"\n')
        self.assertEqual(config.Config.load().daemon("alpha")["inputs"]["owner"], "old")
        write(self.home / "profiles" / "sc.toml", '[defaults]\nowner = "me"\n')
        inputs = config.Config.load().daemon("alpha")["inputs"]
        self.assertEqual((inputs["owner"], inputs["team"]), ("me", "pack-team"))

    def test_writes_go_to_the_personal_files_only(self):
        write(self.legacy("alpha"), '[inputs]\nr = "legacy"\n')
        before = self.legacy("alpha").read_text()
        cfg = config.Config.load()
        cfg.update_local("alpha", {"stuck_after": 99})
        cfg.update_profile_local("sc", {"owner": "me"})
        self.assertEqual(self.legacy("alpha").read_text(), before)
        self.assertFalse((self.root / "profiles" / "sc" / "profile.local.toml").exists())
        self.assertIn("stuck_after = 99", self.personal("alpha").read_text())
        self.assertIn('owner = "me"', (self.home / "profiles" / "sc.toml").read_text())
        d = config.Config.load().daemon("alpha")
        self.assertEqual(
            (d["stuck_after"], d["inputs"]["r"], d["inputs"]["owner"]), (99, "legacy", "me")
        )

    def test_provenance_counts_legacy_and_personal_as_owned(self):
        write(self.legacy("alpha"), '[inputs]\nowner = "legacy"\n')
        write(self.personal("alpha"), '[inputs]\nr = "new"\n')
        prov = config.Config.load().input_provenance("alpha")
        self.assertEqual(prov["daemon"], {"q": "base", "owner": "legacy", "r": "new"})
        self.assertEqual(prov["profiles"], {"sc": {"team": "pack-team"}})


class MigrateTest(PersonalSettingsBase):
    def run_migrate(self) -> list[str]:
        return migrate.migrate(config.Config.load())

    def effective(self) -> dict:
        cfg = config.Config.load()
        return {s: (cfg.daemon(s), config.render_skill(cfg, s)) for s in cfg.discover()}

    def test_fresh_move_is_verbatim_and_stubs_the_legacy_file(self):
        text = '# my repo\n[daemon]\nworking_dir = "~/x"  # trailing\n\n[inputs]\nq = "mine"\n'
        self.legacy("alpha").write_text(text)
        before = self.effective()
        lines = self.run_migrate()
        self.assertEqual(lines, [f"moved {self.legacy('alpha')} -> {self.personal('alpha')}"])
        self.assertEqual(self.personal("alpha").read_text(), text)
        stub = self.legacy("alpha").read_text()
        self.assertEqual(stub, f"# moved to {self.personal('alpha')} by daimon migrate\n")
        self.assertEqual(tomllib.loads(stub), {})
        self.assertEqual(self.effective(), before)

    def test_merge_keeps_new_values_and_adds_missing_keys_under_their_table(self):
        write(
            self.legacy("alpha"),
            '[daemon]\nmodel = "sonnet"\nrole = "x"\n[inputs]\nq = "legacy"\nextra = ["a"]\n',
        )
        write(self.personal("alpha"), '# keep\n[daemon]\nmodel = "opus"\n\n[other]\nk = 1\n')
        lines = self.run_migrate()
        self.assertEqual(lines, [f"merged {self.legacy('alpha')} -> {self.personal('alpha')}"])
        text = self.personal("alpha").read_text()
        data = tomllib.loads(text)
        self.assertIn("# keep", text)
        self.assertEqual(data["daemon"], {"model": "opus", "role": "x"})
        self.assertEqual(data["inputs"], {"q": "legacy", "extra": ["a"]})
        self.assertEqual(data["other"], {"k": 1})
        self.assertIn('# [daemon] model = "sonnet"', text)  # the overridden value is kept
        self.assertTrue(migrate.is_stub(self.legacy("alpha").read_text()))

    def test_merge_inserts_into_an_existing_table(self):
        write(self.legacy("alpha"), '[inputs]\nr = "legacy"\n')
        write(self.personal("alpha"), '[inputs]\nq = "new"\n\n[daemon]\nrole = "y"\n')
        self.run_migrate()
        data = tomllib.loads(self.personal("alpha").read_text())
        self.assertEqual(data["inputs"], {"q": "new", "r": "legacy"})
        self.assertEqual(data["daemon"], {"role": "y"})

    def test_second_run_is_a_no_op(self):
        write(self.legacy("alpha"), '[inputs]\nq = "mine"\n')
        self.run_migrate()
        snapshot = (self.legacy("alpha").read_text(), self.personal("alpha").read_text())
        self.assertEqual(self.run_migrate(), [])
        self.assertEqual(
            (self.legacy("alpha").read_text(), self.personal("alpha").read_text()), snapshot
        )

    def test_pack_and_private_daemons_and_profiles_migrate(self):
        write(self.pack / "daemons" / "report" / "daemon.local.toml", '[inputs]\nq = "p"\n')
        write(self.root / "daemons" / "secret.local" / "daemon.local.toml", '[inputs]\nq = "s"\n')
        write(
            self.root / "profiles" / "sc" / "profile.local.toml", '# me\n[defaults]\nowner = "me"\n'
        )
        before = self.effective()
        self.assertEqual(len(self.run_migrate()), 3)
        self.assertIn('q = "p"', self.personal("report").read_text())
        self.assertIn('q = "s"', self.personal("secret").read_text())
        self.assertEqual(
            (self.home / "profiles" / "sc.toml").read_text(), '# me\n[defaults]\nowner = "me"\n'
        )
        self.assertEqual(self.effective(), before)

    def test_examples_and_invalid_files_are_left_alone(self):
        example = self.root / "catalog" / "alpha" / "daemon.local.toml.example"
        write(example, '[inputs]\nq = "example"\n')
        write(self.legacy("alpha"), "[inputs\nbroken")
        lines = self.run_migrate()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("skip"))
        self.assertEqual(self.legacy("alpha").read_text(), "[inputs\nbroken")
        self.assertEqual(example.read_text(), '[inputs]\nq = "example"\n')
        self.assertFalse(self.personal("alpha").exists())

    def test_cli_reports_nothing_to_do(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(migrate.main(), 0)
        self.assertIn("nothing to move", out.getvalue())


class InitScaffoldTest(PersonalSettingsBase):
    def seed(self):
        ex = '[daemon]\nworking_dir = "~/code"\n'
        write(self.root / "catalog" / "alpha" / "daemon.local.toml.example", ex)
        write(
            self.root / "profiles" / "sc" / "profile.local.toml.example",
            '[defaults]\nowner = "x"\n',
        )
        make_daemon(self.root / "catalog" / "beta", "beta")
        write(self.legacy("beta"), '[inputs]\nq = "legacy"\n')
        write(self.root / "catalog" / "beta" / "daemon.local.toml.example", '[inputs]\nq = "ex"\n')

    def run_init(self, slugs: list[str]) -> int:
        old_cwd = Path.cwd()
        os.chdir(self.root)
        try:
            with (
                patch.object(init, "INSTALL_ROOT", self.root),
                patch.object(init, "_import_config", return_value=config),
                patch.object(init.sys, "stdin", io.StringIO()),
                redirect_stdout(io.StringIO()),
            ):
                return init.main(slugs)
        finally:
            os.chdir(old_cwd)

    def test_init_migrates_then_scaffolds_into_the_personal_dir(self):
        self.seed()
        self.assertEqual(self.run_init(["alpha", "beta"]), 0)
        self.assertIn("working_dir", self.personal("alpha").read_text())
        self.assertFalse(self.legacy("alpha").exists())
        # beta's legacy settings were migrated first, so the example didn't shadow them
        self.assertEqual(self.personal("beta").read_text(), '[inputs]\nq = "legacy"\n')
        self.assertTrue(migrate.is_stub(self.legacy("beta").read_text()))
        profile = (self.home / "profiles" / "sc.toml").read_text()
        self.assertEqual(profile, '[defaults]\nowner = "x"\n')
        self.assertFalse((self.root / "profiles" / "sc" / "profile.local.toml").exists())


def mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def tree(root: Path) -> dict[str, tuple[int, bytes]]:
    return {
        str(p.relative_to(root)): (mode(p), p.read_bytes() if p.is_file() else b"")
        for p in sorted(root.rglob("*"))
    }


class PersonalDirMoveTest(unittest.TestCase):
    """~/.config/daimon -> ~/.daimon, in a scratch HOME."""

    TODAY = migrate.datetime.date(2026, 11, 17)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name).resolve()
        self.old = self.home / ".config" / "daimon"
        self.new = self.home / ".daimon"
        env = {k: v for k, v in os.environ.items() if k != "DAIMON_CONFIG"}
        env["HOME"] = str(self.home)
        self.env = patch.dict(os.environ, env, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def seed_legacy(self):
        write(
            self.old / "daimon.toml",
            f"""
            # mine
            [core]
            state_dir = "~/.local/state/daimon"
            [packs]
            paths = ["{self.old}/packs/team", "~/tbl/tbl-agents"]
            """,
        )
        write(
            self.old / "daemons" / "slack-commands.toml",
            '[inputs]\nlocal_commands_dir = "~/.config/daimon/commands"\n',
        )
        write(self.old / "profiles" / "shortcut.toml", '[defaults]\nowner = "me"\n')
        write(self.old / "commands" / "deploy.md", "# deploy ~/.config/daimon/x\n")
        (self.old / "no-auto-update").touch()
        for f in ("daemons/slack-commands.toml", "profiles/shortcut.toml"):
            (self.old / f).chmod(0o600)
        (self.old / "daimon.toml").chmod(0o644)

    def seed_junk(self):
        write(self.new / "state" / "reply-to-pr-comments.json", "{}")
        write(self.new / "state.json", '{"old": true}')
        write(self.new / "reply-to-story-comments.json", "[]")

    def run_move(self) -> list[str]:
        return migrate.migrate_personal_dir(today=self.TODAY)

    def assert_moved(self):
        self.assertEqual(sorted(p.name for p in self.old.iterdir()), ["MOVED"])
        self.assertIn(str(self.new), (self.old / "MOVED").read_text())
        conf = (self.new / "daimon.toml").read_text()
        self.assertTrue(conf.startswith("# mine\n"))
        self.assertIn(f'"{self.new}/packs/team", "~/tbl/tbl-agents"', conf)
        self.assertIn(
            'local_commands_dir = "~/.daimon/commands"',
            (self.new / "daemons" / "slack-commands.toml").read_text(),
        )
        # not a .toml: verbatim
        self.assertIn("~/.config/daimon/x", (self.new / "commands" / "deploy.md").read_text())
        self.assertTrue((self.new / "no-auto-update").exists())
        self.assertEqual(mode(self.new / "daemons" / "slack-commands.toml"), 0o600)
        self.assertEqual(mode(self.new / "profiles" / "shortcut.toml"), 0o600)
        self.assertEqual(mode(self.new / "daimon.toml"), 0o644)
        self.assertEqual(config.global_config_path(), self.new / "daimon.toml")

    def test_moves_everything_and_leaves_a_pointer(self):
        self.seed_legacy()
        lines = self.run_move()
        self.assertEqual(lines, [f"moved {self.old} -> {self.new} (5 file(s))"])
        self.assert_moved()
        self.assertFalse(any(p.name.startswith("legacy-") for p in self.new.iterdir()))

    def test_sets_an_older_daimons_files_aside_first(self):
        self.seed_legacy()
        self.seed_junk()
        lines = self.run_move()
        self.assertIn("state, state.json", lines[0])
        self.assert_moved()
        aside = self.new / "legacy-20261117"
        self.assertEqual((aside / "state.json").read_text(), '{"old": true}')
        self.assertTrue((aside / "state" / "reply-to-pr-comments.json").exists())
        self.assertTrue((aside / "reply-to-story-comments.json").exists())
        self.assertEqual(
            sorted(p.name for p in self.new.iterdir()),
            ["commands", "daemons", "daimon.toml", "legacy-20261117", "no-auto-update", "profiles"],
        )

    def test_keeps_a_daimon_checkout_in_app(self):
        self.seed_legacy()
        self.seed_junk()
        write(self.new / "app" / "bin" / "daimon", "#!/bin/sh\n")
        self.run_move()
        self.assert_moved()
        self.assertTrue((self.new / "app" / "bin" / "daimon").exists())
        self.assertFalse((self.new / "legacy-20261117" / "app").exists())

    def test_never_sets_aside_the_running_install(self):
        self.seed_junk()
        running = self.new / "dAImon" / "lib" / "migrate.py"
        write(running, "")
        with patch.object(migrate, "__file__", str(running)):
            self.run_move()
        self.assertTrue(running.exists())
        self.assertTrue((self.new / "legacy-20261117" / "state.json").exists())

    def test_idempotent(self):
        self.seed_legacy()
        self.seed_junk()
        self.run_move()
        before_new, before_old = tree(self.new), tree(self.old)
        self.assertEqual(self.run_move(), [])
        self.assertEqual((tree(self.new), tree(self.old)), (before_new, before_old))
        self.assertEqual(migrate.migrate_personal_dir(), [])  # another day: still nothing

    def test_resumes_a_run_that_stopped_before_daimon_toml(self):
        self.seed_legacy()
        self.seed_junk()
        write(self.new / "profiles" / "shortcut.toml", '[defaults]\nowner = "me"\n')
        (self.new / "profiles" / "shortcut.toml").chmod(0o600)
        # a launchd job firing now still reads the legacy config
        self.assertEqual(config.global_config_path(), self.old / "daimon.toml")
        self.run_move()
        self.assert_moved()

    def test_resumes_a_run_that_stopped_before_cleaning_up(self):
        self.seed_legacy()
        self.run_move()
        # put back what the cleanup would have removed: copies identical to ~/.daimon's
        write(self.old / "profiles" / "shortcut.toml", '[defaults]\nowner = "me"\n')
        (self.old / "MOVED").unlink()
        write(
            self.old / "daimon.toml",
            (self.new / "daimon.toml").read_text().replace(str(self.new), str(self.old)),
        )
        self.assertEqual(self.run_move(), [])
        self.assert_moved()

    def test_never_deletes_a_file_it_did_not_copy(self):
        self.seed_legacy()
        write(self.new / "profiles" / "shortcut.toml", '[defaults]\nowner = "someone else"\n')
        lines = self.run_move()
        self.assertTrue(
            any(line.startswith("skip  ") and "shortcut.toml" in line for line in lines)
        )
        self.assertEqual(
            (self.old / "profiles" / "shortcut.toml").read_text(), '[defaults]\nowner = "me"\n'
        )
        self.assertTrue((self.new / "daimon.toml").exists())
        self.assertFalse((self.old / "daimon.toml").exists())

    def test_both_present_prefers_dot_daimon_and_leaves_the_legacy_dir_alone(self):
        self.seed_legacy()
        write(self.new / "daimon.toml", "# made by hand\n")
        before = tree(self.old)
        lines = self.run_move()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("warn  both"))
        self.assertEqual(tree(self.old), before)
        self.assertEqual((self.new / "daimon.toml").read_text(), "# made by hand\n")
        self.assertEqual(config.global_config_path(), self.new / "daimon.toml")

    def test_fresh_machine_with_an_older_daimons_files(self):
        self.seed_junk()
        self.run_move()
        self.assertEqual(sorted(p.name for p in self.new.iterdir()), ["legacy-20261117"])
        self.assertFalse(self.old.exists())

    def test_nothing_anywhere_is_a_no_op(self):
        self.assertEqual(self.run_move(), [])
        self.assertFalse(self.new.exists())
        self.assertEqual(config.global_config_path(), self.new / "daimon.toml")

    def test_daimon_config_wins_and_nothing_moves(self):
        self.seed_legacy()
        self.seed_junk()
        explicit = self.home / "elsewhere" / "daimon.toml"
        before = (tree(self.old), tree(self.new))
        with patch.dict(os.environ, {"DAIMON_CONFIG": str(explicit)}):
            self.assertEqual(config.global_config_path(), explicit)
            self.assertEqual(config.personal_dir(), explicit.parent)
            self.assertEqual(self.run_move(), [])
        self.assertEqual((tree(self.old), tree(self.new)), before)

    def test_update_window_reads_the_legacy_config(self):
        self.seed_legacy()
        self.seed_junk()  # ~/.daimon exists, but holds no daimon.toml
        self.assertEqual(config.global_config_path(), self.old / "daimon.toml")
        self.assertEqual(config.personal_dir(), self.old)
        self.assertEqual(config.Config.load().source, self.old / "daimon.toml")

    def test_migrate_moves_the_dir_before_loading_the_config(self):
        self.seed_legacy()
        with redirect_stdout(io.StringIO()):
            lines = migrate.migrate()
        self.assertTrue(lines[0].startswith(f"moved {self.old} -> {self.new}"))
        self.assert_moved()


if __name__ == "__main__":
    unittest.main()
