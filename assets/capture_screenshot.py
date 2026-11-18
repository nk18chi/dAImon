"""Render a synthetic TUI screenshot for the README.

Uses only placeholder example data and faked daemon status — never the local
machine's real config, launchd, or tmux state. Regenerate with:

    tui/.venv/bin/python assets/capture_screenshot.py
    rsvg-convert -z 2 assets/tui.svg -o assets/tui.png   # PNG used in the README
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tui"))
sys.path.insert(0, str(REPO / "lib"))

OUT = REPO / "assets" / "tui.svg"

DEMO_LOADED = {
    "pr-manager",
    "review-prs",
    "story-reviewer",
    "reply-to-pr-comments",
    "reply-to-story-comments",
}
DEMO_REGISTERED = DEMO_LOADED | {"work-queue"}
DEMO_RUNNING = {"pr-manager"}

DEMO_LOG = """2026-07-01T09:03:07Z level=info daemon=pr-manager event=start msg="scanning managed PRs"
2026-07-01T09:03:09Z level=info daemon=pr-manager event=merge pr=142 msg="approved + green; squash-merged"
2026-07-01T09:03:10Z level=info daemon=pr-manager event=promote pr=147 msg="draft green 2h; ready for review"
2026-07-01T09:03:11Z level=info daemon=pr-manager event=skip pr=145 msg="ci pending; recheck in ~6h"
2026-07-01T09:03:12Z level=info daemon=pr-manager event=done msg="1 merged, 1 promoted, 1 skipped"
"""


def _sandbox() -> None:
    # Fake HOME so any ~ in a placeholder working_dir renders generically, not the
    # real user's home path.
    os.environ["HOME"] = "/home/you"
    root = Path(tempfile.mkdtemp(prefix="daimon-shot-"))
    ignore = shutil.ignore_patterns(
        "__pycache__", "*.pyc", "daemon.local.toml", "profile.local.toml", "*.local"
    )
    shutil.copytree(REPO / "daemons", root / "daemons", ignore=ignore)
    shutil.copytree(REPO / "profiles", root / "profiles", ignore=ignore)
    for ex in (root / "daemons").glob("*/daemon.local.toml.example"):
        shutil.copy(ex, ex.with_name("daemon.local.toml"))
    for ex in (root / "profiles").glob("*/profile.local.toml.example"):
        shutil.copy(ex, ex.with_name("profile.local.toml"))
    logs = root / "state" / "logs"
    logs.mkdir(parents=True)
    (logs / "pr-manager.log").write_text(DEMO_LOG)
    (root / "daimon.toml").write_text(
        f'[core]\ninstall_root = "{root}"\nstate_dir = "{root}/state"\nnamespace = "daimon-demo"\n'
        '[defaults]\nbackend = "claude"\nmodel = "opus"\ndanger = true\nstuck_after = 2700\n'
    )
    os.environ["DAIMON_CONFIG"] = str(root / "daimon.toml")


def _patch_state() -> None:
    import state

    import config

    config.expand = Path

    def live_sessions() -> set[str]:
        return {f"daimon-demo-{s}" for s in DEMO_RUNNING}

    def loaded_labels_text() -> str:
        return "\n".join(f"-\t0\tcom.daimon-demo.{s}" for s in DEMO_LOADED)

    def launchd_loaded(label: str, text: str | None = None) -> bool:
        return any(label.endswith(f".{s}") for s in DEMO_LOADED)

    def registered(cfg, slug: str) -> bool:
        return slug in DEMO_REGISTERED

    def running_session(cfg, slug: str, sessions=None):
        return f"daimon-demo-{slug}" if slug in DEMO_RUNNING else None

    def session_procs(cfg, slug: str):
        if slug in DEMO_RUNNING:
            return [(4821, 214.0, "claude"), (4822, 76.5, "mcp"), (4823, 41.0, "node")]
        return []

    state.live_sessions = live_sessions
    state.loaded_labels_text = loaded_labels_text
    state.launchd_loaded = launchd_loaded
    state.registered = registered
    state.running_session = running_session
    state.session_procs = session_procs
    state.throttle_level = lambda cfg: "off"


def main() -> int:
    _sandbox()
    _patch_state()
    from daemonctl import DaemonCtl

    app = DaemonCtl()

    async def capture(pilot) -> None:
        await pilot.pause(0.4)
        app.save_screenshot(str(OUT))
        app.exit()

    app.run(headless=True, size=(118, 34), auto_pilot=capture)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
