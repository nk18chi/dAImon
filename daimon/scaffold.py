"""Write a new daemon's folder: `daimon scaffold <slug> [--pack [dir] | --catalog]`.

By default it goes in daemons/, your own (gitignored) daemons, active at once.
--pack puts it in a pack's daemons/ for a team, --catalog in dAImon's catalog/
to contribute it upstream; both then need `daimon add <slug>` to run here.
The files work wherever the daemon lives, and
the daemon starts inert: its gate skips every run until you write it, so a
half-finished daemon can't launch an agent. `daimon new` (the /daimon-builder
interview) runs this, then fills the files in."""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

from daimon.scaffold_templates import DAEMON_TOML, DISCOVER, LOCAL_EXAMPLE, SKILL

INSTALL_ROOT = Path(__file__).resolve().parent.parent
SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


def _config():
    path = INSTALL_ROOT / "lib" / "config.py"
    spec = importlib.util.spec_from_file_location("daimon_config", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load config from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def target_root(cfg, pack: str | None, catalog: bool = False) -> Path:
    """daemons/ in the install root, catalog/ (`catalog`), or a pack's daemons/:
    `pack` is "" for the first configured pack, else a path (which must be a
    configured pack)."""
    if catalog:
        return cfg.catalog_dir()
    if pack is None:
        return cfg.daemons_dir()
    if pack == "":
        if not cfg.packs:
            raise ValueError("no packs configured ([packs].paths in daimon.toml)")
        return cfg.packs[0] / "daemons"
    chosen = Path(pack).expanduser().resolve()
    if chosen not in cfg.packs:
        raise ValueError(f"{chosen} is not in [packs].paths")
    return chosen / "daemons"


def scaffold(cfg, slug: str, pack: str | None = None, catalog: bool = False) -> Path:
    if not SLUG_RE.match(slug):
        raise ValueError(f"{slug!r}: use lowercase words joined by hyphens, e.g. triage-issues")
    existing = cfg.daemon_locations().get(slug)
    if existing:
        raise ValueError(f"{slug} already exists: {existing[0]}")
    folder = target_root(cfg, pack, catalog) / slug
    files = {
        "daemon.toml": DAEMON_TOML,
        "daemon.local.toml.example": LOCAL_EXAMPLE,
        "skill/SKILL.md": SKILL,
        "discover.sh": DISCOVER,
    }
    for name, template in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(template.format(slug=slug))
    (folder / "discover.sh").chmod(0o755)
    return folder


def _parse(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="daimon scaffold")
    p.add_argument("slug")
    where = p.add_mutually_exclusive_group()
    # A bare --pack means the first configured pack.
    where.add_argument("--pack", nargs="?", const="", default=None, metavar="DIR")
    where.add_argument("--catalog", action="store_true", help="contribute it to dAImon's catalog/")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse(argv)
    slug = args.slug
    try:
        folder = scaffold(_config().Config.load(), slug, args.pack, args.catalog)
    except ValueError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    print(f"+ {folder}/")
    print("  daemon.toml, daemon.local.toml.example, skill/SKILL.md, discover.sh")
    print("  The gate skips every run until you write it (discover.sh), so nothing")
    if args.pack is not None or args.catalog:
        print(f"  launches yet. Install it here with daimon add {slug}, then daimon validate,")
    else:
        print("  launches yet. Then: daimon validate,")
    print(f"  daimon run {slug} to try it once, and register it in daimon tui (r).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
