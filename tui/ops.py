"""Side-effecting control-panel actions: launchd, throttle, plist regen, kill."""

import json
import os
import shutil
import subprocess
import sys
import time

from _lib import INSTALL_ROOT
from state import label_for, plist_path

THROTTLE_CYCLE = ["off", "moderate", "severe", "halt"]


def _gui() -> str:
    return f"gui/{os.getuid()}"


def regen_plist(cfg, slug: str) -> None:
    plist_path(cfg, slug).write_text(cfg_render_plist(cfg, slug))


def cfg_render_plist(cfg, slug: str) -> str:
    import config

    return config.render_plist(cfg, slug)


def run_now(cfg, slug: str) -> None:
    # The binding promises "run now (bypass gates)": launch.sh directly.
    # kickstarting the launchd job runs the plist program — the gated run.sh
    # path — so a manual run would still be skipped by discovery/throttle.
    subprocess.Popen(
        ["bash", str(INSTALL_ROOT / "lib" / "launch.sh"), slug],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def enable(cfg, slug: str) -> None:
    subprocess.run(["launchctl", "bootstrap", _gui(), str(plist_path(cfg, slug))], check=False)


def disable(cfg, slug: str) -> None:
    subprocess.run(["launchctl", "bootout", f"{_gui()}/{label_for(cfg, slug)}"], check=False)


def register(cfg, slug: str) -> None:
    regen_plist(cfg, slug)
    enable(cfg, slug)


def unregister(cfg, slug: str) -> None:
    disable(cfg, slug)
    plist_path(cfg, slug).unlink(missing_ok=True)


def kill_run(cfg, slug: str) -> None:
    subprocess.run(["bash", str(INSTALL_ROOT / "lib" / "kill.sh"), slug], check=False)


def duplicate(cfg, src: str, new: str) -> None:
    # exclude daemon.local.toml: the clone targets a different repo, so working_dir starts fresh
    shutil.copytree(
        cfg.daemon_dir(src),
        cfg.daemons_dir() / new,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "daemon.local.toml"),
    )
    cfg.update_daemon_field(new, "command", f"/{new}")


def bridge(action: str) -> tuple[bool, str]:
    """Start ("install") or stop ("uninstall") the env-bridge service through the
    same code as `daimon bridge service`, so its token checks apply here too.
    Output is captured for a notification instead of drawn over the TUI."""
    res = subprocess.run(
        [sys.executable, str(INSTALL_ROOT / "lib" / "bridge_service.py"), action],
        capture_output=True,
        text=True,
        check=False,
    )
    return res.returncode == 0, (res.stdout + res.stderr).strip()


def builder_argv() -> list[str]:
    return ["claude", "/daimon-builder"]


def configure_argv(slug: str) -> list[str]:
    return ["claude", f"/daimon-configure {slug}"]


def cycle_throttle(cfg) -> str:
    path = cfg.state_dir / "runtime" / "throttle.json"
    cur = "off"
    if path.exists():
        try:
            cur = json.loads(path.read_text()).get("level", "off")
        except (ValueError, OSError):
            cur = "off"
    nxt = (
        THROTTLE_CYCLE[(THROTTLE_CYCLE.index(cur) + 1) % len(THROTTLE_CYCLE)]
        if cur in THROTTLE_CYCLE
        else "off"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    expires = time.time() + 3600 if nxt != "off" else None
    path.write_text(
        json.dumps(
            {"level": nxt, "set_at": time.time(), "expires_at": expires, "reason": "set via TUI"}
        )
    )
    return nxt
