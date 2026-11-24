#!/usr/bin/env python3
"""Check a daemon's `[daemon].requires` on this machine: the MCP servers, CLIs
and secrets it can't work without.

    requires.py <slug>

Exit 0: everything is there (prints a one-line summary, or nothing when the
daemon declares no requirements). Exit 1: one line per missing item, each with
how to fix it. Registering a daemon (`daimon sync --all`, the TUI's `r`,
`install --load`) is refused while anything is missing; `daimon doctor` reports
it for every active daemon.

Nothing is started: MCP servers are looked up in the files the daemon's backend
loads them from, CLIs on PATH. Only the probes a daemon declares (a `cli`
`check`, a `commands` input) run, each with a timeout and its output discarded.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from restricted_claude import servers_named  # noqa: E402

KINDS = ("mcp", "cli", "commands")
PROBE_TIMEOUT = 15


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _server_names(table) -> set[str]:
    servers = table.get("mcpServers") if isinstance(table, dict) else None
    return set(servers) if isinstance(servers, dict) else set()


def _strings(value) -> set[str]:
    return {v for v in value if isinstance(v, str)} if isinstance(value, list) else set()


def _git_root(path: Path) -> Path | None:
    for p in (path, *path.parents):
        if (p / ".git").exists():
            return p
    return None


def claude_servers(working_dir: str) -> tuple[set[str], set[str]]:
    """(available, disabled) MCP server names for a claude session started in
    working_dir, from the places Claude Code loads them: user scope
    (~/.claude.json mcpServers), local scope (~/.claude.json projects[<dir>],
    keyed by the folder or its git root), and project scope (.mcp.json in the
    folder or a parent, minus servers rejected for that project). Servers
    switched off with /mcp (disabledMcpServers) are not available."""
    state = _read_json(Path.home() / ".claude.json")
    here = Path(working_dir).expanduser().resolve()
    projects = state.get("projects")
    projects = projects if isinstance(projects, dict) else {}
    keys = {str(here)}
    root = _git_root(here)
    if root:
        keys.add(str(root))
    local = [projects[k] for k in keys if isinstance(projects.get(k), dict)]
    found = _server_names(state)
    rejected: set[str] = set()
    disabled: set[str] = set()
    for project in local:
        found |= _server_names(project)
        rejected |= _strings(project.get("disabledMcpjsonServers"))
        disabled |= _strings(project.get("disabledMcpServers"))
    for folder in (here, *here.parents):
        found |= _server_names(_read_json(folder / ".mcp.json")) - rejected
    return found - disabled, disabled


def enabled_plugins(working_dir: str) -> set[str]:
    """Plugin names (without @marketplace) enabled for a claude session in
    working_dir: user settings, then the project's, then its local ones (last wins)."""
    here = Path(working_dir).expanduser()
    state: dict[str, bool] = {}
    for path in (
        Path.home() / ".claude" / "settings.json",
        here / ".claude" / "settings.json",
        here / ".claude" / "settings.local.json",
    ):
        plugins = _read_json(path).get("enabledPlugins")
        if isinstance(plugins, dict):
            state.update({str(k): bool(v) for k, v in plugins.items()})
    return {k.split("@", 1)[0] for k, on in state.items() if on}


def codex_config_path() -> Path:
    return Path(os.path.expanduser(os.environ.get("CODEX_HOME", "~/.codex"))) / "config.toml"


def codex_servers() -> set[str]:
    """MCP servers in Codex's config.toml ([mcp_servers.<name>]), minus ones
    with enabled = false."""
    try:
        with open(codex_config_path(), "rb") as fh:
            servers = tomllib.load(fh).get("mcp_servers", {})
    except (OSError, tomllib.TOMLDecodeError):
        return set()
    if not isinstance(servers, dict):
        return set()
    return {
        n for n, s in servers.items() if not (isinstance(s, dict) and s.get("enabled") is False)
    }


def _run(command: str, env: dict, cwd: str | None) -> tuple[int | None, str]:
    """(exit code or None on timeout, stdout). stderr is dropped."""
    try:
        proc = subprocess.run(
            ["bash", "-c", command],
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, ""
    return proc.returncode, proc.stdout


def _failed(code: int | None) -> str:
    return f"timed out after {PROBE_TIMEOUT}s" if code is None else f"exit {code}"


class Checker:
    """Answers "is this one requirement met?" for one daemon, with a reason and
    a fix when it isn't. Server lookups are read once per daemon."""

    def __init__(self, cfg, slug: str):
        self.cfg = cfg
        self.slug = slug
        self.daemon = cfg.daemon(slug)
        wd = self.daemon["working_dir"]
        self.wd = wd if os.path.isdir(wd) else None
        self._servers: tuple[set[str], set[str]] | None = None

    def settings_file(self) -> str:
        path = str(self.cfg.daemon_local_path(self.slug))
        home = str(Path.home())
        return "~" + path[len(home) :] if path.startswith(home + os.sep) else path

    def env(self) -> dict:
        """The daemon's inputs as DAIMON_INPUT_*, as its gate and doctor.sh see them."""
        extra = {}
        for key, value in self.daemon["inputs"].items():
            if isinstance(value, bool):
                text = "1" if value else "0"
            elif isinstance(value, list):
                text = " ".join(map(str, value))
            else:
                text = str(value)
            extra[f"DAIMON_INPUT_{key.upper()}"] = text
        return {**os.environ, **extra}

    def servers(self) -> tuple[set[str], set[str]]:
        if self._servers is None:
            self._servers = (
                (codex_servers(), set())
                if self.daemon["backend"] == "codex"
                else claude_servers(self.daemon["working_dir"])
            )
        return self._servers

    def missing(self, kind: str, entry) -> str:
        """ "" when `entry` is met, else one line: what's missing — how to fix it."""
        return getattr(self, f"_{kind}")(entry)

    def _mcp(self, name: str) -> str:
        wd = self.daemon["working_dir"]
        attached = self.daemon["mcp"]
        if attached:
            # launch.sh runs these sessions with --strict-mcp-config: only the
            # servers dAImon writes for [daemon].mcp load, nothing of the user's.
            if name in attached:
                return ""
            return (
                f"MCP server '{name}' can't load: [daemon].mcp = {attached} limits the "
                f"session to dAImon's own servers (--strict-mcp-config) — drop [daemon].mcp"
            )
        if self.daemon["tools"]:
            return self._restricted_mcp(name)
        if self.daemon["backend"] == "codex":
            if name in self.servers()[0]:
                return ""
            return (
                f"MCP server '{name}' is not in {codex_config_path()} — "
                f"add it: codex mcp add {name} -- …"
            )
        if name.startswith("plugin:"):
            # A plugin's server, as Claude Code names it: plugin:<plugin>:<server>.
            plugin = name.split(":")[1]
            if plugin in enabled_plugins(wd):
                return ""
            return (
                f"MCP server '{name}' needs the claude plugin '{plugin}' — "
                f"enable it: claude plugin install {plugin}@<marketplace>"
            )
        available, disabled = self.servers()
        if name in available:
            return ""
        if name in disabled:
            return (
                f"MCP server '{name}' is disabled for {wd} — "
                f"enable it with /mcp in a claude session there"
            )
        if not self.daemon["working_dir_configured"]:
            return (
                f"MCP server '{name}' is not configured for {wd}, and working_dir is not "
                f"set — set it in {self.settings_file()}: servers are looked up for that folder"
            )
        return (
            f"MCP server '{name}' is not configured for {wd} — add it: "
            f"claude mcp add --scope user {name} … (or --scope local from {wd}, or {wd}/.mcp.json)"
        )

    def _restricted_mcp(self, name: str) -> str:
        # A [daemon].tools session loads no settings files: restricted_claude.py
        # copies in only the user-scope servers its rules name, and no plugins.
        limit = (
            f"MCP server '{name}' can't load: [daemon].tools sessions get only "
            f"user-scope servers their rules name"
        )
        if name.startswith("plugin:"):
            return f"{limit}, never a plugin's — drop [daemon].tools or require a user-scope server"
        fixes = []
        if name not in _server_names(_read_json(Path.home() / ".claude.json")):
            fixes.append(f"add it: claude mcp add --scope user {name} …")
        if name not in servers_named(self.daemon["tools"]):
            fixes.append(f"name it in [daemon].tools: mcp__{name}__<tool>")
        return f"{limit} — {'; '.join(fixes)}" if fixes else ""

    def _cli(self, spec: dict) -> str:
        name, check, fix = spec["name"], spec["check"], spec["fix"]
        if not shutil.which(name):
            return f"command '{name}' is not on PATH — {fix or 'install it'}"
        if not check:
            return ""
        code, _ = _run(check, self.env(), self.wd)
        if code == 0:
            return ""
        return f"`{check}` failed ({_failed(code)}) — {fix or 'make it succeed'}"

    def _commands(self, key: str) -> str:
        command = self.daemon["inputs"].get(key)
        where = f"set [inputs].{key} in {self.settings_file()}"
        if not isinstance(command, str) or not command.strip():
            return f"input '{key}' is empty — {where} to a command that prints the value"
        # The output is usually a secret: it is checked, never shown.
        code, out = _run(command, self.env(), self.wd)
        if code != 0:
            return f"input '{key}' command failed ({_failed(code)}) — fix it, or {where}"
        if not out.strip():
            return f"input '{key}' command printed nothing — fix it, or {where}"
        return ""


def label(kind: str, entry) -> str:
    if kind == "cli":
        return f"command '{entry['name']}'"
    if kind == "commands":
        return f"input '{entry}'"
    return f"MCP server '{entry}'"


def check(cfg, slug: str) -> list[str]:
    """One line per missing requirement of `slug`; [] when all are met."""
    req = cfg.requires(slug)
    if not any(req[k] for k in (*KINDS, "one_of")):
        return []
    checker = Checker(cfg, slug)
    lines = [m for kind in KINDS for entry in req[kind] if (m := checker.missing(kind, entry))]
    for group in req["one_of"]:
        alternatives = [(kind, entry) for kind in KINDS for entry in group[kind]]
        reasons = []
        for kind, entry in alternatives:
            reason = checker.missing(kind, entry)
            if not reason:
                break
            reasons.append(reason)
        else:
            names = " or ".join(label(k, e) for k, e in alternatives)
            lines.append(f"one of {names} is needed: " + "; ".join(reasons))
    return lines


def summary(cfg, slug: str) -> str:
    """What `slug` requires, in one line ("" when nothing)."""
    req = cfg.requires(slug)

    def names(group: dict) -> list[str]:
        return [label(k, e) for k in KINDS for e in group[k]]

    parts = names(req)
    parts += [f"one of {' / '.join(names(g))}" for g in req["one_of"]]
    return ", ".join(parts)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: requires.py <slug>", file=sys.stderr)
        return 2
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import config

    cfg = config.Config.load()
    slug = argv[0]
    try:
        missing = check(cfg, slug)
    except KeyError as e:
        print(e.args[0] if e.args else str(e), file=sys.stderr)
        return 2
    if missing:
        print("\n".join(missing))
        return 1
    text = summary(cfg, slug)
    if text:
        print(f"requirements met: {text}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
