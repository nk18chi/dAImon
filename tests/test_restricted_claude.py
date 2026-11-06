import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import restricted_claude  # noqa: E402


class RestrictedClaudeTest(unittest.TestCase):
    def test_servers_named_from_mcp_rules_only(self):
        tools = [
            "Read",
            "Bash(pup logs search:*)",
            "mcp__mongo-x__find",
            "mcp__mongo-x__count",
            "mcp__hubspot__get",
        ]
        self.assertEqual(restricted_claude.servers_named(tools), ["mongo-x", "hubspot"])

    def test_writes_hooks_and_only_the_named_servers_privately(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as out:
            Path(home, ".claude.json").write_text(
                json.dumps(
                    {"mcpServers": {"mongo-x": {"command": "npx"}, "other": {"command": "x"}}}
                )
            )
            env = {"DAIMON_D_TOOLS": "Read 'mcp__mongo-x__find' 'mcp__absent__get'"}
            with (
                mock.patch.dict(os.environ, env),
                mock.patch.object(Path, "home", return_value=Path(home)),
            ):
                self.assertEqual(restricted_claude.main([out]), 0)

            mcp = json.loads(Path(out, "mcp.json").read_text())
            self.assertEqual(mcp, {"mcpServers": {"mongo-x": {"command": "npx"}}})
            settings = json.loads(Path(out, "settings.json").read_text())
            self.assertEqual(set(settings), {"hooks"})
            self.assertIn("Stop", settings["hooks"])
            for name in ("mcp.json", "settings.json"):
                self.assertEqual(stat.S_IMODE(Path(out, name).stat().st_mode), 0o600, name)


if __name__ == "__main__":
    unittest.main()
