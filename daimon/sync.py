"""Regenerate launchd plists and render daemon skills from the daemon folders.
Run via `daimon sync` or `python -m daimon.sync`."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

INSTALL_ROOT = Path(__file__).resolve().parent.parent


def _import_from_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {name} from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RELOAD_NOTES: list[str] = []


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)


def _write_plist(path: Path, text: str, label: str) -> None:
    """Write a plist; when it changed and its job is loaded, reload the job so the
    new schedule takes effect. launchd keeps running the old definition until a
    reload. A job mid-run is left alone (a bootout would kill its launcher and
    strand the agent session) and reported instead."""
    changed = not path.exists() or path.read_text() != text
    path.write_text(text)
    if not changed or sys.platform != "darwin" or os.environ.get("DAIMON_SYNC_NO_RELOAD"):
        return
    target = f"gui/{os.getuid()}/{label}"
    info = _launchctl("print", target)
    if info.returncode != 0:
        return  # not loaded (disabled or never registered): nothing to refresh
    if "state = running" in info.stdout:
        RELOAD_NOTES.append(f"{label}: running, reload after it finishes (re-run sync)")
        return
    _launchctl("bootout", target)
    for _ in range(10):
        if _launchctl("bootstrap", f"gui/{os.getuid()}", str(path)).returncode == 0:
            RELOAD_NOTES.append(f"{label}: reloaded")
            return
        subprocess.run(["sleep", "0.5"], check=False)
    RELOAD_NOTES.append(
        f"{label}: RELOAD FAILED, run `launchctl bootstrap gui/{os.getuid()} {path}`"
    )


def materialize(cfg_mod, create_missing: bool = True):
    """Render skills for every discovered daemon; write plists. A plist file is
    the registration marker (TUI register/unregister creates/deletes it), so by
    default only existing plists are refreshed — create_missing=True (install)
    also creates absent ones. Returns (cfg, skipped_slugs)."""
    RELOAD_NOTES.clear()
    cfg = cfg_mod.Config.load()
    schema_path = cfg.catalog_dir() / "daemon.schema.json"
    schema_path.write_text(json.dumps(cfg_mod.daemon_schema(), indent=2) + "\n")
    skills_root = Path(os.path.expanduser("~/.claude/skills"))
    agents = Path(os.path.expanduser("~/Library/LaunchAgents"))
    if sys.platform == "darwin":
        agents.mkdir(parents=True, exist_ok=True)
    ns = cfg.core["namespace"]
    skipped: list[str] = []
    for slug in cfg.discover():
        cmd = cfg.daemon(slug)["command"].lstrip("/")
        sd = skills_root / cmd
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "SKILL.md").write_text(cfg_mod.render_skill(cfg, slug))
        if agents.is_dir():
            plist = agents / f"com.{ns}.{slug}.plist"
            if create_missing or plist.exists():
                _write_plist(plist, cfg_mod.render_plist(cfg, slug), f"com.{ns}.{slug}")
            else:
                skipped.append(slug)
    if agents.is_dir():
        _write_plist(
            agents / f"com.{ns}.watchdog.plist",
            cfg_mod.render_watchdog_plist(cfg),
            f"com.{ns}.watchdog",
        )
        sync_updater(cfg_mod, cfg, agents / f"com.{ns}.update.plist", f"com.{ns}.update")
    return cfg, skipped


def sync_updater(cfg_mod, cfg, plist: Path, label: str) -> None:
    """[update].auto on: write com.<ns>.update and make sure it is loaded (it is
    infrastructure the user turned on, not a daemon to register). Off: unload
    and remove it."""
    live = sys.platform == "darwin" and not os.environ.get("DAIMON_SYNC_NO_RELOAD")
    target = f"gui/{os.getuid()}/{label}"
    if not cfg.update["auto"]:
        if plist.exists():
            if live:
                _launchctl("bootout", target)
            plist.unlink()
            RELOAD_NOTES.append(f"{label}: auto-update off, removed")
        return
    _write_plist(plist, cfg_mod.render_update_plist(cfg), label)
    if live and _launchctl("print", target).returncode != 0:
        ok = _launchctl("bootstrap", f"gui/{os.getuid()}", str(plist)).returncode == 0
        RELOAD_NOTES.append(f"{label}: {'loaded' if ok else 'LOAD FAILED'} (auto-update on)")


def _git(pack: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(pack), *args], capture_output=True, text=True, check=False
    )


def pull_packs(packs: list[Path]) -> list[str]:
    """Fast-forward each pack that is a clean git checkout; never merge or stash."""
    notes = []
    for pack in packs:
        if not (pack / ".git").exists():
            continue
        if _git(pack, "status", "--porcelain").stdout.strip():
            notes.append(f"pack {pack}: local changes, not pulled")
            continue
        r = _git(pack, "pull", "--ff-only", "--quiet")
        notes.append(
            f"pack {pack}: {'up to date' if r.returncode == 0 else 'pull failed: ' + r.stderr.strip()[:120]}"
        )
    return notes


def main(argv: list[str]) -> int:
    create_missing = "--all" in argv
    cfg_mod = _import_from_path("daimon_config", INSTALL_ROOT / "lib" / "config.py")
    for note in pull_packs(cfg_mod.Config.load().packs):
        print(note)
    errs = cfg_mod.validate(cfg_mod.Config.load())
    if errs:
        print("config INVALID after sync:", *(f"  - {e}" for e in errs), sep="\n", file=sys.stderr)
        return 1
    cfg, skipped = materialize(cfg_mod, create_missing=create_missing)
    print(f"synced {len(cfg.discover())} daemon(s): plists + skills regenerated")
    for note in RELOAD_NOTES:
        print(f"  {note}")
    if skipped:
        print(
            f"unregistered (no plist, left alone): {', '.join(skipped)} — register via TUI `r` or `daimon sync --all`"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
