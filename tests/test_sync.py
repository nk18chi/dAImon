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
            self.root / "catalog" / "alpha" / "daemon.toml",
            """
            [daemon]
            schedule = { interval = 1200 }
            command = "/alpha"
        """,
        )
        write(
            self.root / "catalog" / "alpha" / "skill" / "SKILL.md",
            "---\nname: alpha\ndescription: a\n---\nHi.\n",
        )
        os.environ["DAIMON_CONFIG"] = str(self.root / "config" / "daimon.toml")
        os.environ["HOME"] = str(self.home)
        self.config = importlib.import_module("config")
        importlib.reload(self.config)
        self.sync = importlib.import_module("daimon.sync")
        importlib.reload(self.sync)
        # Never touch the real launchd from tests; record the calls instead.
        self.calls: list[tuple] = []
        self.loaded_state = None  # None = not loaded, else the `print` stdout

        def fake_launchctl(*args):
            self.calls.append(args)
            ok = args[0] != "print" or self.loaded_state is not None
            out = self.loaded_state or "" if args[0] == "print" else ""
            return self.sync.subprocess.CompletedProcess(args, 0 if ok else 113, out, "")

        patcher = patch.object(self.sync, "_launchctl", side_effect=fake_launchctl)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def _auto_update(self, on: bool):
        cfg = self.root / "config" / "daimon.toml"
        text = cfg.read_text().split("[update]")[0]
        cfg.write_text(text + f"[update]\nauto = {'true' if on else 'false'}\n")

    def test_updater_is_written_and_loaded_when_auto_is_on(self):
        self._auto_update(True)
        with patch.object(self.sync.sys, "platform", "darwin"):
            self.sync.materialize(self.config)
        plist = self.home / "Library" / "LaunchAgents" / "com.testns.update.plist"
        text = plist.read_text()
        self.assertIn("self_update.sh", text)
        self.assertIn("<key>RunAtLoad</key>\n    <true/>", text)
        self.assertIn(("bootstrap", f"gui/{os.getuid()}", str(plist)), self.calls)

    def test_updater_is_unloaded_and_removed_when_auto_turns_off(self):
        self._auto_update(True)
        with patch.object(self.sync.sys, "platform", "darwin"):
            self.sync.materialize(self.config)
            self._auto_update(False)
            self.sync.materialize(self.config)
        plist = self.home / "Library" / "LaunchAgents" / "com.testns.update.plist"
        self.assertFalse(plist.exists())
        self.assertIn(("bootout", f"gui/{os.getuid()}/com.testns.update"), self.calls)

    def test_no_updater_by_default_and_watchdog_not_run_at_load(self):
        with patch.object(self.sync.sys, "platform", "darwin"):
            self.sync.materialize(self.config)
        agents = self.home / "Library" / "LaunchAgents"
        self.assertFalse((agents / "com.testns.update.plist").exists())
        self.assertIn(
            "<key>RunAtLoad</key>\n    <false/>", (agents / "com.testns.watchdog.plist").read_text()
        )

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

    def _changed_plist(self):
        agents = self.home / "Library" / "LaunchAgents"
        agents.mkdir(parents=True)
        (agents / "com.testns.alpha.plist").write_text("stale")

    def test_changed_plist_reloads_a_loaded_idle_job(self):
        self._changed_plist()
        self.loaded_state = "state = not running"
        with patch.object(self.sync.sys, "platform", "darwin"):
            self.sync.materialize(self.config, create_missing=False)
        verbs = [c[0] for c in self.calls if c[0] != "print"]
        self.assertIn("bootout", verbs)
        self.assertIn("bootstrap", verbs)
        self.assertIn("com.testns.alpha: reloaded", self.sync.RELOAD_NOTES)

    def test_changed_plist_leaves_a_running_job_alone(self):
        self._changed_plist()
        self.loaded_state = "state = running"
        with patch.object(self.sync.sys, "platform", "darwin"):
            self.sync.materialize(self.config, create_missing=False)
        self.assertFalse([c for c in self.calls if c[0] in ("bootout", "bootstrap")])
        self.assertTrue(any("running" in n for n in self.sync.RELOAD_NOTES))

    def test_unloaded_or_unchanged_plist_is_not_reloaded(self):
        self._changed_plist()
        with patch.object(self.sync.sys, "platform", "darwin"):
            self.sync.materialize(self.config, create_missing=False)  # not loaded
            self.loaded_state = "state = not running"
            self.calls.clear()
            self.sync.materialize(self.config, create_missing=False)  # unchanged now
        self.assertFalse([c for c in self.calls if c[0] in ("bootout", "bootstrap")])


if __name__ == "__main__":
    unittest.main()
