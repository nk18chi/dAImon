"""Own a copy of a daemon: `daimon eject`, `uneject`, `outdated`, `diff`.

A linked daemon runs from its catalog (dAImon's `catalog/` or a pack's
`daemons/`), so updates reach it. `daimon eject <slug>` copies it into the
install's gitignored `daemons/<slug>/` to edit, which then takes precedence;
`daimon eject <slug> --pack [dir]` copies a dAImon catalog daemon into a pack's
`daemons/<slug>/` instead, for the team to own and change by PR. Either copy
records where it came from in `.origin.json`: {source, path, hash}, the hash
covering the files as copied (daimon/fingerprint.py). Comparing that hash with
upstream's files today, and with the copy's, tells which side changed since
(`outdated`, `diff`). `daimon uneject <slug>` deletes a local copy so the
daemon is linked again.

`daimon eject <slug> --as <new> [--pack [dir]]` forks instead: the copy goes to
`daemons/<new>/` with the slug rewritten in its files (command, skill name,
state file names), so it runs beside the original as a distinct daemon. Its
.origin.json adds "as": <new>; `outdated` and `diff` compare it with upstream
through the same rewrite."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from daimon.catalog import _confirm, _modules, _set_list, _sync
from daimon.fingerprint import DIFF_EXCLUDES, Rename, content_hash, copy_content
from daimon.scaffold import SLUG_RE


def _fail(message: str) -> int:
    print(f"✗ {message}", file=sys.stderr)
    return 1


def _sync_or_warn() -> int:
    if _sync():
        return 0
    print("  sync failed: run `daimon sync`", file=sys.stderr)
    return 1


def _root_of(cfg, source: str) -> Path | None:
    if source == "dAImon":
        return cfg.install_root
    return next((p for p in cfg.packs if p.name == source), None)


def upstream_dir(cfg, origin: dict) -> Path | None:
    """The folder a copy was taken from, when it still holds a daemon."""
    root = _root_of(cfg, str(origin.get("source", "")))
    path = origin.get("path")
    if root is None or not isinstance(path, str) or not path:
        return None
    folder = root / path
    return folder if (folder / "daemon.toml").exists() else None


def rename_of(origin: dict) -> Rename | None:
    """(upstream slug, copy's slug) for a renamed copy, else None."""
    new, path = origin.get("as"), origin.get("path")
    if not isinstance(new, str) or not new or not isinstance(path, str) or not path:
        return None
    return Path(path).name, new


def copy_daemon(src: Path, dest: Path, source: str, rel_path: str, new: str | None = None) -> None:
    rename = (src.name, new) if new else None
    copy_content(src, dest, rename)
    origin = {"source": source, "path": rel_path, "hash": content_hash(dest)}
    if new:
        origin["as"] = new
    (dest / ".origin.json").write_text(json.dumps(origin, indent=2) + "\n")


@dataclass
class Copy:
    slug: str
    folder: Path
    where: str  # "local" or the pack's name
    origin: dict

    def edited(self) -> bool:
        return content_hash(self.folder) != self.origin.get("hash")

    def upstream_changed(self, cfg) -> bool | None:
        """None when upstream no longer has the daemon."""
        up = upstream_dir(cfg, self.origin)
        if up is None:
            return None
        return content_hash(up, rename_of(self.origin)) != self.origin.get("hash")


def copies(cfg) -> list[Copy]:
    """Every copy with an .origin.json: local ejected ones, then packs'."""
    config, _ = _modules()
    found = [
        (slug, folder, "local")
        for slug, dirs in sorted(cfg.ejected_locations().items())
        for folder in dirs
    ]
    for pack in cfg.packs:
        for toml in sorted((pack / "daemons").glob("*/daemon.toml")):
            found.append((toml.parent.name, toml.parent, pack.name))
    return [
        Copy(slug, folder, where, origin)
        for slug, folder, where in found
        if (origin := config.read_origin(folder)) is not None
    ]


def choose_pack(cfg, pack: str) -> Path:
    """`--pack` with no directory means the only configured pack."""
    if pack:
        chosen = Path(pack).expanduser().resolve()
        if chosen not in cfg.packs:
            raise ValueError(f"{chosen} is not in [packs].paths")
        return chosen
    if not cfg.packs:
        raise ValueError("no packs configured ([packs].paths in daimon.toml)")
    if len(cfg.packs) > 1:
        names = ", ".join(map(str, cfg.packs))
        raise ValueError(f"several packs configured ({names}); name one: --pack <dir>")
    return cfg.packs[0]


def eject_to_pack(cfg, slug: str, pack: str) -> Path:
    """Copy dAImon's catalog/<slug> into a pack's daemons/<slug>, team-owned."""
    target = choose_pack(cfg, pack)
    src = cfg.catalog_dir() / slug
    if not (src / "daemon.toml").exists():
        raise ValueError(f"{slug} is not in dAImon's catalog ({cfg.catalog_dir()})")
    dest = target / "daemons" / slug
    if dest.exists():
        raise ValueError(f"{dest} already exists")
    copy_daemon(src, dest, "dAImon", f"catalog/{slug}")
    print(f"+ {dest}/ (from dAImon's catalog; .origin.json records it)")
    print("  it now replaces dAImon's copy: commit it in the pack's repo")
    return dest


def _ensure_installed(cfg, migrate, slug: str) -> None:
    if slug not in cfg.installed() and not _set_list(
        cfg, migrate, "installed", [*cfg.installed(), slug]
    ):
        raise ValueError(f"could not add {slug} to [daemons].installed")


def _move_legacy_settings(cfg, migrate, slug: str, folders: list[Path]) -> None:
    """A gitignored daemon.local.toml beside the daemon is still read; a copy
    leaves it behind and deleting a copy would lose it, so move it to the
    personal settings file first, and stop if it can't be moved."""
    for folder in folders:
        line = migrate.migrate_file(folder / "daemon.local.toml", cfg.daemon_local_path(slug))
        if line and line.startswith("skip"):
            raise ValueError(f"{line}; fix it, then retry")
        if line:
            print(f"  {line}")


def eject_local(cfg, migrate, slug: str) -> Path:
    mine = cfg.ejected_locations().get(slug)
    if mine:
        raise ValueError(f"{slug} is already ejected: {mine[0]}")
    entry = cfg.catalog().get(slug)
    if entry is None:
        raise ValueError(f"{slug} is not in any catalog (see `daimon catalog`)")
    src, source = entry["path"], entry["source"]
    root = _root_of(cfg, source)
    if root is None:
        raise ValueError(f"cannot tell which catalog {src} belongs to")
    rel = src.relative_to(root).as_posix()
    dest = cfg.daemons_dir() / slug
    _move_legacy_settings(cfg, migrate, slug, [src, dest])
    copy_daemon(src, dest, source, rel)
    _ensure_installed(cfg, migrate, slug)
    print(f"+ {dest}/ (from {source}: {rel})")
    print(f"  edit it there; `daimon outdated` / `daimon diff {slug}` show upstream changes,")
    print(f"  `daimon uneject {slug}` links it again")
    return dest


def _check_new_slug(cfg, slug: str, new: str) -> None:
    if new == slug:
        raise ValueError(f"--as {new} is the daemon's own name: drop --as to eject it")
    if not SLUG_RE.match(new):
        raise ValueError(f"--as {new!r}: use lowercase words joined by hyphens, e.g. triage-issues")
    existing = cfg.daemon_locations().get(new)
    if existing:
        raise ValueError(f"{new} already exists: {existing[0]}")


def _copy_settings(cfg, slug: str, new: str) -> None:
    """Start the fork from your settings for the original, when you have some."""
    src, dest = cfg.daemon_local_path(slug), cfg.daemon_local_path(new)
    if src.exists() and not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        print(f"+ {dest} (a copy of your {slug} settings)")


Baked = dict[tuple[str, str], tuple[object, Path]]


def _team_overrides(cfg, slug: str) -> Baked:
    """The [daemon]/[inputs] values every pack's overrides/<slug>.toml sets, in
    raw_daemon's order (a later pack wins), each with the file it came from.
    They name `slug`, so a fork would lose them; it takes them into its own
    daemon.toml instead."""
    import toml_emit  # lib/, on sys.path once _modules() ran

    baked: Baked = {}
    for path in cfg.pack_overrides(slug):
        if not path.exists():
            continue
        try:
            data = tomllib.loads(path.read_text())
        except (OSError, tomllib.TOMLDecodeError) as e:
            raise ValueError(f"cannot read {path}: {e}") from e
        for table in ("daemon", "inputs"):
            for key, value in data.get(table, {}).items():
                try:
                    toml_emit.emit_value(value)
                except TypeError as e:
                    raise ValueError(f"{path}: cannot copy [{table}].{key}: {e}") from e
                baked[(table, key)] = (value, path)
    return baked


def _bake(dest: Path, slug: str, baked: Baked) -> None:
    import toml_emit

    toml = dest / "daemon.toml"
    text = toml.read_text()
    for (table, key), (value, path) in baked.items():
        note = (
            f"from the {path.parent.parent.name} pack's overrides/{slug}.toml (daimon eject --as)"
        )
        text = toml_emit.set_key_text(text, table, key, value, comment=note)
    toml.write_text(text)
    files = ", ".join(dict.fromkeys(str(path) for _, path in baked.values()))
    print(f"  folded in the team overrides of {slug}: {files}")


def fork(cfg, migrate, slug: str, new: str, pack: str | None) -> Path:
    """Copy `slug` from its catalog to daemons/<new> (or the pack's), renamed: a
    distinct daemon with its own skill, launchd job, state and logs, carrying
    the packs' team overrides of `slug` in its daemon.toml. The original is left
    as it is."""
    _check_new_slug(cfg, slug, new)
    entry = cfg.catalog().get(slug)
    if entry is None:
        raise ValueError(f"{slug} is not in any catalog (see `daimon catalog`)")
    src, source = entry["path"], entry["source"]
    root = _root_of(cfg, source)
    if root is None:
        raise ValueError(f"cannot tell which catalog {src} belongs to")
    target = cfg.daemons_dir() if pack is None else choose_pack(cfg, pack) / "daemons"
    dest = target / new
    if dest.exists():
        raise ValueError(f"{dest} already exists")
    rel = src.relative_to(root).as_posix()
    baked = _team_overrides(cfg, slug)
    copy_daemon(src, dest, source, rel, new)
    _ensure_installed(cfg, migrate, new)
    print(f"+ {dest}/ ({slug} from {source}: {rel}, renamed {new})")
    if baked:
        # After the hash: these are the fork's own values from now on.
        _bake(dest, slug, baked)
    _copy_settings(cfg, slug, new)
    print(f"  {new} runs beside {slug} with its own job, state and logs; edit it there.")
    print(f"  `daimon outdated` / `daimon diff {new}` show changes to {slug} upstream")
    if pack is not None:
        print("  commit it in the pack's repo")
    return dest


def eject(config, migrate, slug: str, pack: str | None, new: str | None = None) -> int:
    cfg = config.Config.load()
    try:
        if new is not None:
            fork(cfg, migrate, slug, new, pack)
        elif pack is None:
            eject_local(cfg, migrate, slug)
        else:
            eject_to_pack(cfg, slug, pack)
    except ValueError as e:
        return _fail(str(e))
    return _sync_or_warn() if (new or slug) in config.Config.load().discover() else 0


def _unejectable(cfg, slug: str) -> Copy:
    """The local copy uneject may delete; ValueError says why not."""
    mine = cfg.ejected_locations().get(slug)
    if not mine:
        team = [c for c in copies(cfg) if c.slug == slug and c.where != "local"]
        if team:
            raise ValueError(
                f"{slug} is the {team[0].where} pack's copy ({team[0].folder}): "
                "change it by a PR to the pack"
            )
        raise ValueError(f"{slug} is not ejected")
    local = [c for c in copies(cfg) if c.folder == mine[0]]
    if not local:
        raise ValueError(f"{mine[0]} has no .origin.json: it is your own daemon, not a copy")
    renamed = rename_of(local[0].origin)
    if renamed:
        raise ValueError(
            f"{slug} is a renamed copy of {renamed[0]}, with no original under its own name "
            f"to link back to. To drop it: `daimon remove {slug}`, then delete {mine[0]}"
        )
    if slug not in cfg.catalog():
        raise ValueError(f"no catalog offers {slug} any more: keeping {mine[0]}")
    return local[0]


def uneject(config, migrate, slug: str, yes: bool) -> int:
    cfg = config.Config.load()
    try:
        copy = _unejectable(cfg, slug)
    except ValueError as e:
        return _fail(str(e))
    source = cfg.catalog()[slug]["source"]
    lost = " (your edits there are lost)" if copy.edited() else ""
    if not yes and not _confirm(f"Delete {copy.folder}{lost} and link {slug} to {source} again?"):
        print(f"  kept {copy.folder} (pass --yes to delete it)", file=sys.stderr)
        return 1
    try:
        _move_legacy_settings(cfg, migrate, slug, [copy.folder])
        shutil.rmtree(copy.folder)
        print(f"- {copy.folder}")
        print(f"  {slug} is linked to {source} again; personal settings kept")
        _ensure_installed(cfg, migrate, slug)
    except ValueError as e:
        return _fail(str(e))
    return _sync_or_warn()


UPSTREAM_LABEL = {None: "gone", True: "changed", False: "unchanged"}


def report(cfg) -> list[tuple[Copy, bool | None, bool]]:
    """(copy, upstream changed (None = gone), edited) for every copy."""
    return [(c, c.upstream_changed(cfg), c.edited()) for c in copies(cfg)]


def _print_table(rows: list[tuple[Copy, bool | None, bool]]) -> None:
    width = max(len(c.slug) for c, _, _ in rows) + 2
    where_width = max(len(c.where) for c, _, _ in rows) + 2
    print(f"{'DAEMON':<{width}}{'COPY':<{where_width}}{'UPSTREAM':<12}{'YOUR COPY':<12}FROM")
    for c, up, edited in rows:
        src = f"{c.origin.get('source')}: {c.origin.get('path')}"
        mine = "edited" if edited else "unchanged"
        print(f"{c.slug:<{width}}{c.where:<{where_width}}{UPSTREAM_LABEL[up]:<12}{mine:<12}{src}")


def outdated(config, brief: bool) -> int:
    rows = report(config.Config.load())
    if brief:
        for c, up, _ in rows:
            if up is not False:
                print(f"{c.slug} ({c.where}): upstream {UPSTREAM_LABEL[up]}")
        return 0
    if not rows:
        print("no ejected daemons (daimon eject <slug>)")
        return 0
    _print_table(rows)
    print("\n(changed since the copy was made; see one: daimon diff <slug>)")
    return 0


def diff(config, slug: str) -> int:
    cfg = config.Config.load()
    copy = next((c for c in copies(cfg) if c.slug == slug), None)
    if copy is None:
        return _fail(f"{slug} has no ejected copy with an .origin.json")
    up = upstream_dir(cfg, copy.origin)
    if up is None:
        return _fail(f"upstream {copy.origin.get('source')}: {copy.origin.get('path')} is gone")
    upstream = "changed" if copy.upstream_changed(cfg) else "unchanged"
    mine = "edited" if copy.edited() else "unchanged"
    print(f"# {slug}: --- upstream {up}  +++ your copy {copy.folder}")
    print(f"# since the eject: upstream {upstream}, your copy {mine}", flush=True)
    rename = rename_of(copy.origin)
    if rename is None:
        return _run_diff(up, copy.folder)
    print(f"# renamed: upstream shown with {rename[0]} -> {rename[1]}", flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        # Diff a renamed view of upstream, so the rename alone isn't an edit.
        view = Path(tmp) / up.name
        copy_content(up, view, rename)
        return _run_diff(view, copy.folder, shown_as=up)


def _run_diff(old: Path, new: Path, shown_as: Path | None = None) -> int:
    excludes = [arg for name in DIFF_EXCLUDES for arg in ("-x", name)]
    argv = ["diff", "-ru", *excludes, str(old), str(new)]
    if shown_as is None:
        proc = subprocess.run(argv, check=False)
    else:
        proc = subprocess.run(argv, check=False, capture_output=True, text=True)
        sys.stdout.write(proc.stdout.replace(str(old), str(shown_as)))
        sys.stderr.write(proc.stderr)
    return 0 if proc.returncode in (0, 1) else proc.returncode


def _parse(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="daimon")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("eject", help="copy a daemon into daemons/ (or a pack) to edit")
    e.add_argument("slug")
    e.add_argument("--pack", nargs="?", const="", default=None, metavar="DIR")
    e.add_argument("--as", dest="new", metavar="NEW", help="fork it under a new slug")
    u = sub.add_parser("uneject", help="delete your ejected copy; link the daemon again")
    u.add_argument("slug")
    u.add_argument("--yes", "-y", action="store_true")
    o = sub.add_parser("outdated", help="ejected copies whose upstream or copy changed")
    o.add_argument("--brief", action="store_true", help="only copies whose upstream changed")
    d = sub.add_parser("diff", help="diff -ru upstream against your copy")
    d.add_argument("slug")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse(argv)
    config, migrate = _modules()
    if args.cmd == "eject":
        return eject(config, migrate, args.slug, args.pack, args.new)
    if args.cmd == "uneject":
        return uneject(config, migrate, args.slug, args.yes)
    if args.cmd == "outdated":
        return outdated(config, args.brief)
    return diff(config, args.slug)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
