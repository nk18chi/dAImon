"""Choose which daemons this machine has: `daimon catalog`, `daimon add <slug>…`,
`daimon remove <slug>…`.

A catalog is a folder of daemons you can install: dAImon's own `catalog/`, then
each pack's `daemons/`. Installing writes the slug into `[daemons].installed` in
daimon.toml; it schedules nothing. Registering (a launchd plist, `r` in
`daimon tui`) stays a separate step, so `add` never starts a job and `remove`
unregisters before it uninstalls."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from daimon.gen_docs import _frontmatter

INSTALL_ROOT = Path(__file__).resolve().parent.parent


def _modules():
    sys.path.insert(0, str(INSTALL_ROOT / "lib"))
    import config
    import migrate

    return config, migrate


def _description(folder: Path) -> str:
    try:
        text = (folder / "skill" / "SKILL.md").read_text()
    except OSError:
        return ""
    return _frontmatter(text).get("description", "")


def rows(cfg) -> list[tuple[str, str, str, str]]:
    """(slug, source, state, description) for every daemon a catalog offers, plus
    ejected-only ones (your own and private `.local` daemons)."""
    installed = set(cfg.installed())
    ejected = cfg.ejected_locations()
    offered = cfg.catalog()
    out = []
    for slug in sorted(set(offered) | set(ejected)):
        source = offered[slug]["source"] if slug in offered else "local"
        state = [
            label
            for label, on in (
                ("installed", slug in installed),
                ("ejected", slug in ejected),
                ("disabled", slug in cfg.disabled),
            )
            if on
        ]
        out.append((slug, source, ", ".join(state) or "-", _description(cfg.daemon_dir(slug))))
    return out


def list_catalog(cfg) -> int:
    table = rows(cfg)
    if not table:
        print(f"no daemons in {', '.join(map(str, cfg.catalog_roots()))}")
        return 0
    width = max(len(r[0]) for r in table) + 2
    src_width = max(len(r[1]) for r in table) + 2
    print(f"{'DAEMON':<{width}}{'SOURCE':<{src_width}}{'STATE':<20}DESCRIPTION")
    for slug, source, state, desc in table:
        print(f"{slug:<{width}}{source:<{src_width}}{state:<20}{desc}")
    if cfg.installed_list is None:
        print(
            "\n(no [daemons].installed yet: every catalog daemon not disabled counts as installed)"
        )
    print("\nadd one: daimon add <slug>   ·   remove: daimon remove <slug>")
    return 0


def _set_list(cfg, migrate, key: str, values: list[str]) -> bool:
    """Write [daemons].<key>; report and return False when it can't be written."""
    try:
        if cfg.source is None:
            raise ValueError("no daimon.toml yet — run `daimon install` first")
        migrate.set_config_key(cfg.source, "daemons", key, values)
    except ValueError as e:
        print(f"✗ {e}", file=sys.stderr)
        return False
    return True


def _scaffold_personal(cfg, slug: str) -> list[str]:
    """Copy the daemon's (and its source profiles') *.local.toml.example to your
    personal settings when you have none yet."""
    pairs = [(cfg.daemon_dir(slug) / "daemon.local.toml.example", cfg.daemon_local_path(slug))]
    for src in cfg.daemon(slug)["sources"]:
        pairs.append(
            (cfg.profiles_dir() / src / "profile.local.toml.example", cfg.profile_local_path(src))
        )
    made = []
    for example, dest in pairs:
        if example.exists() and not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(example, dest)
            made.append(str(dest))
    return made


def _install(cfg, migrate, slugs: list[str]) -> bool:
    """Append `slugs` to installed (writing the legacy set first when the key is
    absent) and take them off `disabled`."""
    installed = cfg.installed()
    new = [s for s in slugs if s not in installed]
    if (new or cfg.installed_list is None) and not _set_list(
        cfg, migrate, "installed", installed + new
    ):
        return False
    for s in slugs:
        print(f"+ {s}" if s in new else f"= {s} (already installed)")
    enabled = [s for s in slugs if s in cfg.disabled]
    if not enabled:
        return True
    print(f"  no longer disabled: {', '.join(enabled)}")
    return _set_list(cfg, migrate, "disabled", [s for s in cfg.disabled if s not in enabled])


def _sync() -> bool:
    env = {**os.environ, "PYTHONPATH": str(INSTALL_ROOT)}
    proc = subprocess.run(
        [sys.executable, "-m", "daimon.sync"], cwd=INSTALL_ROOT, env=env, check=False
    )
    return proc.returncode == 0


def _copy_into_pack(cfg, slugs: list[str], pack: str) -> bool:
    """`add --pack`: copy each dAImon catalog daemon into the pack first."""
    from daimon.eject import eject_to_pack  # daimon.eject imports this module

    try:
        for slug in slugs:
            eject_to_pack(cfg, slug, pack)
    except ValueError as e:
        print(f"✗ {e}", file=sys.stderr)
        return False
    return True


def add(config, migrate, slugs: list[str], pack: str | None = None) -> int:
    cfg = config.Config.load()
    slugs = list(dict.fromkeys(slugs))
    if pack is not None:
        if not _copy_into_pack(cfg, slugs, pack):
            return 1
        cfg = config.Config.load()
    unknown = [s for s in slugs if s not in cfg.catalog() and s not in cfg.ejected_locations()]
    if unknown:
        print(f"✗ not in any catalog: {', '.join(unknown)} (see `daimon catalog`)", file=sys.stderr)
        return 1
    if not _install(cfg, migrate, slugs):
        return 1
    cfg = config.Config.load()
    for slug in slugs:
        for path in _scaffold_personal(cfg, slug):
            print(f"  new   {path}: review it (working_dir, inputs)")
    synced = _sync()
    if not synced:
        print("  sync failed: fill in the settings above, then run `daimon sync`", file=sys.stderr)
    print("registered nothing: register with `daimon tui` → r")
    return 0 if synced else 1


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)


def _plist(cfg, slug: str) -> Path:
    label = f"com.{cfg.core['namespace']}.{slug}"
    return Path(os.path.expanduser(f"~/Library/LaunchAgents/{label}.plist"))


def _confirm(question: str) -> bool:
    if not sys.stdin.isatty():
        return False
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def unregister(cfg, slug: str, yes: bool) -> bool:
    """Unload and delete the daemon's plist. False when the user declined."""
    plist = _plist(cfg, slug)
    if not plist.exists():
        return True
    target = f"gui/{os.getuid()}/com.{cfg.core['namespace']}.{slug}"
    if _launchctl("print", target).returncode == 0:
        if not yes and not _confirm(f"{slug} is loaded (scheduled). Unregister it?"):
            print(f"  kept {slug}: it is loaded (pass --yes to unregister it)", file=sys.stderr)
            return False
        _launchctl("bootout", target)
    plist.unlink(missing_ok=True)
    print(f"  unregistered {slug} ({plist})")
    return True


def remove(config, migrate, slugs: list[str], yes: bool) -> int:
    cfg = config.Config.load()
    installed, ejected = cfg.installed(), cfg.ejected_locations()
    done, rc = [], 0
    for slug in dict.fromkeys(slugs):
        if slug not in installed and slug not in ejected:
            print(f"= {slug} (not installed)")
        elif unregister(cfg, slug, yes):
            done.append(slug)
        else:
            rc = 1
    if done and not _set_list(cfg, migrate, "installed", [s for s in installed if s not in done]):
        return 1
    for slug in done:
        print(f"- {slug} (personal settings kept: {cfg.daemon_local_path(slug)})")
        if slug in ejected:
            print(f"  still active: your copy in {ejected[slug][0]}; delete it to remove it")
    return rc


def _parse(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="daimon")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list every daemon you can install")
    a = sub.add_parser("add", help="install daemons (registers nothing)")
    a.add_argument("slugs", nargs="+")
    # A bare --pack means the only configured pack.
    a.add_argument("--pack", nargs="?", const="", default=None, metavar="DIR")
    r = sub.add_parser("remove", help="unregister and uninstall daemons")
    r.add_argument("slugs", nargs="+")
    r.add_argument("--yes", "-y", action="store_true", help="unregister loaded daemons unasked")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse(argv)
    config, migrate = _modules()
    if args.cmd == "add":
        return add(config, migrate, args.slugs, args.pack)
    if args.cmd == "remove":
        return remove(config, migrate, args.slugs, args.yes)
    return list_catalog(config.Config.load())


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
