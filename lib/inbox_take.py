#!/usr/bin/env python3
"""`daimon inbox take <slug> [--one]`: remove a daemon's queued inbox messages
and print the ones it has not handled yet, as a JSON list. `--one` takes only
the oldest, so each run answers one message; launch.sh starts the next run
while more are queued.

This exists so an agent restricted by a tools allowlist can drain its inbox with
one exact command instead of needing python/jq/shell access. Dedupe on
(channel, ts) is recorded here too, in the daemon's own state record, so a
re-forwarded message is dropped structurally rather than by prompt discipline.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

HANDLED_KEEP = 200


def _load(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _write_atomic(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def take(inbox_path: Path, state_path: Path, slug: str, limit: int | None = None) -> list[dict]:
    """Remove and return the slug's unhandled messages, oldest first. With a
    limit, stop after that many fresh ones and leave the rest queued."""
    inbox = _load(inbox_path, {})
    messages = inbox.get("messages", []) if isinstance(inbox, dict) else []
    state = _load(state_path, {})
    if not isinstance(state, dict):
        state = {}
    handled = list(state.get("handled_keys", []))
    seen = set(handled)
    mine = [m for m in messages if m.get("to") == slug]
    if limit is not None:
        # A person's question goes before automatic work (a first look at a new
        # report): someone is waiting on it. Stable, so each group stays oldest-first.
        mine.sort(key=lambda m: m.get("via") == "report")
    fresh, taken = [], set()
    for m in mine:
        if limit is not None and len(fresh) >= limit:
            break
        taken.add(id(m))
        key = f"{m.get('channel', '')}:{m.get('ts', '')}"
        # A message without a ts has no stable identity; pass it through rather
        # than collapse every such message onto one key.
        if m.get("ts") and key in seen:
            continue
        if m.get("ts"):
            seen.add(key)
            handled.append(key)
        fresh.append(m)
    keep = [m for m in messages if id(m) not in taken]
    if len(keep) == len(messages):
        return []
    _write_atomic(inbox_path, {"messages": keep})
    state["handled_keys"] = handled[-HANDLED_KEEP:]
    _write_atomic(state_path, state)
    return fresh


def main(argv: list[str]) -> int:
    one = argv[2:] == ["--one"]
    if len(argv) not in (2, 3) or argv[0] != "take" or (len(argv) == 3 and not one):
        print("usage: daimon inbox take <slug> [--one]", file=sys.stderr)
        return 2
    slug = argv[1]
    state_dir = config.Config.load().state_dir
    msgs = take(
        state_dir / "runtime" / "inbox.json",
        state_dir / "state" / f"{slug}.json",
        slug,
        limit=1 if one else None,
    )
    print(json.dumps(msgs, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
