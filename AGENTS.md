# AGENTS.md

Guidance for AI agents and contributors working **on** dAImon itself. For what
dAImon *is* and how to operate it, see [README.md](README.md).

## Orientation

- [docs/architecture.md](docs/architecture.md) — how the pieces fit.
- [docs/writing-a-daemon.md](docs/writing-a-daemon.md) — add or change a daemon.
- [docs/catalog.md](docs/catalog.md) — catalogs, installed daemons, your own `daemons/`.
- [docs/writing-a-source.md](docs/writing-a-source.md) — add a source profile (GitHub, Shortcut, Datadog, …).
- [docs/configuration.md](docs/configuration.md) — every config field.
- [docs/troubleshooting.md](docs/troubleshooting.md) — common failures and fixes.
- `lib/` framework · `backends/` agent CLIs · `catalog/` dAImon's daemons ·
  `daemons/` each person's own (gitignored) · `daimon/` sync + CLI · `tui/`
  control panel · `skills/` management commands · `config/` defaults.

## Workflow

```bash
make test        # bash syntax + shellcheck + python unit tests + gate tests
make lint        # ruff + shellcheck
make typecheck   # pyright
make fmt         # ruff format + autofix
```

`uv run pre-commit install` wires lint + typecheck into every commit. CI runs the
same checks. Use feature branches and PRs; never commit to `main` directly.

## Invariants — do not break these

- **`lib/config.py` is the single source of truth for config.** Bash, the TUI,
  and the installer all shell out to it. Never parse `daemon.toml` elsewhere.
- **The runtime core stays stdlib-only.** Nothing under `lib/`, `catalog/`, or
  `daimon/` may import a third-party package — daemons and gates run with no
  venv. Only `tui/` may depend on `textual`. New deps go in pyproject's `dev`
  group, never in `[project.dependencies]`.
- **Every daemon must set `working_dir`** (in `~/.daimon/daemons/<slug>.toml`)
  to the target repo. Left unset, `config.py` defaults it to the dAImon install
  root, so the agent would run against this repo instead of its target.
- **Personal settings live in `~/.daimon/`, never the repo:**
  `daemons/<slug>.toml` (machine-specific `working_dir` + `[inputs]`) and
  `profiles/<name>.toml`, beside the global config. Committed `daemon.toml` holds
  shared defaults only. Legacy in-repo `*.local.toml` files (still gitignored) are
  read under the new files and moved by `lib/migrate.py`, which install and init
  run; `config.py` writes only the new files.
- **Team-specific daemons go in a pack, never in `catalog/`.** `catalog/` holds
  generic daemons anyone can install; a daemon that names a team's systems,
  channels, IDs or workflow belongs in that team's [pack](docs/packs.md).
- **Installing is not registering.** `[daemons].installed` decides what is
  active (synced, validated, listed); only a launchd plist schedules a daemon.
  `daimon add` and `daimon init` never create one. With no `installed` key,
  `config.py` falls back to every catalog daemon minus `disabled` (installs from
  before the catalog, until `lib/migrate.py` writes the key).
- **Catalog gates find dAImon through `$DAIMON_INSTALL_ROOT`** (the scaffold's
  fallback line), never `$(dirname "$0")/../..`: the same folder must run from
  `catalog/`, an ejected copy in `daemons/`, or a pack.

## Documentation

- **Each catalog daemon has a generated `README.md`** (and there's a generated
  `catalog/README.md` index). They're built from committed metadata only —
  `daemon.toml` + `skill/SKILL.md` — never machine-local files. Do not hand-edit
  them; run `make docs` to regenerate. A pre-commit hook regenerates them when a
  `daemon.toml` or `SKILL.md` changes, and `tests/test_docs.py` fails CI if any is
  stale. Change the daemon's metadata (or `daimon/gen_docs.py`), not the README.

## House style

- Shell: hand-aligned definitions and the compact `cmd; return 0` dispatch style
  are intentional. shellcheck is enforced; shfmt is deliberately not.
- This repo's `.claude/settings.json` is committed and grants permissions only —
  it never defines hooks. The runtime sentinel/heartbeat hooks are installed at
  the user level by `bin/daimon-install`; keep them out of repo config.
