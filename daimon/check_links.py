"""Verify that every relative Markdown link in the repo's docs resolves to a file
that exists. External links (http/https/mailto) and pure #anchors are skipped.

Run `python -m daimon.check_links` (part of `make check`); exits non-zero if any
link is broken."""

from __future__ import annotations

import re
import sys
from pathlib import Path

INSTALL_ROOT = Path(__file__).resolve().parent.parent
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
SKIP_PREFIXES = ("http://", "https://", "mailto:", "#")
# commands.local holds gitignored per-machine command plugins — their prose is
# operator-authored and must not gate the repo's link check.
SKIP_DIRS = {".venv", "node_modules", "__pycache__", ".git", "commands.local"}


def _md_files(root: Path) -> list[Path]:
    return sorted(
        p
        for p in root.rglob("*.md")
        if not any(part in SKIP_DIRS for part in p.relative_to(root).parts)
    )


def _broken_links(md: Path) -> list[str]:
    out = []
    for target in LINK.findall(md.read_text()):
        target = target.split()[0]  # drop any "title" after the path
        if target.startswith(SKIP_PREFIXES):
            continue
        path = target.split("#", 1)[0]
        if not path:
            continue
        if not (md.parent / path).exists():
            out.append(target)
    return out


def main() -> int:
    broken = {}
    for md in _md_files(INSTALL_ROOT):
        found = _broken_links(md)
        if found:
            broken[md.relative_to(INSTALL_ROOT)] = found
    for rel, links in broken.items():
        for link in links:
            print(f"{rel}: broken link -> {link}", file=sys.stderr)
    if broken:
        print(f"\n{sum(len(v) for v in broken.values())} broken link(s)", file=sys.stderr)
        return 1
    print(f"checked links in {len(_md_files(INSTALL_ROOT))} markdown files — all resolve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
