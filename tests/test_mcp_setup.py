import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import mcp_setup  # noqa: E402


class McpSetupTest(unittest.TestCase):
    def test_callback_is_fixed_for_slack_endpoint(self):
        self.assertEqual(mcp_setup.callback_id(), "lukW65nqn7xj")
        self.assertEqual(
            mcp_setup.callback_url(),
            "http://127.0.0.1:3118/callback/lukW65nqn7xj",
        )

    def test_manifest_enables_mcp_and_pkce(self):
        manifest = mcp_setup.slack_manifest()
        self.assertTrue(manifest["settings"]["is_mcp_enabled"])
        self.assertTrue(manifest["oauth_config"]["pkce_enabled"])
        self.assertEqual(manifest["oauth_config"]["redirect_urls"], [mcp_setup.callback_url()])
        self.assertIn("search:read.private", manifest["oauth_config"]["scopes"]["user"])
        self.assertIn("chat:write", manifest["oauth_config"]["scopes"]["user"])

    @patch("mcp_setup.subprocess.run")
    def test_detects_official_slack_endpoint(self, run):
        run.return_value = subprocess.CompletedProcess(
            [],
            0,
            stdout=json.dumps({"transport": {"url": mcp_setup.SLACK_MCP_URL}}),
            stderr="",
        )
        self.assertTrue(mcp_setup.codex_slack_configured("codex"))

    @patch("mcp_setup.subprocess.run")
    def test_detects_authenticated_slack(self, run):
        run.return_value = subprocess.CompletedProcess(
            [],
            0,
            stdout=("Name Url Status Auth\nslack https://mcp.slack.com/mcp enabled OAuth\n"),
            stderr="",
        )
        self.assertTrue(mcp_setup.codex_slack_authenticated("codex"))

    @patch("mcp_setup.subprocess.run")
    def test_replaces_existing_config_and_adds_with_fixed_port(self, run):
        run.side_effect = [
            subprocess.CompletedProcess(
                [],
                0,
                stdout=json.dumps({"transport": {"url": mcp_setup.SLACK_MCP_URL}}),
            ),
            subprocess.CompletedProcess([], 0),
            subprocess.CompletedProcess([], 0),
        ]
        with (
            patch("mcp_setup.shutil.which", return_value="/bin/codex"),
            patch(
                "mcp_setup.get_or_create_slack_app",
                return_value={"client_id": "123.456"},
            ),
        ):
            self.assertEqual(mcp_setup.setup_codex_slack("codex"), 0)
        self.assertEqual(run.call_args_list[1].args[0], ["codex", "mcp", "remove", "slack"])
        add = run.call_args_list[2].args[0]
        self.assertEqual(add[:4], ["codex", "mcp", "add", "-c"])
        self.assertIn("mcp_oauth_callback_port=3118", add)
        self.assertIn("123.456", add)

    def test_saves_only_public_app_state(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "slack.json"
            with patch.dict("os.environ", {"DAIMON_SLACK_MCP_STATE": str(path)}):
                mcp_setup.save_state(
                    {
                        "app_id": "A123",
                        "client_id": "123.456",
                        "team_id": "T123",
                        "callback_url": mcp_setup.callback_url(),
                    }
                )
                self.assertEqual(mcp_setup.load_state()["client_id"], "123.456")
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_supplied_team_client_id_is_saved_for_sharing(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "slack.json"
            with patch.dict("os.environ", {"DAIMON_SLACK_MCP_STATE": str(path)}):
                app = mcp_setup.get_or_create_slack_app("123.456")
                self.assertEqual(app["client_id"], "123.456")
                self.assertEqual(mcp_setup.load_state()["client_id"], "123.456")


if __name__ == "__main__":
    unittest.main()
