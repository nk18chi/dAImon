#!/usr/bin/env python3
"""This machine's daemon status as one JSON document, for [status].command.

    {"agents": [{"name": "<slug>", "state": "working|idle|blocked",
                 "role": "<role>", "note": "<=40 chars"}]}

One entry per discovered daemon that is loaded in launchd; `role` and `note`
appear only when set. `build` is pure (tests inject the sets); `main` gathers
launchd, tmux and throttle state and prints the document.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

MAX_AGENTS = 32
MAX_NOTE = 40
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


def build(cfg: config.Config, loaded: set[str], running: set[str], throttle_level: str) -> dict:
    """`loaded` / `running` are daemon slugs: loaded in launchd / with a live session."""
    # Throttle-exempt daemons still run under a halt, so they are not blocked.
    halted = throttle_level == "halt"
    exempt = set(cfg.throttle.get("exempt", []))
    slugs = [s for s in cfg.discover() if s in loaded and NAME_PATTERN.match(s)]
    agents = []
    for slug in slugs[:MAX_AGENTS]:
        state, note = _state(slug in running, halted and slug not in exempt)
        entry = {"name": slug, "state": state}
        role = cfg.daemon(slug).get("role")
        if role:
            entry["role"] = str(role)
        if note:
            entry["note"] = note[:MAX_NOTE]
        agents.append(entry)
    return {"agents": agents}


def _state(working: bool, halted: bool) -> tuple[str, str]:
    """(state, note) for one daemon: a live session wins over a throttle halt."""
    if working:
        return "working", ""
    if halted:
        return "blocked", "throttled"
    return "idle", ""


def loaded_slugs(launchctl_list: str, namespace: str, slugs: list[str]) -> set[str]:
    """Slugs whose `com.<ns>.<slug>` label appears in `launchctl list` output."""
    labels = {line.split("\t")[-1].strip() for line in launchctl_list.splitlines()}
    return {s for s in slugs if f"com.{namespace}.{s}" in labels}


def running_slugs(sessions: list[str], namespace: str, slugs: list[str]) -> set[str]:
    """Slugs with a tmux session named `<ns>-<slug>` or `<ns>-<slug>-<backend>`."""
    live = set(sessions)
    out = set()
    for s in slugs:
        names = {f"{namespace}-{s}"} | {f"{namespace}-{s}-{be}" for be in config.BACKENDS}
        if names & live:
            out.add(s)
    return out


def throttle_level(path: Path, now: float | None = None) -> str:
    """The active throttle level in runtime/throttle.json, honoring expires_at."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return "off"
    if not isinstance(data, dict):
        return "off"
    level = str(data.get("level") or "off")
    try:
        exp = int(float(data.get("expires_at") or 0))
    except (TypeError, ValueError):
        exp = 0  # non-numeric reads as "no expiry", as in throttle.sh
    if exp > 0 and (time.time() if now is None else now) > exp:
        return "off"
    return level


def _run(argv: list[str]) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def gather(cfg: config.Config) -> dict:
    ns = cfg.core["namespace"]
    slugs = list(cfg.discover())
    loaded = loaded_slugs(_run(["launchctl", "list"]), ns, slugs)
    sessions = _run(["tmux", "ls", "-F", "#{session_name}"]).split()
    running = running_slugs(sessions, ns, slugs)
    level = throttle_level(cfg.state_dir / "runtime" / "throttle.json")
    return build(cfg, loaded, running, level)


def main() -> int:
    print(json.dumps(gather(config.Config.load()), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
