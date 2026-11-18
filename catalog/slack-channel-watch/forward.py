#!/usr/bin/env python3
"""Scripted channel watcher: read watched Slack channels since last_ts,
select trigger-prefixed command messages — top-level AND thread replies —
append them to the target daemon's inbox, and update per-channel state.
Stdlib only; runs from discover.sh so no agent has to launch just to poll.

Thread replies never appear in conversations.history, so threads are found
via each parent's latest_reply watermark and read with conversations.replies.

usage: forward.py <state_file> <inbox_file>
env:   SLACK_TOKEN, DAIMON_INPUT_WATCH_CHANNELS (space-separated ids),
       DAIMON_INPUT_TRIGGER_PREFIX, DAIMON_INPUT_TARGET
Prints the number of commands forwarded."""

import json
import os
import sys
import urllib.parse
import urllib.request


def _slack_get(token: str, method: str, params: dict) -> dict:
    url = f"https://slack.com/api/{method}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.load(resp)
    if not data.get("ok"):
        raise RuntimeError(
            f"{method} {params.get('channel')}: slack api error: {data.get('error')}"
        )
    return data


def fetch_history(token: str, channel: str) -> list[dict]:
    return _slack_get(token, "conversations.history", {"channel": channel, "limit": 50}).get(
        "messages", []
    )


def fetch_replies(token: str, channel: str, thread_ts: str, oldest: str) -> list[dict]:
    params = {"channel": channel, "ts": thread_ts, "limit": 50}
    if oldest:
        params["oldest"] = oldest
    return _slack_get(token, "conversations.replies", params).get("messages", [])


def _is_command(msg: dict, prefix: str, after: str) -> bool:
    return (
        bool(msg.get("user"))
        and not msg.get("bot_id")
        and float(msg["ts"]) > float(after or 0)
        and msg.get("text", "").startswith(prefix)
    )


def select_top_level(messages: list[dict], prefix: str, after: str) -> list[dict]:
    return [m for m in messages if not m.get("thread_ts") and _is_command(m, prefix, after)]


def select_replies(messages: list[dict], prefix: str, after: str) -> list[dict]:
    """Replies only — the parent shows up in conversations.replies too."""
    return [
        m for m in messages if m.get("thread_ts") != m.get("ts") and _is_command(m, prefix, after)
    ]


def to_inbox_entry(msg: dict, channel: str, prefix: str, target: str) -> dict:
    return {
        "to": target,
        "command": msg["text"][len(prefix) :].strip(),
        # the message's own ts is the engine's dedupe key;
        # replies thread under their parent, top-level under themselves
        "ts": msg["ts"],
        "thread_ts": msg.get("thread_ts") or msg["ts"],
        "channel": channel,
        "user": msg["user"],
        "via": "channel",
    }


def load_json(path: str, default: dict) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def dump_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _channel_commands(token: str, channel: str, after: str, prefix: str, fetch, fetch_r):
    """All new commands in one channel plus the new high-water mark.

    A channel with no watermark yet gets a baseline-only pass: record the
    high-water mark, forward nothing — otherwise the first sight of a
    channel would replay old commands and fan out a replies fetch per
    thread."""
    messages = fetch(token, channel)
    if not after:
        return [], max((m["ts"] for m in messages), key=float, default="")
    commands = select_top_level(messages, prefix, after)
    marks = [m["ts"] for m in messages]
    for parent in messages:
        latest = parent.get("latest_reply", "")
        if latest and float(latest) > float(after or 0):
            replies = fetch_r(token, channel, parent["ts"], after)
            commands += select_replies(replies, prefix, after)
            marks.append(latest)
    mark = max(marks, key=float, default=after)
    return commands, mark


def forward(state_file: str, inbox_file: str, fetch=fetch_history, fetch_r=fetch_replies) -> int:
    token = os.environ["SLACK_TOKEN"]
    channels = os.environ["DAIMON_INPUT_WATCH_CHANNELS"].split()
    prefix = os.environ.get("DAIMON_INPUT_TRIGGER_PREFIX", "?")
    target = os.environ.get("DAIMON_INPUT_TARGET", "slack-commands")

    state = load_json(state_file, {})
    last_ts = state.get("last_ts", {})
    inbox = load_json(inbox_file, {"messages": []})
    forwarded = 0

    for channel in channels:
        after = last_ts.get(channel, "")
        commands, mark = _channel_commands(token, channel, after, prefix, fetch, fetch_r)
        for msg in commands:
            inbox.setdefault("messages", []).append(to_inbox_entry(msg, channel, prefix, target))
            forwarded += 1
        if mark:
            last_ts[channel] = mark

    if forwarded:
        dump_json(inbox_file, inbox)
    state["last_ts"] = last_ts
    dump_json(state_file, state)
    return forwarded


if __name__ == "__main__":
    print(forward(sys.argv[1], sys.argv[2]))
