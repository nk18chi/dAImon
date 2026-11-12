import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "channel_watch_forward", ROOT / "daemons" / "slack-channel-watch" / "forward.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fwd = _load()


def _read(path):
    with open(path) as f:
        return json.load(f)


def _write(path, data):
    with open(path, "w") as f:
        json.dump(data, f)


HUMAN_CMD = {"user": "U1", "ts": "2.0", "text": "?help"}
HUMAN_CHAT = {"user": "U1", "ts": "3.0", "text": "hello all"}
BOT_MSG = {"user": "U9", "bot_id": "B1", "ts": "5.0", "text": "?bot"}
PARENT_WITH_REPLIES = {"user": "U1", "ts": "2.0", "text": "?help", "latest_reply": "6.0"}
THREAD_PARENT_ROW = {"user": "U1", "ts": "2.0", "thread_ts": "2.0", "text": "?help"}
THREAD_CMD = {"user": "U2", "ts": "6.0", "thread_ts": "2.0", "text": "?staging status"}
THREAD_CHAT = {"user": "U2", "ts": "5.5", "thread_ts": "2.0", "text": "nice"}


class SelectTest(unittest.TestCase):
    def test_top_level_selects_only_new_human_prefixed(self):
        picked = fwd.select_top_level([HUMAN_CMD, HUMAN_CHAT, BOT_MSG, THREAD_CMD], "?", "1.0")
        self.assertEqual(picked, [HUMAN_CMD])

    def test_replies_exclude_the_parent_row(self):
        picked = fwd.select_replies([THREAD_PARENT_ROW, THREAD_CHAT, THREAD_CMD], "?", "4.0")
        self.assertEqual(picked, [THREAD_CMD])


class ForwardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, "state.json")
        self.inbox = os.path.join(self.tmp.name, "inbox.json")
        os.environ.update(
            SLACK_TOKEN="xoxb-test",
            DAIMON_INPUT_WATCH_CHANNELS="C1",
            DAIMON_INPUT_TRIGGER_PREFIX="?",
            DAIMON_INPUT_TARGET="engine",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, history, replies=None):
        return fwd.forward(
            self.state,
            self.inbox,
            fetch=lambda t, c: history,
            fetch_r=lambda t, c, ts, o: (replies or {}).get(ts, []),
        )

    def test_first_sight_baselines_without_forwarding(self):
        count = self._run([HUMAN_CMD, HUMAN_CHAT])
        self.assertEqual(count, 0)
        self.assertEqual(_read(self.state)["last_ts"], {"C1": "3.0"})
        self.assertFalse(os.path.exists(self.inbox))

    def test_forwards_new_top_level_after_baseline(self):
        _write(self.state, {"last_ts": {"C1": "1.0"}})
        count = self._run([HUMAN_CMD, HUMAN_CHAT])
        self.assertEqual(count, 1)
        entry = _read(self.inbox)["messages"][0]
        self.assertEqual(entry["command"], "help")
        self.assertEqual(entry["ts"], "2.0")
        self.assertEqual(entry["thread_ts"], "2.0")
        self.assertEqual(_read(self.state)["last_ts"], {"C1": "3.0"})

    def test_forwards_thread_replies_and_advances_to_latest_reply(self):
        _write(self.state, {"last_ts": {"C1": "4.0"}})
        replies = {"2.0": [THREAD_PARENT_ROW, THREAD_CHAT, THREAD_CMD]}
        count = self._run([PARENT_WITH_REPLIES, HUMAN_CHAT], replies)
        self.assertEqual(count, 1)
        entry = _read(self.inbox)["messages"][0]
        self.assertEqual(entry["command"], "staging status")
        self.assertEqual(entry["ts"], "6.0")
        self.assertEqual(entry["thread_ts"], "2.0")
        self.assertEqual(_read(self.state)["last_ts"], {"C1": "6.0"})

    def test_preserves_other_daemons_messages(self):
        _write(self.state, {"last_ts": {"C1": "1.0"}})
        _write(self.inbox, {"messages": [{"to": "other", "command": "x"}]})
        self._run([HUMAN_CMD])
        self.assertEqual([m["to"] for m in _read(self.inbox)["messages"]], ["other", "engine"])


if __name__ == "__main__":
    sys.exit(unittest.main())
