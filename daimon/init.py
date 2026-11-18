"""Choose which catalog daemons this machine has, and scaffold their personal
settings from *.example files. Run via `daimon init [slug ...]` or
`python -m daimon.init`.

With slugs, those daemons become `[daemons].installed` (and come off
`disabled`). With no slugs, a terminal gets a multi-select of the catalog
(dAImon's catalog/ plus each pack's daemons/), starting from what is installed
now; non-interactively it scaffolds the current set without changing it.
Installing registers nothing: schedule a daemon with `daimon tui` → r."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
import tomllib
from pathlib import Path

INSTALL_ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER_WORKING_DIRS = {"~/code", "~/code/your-repo"}


def _import_config():
    path = INSTALL_ROOT / "lib" / "config.py"
    spec = importlib.util.spec_from_file_location("daimon_config", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load config from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _shown(path: Path) -> str:
    """A path for messages: relative to the install root when inside it, else ~-abbreviated."""
    if path.is_relative_to(INSTALL_ROOT):
        return str(path.relative_to(INSTALL_ROOT))
    home = Path.home()
    return f"~/{path.relative_to(home)}" if path.is_relative_to(home) else str(path)


def _scaffold(example: Path, dest: Path) -> Path:
    """Copy a tracked *.example to this person's settings file `dest` unless it exists."""
    if dest.exists():
        print(f"  skip  {_shown(dest)} (exists)")
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(example, dest)
        print(f"  new   {_shown(dest)}")
    return dest


def set_working_dir_text(text: str, working_dir: str) -> str:
    """Rewrite `working_dir = ...` under `[daemon]`, preserving the rest of the file."""
    new_value = json.dumps(working_dir)
    out: list[str] = []
    in_daemon = False
    done = False
    for ln in text.splitlines():
        stripped = ln.strip()
        is_header = (
            stripped.startswith("[") and stripped.endswith("]") and not stripped.startswith("[[")
        )
        if is_header:
            if in_daemon and not done:
                out.append(f"working_dir = {new_value}")
                done = True
            in_daemon = stripped == "[daemon]"
            out.append(ln)
            continue
        if in_daemon and not done:
            m = re.match(r"(\s*)working_dir\s*=", ln)
            if m:
                comment = ""
                hash_at = ln.find("#")
                if hash_at >= 0:
                    comment = " " + ln[hash_at:].strip()
                out.append(f"{m.group(1)}working_dir = {new_value}{comment}")
                done = True
                continue
        out.append(ln)
    if in_daemon and not done:
        out.append(f"working_dir = {new_value}")
        done = True
    if not done:
        if out and out[-1].strip():
            out.append("")
        out += ["[daemon]", f"working_dir = {new_value}"]
    result = "\n".join(out)
    return result + "\n" if text.endswith("\n") else result


def _raw_daemon(path: Path) -> dict:
    try:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    daemon = raw.get("daemon", {})
    return daemon if isinstance(daemon, dict) else {}


def _raw_working_dir(path: Path) -> str:
    daemon = _raw_daemon(path)
    value = daemon.get("working_dir", "")
    return value if isinstance(value, str) else ""


def _git_root(path: Path) -> Path | None:
    cur = path.resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _cwd_working_dir_default() -> str:
    git_root = _git_root(Path.cwd())
    if git_root is None or git_root == INSTALL_ROOT.resolve():
        return ""
    return str(git_root)


def _normalize_working_dir(value: str) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return str(path.resolve())


def _is_install_root(value: str) -> bool:
    return bool(value) and Path(value).expanduser().resolve() == INSTALL_ROOT.resolve()


def _needs_working_dir(path: Path) -> bool:
    value = _raw_working_dir(path)
    return not value or value in PLACEHOLDER_WORKING_DIRS


def _set_working_dir(path: Path, working_dir: str) -> None:
    text = set_working_dir_text(path.read_text(), working_dir)
    path.write_text(text)


def _resolve_working_dir(auto_default: str, interactive: bool) -> str:
    cwd = str(Path.cwd().resolve())
    if not interactive:
        if auto_default:
            print(f"using working_dir for selected daemons: {auto_default} (from cwd)")
            return auto_default
        return ""
    print(f"current directory: {cwd}")
    if _is_install_root(cwd):
        print("current directory is the dAImon install root")
        print("use this only if you want daemons to operate on dAImon itself")
        resp = input(f"working_dir for selected daemons [{cwd}]: ").strip()
    else:
        resp = input(f"working_dir for selected daemons [{cwd}]: ").strip()
    working_dir = _normalize_working_dir(resp) if resp else cwd
    return working_dir


def _configure_working_dirs(local_paths: list[Path], default: str, interactive: bool) -> None:
    pending = [path for path in local_paths if _needs_working_dir(path)]
    if not pending:
        return
    working_dir = _resolve_working_dir(default, interactive)
    if not working_dir:
        for path in pending:
            print(f"  keep  {_shown(path)} working_dir placeholder")
        return
    for path in pending:
        _set_working_dir(path, working_dir)
        print(f"  set   {_shown(path)} working_dir = {working_dir}")


def _parse_choice(resp: str, offered: list[str], current: list[str]) -> list[str]:
    """A multi-select answer: numbers and/or slugs, `all`, `none`, or blank to
    keep `current`."""
    if resp == "":
        return current
    if resp == "all":
        return offered
    if resp == "none":
        return []
    chosen = []
    for tok in resp.replace(",", " ").split():
        if tok.isdigit() and 1 <= int(tok) <= len(offered):
            chosen.append(offered[int(tok) - 1])
        elif tok in offered:
            chosen.append(tok)
        else:
            raise ValueError(f"not in the catalog: {tok}")
    return list(dict.fromkeys(chosen))


def _prompt_selection(cfg, offered: list[str], current: list[str]) -> list[str]:
    print("catalog (● installed, ○ not):")
    for n, slug in enumerate(offered, 1):
        source = cfg.catalog()[slug]["source"]
        print(f"  {n:>2}. {'●' if slug in current else '○'} {slug}  ({source})")
    while True:
        resp = input("install which? numbers or names, 'all', 'none' [keep ●]: ").strip()
        try:
            return _parse_choice(resp, offered, current)
        except ValueError as e:
            print(f"  {e}")


def _resolve_selection(cfg, argv: list[str]) -> tuple[list[str], bool]:
    """Return (selected, explicit). `explicit` means `installed` should be rewritten."""
    offered = list(cfg.catalog())
    current = [s for s in cfg.installed() if s in offered]
    if argv:
        known = set(offered) | set(cfg.ejected_locations())
        unknown = [s for s in argv if s not in known]
        if unknown:
            sys.exit(f"not in any catalog: {', '.join(unknown)}\nknown: {', '.join(offered)}")
        return list(dict.fromkeys(argv)), True
    if sys.stdin.isatty():
        return _prompt_selection(cfg, offered, current), True
    # non-interactive, no args: keep what is installed
    return current, False


def _write_selection(cfg, migrate, selected: list[str]) -> None:
    offered = cfg.catalog()
    migrate.set_config_key(
        cfg.source, "daemons", "installed", [s for s in selected if s in offered]
    )
    print(f"installed: {', '.join(selected) or '(none)'}")
    if enabled := [s for s in cfg.disabled if s in selected]:
        migrate.set_config_key(
            cfg.source, "daemons", "disabled", [s for s in cfg.disabled if s not in enabled]
        )
        print(f"no longer disabled: {', '.join(enabled)}")


def _migrate_module():
    sys.path.insert(0, str(INSTALL_ROOT / "lib"))
    import migrate

    return migrate


def _migrate(migrate) -> None:
    """Bring the install up to date first (legacy in-repo settings to the personal
    dir, `installed` written once), so scaffolding sees (and never shadows) what
    this person already set."""
    for line in migrate.migrate():
        print(f"  migrate: {line}")


def main(argv: list[str]) -> int:
    cfg_mod = _import_config()
    migrate = _migrate_module()
    # ~/.config/daimon -> ~/.daimon before looking for daimon.toml, so a fresh one
    # is never created in front of the legacy one.
    for line in migrate.migrate_personal_dir():
        print(f"  migrate: {line}")
    config_path = cfg_mod.global_config_path()
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(INSTALL_ROOT / "config" / "daimon.toml.example", config_path)
        print(f"  new   {config_path}")
    _migrate(migrate)

    cfg = cfg_mod.Config.load()
    selected, explicit = _resolve_selection(cfg, argv)
    if explicit:
        _write_selection(cfg, migrate, selected)

    print("scaffolding personal settings for installed daemons:")
    cfg = cfg_mod.Config.load()  # reload so newly-installed daemons are discoverable
    sources: set[str] = set()
    default_working_dir = _cwd_working_dir_default()
    interactive = sys.stdin.isatty()
    local_paths: list[Path] = []
    for slug in selected:
        ex = cfg.daemon_dir(slug) / "daemon.local.toml.example"
        if ex.exists():
            local_paths.append(_scaffold(ex, cfg.daemon_local_path(slug)))
        sources.update(cfg.daemon(slug)["sources"])
    _configure_working_dirs(local_paths, default_working_dir, interactive)
    for src in sorted(sources):
        ex = cfg.profiles_dir() / src / "profile.local.toml.example"
        if ex.exists():
            _scaffold(ex, cfg.profile_local_path(src))

    personal = _shown(cfg_mod.personal_dir())
    print(f"\nnext: review {personal}/daemons/*.toml, then run 'daimon doctor'.")
    print("installing registers nothing: schedule a daemon with `daimon tui` → r.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
