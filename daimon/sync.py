"""Regenerate launchd plists and render daemon skills from the daemon folders.
Run via `daimon sync` or `python -m daimon.sync`."""

from __future__ import annotations

import importlib.util
import json
import os
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


def materialize(cfg_mod, create_missing: bool = True):
    """Render skills for every discovered daemon; write plists. A plist file is
    the registration marker (TUI register/unregister creates/deletes it), so by
    default only existing plists are refreshed — create_missing=True (install)
    also creates absent ones. Returns (cfg, skipped_slugs)."""
    cfg = cfg_mod.Config.load()
    schema_path = cfg.install_root / "daemons" / "daemon.schema.json"
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
                plist.write_text(cfg_mod.render_plist(cfg, slug))
            else:
                skipped.append(slug)
    if agents.is_dir():
        (agents / f"com.{ns}.watchdog.plist").write_text(cfg_mod.render_watchdog_plist(cfg))
    return cfg, skipped


def main(argv: list[str]) -> int:
    create_missing = "--all" in argv
    cfg_mod = _import_from_path("daimon_config", INSTALL_ROOT / "lib" / "config.py")
    errs = cfg_mod.validate(cfg_mod.Config.load())
    if errs:
        print("config INVALID after sync:", *(f"  - {e}" for e in errs), sep="\n", file=sys.stderr)
        return 1
    cfg, skipped = materialize(cfg_mod, create_missing=create_missing)
    print(f"synced {len(cfg.discover())} daemon(s): plists + skills regenerated")
    if skipped:
        print(
            f"unregistered (no plist, left alone): {', '.join(skipped)} — register via TUI `r` or `daimon sync --all`"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
