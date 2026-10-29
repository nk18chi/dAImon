import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import inbox_take  # noqa: E402


class InboxTakeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.inbox = root / "runtime" / "inbox.json"
        self.state = root / "state" / "ask.json"
        self.inbox.parent.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _queue(self, *messages):
        self.inbox.write_text(json.dumps({"messages": list(messages)}))

    def _take(self):
        return inbox_take.take(self.inbox, self.state, "ask")

    def test_takes_only_own_messages_and_leaves_the_rest(self):
        self._queue(
            {"to": "ask", "channel": "C1", "ts": "1.0"},
            {"to": "other", "channel": "C1", "ts": "2.0"},
        )
        self.assertEqual([m["ts"] for m in self._take()], ["1.0"])
        left = json.loads(self.inbox.read_text())["messages"]
        self.assertEqual([m["to"] for m in left], ["other"])

    def test_drops_already_handled_messages(self):
        self._queue({"to": "ask", "channel": "C1", "ts": "1.0"})
        self._take()
        self._queue(
            {"to": "ask", "channel": "C1", "ts": "1.0"},
            {"to": "ask", "channel": "C1", "ts": "3.0"},
        )
        self.assertEqual([m["ts"] for m in self._take()], ["3.0"])
        handled = json.loads(self.state.read_text())["handled_keys"]
        self.assertEqual(handled, ["C1:1.0", "C1:3.0"])

    def test_message_without_ts_is_never_deduped(self):
        self._queue({"to": "ask", "channel": "C1"})
        self._take()
        self._queue({"to": "ask", "channel": "C1"})
        self.assertEqual(len(self._take()), 1)

    def test_missing_or_corrupt_inbox_yields_nothing(self):
        self.assertEqual(self._take(), [])
        self.inbox.write_text("not json")
        self.assertEqual(self._take(), [])
        self.assertFalse(self.state.exists())

    def test_usage_error(self):
        self.assertEqual(inbox_take.main(["drain", "ask"]), 2)


if __name__ == "__main__":
    unittest.main()
