#!/usr/bin/env python3
"""Scaffold a slack-commands plugin: `daimon command new <name> [--shared]`.

Plugins are markdown runbooks: your own in ~/.daimon/commands (beside
daimon.toml), shared ones in catalog/slack-commands/commands (--shared,
committed), or a pack's commands/ (--pack). Naming is {domain}-{action}, one
hyphenated token."""

import re
import sys
from pathlib import Path

INSTALL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(INSTALL_ROOT / "lib"))
import config  # noqa: E402

SHARED = INSTALL_ROOT / "catalog" / "slack-commands" / "commands"
NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")

TEMPLATE = """---
name: {name}
match: {name}
mutating: {mutating}
description: TODO one line — this is what `help` lists.
---

TODO: the runbook. Write it as instructions for an agent, not a script:
what to gather, then what to reply.

1. Gather — the commands to run (they execute from the daemon's
   working_dir, so repo tooling is available).
2. Reply — lead with the answer, then supporting bullets. Labeled links
   only (never bare URLs), no timestamps, no closing offers.

Arguments, if any, arrive as everything after the command word.
"""


def create(name: str, shared: bool, mutating: bool, pack: Path | None = None) -> int:
    if not NAME_RE.match(name):
        print(
            f"✗ {name!r} is not a valid command name — use one lowercase "
            "hyphenated token, {domain}-{action}: staging-push, epic-status",
            file=sys.stderr,
        )
        return 1

    local = config.personal_dir() / "commands"
    target_dir = pack / "commands" if pack is not None else (SHARED if shared else local)
    path = target_dir / f"{name}.md"
    for existing in (SHARED, local, target_dir):
        if (existing / f"{name}.md").exists():
            print(f"✗ {name} already exists: {existing / f'{name}.md'}", file=sys.stderr)
            return 1

    target_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE.format(name=name, mutating=str(mutating).lower()))
    print(f"+ {path}")
    print("  edit it, then use it in Slack immediately — plugins load per run, no sync")
    if mutating:
        print("  mutating: restricted to mutate_allowlist + Slack-granted users")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] != "new":
        print(
            "usage: daimon command new <name> [--shared | --pack <dir>] [--mutating]",
            file=sys.stderr,
        )
        return 2
    pack = None
    if "--pack" in argv:
        i = argv.index("--pack")
        if i + 1 >= len(argv):
            print("--pack needs a directory", file=sys.stderr)
            return 2
        pack = Path(argv[i + 1]).expanduser()
    return create(argv[1], "--shared" in argv, "--mutating" in argv, pack)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
