import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import bridge_service  # noqa: E402

import config  # noqa: E402


class BridgeServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bdir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _ready(self, env_text):
        (self.bdir / ".env").write_text(env_text)
        (self.bdir / "manifest.json").write_text("{}")
        (self.bdir / "node_modules").mkdir()

    def test_read_env_handles_comments_blanks_and_quotes(self):
        (self.bdir / ".env").write_text(
            "# comment\n\nSLACK_BOT_TOKEN='xoxb-1'\nDAIMON_BIN=\"/x/daimon\"\nnot a pair\n"
        )
        self.assertEqual(
            bridge_service.read_env(self.bdir / ".env"),
            {"SLACK_BOT_TOKEN": "xoxb-1", "DAIMON_BIN": "/x/daimon"},
        )

    def test_ready_when_both_tokens_and_setup_are_there(self):
        self._ready("SLACK_BOT_TOKEN=xoxb-1\nSLACK_APP_TOKEN=xapp-1\n")
        self.assertEqual(bridge_service.problems(self.bdir), [])

    def test_names_each_missing_or_swapped_token(self):
        # A bot token pasted into the app-token slot is the likely mistake.
        self._ready("SLACK_BOT_TOKEN=xoxb-1\nSLACK_APP_TOKEN=xoxb-2\n")
        issues = bridge_service.problems(self.bdir)
        self.assertEqual(len(issues), 1)
        self.assertIn("SLACK_APP_TOKEN", issues[0])

    def test_no_env_no_setup_lists_everything(self):
        issues = bridge_service.problems(self.bdir)
        self.assertEqual(len(issues), 4)

    def test_plist_is_a_kept_alive_service_with_quiet_logs(self):
        cfg = config.Config.load()
        plist = plistlib.loads(bridge_service.render(cfg, "/usr/local/bin/node").encode())
        ns = cfg.core["namespace"]
        self.assertEqual(plist["Label"], f"com.{ns}.bridge")
        self.assertEqual(plist["ProgramArguments"], ["/usr/local/bin/node", "app.js"])
        self.assertTrue(plist["RunAtLoad"])
        self.assertTrue(plist["KeepAlive"])
        self.assertEqual(plist["EnvironmentVariables"]["BRIDGE_LOG_LEVEL"], "info")
        self.assertEqual(plist["EnvironmentVariables"]["DAIMON_NS"], ns)
        self.assertTrue(plist["WorkingDirectory"].endswith("bridges/env-bridge"))

    def test_scheduled_daemon_plists_still_do_not_run_at_load(self):
        cfg = config.Config.load()
        plist = plistlib.loads(config.render_watchdog_plist(cfg).encode())
        self.assertFalse(plist["RunAtLoad"])
        self.assertNotIn("KeepAlive", plist)

    def test_usage_error(self):
        with mock.patch.object(config.Config, "load"):
            self.assertEqual(bridge_service.main(["start"]), 2)


if __name__ == "__main__":
    unittest.main()
