"""Packs: folders outside the install root that add daemons, team overrides,
profile defaults and slack-commands runbooks (docs/packs.md)."""

import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import config  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from daimon import sync  # noqa: E402


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text))


def daemon(folder: Path, slug: str, inputs: str = "", extra: str = ""):
    write(
        folder / "daemon.toml",
        f"""
        [daemon]
        schedule = {{ interval = 600 }}
        command = "/{slug}"
        {extra}
        [inputs]
        {inputs}
        """,
    )
    write(
        folder / "skill" / "SKILL.md",
        f"---\nname: {slug}\n---\nq={{{{inputs.q}}}} dir={{{{daemon_dir}}}}\n",
    )


class PacksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.root = base / "install"
        self.pack = base / "team"
        daemon(
            self.root / "catalog" / "watcher", "watcher", 'q = "base"\nepic = 1', 'sources = ["sc"]'
        )
        write(
            self.root / "profiles" / "sc" / "profile.toml",
            """
            [profile]
            tool = "sc"
            [defaults]
            label = "base"
            owner = "nobody"
            """,
        )
        daemon(self.pack / "daemons" / "report", "report", 'q = "pack"')
        write(
            self.pack / "overrides" / "watcher.toml",
            '[daemon]\nrole = "errors"\n[inputs]\nq = "team"\nepic = 2\n',
        )
        write(
            self.pack / "profiles" / "sc.toml", '[defaults]\nlabel = "team"\nowner = "team-owner"\n'
        )
        write(self.pack / "commands" / "deploy.md", "---\nname: deploy\n---\n")
        self.write_config(f'[packs]\npaths = ["{self.pack}"]\n')

    def write_config(self, extra: str = ""):
        path = Path(self.tmp.name) / "daimon.toml"
        path.write_text(
            f'[core]\ninstall_root = "{self.root}"\nstate_dir = "{self.tmp.name}/state"\n'
            f'[roles]\ncommand = "holder {{role}} {{seconds}}"\n{extra}'
        )
        os.environ["DAIMON_CONFIG"] = str(path)

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("DAIMON_CONFIG", None)

    def test_pack_daemons_are_discovered_beside_the_install_roots(self):
        cfg = config.Config.load()
        self.assertEqual(set(cfg.discover()), {"watcher", "report"})
        self.assertEqual(cfg.daemon_dir("report"), self.pack / "daemons" / "report")
        self.assertEqual(config.validate(cfg), [])

    def test_overrides_sit_between_daemon_toml_and_daemon_local(self):
        cfg = config.Config.load()
        w = cfg.daemon("watcher")
        self.assertEqual((w["inputs"]["q"], w["inputs"]["epic"], w["role"]), ("team", 2, "errors"))
        write(self.root / "catalog" / "watcher" / "daemon.local.toml", '[inputs]\nq = "mine"\n')
        w = config.Config.load().daemon("watcher")
        self.assertEqual((w["inputs"]["q"], w["inputs"]["epic"]), ("mine", 2))

    def test_pack_profile_defaults_sit_under_profile_local(self):
        self.assertEqual(config.Config.load().daemon("watcher")["inputs"]["label"], "team")
        write(self.root / "profiles" / "sc" / "profile.local.toml", '[defaults]\nowner = "me"\n')
        inputs = config.Config.load().daemon("watcher")["inputs"]
        self.assertEqual((inputs["label"], inputs["owner"]), ("team", "me"))

    def test_skill_renders_from_the_pack_with_its_folder(self):
        text = config.render_skill(config.Config.load(), "report")
        self.assertIn("q=pack", text)
        self.assertIn(f"dir={self.pack / 'daemons' / 'report'}", text)

    def test_same_slug_in_a_pack_and_the_install_root_is_invalid(self):
        daemon(self.pack / "daemons" / "watcher", "watcher")
        errors = config.validate(config.Config.load())
        self.assertTrue(any(e.startswith("watcher: defined twice") for e in errors), errors)

    def test_missing_pack_is_a_validation_error(self):
        self.write_config('[packs]\npaths = ["/nonexistent/pack"]\n')
        errors = config.validate(config.Config.load())
        self.assertIn("[packs].paths: /nonexistent/pack does not exist", errors)

    def test_disabled_works_for_pack_daemons(self):
        self.write_config(f'[packs]\npaths = ["{self.pack}"]\n[daemons]\ndisabled = ["report"]\n')
        cfg = config.Config.load()
        self.assertNotIn("report", cfg.discover())
        self.assertEqual(config.validate(cfg), [])

    def test_declared_pack_commands_dirs_fill_from_packs(self):
        daemon(self.root / "catalog" / "cmds", "cmds", "pack_commands_dirs = []")
        cfg = config.Config.load()
        self.assertEqual(
            cfg.daemon("cmds")["inputs"]["pack_commands_dirs"], [str(self.pack / "commands")]
        )
        self.assertNotIn("pack_commands_dirs", cfg.daemon("watcher")["inputs"])

    def test_describe_packs_lists_what_each_adds(self):
        out = config.describe_packs(config.Config.load())
        self.assertIn("daemons    report", out)
        self.assertIn("overrides  watcher", out)
        self.assertIn("profiles   sc", out)
        self.assertIn("commands   deploy", out)

    def test_no_packs(self):
        self.write_config()
        cfg = config.Config.load()
        self.assertEqual(cfg.packs, [])
        self.assertIn("no packs configured", config.describe_packs(cfg))

    def test_catalog_lists_pack_daemons_after_the_install_roots(self):
        catalog = config.Config.load().catalog()
        self.assertEqual(list(catalog), ["watcher", "report"])
        self.assertEqual(catalog["report"]["source"], self.pack.name)

    def test_sync_pulls_only_clean_git_packs(self):
        self.assertEqual(sync.pull_packs([self.pack]), [])  # not a git checkout
        os.system(f"git -C {self.pack} init -q && git -C {self.pack} add -A >/dev/null")
        notes = sync.pull_packs([self.pack])
        self.assertEqual(notes, [f"pack {self.pack}: local changes, not pulled"])


if __name__ == "__main__":
    unittest.main()
