"""Read-only queries the control panel renders: session, launchd, log, throttle."""

import json
import os
import subprocess
import time
from pathlib import Path


def sh(*cmd: str) -> str:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def label_for(cfg, slug: str) -> str:
    return f"com.{cfg.core['namespace']}.{slug}"


def candidate_sessions(cfg, slug: str) -> list[str]:
    ns = cfg.core["namespace"]
    return [f"{ns}-{slug}", *(f"{ns}-{slug}-{backend}" for backend in cfg.backends(slug))]


def live_sessions() -> set[str]:
    return set(sh("tmux", "ls", "-F", "#{session_name}").splitlines())


def loaded_labels_text() -> str:
    return sh("launchctl", "list")


def running_session(cfg, slug: str, sessions: set[str] | None = None) -> str | None:
    live = sessions if sessions is not None else live_sessions()
    for s in candidate_sessions(cfg, slug):
        if s in live:
            return s
    return None


def session_runtime(session: str) -> str:
    return sh("tmux", "display-message", "-p", "-t", session, "#{session_activity}") and sh(
        "tmux", "display-message", "-p", "-t", session, "#{t:session_created}"
    )


def launchd_loaded(label: str, text: str | None = None) -> bool:
    listing = text if text is not None else sh("launchctl", "list")
    return any(label in line for line in listing.splitlines())


def bridge_state(cfg, listing: str | None = None) -> tuple[str, str | None]:
    """The env-bridge service from `launchctl list` (PID, status, label per line;
    PID "-" = loaded but not running): ("running", pid) | ("loaded", None) |
    ("off", None)."""
    label = f"com.{cfg.core['namespace']}.bridge"
    text = listing if listing is not None else sh("launchctl", "list")
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2] == label:
            return ("running", parts[0]) if parts[0].isdigit() else ("loaded", None)
    return ("off", None)


def plist_path(cfg, slug: str) -> Path:
    return Path(os.path.expanduser(f"~/Library/LaunchAgents/{label_for(cfg, slug)}.plist"))


def registered(cfg, slug: str) -> bool:
    return plist_path(cfg, slug).exists()


def last_log(cfg, slug: str) -> str:
    path = cfg.state_dir / "logs" / f"{slug}.log"
    if not path.exists():
        return ""
    lines = path.read_text(errors="replace").splitlines()
    return lines[-1][:80] if lines else ""


def _ps_snapshot() -> dict:
    snap = {}
    for line in sh("ps", "-axo", "pid=,ppid=,rss=,command=").splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[0].isdigit():
            snap[int(parts[0])] = (int(parts[1]), int(parts[2]), parts[3])
    return snap


def _pane_pid(session: str) -> int | None:
    out = sh("tmux", "list-panes", "-t", session, "-F", "#{pane_pid}").splitlines()
    return int(out[0]) if out and out[0].isdigit() else None


def _label(cmd: str) -> str:
    low = cmd.lower()
    if "claude" in low:
        return "claude"
    if "codex" in low:
        return "codex"
    if "mcp" in low or "npx" in low:
        return "mcp"
    if "node" in low:
        return "node"
    return (cmd.split() or ["?"])[0].rsplit("/", 1)[-1][:10]


def session_procs(cfg, slug: str) -> list[tuple[int, float, str]]:
    if not running_session(cfg, slug):
        return []
    snap = _ps_snapshot()
    kids: dict[int, list[int]] = {}
    for pid, (ppid, _, _) in snap.items():
        kids.setdefault(ppid, []).append(pid)
    procs, seen = [], set()
    for sess in candidate_sessions(cfg, slug):
        root = _pane_pid(sess)
        stack = [root] if root else []
        while stack:
            cur = stack.pop()
            if cur in seen or cur not in snap:
                continue
            seen.add(cur)
            ppid, rss, cmd = snap[cur]
            procs.append((cur, rss / 1024, _label(cmd)))
            stack.extend(kids.get(cur, []))
    return procs


def throttle_level(cfg) -> str:
    path = cfg.state_dir / "runtime" / "throttle.json"
    if not path.exists():
        return "off"
    try:
        d = json.loads(path.read_text())
    except (ValueError, OSError):
        return "off"
    if d.get("expires_at") and time.time() > d["expires_at"]:
        return "off"
    return d.get("level", "off")
