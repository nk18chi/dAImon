# Architecture

## Layers

- **Config core** (`lib/config.py`) — the only TOML parser. Discovers daemons,
  merges `[defaults]` ← per-daemon `[daemon]`, resolves per-backend models,
  renders plists and skills, validates. Bash, the TUI, and the installer all call
  it; the emitter for write-back lives in `lib/toml_emit.py`.
- **Runtime** (`lib/`) — `run.sh` (the launchd entrypoint) gates on throttle,
  inbox, and the daemon's `discover.sh`, then hands to `launch.sh`. `launch.sh`
  dispatches to one or more backends; `reap.sh` tears sessions down. `watchdog.sh`
  is the periodic safety net.
- **Backends** (`backends/`) — each teaches the launcher how to drive one agent
  CLI (binary, args, ready banner, completion mode). See `backends/README.md`.
- **Sync** (`daimon/sync.py`) — `daimon sync` regenerates launchd plists and
  renders each daemon's skill from the daemon folders the runtime reads.
- **TUI** (`tui/`) — Textual control panel; reads the config core, drives launchd
  and tmux.

## Run lifecycle

1. launchd fires `lib/run.sh <slug>` on the daemon's schedule.
2. Gates: throttle → inbox → `discover.sh` (exit 0 to proceed).
3. `launch.sh` opens a detached tmux session in the daemon's `working_dir`,
   running the primary backend CLI with the configured model and danger flag.
4. It waits for the ready banner, types the daemon's `command`, then blocks.
5. Completion: a sentinel file (Claude's Stop hook), or heartbeat-idle for a
   backend with no such hook. No wall-clock cap — only `stuck_after` seconds of silence.
6. The pane scrollback is saved as a transcript. If the backend-specific capacity
   classifier recognizes a provider usage/spend limit, the configured fallback
   backend runs the same skill. Other failures stop the chain.
7. The session is reaped, taking
   its whole descendant tree (so MCP servers don't leak).

## Completion & liveness

`launch.sh` exports `DAIMON_SENTINEL`, `DAIMON_HEARTBEAT`, `DAIMON_WAIT` into the
session. Claude's hooks (installed into `~/.claude/settings.json`, gated on those
vars) touch the sentinel on Stop and the heartbeat on every tool call. A backend
with no equivalent hook can declare `idle` completion instead, and `launch.sh` runs
a pane-activity heartbeat (touch on pane change) as a CLI-agnostic backstop.

## State

Everything runtime lives under `state_dir`: `logs/<slug>.log` (structured
operational log), `logs/transcripts/` (per-run agent output, pruned after
`log_retention_days`), `runtime/` (throttle, budget, inbox, fire counters),
`queues/`. Nothing is written inside the repo.
