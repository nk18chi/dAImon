# Agent backends

A backend teaches dAImon how to drive one agent CLI inside a tmux session. Each
backend is a bash file (`backends/<name>.sh`) sourced by `lib/launch.sh`, selected
per daemon with `[daemon].backend`. Two ship today — `claude` (interactive) and
`codex` (one-shot `codex exec`) — add another by dropping in `backends/<name>.sh`
that implements the contract below.

## Contract

A backend must define these functions:

| Function | Args | Returns / effect |
|----------|------|------------------|
| `backend_bin` | — | Absolute path to the CLI (honor `DAIMON_<NAME>_BIN` override). |
| `backend_cli_args` | `model danger session_name` | The argument string placed after the binary. `danger` is `1`/`0`; map it to the CLI's run-dangerous flag (empty when `0`). |
| `backend_ready_regex` | `danger` | A regex `lib/launch.sh` greps the pane for to know the UI is ready. Echo empty to skip banner detection and use a fixed boot delay instead. |
| `backend_completion_mode` | — | `hook` (a Stop-hook touches the sentinel; precise), `idle` (no hook; completion inferred from heartbeat staleness), or `oneshot` (see below). |
| `backend_exhausted_regex` | — | Case-insensitive transcript regex that matches only provider-capacity exhaustion. This is the sole condition that permits `fallback_backend`; keep it narrower than ordinary errors or advisory limit text. |

Optionally, `backend_supports_resume` (returns 0) declares that the CLI can
continue an earlier session by id; see below.

Optionally, `backend_initial_prompt` (returns 0) declares that the CLI takes its
first prompt as a trailing command-line argument. The launcher then appends the
daemon's `command` (one shell-quoted word) to the launch line instead of waiting
for `backend_ready_regex` and typing it, so a change to the CLI's idle-prompt text
(which can also vary with the user's own settings) can't stop the command being
sent. Boot is then checked only by the session still being alive after a short
grace. `claude` declares it.

Optionally, `backend_launch_check <working_dir>` returns non-zero, with the
reason on stdout, when the CLI would stop at a start-up dialog in that folder.
The launcher then logs `boot_fail` with the reason and doesn't start the
session, so the run fails at once instead of waiting behind the dialog until the
`stuck_after` reaper. `claude` uses it for its folder-trust prompt
(`lib/claude_trust.py`: the folder's own record, else its git repository root's).

## Resuming a session

A gate can ask to continue an earlier agent session instead of starting fresh, so
the agent keeps the context it built (see `$DAIMON_GATE_RESUME` in
docs/writing-a-daemon.md). When the backend declares `backend_supports_resume`,
the launcher sets `DAIMON_AGENT_SESSION` to that session's id and
`DAIMON_RESUME=1`, and `backend_cli_args` emits the CLI's resume flag in place of
its new-session flag. The command typed into the session is the one the gate
asked for. A backend without resume support starts a fresh session and runs that
command.

## Capacity fallback

Set `fallback_backend = "codex"` under global `[defaults]` or a daemon's
`[daemon]` table to opt in. The primary run is captured first. The fallback runs
the same rendered skill only when `backend_exhausted_regex` matches; successful
completion and ordinary boot, authentication, permission, or task failures never
start it. A successful fallback also suppresses the legacy fleet-wide quota halt,
so later fires can follow the same primary-then-fallback path.

## One-shot backends

A `oneshot` backend is non-interactive: it takes its whole task on stdin and
exits when done, instead of accepting a typed command in a live UI. For these the
launcher renders the daemon's skill to a prompt file and pipes it into the process
(`<env> exec <bin> <cli_args> < prompt`), skips the ready-banner wait and the
command-typing, and treats **process exit** as completion (heartbeat staleness is
only the hang safety-net). `codex` is one — it runs `codex exec`. A oneshot
backend's `backend_ready_regex` is unused, and its `backend_cli_args` may read
`DAIMON_D_WORKING_DIR` (e.g. `codex` trusts it inline to avoid a boot prompt).

## MCP config

When a daemon opts into MCP servers (`[daemon].mcp`), the launcher writes a
`.mcp.json`-style file and exports `DAIMON_MCP_CONFIG` with its path before
calling `backend_cli_args`. A backend that supports MCP should read that env var
and pass the file to its CLI's MCP flag (empty/unset means no MCP). The `claude`
backend maps it to `--mcp-config <file> --strict-mcp-config`.

## How the launcher uses them

`lib/launch.sh` exports `DAIMON_SENTINEL`, `DAIMON_HEARTBEAT`, and `DAIMON_WAIT`,
opens `tmux new-session` running `<env> exec <backend_bin> <backend_cli_args>`
(plus the daemon's `command` for a `backend_initial_prompt` backend; otherwise it
waits for `backend_ready_regex`, or the boot delay, and types the `command`),
then blocks until: the sentinel appears (`hook` mode), the session
dies, or the heartbeat goes stale for `stuck_after` seconds. Teardown and the
MCP-orphan sweep in `lib/reap.sh` are backend-independent.

## Hooks

`hook`-mode backends need their hooks installed once (the installer merges
`config/hooks/<name>-hooks.*`). The hooks are gated on the `DAIMON_*` env vars so
they are inert in your own non-daemon sessions.
