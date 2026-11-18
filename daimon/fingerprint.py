"""A daemon folder's content, minus what is not part of the daemon: the
`.origin.json` record, caches, and personal files (*.local.toml settings,
legacy commands.local/ runbooks). `daimon eject` copies exactly these files
and records their hash, so the hash later tells whether either side changed.

A renamed copy (`daimon eject <slug> --as <new>`) has the slug rewritten in its
text files (rename_slug); hashing upstream through the same rewrite keeps the
rename itself from counting as a change."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path

SKIP_NAMES = (".origin.json", "__pycache__", ".DS_Store", "commands.local")
SKIP_SUFFIXES = (".pyc", ".local.toml")
# The same exclusions as `diff -x` patterns.
DIFF_EXCLUDES = (*SKIP_NAMES, *(f"*{s}" for s in SKIP_SUFFIXES))


def skipped(name: str) -> bool:
    return name in SKIP_NAMES or name.endswith(SKIP_SUFFIXES)


def content_files(folder: Path) -> list[Path]:
    """The daemon's files, relative to `folder`, sorted."""
    out = []
    for path in folder.rglob("*"):
        rel = path.relative_to(folder)
        if path.is_file() and not any(skipped(part) for part in rel.parts):
            out.append(rel)
    return sorted(out)


# (old slug, new slug) for a renamed copy.
Rename = tuple[str, str]


def rename_slug(data: bytes, rename: Rename | None) -> bytes:
    """`old` -> `new` wherever it stands alone as a slug ("/old", "state_file old",
    "old.toml", "name: old"), not inside a longer slug like "old-two". Files that
    aren't UTF-8 text are left alone."""
    if rename is None:
        return data
    try:
        data.decode()
    except UnicodeDecodeError:
        return data
    old, new = (s.encode() for s in rename)
    pattern = rb"(?<![A-Za-z0-9_-])" + re.escape(old) + rb"(?![A-Za-z0-9_-])"
    return re.sub(pattern, lambda _m: new, data)


def content_hash(folder: Path, rename: Rename | None = None) -> str:
    """Deterministic: each file's path, executable bit and bytes, in path order;
    with `rename`, the bytes as rename_slug would rewrite them."""
    digest = hashlib.sha256()
    for rel in content_files(folder):
        path = folder / rel
        digest.update(rel.as_posix().encode() + b"\0")
        digest.update(b"x" if os.access(path, os.X_OK) else b"-")
        digest.update(hashlib.sha256(rename_slug(path.read_bytes(), rename)).digest())
    return f"sha256:{digest.hexdigest()}"


def copy_content(src: Path, dest: Path, rename: Rename | None = None) -> None:
    """Copy `src` to `dest` without the skipped files, rewriting the slug when
    `rename` is given. `dest` may already exist (a leftover folder holding only
    migration stubs)."""
    shutil.copytree(
        src, dest, ignore=lambda _d, names: [n for n in names if skipped(n)], dirs_exist_ok=True
    )
    if rename is None:
        return
    for rel in content_files(dest):
        path = dest / rel
        data = path.read_bytes()
        if (out := rename_slug(data, rename)) != data:
            path.write_bytes(out)
