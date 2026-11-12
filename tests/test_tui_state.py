import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tui"))
import state  # noqa: E402

CFG = SimpleNamespace(core={"namespace": "daimon"})


class BridgeStateTest(unittest.TestCase):
    """The control panel's Slack-bridge line reads `launchctl list`: PID,
    last exit status, label — with "-" as the PID while it isn't running."""

    def test_running_shows_its_pid(self):
        listing = "PID\tStatus\tLabel\n4242\t0\tcom.daimon.bridge\n-\t0\tcom.daimon.watchdog\n"
        self.assertEqual(state.bridge_state(CFG, listing), ("running", "4242"))

    def test_loaded_without_pid_is_between_restarts(self):
        listing = "-\t1\tcom.daimon.bridge\n"
        self.assertEqual(state.bridge_state(CFG, listing), ("loaded", None))

    def test_absent_is_off_and_a_lookalike_label_does_not_count(self):
        listing = "4242\t0\tcom.daimon.bridge-old\n77\t0\tcom.other.bridge\n"
        self.assertEqual(state.bridge_state(CFG, listing), ("off", None))


if __name__ == "__main__":
    unittest.main()
