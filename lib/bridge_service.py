#!/usr/bin/env python3
"""`daimon bridge service install|uninstall|status`: run env-bridge as a
launchd service instead of `slack run` in a terminal.

The service runs the bridge's own `node app.js`, so it needs the two tokens
`slack run` otherwise supplies, in bridges/env-bridge/.env:

  SLACK_BOT_TOKEN=xoxb-...   OAuth & Permissions -> Bot User OAuth Token
  SLACK_APP_TOKEN=xapp-...   Basic Information -> App-Level Tokens
                             (scope connections:write; leave rotation off)

It starts at login, restarts if it exits, and logs to <state>/logs/bridge.log.
It still runs only while this Mac is awake.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

TOKEN_PREFIXES = {"SLACK_BOT_TOKEN": "xoxb-", "SLACK_APP_TOKEN": "xapp-"}


def bridge_dir(cfg: config.Config) -> Path:
    return cfg.install_root / "bridges" / "env-bridge"


def label(cfg: config.Config) -> str:
    return f"com.{cfg.core['namespace']}.bridge"


def plist_path(cfg: config.Config) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label(cfg)}.plist"


def log_path(cfg: config.Config) -> Path:
    return cfg.state_dir / "logs" / "bridge.log"


def read_env(path: Path) -> dict[str, str]:
    """KEY=VALUE lines of a dotenv file; comments, blanks, and quotes handled."""
    env = {}
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return env
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip("'\"")
    return env


def problems(bdir: Path) -> list[str]:
    """What stops the service from starting, in fix-it terms. Empty = ready."""
    out = []
    env = read_env(bdir / ".env")
    for key, prefix in TOKEN_PREFIXES.items():
        if not env.get(key, "").startswith(prefix):
            out.append(f"{key} missing from {bdir / '.env'} (should start with {prefix})")
    if not (bdir / "manifest.json").exists():
        out.append(f"{bdir / 'manifest.json'} missing — run `npm run setup` there")
    if not (bdir / "node_modules").is_dir():
        out.append(f"{bdir / 'node_modules'} missing — run `npm install` there")
    return out


def render(cfg: config.Config, node: str) -> str:
    return config.render_plist_raw(
        label=label(cfg),
        program=[node, "app.js"],
        working_dir=str(bridge_dir(cfg)),
        schedule_xml="",
        log=str(log_path(cfg)),
        keep_alive=True,
        # Debug logging (the `slack run` default) would fill the log with every
        # event; the queue note needs the namespace to find the bot's session.
        extra_env={"BRIDGE_LOG_LEVEL": "info", "DAIMON_NS": cfg.core["namespace"]},
    )


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def install(cfg: config.Config) -> int:
    bdir = bridge_dir(cfg)
    issues = problems(bdir)
    if issues:
        print("bridge service not installed:", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue}", file=sys.stderr)
        return 1
    node = shutil.which("node")
    if not node:
        print("node not found on PATH", file=sys.stderr)
        return 1
    plist = plist_path(cfg)
    plist.parent.mkdir(parents=True, exist_ok=True)
    log_path(cfg).parent.mkdir(parents=True, exist_ok=True)
    plist.write_text(render(cfg, node))
    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", domain, str(plist))  # replace a running copy, if any
    res = _launchctl("bootstrap", domain, str(plist))
    if res.returncode != 0:
        print(f"launchctl bootstrap failed: {res.stderr.strip()}", file=sys.stderr)
        return 1
    print(f"bridge service running ({label(cfg)}); log: {log_path(cfg)}")
    print("stop any `slack run` / `daimon bridge` terminal so only one bridge is connected")
    return 0


def uninstall(cfg: config.Config) -> int:
    plist = plist_path(cfg)
    _launchctl("bootout", f"gui/{os.getuid()}", str(plist))
    plist.unlink(missing_ok=True)
    print(f"bridge service removed ({label(cfg)})")
    return 0


def status(cfg: config.Config) -> int:
    res = _launchctl("list", label(cfg))
    if res.returncode != 0:
        print(f"bridge service not loaded ({label(cfg)})")
        return 1
    pid = next((ln for ln in res.stdout.splitlines() if '"PID"' in ln), None)
    state = f"running, pid {pid.split('=')[1].strip(' ;')}" if pid else "loaded, not running"
    print(f"bridge service {state}; log: {log_path(cfg)}")
    return 0


def main(argv: list[str]) -> int:
    actions = {"install": install, "uninstall": uninstall, "status": status}
    if len(argv) != 1 or argv[0] not in actions:
        print("usage: daimon bridge service install|uninstall|status", file=sys.stderr)
        return 2
    return actions[argv[0]](config.Config.load())


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
