#!/usr/bin/env python3
"""Write what a tools-restricted Claude session starts from.

usage: restricted_claude.py <out-dir> <slug>   (reads DAIMON_D_TOOLS from the env)

A restricted session loads NO settings files: the user's own allow rules
(`Bash(git commit:*)`, a broad loop pattern, ...) would otherwise widen the
daemon's allowlist. That also drops what it does need from them, so this
writes those back, and nothing else:

  settings.json  dAImon's own hooks (heartbeat + completion sentinel)
  mcp.json       the user-scope MCP servers the allowlist names
                 (`mcp__<server>__<tool>`), copied from ~/.claude.json
  plugin/        a one-skill plugin holding the daemon's synced skill. User
                 skills are a user setting source too, so without this the
                 launch command `/<slug>` is unknown and the session sits idle.

mcp.json can hold credentials, so both files are written 0600.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def servers_named(tools: list[str]) -> list[str]:
    names = []
    for rule in tools:
        if rule.startswith("mcp__"):
            name = rule[len("mcp__") :].split("__", 1)[0]
            if name not in names:
                names.append(name)
    return names


def mcp_subset(user_servers: dict, names: list[str]) -> dict:
    return {n: user_servers[n] for n in names if n in user_servers}


# Writes here are atomic (temp + rename): two launchers started at once both run
# this, and the loser must not truncate a file the winner's session is reading.
def _write_private(path: Path, data) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w") as f:  # mkstemp creates it 0600
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def write_skill_plugin(out: Path, slug: str) -> bool:
    """Copy the skill `daimon sync` installed into a plugin dir for --plugin-dir."""
    plugin = out / "plugin"
    skill = Path.home() / ".claude" / "skills" / slug
    if not (skill / "SKILL.md").is_file():
        shutil.rmtree(plugin, ignore_errors=True)
        return False
    current = plugin / "skills" / slug / "SKILL.md"
    if current.is_file() and current.read_bytes() == (skill / "SKILL.md").read_bytes():
        return True  # unchanged: leave it, a session may be loading it
    staged = Path(tempfile.mkdtemp(dir=out, prefix=".plugin."))
    (staged / ".claude-plugin").mkdir()
    (staged / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": f"daimon-{slug}", "version": "0.0.0"}) + "\n"
    )
    shutil.copytree(skill, staged / "skills" / slug)
    shutil.rmtree(plugin, ignore_errors=True)
    staged.rename(plugin)
    return True


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: restricted_claude.py <out-dir> <slug>", file=sys.stderr)
        return 2
    out, slug = Path(argv[0]), argv[1]
    out.mkdir(parents=True, exist_ok=True)
    if not write_skill_plugin(out, slug):
        print(f"restricted_claude: skill '{slug}' not synced — run: daimon sync", file=sys.stderr)
    tools = shlex.split(os.environ.get("DAIMON_D_TOOLS", ""))

    hooks = json.loads((ROOT / "config" / "hooks" / "claude-hooks.json").read_text())
    _write_private(out / "settings.json", {"hooks": hooks})

    try:
        user = json.loads((Path.home() / ".claude.json").read_text()).get("mcpServers", {})
    except (OSError, ValueError):
        user = {}
    names = servers_named(tools)
    servers = mcp_subset(user, names)
    for missing in sorted(set(names) - set(servers)):
        print(
            f"restricted_claude: no user-scope MCP server '{missing}' in ~/.claude.json",
            file=sys.stderr,
        )
    _write_private(out / "mcp.json", {"mcpServers": servers})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
