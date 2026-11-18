"""Ejected copies: `daimon eject` (locally or into a pack), `uneject`, `outdated`,
`diff`, the pack copy that shadows dAImon's daemon, and `{{daemon_dir}}` inputs."""

import io
import json
import os
import shutil
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from test_catalog import CatalogBase, make_daemon, write

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT))
import config  # noqa: E402
from daimon import catalog, eject  # noqa: E402
from daimon.fingerprint import content_hash  # noqa: E402


class EjectBase(CatalogBase):
    def setUp(self):
        super().setUp()
        self.write_config('installed = ["alpha", "report"]')
        write(self.root / "catalog" / "alpha" / "skill" / "SKILL.md", "alpha at {{daemon_dir}}\n")
        (self.root / "catalog" / "alpha" / "discover.sh").write_text("exit 1\n")
        (self.root / "catalog" / "alpha" / "discover.sh").chmod(0o755)

    def run_cmd(self, *argv: str, module=eject, confirm=False) -> tuple[int, str]:
        out = io.StringIO()
        with (
            patch.object(catalog, "_sync", return_value=True),
            patch.object(eject, "_sync", return_value=True),
            patch.object(eject, "_confirm", return_value=confirm) as self.asked,
            redirect_stdout(out),
            redirect_stderr(out),
        ):
            rc = module.main(list(argv))
        return rc, out.getvalue()

    def effective(self, slug: str) -> tuple[dict, str]:
        cfg = self.cfg()
        here = str(cfg.daemon_dir(slug))
        skill = config.render_skill(cfg, slug).replace(here, "<daemon_dir>")
        return cfg.daemon(slug), skill

    def origin(self, folder: Path) -> dict:
        return json.loads((folder / ".origin.json").read_text())

    def diff(self, slug: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "PYTHONPATH": str(ROOT)}
        return subprocess.run(
            [sys.executable, "-m", "daimon.eject", "diff", slug],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )


class EjectLocalTest(EjectBase):
    def test_round_trip_keeps_effective_config_and_settings(self):
        personal = write(self.conf.parent / "daemons" / "alpha.toml", '[inputs]\nq = "mine"\n')
        before = self.effective("alpha")
        rc, out = self.run_cmd("eject", "alpha")
        self.assertEqual(rc, 0, out)
        copy = self.root / "daemons" / "alpha"
        self.assertEqual(self.cfg().daemon_dir("alpha"), copy)
        self.assertEqual(
            self.origin(copy),
            {"source": "dAImon", "path": "catalog/alpha", "hash": content_hash(copy)},
        )
        self.assertEqual(content_hash(copy), content_hash(self.root / "catalog" / "alpha"))
        self.assertTrue(os.access(copy / "discover.sh", os.X_OK))
        self.assertEqual(self.effective("alpha"), before)
        self.assertEqual(self.daemons_key("installed"), ["alpha", "report"])

        rc, out = self.run_cmd("uneject", "--yes", "alpha")
        self.assertEqual(rc, 0, out)
        self.assertFalse(copy.exists())
        self.assertEqual(self.cfg().daemon_dir("alpha"), self.root / "catalog" / "alpha")
        self.assertEqual(self.effective("alpha"), before)
        self.assertEqual(personal.read_text(), '[inputs]\nq = "mine"\n')
        self.assertEqual(self.daemons_key("installed"), ["alpha", "report"])

    def test_ejecting_a_pack_daemon_records_the_pack(self):
        self.run_cmd("eject", "report")
        self.assertEqual(
            self.origin(self.root / "daemons" / "report"),
            {
                "source": "team",
                "path": "daemons/report",
                "hash": content_hash(self.pack / "daemons" / "report"),
            },
        )

    def test_ejecting_an_uninstalled_daemon_installs_it(self):
        self.run_cmd("eject", "beta")
        self.assertEqual(self.daemons_key("installed"), ["alpha", "report", "beta"])

    def test_a_legacy_settings_file_beside_the_daemon_moves_to_personal_first(self):
        write(self.root / "catalog" / "alpha" / "daemon.local.toml", '[inputs]\nq = "legacy"\n')
        before = self.effective("alpha")
        self.run_cmd("eject", "alpha")
        self.assertFalse((self.root / "daemons" / "alpha" / "daemon.local.toml").exists())
        self.assertIn("legacy", (self.conf.parent / "daemons" / "alpha.toml").read_text())
        self.assertEqual(self.effective("alpha"), before)

    def test_caches_and_personal_files_are_neither_copied_nor_hashed(self):
        src = self.root / "catalog" / "alpha"
        before = content_hash(src)
        write(src / "__pycache__" / "x.pyc", "junk")
        write(src / "extra.local.toml", "x = 1\n")
        self.assertEqual(content_hash(src), before)
        self.run_cmd("eject", "alpha")
        self.assertFalse((self.root / "daemons" / "alpha" / "__pycache__").exists())
        self.assertFalse((self.root / "daemons" / "alpha" / "extra.local.toml").exists())

    def test_refusals(self):
        self.run_cmd("eject", "alpha")
        rc, out = self.run_cmd("eject", "alpha")
        self.assertEqual(rc, 1)
        self.assertIn("already ejected", out)
        rc, out = self.run_cmd("eject", "ghost")
        self.assertEqual(rc, 1)
        self.assertIn("not in any catalog", out)
        rc, out = self.run_cmd("uneject", "beta")
        self.assertEqual((rc, "not ejected" in out), (1, True))

    def test_uneject_asks_first(self):
        self.run_cmd("eject", "alpha")
        (self.root / "daemons" / "alpha" / "skill" / "SKILL.md").write_text("edited\n")
        rc, out = self.run_cmd("uneject", "alpha")
        self.assertEqual(rc, 1)
        self.assertIn("--yes", out)
        self.assertIn("your edits there are lost", self.asked.call_args.args[0])
        self.assertTrue((self.root / "daemons" / "alpha").exists())
        rc, _ = self.run_cmd("uneject", "alpha", confirm=True)
        self.assertEqual(rc, 0)
        self.assertFalse((self.root / "daemons" / "alpha").exists())

    def test_uneject_refuses_your_own_daemon(self):
        make_daemon(self.root / "daemons" / "mine", "mine")
        rc, out = self.run_cmd("uneject", "--yes", "mine")
        self.assertEqual(rc, 1)
        self.assertIn("your own daemon", out)
        self.assertTrue((self.root / "daemons" / "mine").exists())


class EjectToPackTest(EjectBase):
    def test_pack_copy_shadows_dAImons_and_validates(self):
        before = self.effective("alpha")
        rc, out = self.run_cmd("eject", "alpha", "--pack")
        self.assertEqual(rc, 0, out)
        copy = self.pack / "daemons" / "alpha"
        self.assertEqual(self.origin(copy)["source"], "dAImon")
        self.assertEqual(self.origin(copy)["path"], "catalog/alpha")
        cfg = self.cfg()
        self.assertEqual(cfg.daemon_dir("alpha"), copy)
        self.assertEqual(cfg.catalog()["alpha"]["source"], "team")
        self.assertEqual(config.validate(cfg), [])
        self.assertEqual(self.effective("alpha"), before)
        self.assertFalse((self.root / "daemons" / "alpha").exists())

    def test_a_plain_pack_duplicate_is_still_an_error(self):
        make_daemon(self.pack / "daemons" / "alpha", "alpha")
        errors = config.validate(self.cfg())
        self.assertTrue(any(e.startswith("alpha: defined twice") for e in errors), errors)

    def test_add_pack_copies_and_installs(self):
        rc, out = self.run_cmd("add", "beta", "--pack", str(self.pack), module=catalog)
        self.assertEqual(rc, 0, out)
        self.assertTrue((self.pack / "daemons" / "beta" / ".origin.json").exists())
        self.assertEqual(self.daemons_key("installed"), ["alpha", "report", "beta"])
        self.assertEqual(self.cfg().daemon_dir("beta"), self.pack / "daemons" / "beta")

    def test_pack_refusals(self):
        rc, out = self.run_cmd("eject", "report", "--pack")
        self.assertEqual(rc, 1)
        self.assertIn("not in dAImon's catalog", out)
        self.run_cmd("eject", "alpha", "--pack")
        rc, out = self.run_cmd("eject", "alpha", "--pack")
        self.assertIn("already exists", out)
        rc, out = self.run_cmd("uneject", "--yes", "alpha")
        self.assertEqual(rc, 1)
        self.assertIn("PR to the pack", out)
        rc, out = self.run_cmd("eject", "beta", "--pack", str(self.root))
        self.assertIn("is not in [packs].paths", out)

    def test_several_packs_need_one_named(self):
        other = self.root.parent / "other"
        (other / "daemons").mkdir(parents=True)
        self.conf.write_text(
            self.conf.read_text().replace(
                f'paths = ["{self.pack}"]', f'paths = ["{self.pack}", "{other}"]'
            )
        )
        rc, out = self.run_cmd("eject", "beta", "--pack")
        self.assertEqual(rc, 1)
        self.assertIn("several packs configured", out)
        rc, out = self.run_cmd("eject", "beta", "--pack", str(other))
        self.assertEqual(rc, 0, out)
        self.assertTrue((other / "daemons" / "beta" / ".origin.json").exists())


class OutdatedDiffTest(EjectBase):
    def setUp(self):
        super().setUp()
        self.run_cmd("eject", "alpha")
        self.run_cmd("eject", "beta", "--pack")
        self.copy = self.root / "daemons" / "alpha"

    def rows(self) -> dict:
        return {(c.slug, c.where): (up, edited) for c, up, edited in eject.report(self.cfg())}

    def test_fresh_copies_are_current(self):
        self.assertEqual(
            self.rows(), {("alpha", "local"): (False, False), ("beta", "team"): (False, False)}
        )
        rc, out = self.run_cmd("outdated", "--brief")
        self.assertEqual((rc, out), (0, ""))

    def test_upstream_and_local_changes_are_told_apart(self):
        write(self.root / "catalog" / "alpha" / "NOTES.md", "upstream fix\n")
        write(self.pack / "daemons" / "beta" / "skill" / "SKILL.md", "team edit\n")
        self.assertEqual(
            self.rows(), {("alpha", "local"): (True, False), ("beta", "team"): (False, True)}
        )
        rc, out = self.run_cmd("outdated")
        self.assertEqual(rc, 0)
        self.assertRegex(out, r"alpha\s+local\s+changed\s+unchanged\s+dAImon: catalog/alpha")
        self.assertRegex(out, r"beta\s+team\s+unchanged\s+edited\s+dAImon: catalog/beta")
        _, brief = self.run_cmd("outdated", "--brief")
        self.assertEqual(brief, "alpha (local): upstream changed\n")

    def test_a_vanished_upstream_is_reported(self):
        shutil.rmtree(self.root / "catalog" / "beta")
        self.assertEqual(self.rows()[("beta", "team")], (None, False))

    def test_diff_shows_the_edit_and_which_side_changed(self):
        (self.copy / "skill" / "SKILL.md").write_text("alpha, my way\n")
        proc = self.diff("alpha")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("upstream unchanged, your copy edited", proc.stdout)
        self.assertIn("-alpha at {{daemon_dir}}", proc.stdout)
        self.assertIn("+alpha, my way", proc.stdout)
        self.assertNotIn("Only in", proc.stdout)

    def test_diff_of_an_upstream_change(self):
        write(self.root / "catalog" / "alpha" / "NOTES.md", "upstream fix\n")
        proc = self.diff("alpha")
        self.assertIn("upstream changed, your copy unchanged", proc.stdout)
        self.assertIn("Only in", proc.stdout)

    def test_diff_without_a_copy(self):
        self.assertEqual(self.diff("gamma").returncode, 1)


class ForkTest(EjectBase):
    """`daimon eject <slug> --as <new>`: a renamed copy that runs beside the original."""

    def setUp(self):
        super().setUp()
        src = self.root / "catalog" / "alpha"
        write(
            src / "skill" / "SKILL.md",
            "---\nname: alpha\ndescription: alpha does it\n---\n\n# alpha\n"
            "Run `daimon state get alpha`; leave alpha-two alone.\n",
        )
        (src / "discover.sh").write_text('seen="$(state_file alpha)"\nexit 1\n')
        self.fork = self.root / "daemons" / "omega"

    def test_round_trip_both_resolve_and_the_fork_has_its_own_names(self):
        rc, out = self.run_cmd("eject", "alpha", "--as", "omega")
        self.assertEqual(rc, 0, out)
        self.assertEqual(
            self.origin(self.fork),
            {
                "source": "dAImon",
                "path": "catalog/alpha",
                "hash": content_hash(self.fork),
                "as": "omega",
            },
        )
        self.assertIn('command = "/omega"', (self.fork / "daemon.toml").read_text())
        skill = (self.fork / "skill" / "SKILL.md").read_text()
        self.assertIn("name: omega\n", skill)
        self.assertIn("daimon state get omega`; leave alpha-two alone", skill)
        self.assertIn("state_file omega", (self.fork / "discover.sh").read_text())
        self.assertTrue(os.access(self.fork / "discover.sh", os.X_OK))

        cfg = self.cfg()
        self.assertEqual(cfg.daemon_dir("alpha"), self.root / "catalog" / "alpha")
        self.assertEqual(cfg.daemon_dir("omega"), self.fork)
        self.assertIn("alpha", cfg.discover())
        self.assertIn("omega", cfg.discover())
        self.assertEqual(self.daemons_key("installed"), ["alpha", "report", "omega"])
        self.assertEqual(config.validate(cfg), [])
        self.assertEqual(cfg.daemon("omega")["command"], "/omega")
        rendered = config.render_skill(cfg, "omega")
        self.assertIn("name: omega\n", rendered)
        self.assertNotIn("name: alpha\n", rendered)
        self.assertIn("name: alpha\n", config.render_skill(cfg, "alpha"))
        plist = config.render_plist(cfg, "omega")
        self.assertIn(f"<string>com.{cfg.core['namespace']}.omega</string>", plist)
        self.assertIn("logs/omega.log", plist)
        self.assertEqual(eject.report(cfg)[0][1:], (False, False))

        rc, out = self.run_cmd("uneject", "--yes", "omega")
        self.assertEqual(rc, 1)
        self.assertIn("renamed copy of alpha", out)
        self.assertIn("daimon remove omega", out)
        self.assertTrue(self.fork.exists())

    def test_pack_fork_is_a_distinct_daemon_not_an_override(self):
        rc, out = self.run_cmd("eject", "alpha", "--as", "omega", "--pack")
        self.assertEqual(rc, 0, out)
        copy = self.pack / "daemons" / "omega"
        self.assertEqual(self.origin(copy)["as"], "omega")
        self.assertIn("commit it in the pack", out)
        cfg = self.cfg()
        self.assertFalse(cfg.shadows_daimon(copy, "omega"))
        self.assertEqual(cfg.daemon_dir("alpha"), self.root / "catalog" / "alpha")
        self.assertEqual(cfg.catalog()["alpha"]["source"], "dAImon")
        self.assertEqual(cfg.catalog()["omega"]["source"], "team")
        self.assertEqual(config.validate(cfg), [])
        self.assertFalse(self.fork.exists())

    def test_forking_a_pack_daemon_records_the_pack(self):
        rc, out = self.run_cmd("eject", "report", "--as", "digest")
        self.assertEqual(rc, 0, out)
        origin = self.origin(self.root / "daemons" / "digest")
        self.assertEqual((origin["source"], origin["path"]), ("team", "daemons/report"))
        self.assertEqual(self.cfg().daemon("digest")["command"], "/digest")

    def test_outdated_and_diff_track_the_original_through_the_rename(self):
        self.run_cmd("eject", "alpha", "--as", "omega")
        proc = self.diff("omega")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("upstream unchanged, your copy unchanged", proc.stdout)
        self.assertIn("alpha -> omega", proc.stdout)
        self.assertNotIn("\n-", proc.stdout)
        self.assertNotIn("\n+", proc.stdout)

        skill = self.root / "catalog" / "alpha" / "skill" / "SKILL.md"
        skill.write_text(skill.read_text() + "Then tell alpha's owner.\n")
        self.assertEqual(eject.report(self.cfg())[0][1:], (True, False))
        proc = self.diff("omega")
        self.assertIn("upstream changed, your copy unchanged", proc.stdout)
        self.assertIn("-Then tell omega's owner.", proc.stdout)
        self.assertIn(f"--- {self.root}/catalog/alpha/skill/SKILL.md", proc.stdout)
        self.assertNotIn("name: ", proc.stdout)

        (self.fork / "NOTES.md").write_text("mine\n")
        self.assertEqual(eject.report(self.cfg())[0][1:], (True, True))
        _, brief = self.run_cmd("outdated", "--brief")
        self.assertEqual(brief, "omega (local): upstream changed\n")

    def test_personal_settings_are_copied_once(self):
        personal = self.conf.parent / "daemons"
        write(personal / "alpha.toml", '[inputs]\nq = "mine"\n')
        rc, out = self.run_cmd("eject", "alpha", "--as", "omega")
        self.assertEqual(rc, 0, out)
        self.assertEqual((personal / "omega.toml").read_text(), '[inputs]\nq = "mine"\n')
        self.assertIn("a copy of your alpha settings", out)
        self.assertEqual(self.cfg().daemon("omega")["inputs"]["q"], "mine")

        write(personal / "zeta.toml", '[inputs]\nq = "zeta"\n')
        rc, out = self.run_cmd("eject", "alpha", "--as", "zeta")
        self.assertEqual(rc, 0, out)
        self.assertEqual((personal / "zeta.toml").read_text(), '[inputs]\nq = "zeta"\n')
        self.assertNotIn("settings", out)

    def without_name(self, slug: str) -> dict:
        d = dict(self.cfg().daemon(slug))
        del d["slug"], d["command"]
        return d

    def test_team_overrides_are_folded_into_the_fork(self):
        override = write(
            self.pack / "overrides" / "alpha.toml",
            '[daemon]\nworking_dir = "~/team/hub"\n'
            '[inputs]\nq = "team"\nrepos = ["team/one", "team/two"]\n',
        )
        write(self.conf.parent / "daemons" / "alpha.toml", '[inputs]\nrepos = ["mine/x"]\n')
        before = self.without_name("alpha")
        self.assertEqual(before["working_dir"], str(self.home / "team" / "hub"))
        for args, folder in (
            (("--as", "omega"), self.fork),
            (("--as", "zeta", "--pack"), self.pack / "daemons" / "zeta"),
        ):
            rc, out = self.run_cmd("eject", "alpha", *args)
            self.assertEqual(rc, 0, out)
            self.assertIn(f"folded in the team overrides of alpha: {override}", out)
            self.assertEqual(self.without_name(folder.name), before)
            toml = (folder / "daemon.toml").read_text()
            self.assertIn("# from the team pack's overrides/alpha.toml", toml)
            self.assertEqual(toml.count('q = "'), 1)
            self.assertEqual(
                eject.report(self.cfg())[0 if folder == self.fork else 1][1:], (False, True)
            )
        self.assertEqual(self.without_name("alpha"), before)

    def test_refusals(self):
        make_daemon(self.root / "daemons" / "mine", "mine")
        cases = {
            ("alpha", "alpha"): "the daemon's own name",
            ("alpha", "Not_A_Slug"): "lowercase words joined by hyphens",
            ("alpha", "beta"): "beta already exists",
            ("alpha", "report"): "report already exists",
            ("alpha", "mine"): "mine already exists",
            ("ghost", "omega"): "not in any catalog",
        }
        for (slug, new), message in cases.items():
            rc, out = self.run_cmd("eject", slug, "--as", new)
            self.assertEqual(rc, 1, (slug, new, out))
            self.assertIn(message, out)
        self.assertFalse(self.fork.exists())
        self.assertEqual(self.daemons_key("installed"), ["alpha", "report"])


class DaemonDirInputTest(EjectBase):
    """slack-commands' commands_dir = "{{daemon_dir}}/commands" follows the copy."""

    def setUp(self):
        super().setUp()
        make_daemon(
            self.root / "catalog" / "cmds",
            "cmds",
            'commands_dir = "{{daemon_dir}}/commands"\nextra = ["{{daemon_dir}}/x"]',
        )
        self.write_config('installed = ["cmds"]')

    def test_resolves_to_the_catalog_until_ejected_then_to_the_copy(self):
        inputs = self.cfg().daemon("cmds")["inputs"]
        self.assertEqual(inputs["commands_dir"], f"{self.root}/catalog/cmds/commands")
        self.assertEqual(inputs["extra"], [f"{self.root}/catalog/cmds/x"])
        self.run_cmd("eject", "cmds")
        inputs = self.cfg().daemon("cmds")["inputs"]
        self.assertEqual(inputs["commands_dir"], f"{self.root}/daemons/cmds/commands")

    def test_the_real_slack_commands_default_points_at_its_own_runbooks(self):
        real = config._load_toml(ROOT / "catalog" / "slack-commands" / "daemon.toml")
        self.assertEqual(real["inputs"]["commands_dir"], "{{daemon_dir}}/commands")


if __name__ == "__main__":
    unittest.main()
