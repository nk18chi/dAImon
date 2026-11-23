#!/usr/bin/env python3
"""Exit 0 if claude would start in the given directory without a trust prompt.

    claude_trust.py <dir>

Trust lives in ~/.claude.json under projects[<dir>].hasTrustDialogAccepted.
Claude asks once per workspace: the directory itself, or the git repository it
sits in. A record for the directory wins; without one, the repository root's
record covers it. Any other parent's record does not: a plain subfolder of a
trusted non-git folder still prompts. An untrusted working_dir makes a claude
daemon stop at the first-run trust prompt.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _git_root(path: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", path, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    root = out.stdout.strip() if out.returncode == 0 else ""
    return str(Path(root).resolve()) if root else None


def is_trusted(directory: str) -> bool:
    try:
        with open(os.path.expanduser("~/.claude.json")) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return False
    projects = data.get("projects", {})
    if not isinstance(projects, dict):
        return False

    path = str(Path(directory).expanduser().resolve())
    for candidate in (path, _git_root(path)):
        project = projects.get(candidate) if candidate else None
        if isinstance(project, dict) and "hasTrustDialogAccepted" in project:
            return bool(project.get("hasTrustDialogAccepted"))
    return False


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: claude_trust.py <dir>", file=sys.stderr)
        sys.exit(2)
    sys.exit(0 if is_trusted(sys.argv[1]) else 1)
