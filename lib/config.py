#!/usr/bin/env python3
"""Single source of truth for dAImon config: load, merge, validate, render.

All other components (bash libs, the TUI, the installer) shell out to this rather
than parse TOML themselves, so defaults/merge/validation live in exactly one place.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import tomllib
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parent))
import schedule_fmt  # noqa: E402
import toml_emit  # noqa: E402

BACKENDS = ("claude", "codex")

MCP_SERVERS = {
    "codex": {"command": "codex", "args": ["mcp-server"]},
}

CORE_DEFAULTS = {
    "namespace": "daimon",
    "state_dir": "~/.local/state/daimon",
    "timezone": "UTC",
    "log_retention_days": 14,
    "log_max_mb": 10,
    "log_keep": 3,
}
DEFAULT_DEFAULTS = {
    "backend": "claude",
    "fallback_backend": "",
    "model": "opus",
    "danger": True,
    "stuck_after": 2700,
    "ready_timeout": 20,
    "mcp": [],
}
PLACEHOLDER_WORKING_DIRS = {"~/code", "~/code/your-repo"}
THROTTLE_DEFAULTS = {
    "exempt": [],
    "moderate_mod": 2,
    "severe_mod": 4,
    "severe_critical": [],
}
BUDGET_DEFAULTS = {"hourly_cap": 12, "defer_at_pct": 80, "exempt": []}
# `command` decides whether this machine runs a daemon that has a `role`: a
# template with {role} and {seconds}, exit 0 = run here, 1 = another machine does.
ROLES_DEFAULTS = {"command": ""}
ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
# `command` receives this machine's daemon status as JSON on stdin after every
# watchdog sweep and agent run: a template with {seconds} (how long the report
# should be trusted). Empty: no report.
STATUS_DEFAULTS = {"command": ""}
# `auto` loads com.<ns>.update, which runs `daimon update` hourly: fast-forward
# to a green upstream, then install + sync. Off unless a setup turns it on.
UPDATE_DEFAULTS = {"auto": False}
UPDATE_INTERVAL_SECONDS = 3600
STATUS_TTL_SECONDS = 900

DAEMON_FIELDS = (
    "backend",
    "fallback_backend",
    "model",
    "danger",
    "stuck_after",
    "command",
    "schedule",
)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def sources_of(daemon: dict) -> list[dict]:
    raw = daemon.get("sources")
    if raw is None:
        single = daemon.get("source", "")
        raw = [single] if single else []
    elif isinstance(raw, str):
        raw = [raw]
    specs: list[dict] = []
    for entry in raw:
        if isinstance(entry, dict):
            name = entry.get("name", "")
            if name:
                specs.append({"name": name, "write": bool(entry.get("write", False))})
        elif entry:
            specs.append({"name": entry, "write": False})
    return specs


def expand(p: str) -> Path:
    return Path(os.path.expanduser(p)).resolve()


PERSONAL_DIR = "~/.daimon"
# Where personal settings lived before ~/.daimon. `daimon migrate` moves them.
LEGACY_PERSONAL_DIR = "~/.config/daimon"


def global_config_path() -> Path:
    """$DAIMON_CONFIG, else ~/.daimon/daimon.toml. Until `daimon migrate` has moved
    it, a legacy ~/.config/daimon/daimon.toml is read instead: a launchd job that
    fires after an update's fast-forward but before its install still finds it."""
    env = os.environ.get("DAIMON_CONFIG")
    if env:
        return Path(os.path.expanduser(env))
    current = Path(os.path.expanduser(PERSONAL_DIR)) / "daimon.toml"
    legacy = Path(os.path.expanduser(LEGACY_PERSONAL_DIR)) / "daimon.toml"
    if not current.exists() and legacy.exists():
        return legacy
    return current


def personal_dir() -> Path:
    """Where each person's own settings live, outside any repo: the folder holding
    the global config (~/.daimon, or $DAIMON_CONFIG's parent)."""
    return global_config_path().parent


def _load_toml(path: Path) -> dict:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


# A daemon folder named <slug>.local is private: .gitignore keeps it out of the
# repo, but it loads exactly like daemons/<slug> under the plain slug.
LOCAL_SUFFIX = ".local"


def slug_for_dir(name: str) -> str:
    return name[: -len(LOCAL_SUFFIX)] if name.endswith(LOCAL_SUFFIX) else name


# An ejected copy (`daimon eject`) records where it came from in this file:
# {"source": "dAImon" or a pack's name, "path": the folder relative to that
# root, "hash": the content hash of the files when they were copied}, plus
# "as": the copy's own slug when it was forked under a new name (`--as`).
ORIGIN_FILE = ".origin.json"


def read_origin(folder: Path) -> dict | None:
    try:
        data = json.loads((folder / ORIGIN_FILE).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class Config:
    def __init__(self, raw: dict, source: Path | None):
        self.source = source
        self.core = {**CORE_DEFAULTS, **raw.get("core", {})}
        self.defaults = {**DEFAULT_DEFAULTS, **raw.get("defaults", {})}
        self.throttle = {**THROTTLE_DEFAULTS, **raw.get("throttle", {})}
        self.budget = {**BUDGET_DEFAULTS, **raw.get("budget", {})}
        self.roles = {**ROLES_DEFAULTS, **raw.get("roles", {})}
        self.status = {**STATUS_DEFAULTS, **raw.get("status", {})}
        self.update = {**UPDATE_DEFAULTS, **raw.get("update", {})}
        daemons = raw.get("daemons", {})
        self.disabled = list(daemons.get("disabled", []))
        # None = no `installed` key (an install from before the catalog).
        self.installed_list = (
            list(daemons["installed"]) if isinstance(daemons.get("installed"), list) else None
        )
        # Packs: directories outside the install root that add daemons, team
        # overrides, profile defaults and slack-commands runbooks (docs/packs.md).
        self.packs = [expand(p) for p in raw.get("packs", {}).get("paths", [])]
        if "install_root" in self.core:
            self.install_root = expand(self.core["install_root"])
        else:
            self.install_root = repo_root()
        self.state_dir = expand(self.core["state_dir"])
        self._discover_cache: dict[str, dict] | None = None

    @classmethod
    def load(cls) -> Config:
        path = global_config_path()
        raw = _load_toml(path) if path.exists() else {}
        return cls(raw, path if path.exists() else None)

    def daemons_dir(self) -> Path:
        """Ejected daemons: <install_root>/daemons/, gitignored apart from its README.
        Your own daemons and private `<slug>.local` ones live here too."""
        return self.install_root / "daemons"

    def catalog_dir(self) -> Path:
        """dAImon's own catalog, in git: <install_root>/catalog/."""
        return self.install_root / "catalog"

    def catalog_roots(self) -> list[Path]:
        """Where installable daemons come from: dAImon's catalog/, then each pack's
        daemons/."""
        return [self.catalog_dir(), *(p / "daemons" for p in self.packs)]

    def daemon_roots(self) -> list[Path]:
        """Every folder a daemon can load from: ejected first, then the catalogs."""
        return [self.daemons_dir(), *self.catalog_roots()]

    @staticmethod
    def _scan_root(root: Path, out: dict[str, list[Path]]) -> dict[str, list[Path]]:
        # Only a folder with a daemon.toml is a daemon: a leftover folder holding
        # nothing but gitignored files (an old daemon.local.toml) is not.
        for cfg in sorted(root.glob("*/daemon.toml")):
            out.setdefault(slug_for_dir(cfg.parent.name), []).append(cfg.parent)
        return out

    def shadows_daimon(self, folder: Path, slug: str) -> bool:
        """A pack's copy of a dAImon catalog daemon (`daimon eject --pack`): its
        .origin.json names dAImon's catalog/<slug>, so it overrides that daemon on
        purpose rather than duplicating it. A renamed copy (`--as`) is a distinct
        daemon and never shadows anything."""
        if folder.parent == self.catalog_dir():
            return False
        origin = read_origin(folder) or {}
        if origin.get("as"):
            return False
        return origin.get("source") == "dAImon" and origin.get("path") == f"catalog/{slug}"

    def catalog_locations(self) -> dict[str, list[Path]]:
        """Every catalog folder offering each slug, in catalog order, except that a
        pack copy taken from dAImon's catalog comes before the original it shadows."""
        out: dict[str, list[Path]] = {}
        for root in self.catalog_roots():
            self._scan_root(root, out)
        return {
            slug: sorted(dirs, key=lambda d, s=slug: not self.shadows_daimon(d, s))
            for slug, dirs in out.items()
        }

    def ejected_locations(self) -> dict[str, list[Path]]:
        """Ejected copies under daemons/: `<slug>` and/or private `<slug>.local`."""
        return self._scan_root(self.daemons_dir(), {})

    def daemon_locations(self) -> dict[str, list[Path]]:
        """Every folder defining each slug, ejected first; the first one loads."""
        out = {slug: list(dirs) for slug, dirs in self.ejected_locations().items()}
        for slug, dirs in self.catalog_locations().items():
            out.setdefault(slug, []).extend(dirs)
        return out

    def catalog_source(self, path: Path) -> str:
        """A short name for where a daemon folder comes from."""
        if path.parent == self.daemons_dir():
            return "ejected"
        if path.parent == self.catalog_dir():
            return "dAImon"
        return path.parent.parent.name  # <pack>/daemons/<slug>

    def catalog(self) -> dict[str, dict]:
        """Every installable slug: {slug: {"path": folder, "source": name}}, from
        the first catalog that has it (dAImon's, then packs in order)."""
        return {
            slug: {"path": dirs[0], "source": self.catalog_source(dirs[0])}
            for slug, dirs in self.catalog_locations().items()
        }

    def installed(self) -> list[str]:
        """`[daemons].installed`. Absent (an install from before the catalog):
        every catalog slug minus `disabled`, which is how it behaved then."""
        if self.installed_list is not None:
            return list(self.installed_list)
        return [s for s in self.catalog_locations() if s not in self.disabled]

    def daemon_dir(self, slug: str) -> Path:
        """The folder holding `slug`: an ejected daemons/<slug> (or the private
        daemons/<slug>.local) when present, else the first catalog with it."""
        found = self.daemon_locations().get(slug)
        return found[0] if found else self.daemons_dir() / slug

    def pack_overrides(self, slug: str) -> list[Path]:
        return [p / "overrides" / f"{slug}.toml" for p in self.packs]

    def pack_commands_dirs(self) -> list[str]:
        return [str(p / "commands") for p in self.packs if (p / "commands").is_dir()]

    def local_commands_dir(self) -> Path:
        """slack-commands runbooks of your own: <personal dir>/commands."""
        return personal_dir() / "commands"

    def legacy_local_commands_dir(self) -> Path:
        """Where your own runbooks lived before the catalog. Still read until
        `daimon migrate` moves them to local_commands_dir()."""
        return self.daemons_dir() / "slack-commands" / "commands.local"

    def discover(self) -> dict[str, dict]:
        if self._discover_cache is None:
            self._discover_cache = self._scan_daemons()
        return self._discover_cache

    def _scan_daemons(self) -> dict[str, dict]:
        """installed ∪ ejected − disabled. Ordered like the folders: the install
        root's daemons (ejected or dAImon's catalog) sorted, then each pack's."""
        locations = self.daemon_locations()
        wanted = (set(self.installed()) | set(self.ejected_locations())) - set(self.disabled)
        home = {self.daemons_dir(), self.catalog_dir()}
        own = sorted(s for s in wanted if s in locations and locations[s][0].parent in home)
        packs = [s for s in locations if s in wanted and s not in own]
        return {slug: _load_toml(locations[slug][0] / "daemon.toml") for slug in own + packs}

    def profiles_dir(self) -> Path:
        return self.install_root / "profiles"

    def load_profile(self, name: str) -> dict | None:
        path = self.profiles_dir() / name / "profile.toml"
        if not path.exists():
            return None
        prof = _load_toml(path)
        for pack in self.packs:
            team = pack / "profiles" / f"{name}.toml"
            if team.exists():
                prof.setdefault("defaults", {}).update(_load_toml(team).get("defaults", {}))
        # profile.toml < pack profiles < legacy profile.local.toml < personal file
        for local in (self.legacy_profile_local_path(name), self.profile_local_path(name)):
            if local.exists():
                prof.setdefault("defaults", {}).update(_load_toml(local).get("defaults", {}))
        return prof

    def daemon_local_path(self, slug: str) -> Path:
        """This person's settings for `slug`: <personal dir>/daemons/<slug>.toml."""
        return personal_dir() / "daemons" / f"{slug}.toml"

    def legacy_daemon_local_paths(self, slug: str) -> list[Path]:
        """The pre-personal-dir locations, lowest first: daemons/<slug>/, where the
        file stayed (gitignored) when the daemon's code moved to catalog/, then
        beside the daemon.toml that loads. Still read (under the personal file)
        until `daimon migrate` moves them."""
        here = self.daemon_dir(slug) / "daemon.local.toml"
        moved_out = self.daemons_dir() / slug / "daemon.local.toml"
        return [here] if moved_out == here else [moved_out, here]

    def raw_daemon(self, slug: str) -> dict:
        raw = self.discover().get(slug, {})
        d, i = dict(raw.get("daemon", {})), dict(raw.get("inputs", {}))
        # daemon.toml < each pack's overrides/<slug>.toml (team) < legacy
        # daemon.local.toml < the personal <personal dir>/daemons/<slug>.toml
        layers = [
            *self.pack_overrides(slug),
            *self.legacy_daemon_local_paths(slug),
            self.daemon_local_path(slug),
        ]
        for layer in layers:
            if layer.exists():
                over = _load_toml(layer)
                d.update(over.get("daemon", {}))
                i.update(over.get("inputs", {}))
        return {"daemon": d, "inputs": i}

    def daemon(self, slug: str) -> dict:
        if self.discover().get(slug) is None:
            raise KeyError(f"unknown daemon: {slug}")
        raw = self.raw_daemon(slug)
        merged = dict(self.defaults)
        merged.update(raw["daemon"])
        specs = sources_of(merged)
        inputs: dict = {}
        for s in specs:
            prof = self.load_profile(s["name"])
            if prof:
                inputs.update(prof.get("defaults", {}))
        inputs.update(raw["inputs"])
        # A daemon that declares pack_commands_dirs (slack-commands) gets every
        # pack's commands/ folder unless it set the list itself.
        if "pack_commands_dirs" in inputs and _is_empty(inputs["pack_commands_dirs"]):
            inputs["pack_commands_dirs"] = self.pack_commands_dirs()
        # ...and an empty local_commands_dir means <personal dir>/commands. Runbooks
        # not yet migrated from the old in-repo commands.local/ are read just
        # before it, so they keep overriding shared and pack ones.
        if "local_commands_dir" in inputs and _is_empty(inputs["local_commands_dir"]):
            inputs["local_commands_dir"] = str(self.local_commands_dir())
            legacy = self.legacy_local_commands_dir()
            if any(legacy.glob("*.md")):
                inputs["pack_commands_dirs"] = [*inputs.get("pack_commands_dirs", []), str(legacy)]
        # {{daemon_dir}} in an input is the folder the daemon loads from, so a path
        # into the daemon's own files follows it when it is ejected or in a pack.
        here = str(self.daemon_dir(slug))
        merged["inputs"] = {k: _with_daemon_dir(v, here) for k, v in inputs.items()}
        merged["sources"] = [s["name"] for s in specs]
        merged["write_sources"] = [s["name"] for s in specs if s["write"]]
        merged["source"] = specs[0]["name"] if specs else ""
        merged["slug"] = slug
        wd = merged.get("working_dir")
        merged["working_dir_configured"] = bool(wd) and wd not in PLACEHOLDER_WORKING_DIRS
        merged["working_dir"] = str(expand(wd)) if wd else str(self.install_root)
        ri = merged.get("required_inputs", [])
        merged["required_inputs"] = list(ri) if isinstance(ri, list) else [ri]
        mcp = merged.get("mcp", [])
        merged["mcp"] = [mcp] if isinstance(mcp, str) else list(mcp)
        tools = merged.get("tools", [])
        merged["tools"] = [tools] if isinstance(tools, str) else list(tools)
        return merged

    def mcp_config(self, slug: str) -> dict:
        names = self.daemon(slug)["mcp"]
        servers = {n: MCP_SERVERS[n] for n in names if n in MCP_SERVERS}
        return {"mcpServers": servers} if servers else {}

    def backends(self, slug: str) -> list[str]:
        daemon = self.daemon(slug)
        backends = [daemon["backend"]]
        if daemon["fallback_backend"]:
            backends.append(daemon["fallback_backend"])
        return backends

    def model_for(self, slug: str, backend: str) -> str:
        m = self.daemon(slug)["model"]
        if isinstance(m, dict):
            return m.get(backend) or m.get("default") or ""
        return m

    def daemon_toml_path(self, slug: str) -> Path:
        return self.daemon_dir(slug) / "daemon.toml"

    def _merge_write(self, path: Path, daemon: dict, inputs: dict | None) -> None:
        raw = _load_toml(path) if path.exists() else {}
        raw.setdefault("daemon", {}).update(daemon)
        if inputs is not None:
            raw["inputs"] = inputs
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            toml_emit.dump_sections(
                {"daemon": raw.get("daemon", {}), "inputs": raw.get("inputs", {})}
            )
        )
        self._discover_cache = None

    def update_daemon_field(self, slug: str, field: str, value) -> None:
        self._merge_write(self.daemon_toml_path(slug), {field: value}, None)

    def update_local(self, slug: str, daemon: dict, inputs: dict | None = None) -> None:
        self._merge_write(self.daemon_local_path(slug), daemon, inputs)

    def profile_local_path(self, name: str) -> Path:
        """This person's settings for profile `name`: <personal dir>/profiles/<name>.toml."""
        return personal_dir() / "profiles" / f"{name}.toml"

    def legacy_profile_local_path(self, name: str) -> Path:
        return self.profiles_dir() / name / "profile.local.toml"

    def update_profile_local(self, name: str, defaults: dict) -> None:
        path = self.profile_local_path(name)
        raw = _load_toml(path) if path.exists() else {}
        merged = {**raw.get("defaults", {}), **defaults}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(toml_emit.dump_sections({"defaults": merged}))
        self._discover_cache = None

    def input_provenance(self, slug: str) -> dict:
        """Split a daemon's effective inputs by origin: keys it owns (edited in its
        personal settings file) versus keys inherited from each source profile's defaults
        (edited profile-wide). A key the daemon overrides counts as daemon-owned."""
        owned = self.raw_daemon(slug)["inputs"]
        profiles: dict[str, dict] = {}
        for src in self.daemon(slug)["sources"]:
            prof = self.load_profile(src)
            if not prof:
                continue
            inherited = {k: v for k, v in prof.get("defaults", {}).items() if k not in owned}
            if inherited:
                profiles[src] = inherited
        return {"daemon": dict(owned), "profiles": profiles}


def render_plist(cfg: Config, slug: str) -> str:
    d = cfg.daemon(slug)
    return render_plist_raw(
        label=f"com.{cfg.core['namespace']}.{slug}",
        program=[str(cfg.install_root / "lib" / "run.sh"), slug],
        working_dir=d["working_dir"],
        schedule_xml=schedule_fmt.to_plist(d["schedule"]),
        log=str(cfg.state_dir / "logs" / f"{slug}.log"),
    )


def render_watchdog_plist(cfg: Config) -> str:
    return render_plist_raw(
        label=f"com.{cfg.core['namespace']}.watchdog",
        program=[str(cfg.install_root / "lib" / "watchdog.sh")],
        working_dir=str(cfg.install_root),
        schedule_xml="    <key>StartInterval</key>\n    <integer>300</integer>",
        log=str(cfg.state_dir / "logs" / "watchdog.log"),
    )


def render_update_plist(cfg: Config) -> str:
    """com.<ns>.update: `daimon update` hourly, and once at load (login)."""
    return render_plist_raw(
        label=f"com.{cfg.core['namespace']}.update",
        program=[str(cfg.install_root / "lib" / "self_update.sh")],
        working_dir=str(cfg.install_root),
        schedule_xml=(
            f"    <key>StartInterval</key>\n    <integer>{UPDATE_INTERVAL_SECONDS}</integer>"
        ),
        log=str(cfg.state_dir / "logs" / "update.log"),
        run_at_load=True,
    )


def render_plist_raw(label, program, working_dir, schedule_xml, log, run_at_load=False) -> str:
    args = "\n".join(f"        <string>{escape(a)}</string>" for a in program)
    env_xml = "\n".join(
        f"        <key>{k}</key>\n        <string>{escape(os.environ[k])}</string>"
        for k in ("PATH", "HOME", "SSH_AUTH_SOCK")
        if os.environ.get(k)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
{args}
    </array>
    <key>WorkingDirectory</key>
    <string>{working_dir}</string>
{schedule_xml}
    <key>StandardOutPath</key>
    <string>{log}</string>
    <key>StandardErrorPath</key>
    <string>{log}</string>
    <key>EnvironmentVariables</key>
    <dict>
{env_xml}
    </dict>
    <key>RunAtLoad</key>
    <{"true" if run_at_load else "false"}/>
</dict>
</plist>
"""


def _append_ref(text: str, path: Path) -> str:
    """Append a reference doc (separated by a markdown rule) if it exists."""
    if path.exists():
        text += f"\n\n---\n\n{path.read_text()}"
    return text


def render_skill(cfg: Config, slug: str) -> str:
    d = cfg.daemon(slug)
    text = (cfg.daemon_dir(slug) / "skill" / "SKILL.md").read_text()
    for source in d["sources"]:
        text = _append_ref(text, cfg.profiles_dir() / source / "reference.md")
        if source in d["write_sources"]:
            text = _append_ref(text, cfg.profiles_dir() / source / "reference.write.md")
    if "codex" in d["mcp"]:
        text = _append_ref(text, cfg.install_root / "references" / "codex-review.md")
    if "bot_marker" in d["inputs"]:
        text = _append_ref(text, cfg.install_root / "references" / "skill-conventions.md")
        text = _append_ref(text, cfg.install_root / "references" / "output-conventions.md")
    if d.get("learning", True):
        text = _append_ref(text, cfg.install_root / "references" / "learning.md")
    text = _append_ref(text, cfg.install_root / "references" / "unattended.md")
    text = _append_ref(text, cfg.install_root / "references" / "results.md")
    text = text.replace("{{daemon_dir}}", str(cfg.daemon_dir(slug)))
    for key, val in d["inputs"].items():
        rendered = ", ".join(str(x) for x in val) if isinstance(val, list) else str(val)
        text = text.replace(f"{{{{inputs.{key}}}}}", rendered)
    return text


def _with_daemon_dir(value, here: str):
    if isinstance(value, str):
        return value.replace("{{daemon_dir}}", here)
    if isinstance(value, list):
        return [_with_daemon_dir(v, here) for v in value]
    return value


def _is_empty(value) -> bool:
    if value is None or value == [] or value == {}:
        return True
    return isinstance(value, str) and value.strip() == ""


def _missing_required_inputs(cfg: Config, slug: str) -> list[str]:
    merged = cfg.daemon(slug)
    inputs = merged["inputs"]
    return [key for key in merged["required_inputs"] if _is_empty(inputs.get(key))]


def _required_input_errors(cfg: Config, slug: str) -> list[str]:
    return [
        f"{slug}: required input '{key}' is missing or empty"
        for key in _missing_required_inputs(cfg, slug)
    ]


def _mcp_errors(cfg: Config, slug: str) -> list[str]:
    merged = cfg.daemon(slug)
    names = merged["mcp"]
    errors = [
        f"{slug}: unknown mcp server '{n}' (known: {', '.join(MCP_SERVERS)})"
        for n in names
        if n not in MCP_SERVERS
    ]
    if names and not merged["danger"]:
        errors.append(
            f"{slug}: mcp requires danger=true — a non-interactive session "
            f"cannot answer an MCP tool-permission prompt"
        )
    return errors


def _tools_errors(cfg: Config, slug: str) -> list[str]:
    # A tools allowlist is only a restriction if every run enforces it. A codex
    # run (primary or fallback) can't, and an empty list would quietly fall back
    # to `danger`, so both are config errors rather than a silent widening.
    merged = cfg.daemon(slug)
    tools = merged["tools"]
    if not tools:
        declared = "tools" in cfg.raw_daemon(slug)["daemon"] or "tools" in cfg.defaults
        return (
            [f"{slug}: tools is empty — list at least one rule, or remove it"] if declared else []
        )
    errors = [
        f"{slug}: tools allowlist is claude-only — remove {be} as backend/fallback_backend"
        for be in cfg.backends(slug)
        if be != "claude"
    ]
    if any(not isinstance(t, str) or not t.strip() for t in tools):
        errors.append(f"{slug}: every tools rule must be a non-empty string")
    if merged["mcp"]:
        errors.append(
            f"{slug}: mcp can't be combined with tools — a restricted session takes MCP "
            f"servers only from the user-scope ones its tools rules name"
        )
    return errors


def validate(cfg: Config) -> list[str]:
    errors: list[str] = []
    if cfg.source is None:
        errors.append(f"no config file at {global_config_path()} (copy config/daimon.toml.example)")
    if cfg.defaults["backend"] not in BACKENDS:
        errors.append(f"[defaults].backend must be one of {BACKENDS}")
    default_fallback = cfg.defaults["fallback_backend"]
    if default_fallback and default_fallback not in BACKENDS:
        errors.append(f"[defaults].fallback_backend must be one of {BACKENDS}")
    if default_fallback == cfg.defaults["backend"]:
        errors.append("[defaults].fallback_backend must differ from backend")
    daemons = cfg.discover()
    if not daemons and cfg.installed_list is None:
        errors.append(f"no daemons discovered under {', '.join(map(str, cfg.daemon_roots()))}")
    for pack in cfg.packs:
        if not pack.is_dir():
            errors.append(f"[packs].paths: {pack} does not exist")
    for slug, raw in daemons.items():
        d = raw.get("daemon", {})
        merged = cfg.daemon(slug)
        be = merged["backend"]
        fallback = merged["fallback_backend"]
        if be not in BACKENDS:
            errors.append(f"{slug}: backend must be one of {BACKENDS}")
        if fallback and fallback not in BACKENDS:
            errors.append(f"{slug}: fallback_backend must be one of {BACKENDS}")
        if fallback == be:
            errors.append(f"{slug}: fallback_backend must differ from backend")
        cmd = d.get("command")
        if not cmd or not str(cmd).startswith("/"):
            errors.append(f"{slug}: [daemon].command must be set and start with '/'")
        sched = d.get("schedule")
        if not sched:
            errors.append(f"{slug}: [daemon].schedule is required")
        else:
            try:
                schedule_fmt.descriptor(sched)
            except ValueError as e:
                errors.append(f"{slug}: {e}")
        skill = cfg.daemon_dir(slug) / "skill" / "SKILL.md"
        if not skill.exists():
            errors.append(f"{slug}: missing skill/SKILL.md")
        unknown = [s["name"] for s in sources_of(d) if cfg.load_profile(s["name"]) is None]
        if unknown:
            for s in unknown:
                errors.append(
                    f"{slug}: unknown source profile '{s}' (no profiles/{s}/profile.toml)"
                )
        else:
            errors.extend(_required_input_errors(cfg, slug))
            errors.extend(_mcp_errors(cfg, slug))
            errors.extend(_tools_errors(cfg, slug))
        errors.extend(_role_errors(cfg, slug))
    errors.extend(_catalog_errors(cfg))
    return errors


def _catalog_errors(cfg: Config) -> list[str]:
    """Installed slugs nobody offers, slugs offered twice, unknown disabled ones."""
    errors: list[str] = []
    offered = cfg.catalog_locations()
    ejected = cfg.ejected_locations()
    for slug in cfg.installed_list or []:
        if slug not in offered and slug not in ejected:
            errors.append(
                f"[daemons].installed: {slug} is in no catalog "
                f"({', '.join(map(str, cfg.catalog_roots()))}); `daimon remove {slug}`"
            )
    for slug, dirs in sorted(ejected.items()):
        if len(dirs) > 1:
            errors.append(f"{slug}: defined twice ({' and '.join(map(str, dirs))})")
    for slug, dirs in sorted(offered.items()):
        # A pack copy of a dAImon daemon (`daimon eject --pack`) overrides it.
        if any(cfg.shadows_daimon(d, slug) for d in dirs):
            dirs = [d for d in dirs if d.parent != cfg.catalog_dir()]
        # An ejected copy takes precedence, so it settles which one loads.
        if len(dirs) > 1 and slug not in ejected:
            errors.append(f"{slug}: defined twice ({' and '.join(map(str, dirs))})")
    for slug in cfg.disabled:
        if slug not in offered and slug not in ejected:
            errors.append(f"[daemons].disabled references unknown daemon: {slug}")
    return errors


def role_command(cfg: Config, slug: str) -> str:
    """The shell command that asks whether this machine holds `slug`'s role, or ""
    when the daemon has no role. Raises ValueError when the role can't be checked."""
    d = cfg.daemon(slug)
    role = d.get("role", "")
    if not role:
        return ""
    if not ROLE_PATTERN.match(str(role)):
        raise ValueError(f"role must match {ROLE_PATTERN.pattern}: {role!r}")
    template = cfg.roles["command"]
    if not template:
        raise ValueError(f"role {role!r} is set but [roles].command is empty")
    hold = d.get("role_hold")
    if hold is None:
        interval = (d.get("schedule") or {}).get("interval")
        if interval is None:
            raise ValueError("role_hold is required for a role on a minutes/daily schedule")
        hold = 2 * int(interval) + 60
    return template.replace("{role}", shlex.quote(str(role))).replace(
        "{seconds}", shlex.quote(str(int(hold)))
    )


def status_command(cfg: Config, seconds: int = STATUS_TTL_SECONDS) -> str:
    """The shell command that receives the agent-status JSON, or "" when unset."""
    template = cfg.status["command"]
    if not template:
        return ""
    return template.replace("{seconds}", shlex.quote(str(int(seconds))))


def _role_errors(cfg: Config, slug: str) -> list[str]:
    try:
        role_command(cfg, slug)
    except ValueError as e:
        return [f"{slug}: {e}"]
    return []


def daemon_schema() -> dict:
    schedule = {
        "type": "object",
        "oneOf": [
            {
                "required": ["interval"],
                "properties": {"interval": {"type": "integer", "minimum": 1}},
                "additionalProperties": False,
            },
            {
                "required": ["minutes"],
                "properties": {
                    "minutes": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 0, "maximum": 59},
                    }
                },
                "additionalProperties": False,
            },
            {
                "required": ["daily"],
                "properties": {
                    "daily": {"type": "string", "pattern": r"^[0-9]{1,2}:[0-9]{2}$"},
                    "tz": {"type": "string"},
                },
                "additionalProperties": False,
            },
        ],
    }
    daemon = {
        "type": "object",
        "required": ["command", "schedule"],
        "additionalProperties": False,
        "properties": {
            "backend": {"type": "string", "enum": list(BACKENDS)},
            "fallback_backend": {"type": "string", "enum": ["", *BACKENDS]},
            "model": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "object", "additionalProperties": {"type": "string"}},
                ]
            },
            "danger": {"type": "boolean"},
            "stuck_after": {"type": "integer", "minimum": 1},
            "ready_timeout": {"type": "integer", "minimum": 1},
            "hourly_cap": {"type": "integer", "minimum": 1},
            "role": {"type": "string", "pattern": ROLE_PATTERN.pattern},
            "role_hold": {"type": "integer", "minimum": 1},
            "command": {"type": "string", "pattern": "^/"},
            "schedule": schedule,
            "source": {"type": "string"},
            "sources": {
                "type": "array",
                "items": {
                    "oneOf": [
                        {"type": "string"},
                        {
                            "type": "object",
                            "required": ["name"],
                            "additionalProperties": False,
                            "properties": {
                                "name": {"type": "string"},
                                "write": {"type": "boolean"},
                            },
                        },
                    ]
                },
            },
            "working_dir": {"type": "string"},
            "learning": {"type": "boolean"},
            "clean_worktrees": {"type": "string"},
            "mcp": {"type": "array", "items": {"type": "string", "enum": list(MCP_SERVERS)}},
            "tools": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
            "required_inputs": {
                "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]
            },
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "dAImon daemon.toml",
        "type": "object",
        "additionalProperties": False,
        "properties": {"daemon": daemon, "inputs": {"type": "object"}},
    }


def _emit(value) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value)


def bundle_daemon_env(cfg: Config, slug: str) -> str:
    d = cfg.daemon(slug)
    be_list = cfg.backends(slug)
    pairs = [
        ("DAIMON_D_COMMAND", d["command"]),
        ("DAIMON_D_DANGER", d["danger"]),
        ("DAIMON_D_STUCK_AFTER", d["stuck_after"]),
        ("DAIMON_D_WORKING_DIR", d["working_dir"]),
        ("DAIMON_D_CLEAN_WORKTREES", d.get("clean_worktrees", "")),
        ("DAIMON_D_BASE", d["inputs"].get("base", "main")),
        ("DAIMON_D_BACKENDS", be_list),
        ("DAIMON_D_MCP", d["mcp"]),
        # Pre-quoted shell words: rules like "Bash(git log:*)" contain spaces, and
        # the backend splices this into the command tmux runs via `sh -c`.
        # {{state_dir}} lets a rule scope writes to the daemon's own state.
        (
            "DAIMON_D_TOOLS",
            " ".join(
                shlex.quote(str(t).replace("{{state_dir}}", str(cfg.state_dir))) for t in d["tools"]
            ),
        ),
        ("DAIMON_READY_TIMEOUT", cfg.defaults["ready_timeout"]),
    ]
    pairs += [(f"DAIMON_D_MODEL_{be.upper()}", cfg.model_for(slug, be)) for be in be_list]
    return "".join(f"{k}={shlex.quote(_emit(v))}\n" for k, v in pairs)


def describe_packs(cfg: Config) -> str:
    if not cfg.packs:
        return "no packs configured ([packs].paths in daimon.toml)\n"
    lines = []
    locations = cfg.catalog_locations()
    for pack in cfg.packs:
        mine = sorted(s for s, dirs in locations.items() if dirs[0].parent == pack / "daemons")
        overrides = sorted(p.stem for p in (pack / "overrides").glob("*.toml"))
        profiles = sorted(p.stem for p in (pack / "profiles").glob("*.toml"))
        commands = sorted(p.stem for p in (pack / "commands").glob("*.md"))
        lines.append(f"{pack}{'' if pack.is_dir() else '  (missing)'}")
        for label, names in (
            ("daemons", mine),
            ("overrides", overrides),
            ("profiles", profiles),
            ("commands", commands),
        ):
            lines.append(f"  {label:<10} {', '.join(names) or '-'}")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="daimon-config")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("get")
    g.add_argument("key")
    d = sub.add_parser("daemon")
    d.add_argument("slug")
    d.add_argument("field")
    i = sub.add_parser("input")
    i.add_argument("slug")
    i.add_argument("key")
    sub.add_parser("daemons")
    b = sub.add_parser("backends")
    b.add_argument("slug")
    sub.add_parser("backends-all")
    m = sub.add_parser("model")
    m.add_argument("slug")
    m.add_argument("backend")
    s = sub.add_parser("schedule")
    s.add_argument("slug")
    e = sub.add_parser("env")
    e.add_argument("slug")
    de = sub.add_parser("daemon-env")
    de.add_argument("slug")
    mc = sub.add_parser("mcp-config")
    mc.add_argument("slug")
    rc = sub.add_parser("role-command")
    rc.add_argument("slug")
    sub.add_parser("status-command")
    vi = sub.add_parser("validate-inputs")
    vi.add_argument("slug")
    sub.add_parser("validate")
    sub.add_parser("schema")
    rp = sub.add_parser("render-plist")
    rp.add_argument("slug")
    rs = sub.add_parser("render-skill")
    rs.add_argument("slug")
    sub.add_parser("paths")
    dd = sub.add_parser("daemon-dir")
    dd.add_argument("slug")
    sub.add_parser("packs")
    args = p.parse_args(argv)
    cfg = Config.load()

    if args.cmd == "get":
        section, _, field = args.key.partition(".")
        table = {
            "core": cfg.core,
            "defaults": cfg.defaults,
            "throttle": cfg.throttle,
            "budget": cfg.budget,
            "roles": cfg.roles,
            "status": cfg.status,
            "update": cfg.update,
        }.get(section)
        if table is None or field not in table:
            print(f"unknown key: {args.key}", file=sys.stderr)
            return 2
        print(_emit(table[field]))
        return 0
    if args.cmd == "daemon":
        print(_emit(cfg.daemon(args.slug)[args.field]))
        return 0
    if args.cmd == "input":
        print(_emit(cfg.daemon(args.slug)["inputs"].get(args.key, "")))
        return 0
    if args.cmd == "daemons":
        print("\n".join(cfg.discover().keys()))
        return 0
    if args.cmd == "backends":
        print(" ".join(cfg.backends(args.slug)))
        return 0
    if args.cmd == "backends-all":
        print(" ".join(BACKENDS))
        return 0
    if args.cmd == "model":
        print(cfg.model_for(args.slug, args.backend))
        return 0
    if args.cmd == "schedule":
        print(schedule_fmt.descriptor(cfg.daemon(args.slug)["schedule"]))
        return 0
    if args.cmd == "env":
        # Output is eval'd by run.sh (set -a), so each value must be shell-quoted
        # or input values containing spaces (e.g. "In Progress") break the eval.
        for k, v in cfg.daemon(args.slug)["inputs"].items():
            print(f"DAIMON_INPUT_{k.upper()}={shlex.quote(_emit(v))}")
        return 0
    if args.cmd == "daemon-env":
        print(bundle_daemon_env(cfg, args.slug), end="")
        return 0
    if args.cmd == "mcp-config":
        print(json.dumps(cfg.mcp_config(args.slug), indent=2))
        return 0
    if args.cmd == "role-command":
        try:
            print(role_command(cfg, args.slug))
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 2
        return 0
    if args.cmd == "status-command":
        print(status_command(cfg))
        return 0
    if args.cmd == "validate-inputs":
        missing = _missing_required_inputs(cfg, args.slug)
        if missing:
            print(" ".join(missing))
            return 1
        return 0
    if args.cmd == "validate":
        errs = validate(cfg)
        if errs:
            print("config INVALID:", file=sys.stderr)
            for er in errs:
                print(f"  - {er}", file=sys.stderr)
            return 1
        print(f"config OK ({len(cfg.discover())} daemon(s))")
        return 0
    if args.cmd == "schema":
        print(json.dumps(daemon_schema(), indent=2))
        return 0
    if args.cmd == "render-plist":
        print(render_plist(cfg, args.slug), end="")
        return 0
    if args.cmd == "render-skill":
        print(render_skill(cfg, args.slug), end="")
        return 0
    if args.cmd == "daemon-dir":
        print(cfg.daemon_dir(args.slug))
        return 0
    if args.cmd == "packs":
        print(describe_packs(cfg), end="")
        return 0
    if args.cmd == "paths":
        print(f"DAIMON_INSTALL_ROOT='{cfg.install_root}'")
        print(f"DAIMON_STATE_DIR='{cfg.state_dir}'")
        print(f"DAIMON_NS='{cfg.core['namespace']}'")
        print(f"DAIMON_TIMEZONE='{cfg.core['timezone']}'")
        print(f"DAIMON_PERSONAL_DIR='{personal_dir()}'")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
