import importlib
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT))


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text))


class MaterializeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        write(
            self.root / "config" / "daimon.toml",
            f"""
            [core]
            install_root = "{self.root}"
            state_dir = "{self.root}/state"
            namespace = "testns"
        """,
        )
        write(
            self.root / "daemons" / "alpha" / "daemon.toml",
            """
            [daemon]
            schedule = { interval = 1200 }
            command = "/alpha"
        """,
        )
        write(
            self.root / "daemons" / "alpha" / "skill" / "SKILL.md",
            "---\nname: alpha\ndescription: a\n---\nHi.\n",
        )
        os.environ["DAIMON_CONFIG"] = str(self.root / "config" / "daimon.toml")
        os.environ["HOME"] = str(self.home)
        self.config = importlib.import_module("config")
        importlib.reload(self.config)
        self.sync = importlib.import_module("daimon.sync")
        importlib.reload(self.sync)

    def tearDown(self):
        self.tmp.cleanup()

    def test_materialize_renders_skill_into_claude_skills(self):
        cfg, _ = self.sync.materialize(self.config)
        self.assertIn("alpha", cfg.discover())
        skill = self.home / ".claude" / "skills" / "alpha" / "SKILL.md"
        self.assertTrue(skill.exists())
        self.assertIn("Hi.", skill.read_text())

    def test_materialize_creates_launch_agents_on_macos(self):
        agents = self.home / "Library" / "LaunchAgents"
        self.assertFalse(agents.exists())
        with patch.object(self.sync.sys, "platform", "darwin"):
            self.sync.materialize(self.config)
        self.assertTrue((agents / "com.testns.alpha.plist").exists())

    def test_materialize_without_create_missing_skips_unregistered(self):
        agents = self.home / "Library" / "LaunchAgents"
        with patch.object(self.sync.sys, "platform", "darwin"):
            _, skipped = self.sync.materialize(self.config, create_missing=False)
        self.assertEqual(skipped, ["alpha"])
        self.assertFalse((agents / "com.testns.alpha.plist").exists())
        skill = self.home / ".claude" / "skills" / "alpha" / "SKILL.md"
        self.assertTrue(skill.exists())

    def test_materialize_without_create_missing_refreshes_existing(self):
        agents = self.home / "Library" / "LaunchAgents"
        agents.mkdir(parents=True)
        plist = agents / "com.testns.alpha.plist"
        plist.write_text("stale")
        with patch.object(self.sync.sys, "platform", "darwin"):
            _, skipped = self.sync.materialize(self.config, create_missing=False)
        self.assertEqual(skipped, [])
        self.assertNotEqual(plist.read_text(), "stale")


if __name__ == "__main__":
    unittest.main()
