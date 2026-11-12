#!/usr/bin/env python3
"""Idempotently merge dAImon's agent hooks into a settings file.

usage: install_hooks.py <settings.json> <hooks.json>
Backs up the settings file, then appends each hook entry unless every command
in it is already present under that event (exact-command dedupe, so distinct
hook sets — agent heartbeats, the standup worklog — can merge independently).
"""

import json
import shutil
import sys
from pathlib import Path


def _commands(entries) -> set:
    return {h.get("command") for entry in entries for h in entry.get("hooks", [])}


def _merge_new_entries(existing: list, entries: list) -> int:
    """Append each entry whose commands aren't all present already; return count added."""
    have = _commands(existing)
    added = 0
    for entry in entries:
        cmds = _commands([entry])
        if cmds <= have:
            continue
        existing.append(entry)
        have |= cmds
        added += 1
    return added


def main(argv):
    settings_path = Path(argv[0])
    hooks = json.loads(Path(argv[1]).read_text())

    settings = {}
    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
        shutil.copy(settings_path, str(settings_path) + ".daimon-bak")

    settings.setdefault("hooks", {})
    added = 0
    for event, entries in hooks.items():
        added += _merge_new_entries(settings["hooks"].setdefault(event, []), entries)

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"hooks: merged {added} event(s) into {settings_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
