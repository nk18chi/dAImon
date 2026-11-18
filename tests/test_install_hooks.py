import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("install_hooks", ROOT / "lib" / "install_hooks.py")
install_hooks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(install_hooks)

OLD = '[ -n "$DAIMON_SENTINEL" ] && touch "$DAIMON_SENTINEL"; true'
NEW = '[ -n "$DAIMON_SENTINEL" ] && grep -qF "$DAIMON_AGENT_SESSION" && touch "$DAIMON_SENTINEL"; true'
USER = "echo user-stop-hook"


def entry(cmd):
    return {"hooks": [{"type": "command", "command": cmd}]}


class InstallHooksTest(unittest.TestCase):
    def run_install(self, existing, shipped):
        with tempfile.TemporaryDirectory() as d:
            settings, hooks = Path(d) / "settings.json", Path(d) / "hooks.json"
            settings.write_text(json.dumps({"hooks": existing}))
            hooks.write_text(json.dumps(shipped))
            install_hooks.main([str(settings), str(hooks)])
            return json.loads(settings.read_text())["hooks"]

    def test_outdated_sentinel_hook_is_replaced(self):
        out = self.run_install({"Stop": [entry(USER), entry(OLD)]}, {"Stop": [entry(NEW)]})
        cmds = [h["command"] for e in out["Stop"] for h in e["hooks"]]
        self.assertEqual(cmds, [USER, NEW])

    def test_current_sentinel_hook_is_not_duplicated(self):
        out = self.run_install({"Stop": [entry(NEW)]}, {"Stop": [entry(NEW)]})
        self.assertEqual(len(out["Stop"]), 1)

    def test_other_hooks_are_kept(self):
        out = self.run_install({"PostToolUse": [entry(USER)]}, {"Stop": [entry(NEW)]})
        self.assertEqual(out["PostToolUse"], [entry(USER)])


if __name__ == "__main__":
    unittest.main()
