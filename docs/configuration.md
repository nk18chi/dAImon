# Configuration reference

dAImon reads one global file — `~/.config/daimon/daimon.toml` (override with
`$DAIMON_CONFIG`) — plus one `daemon.toml` per daemon folder under `daemons/`.
Run `daimon config validate` after editing. Plists are generated from these by
`daimon sync`; never hand-edit the generated plists.

## Global file: `daimon.toml`

### `[core]`

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `install_root` | path | repo containing `lib/` | Where the dAImon code lives. |
| `state_dir` | path | `~/.local/state/daimon` | Logs, transcripts, queues, runtime files. Not committed. |
| `namespace` | string | `daimon` | Prefix for tmux sessions (`<ns>-<slug>`), launchd labels (`com.<ns>.<slug>`), and `/tmp/<ns>-*` files. |
| `timezone` | string | `UTC` | For human schedule/next-run display only; launchd uses local time. |
| `log_retention_days` | int | `14` | Transcripts older than this are deleted by the watchdog cycle. |
| `log_max_mb` | int | `10` | Operational logs rotate once they exceed this size. |
| `log_keep` | int | `3` | Rotated log generations to keep. |

### `[defaults]`

Inherited by every daemon; a daemon's `[daemon]` block overrides any field.

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `backend` | enum | `claude` | Agent CLI that drives the session: `claude` (interactive) or `codex` (one-shot `codex exec`). Add more via `backends/<name>.sh`. |
| `fallback_backend` | enum | disabled | A second backend to try only when the primary backend's transcript reports that its provider capacity is exhausted. Set to `codex` to keep Claude daemons running after Claude hits a usage/spend limit. |
| `model` | string | `opus` | Passed to the backend as its model flag. |
| `danger` | bool | `true` | Allow the backend to skip its permission/approval prompts (run-dangerous). |
| `stuck_after` | int (sec) | `2700` | Idle-gap reaper. A run is killed only after this many seconds with **no agent activity** (heartbeat stale). This is **not** a max runtime — healthy runs may last hours. |
| `ready_timeout` | int (sec) | `20` | How long to wait for the backend's ready banner before driving input. |
| `mcp` | string[] | `[]` | MCP servers to attach to daemon sessions (opt-in). Known: `codex`. Requires `danger = true`. Set here for fleet-wide, or per-daemon under `[daemon]`. |

### `[throttle]`

| Key | Type | Meaning |
|-----|------|---------|
| `exempt` | string[] | Daemons never throttled. |
| `moderate_mod` | int | Under `moderate`, a daemon runs on every Nth fire. |
| `severe_mod` | int | Under `severe`, every Nth fire — except `severe_critical`. |
| `severe_critical` | string[] | Daemons kept at `moderate_mod` even under `severe`. |

### `[budget]`

| Key | Type | Meaning |
|-----|------|---------|
| `hourly_cap` | int | Target launches per hour across all daemons. |
| `defer_at_pct` | int | Work-style daemons defer new launches at/above this percent of the cap. |

### `[daemons]`

| Key | Type | Meaning |
|-----|------|---------|
| `disabled` | string[] | Slugs of discovered daemons to skip (without deleting their folder). |

## Per-daemon file: `daemons/<slug>/daemon.toml`

### `[daemon]` — framework settings (override `[defaults]`)

| Key | Type | Meaning |
|-----|------|---------|
| `backend` | enum | Override the default backend (`claude` or `codex`) for this daemon. On `codex`, set a Codex model via the `model` table (e.g. `{ codex = "gpt-5.3-codex" }`) — a plain `opus`/`sonnet`/`haiku` falls back to Codex's own default. |
| `fallback_backend` | enum | Override or disable (`""`) the fallback backend. It runs only after the primary reports provider-cap exhaustion; boot, authentication, permission, and task failures do not trigger it. For distinct models, use a table such as `{ claude = "opus", codex = "gpt-5.3-codex" }`. |
| `model` | string | Override the default model. |
| `danger` | bool | Override run-dangerous for this daemon. |
| `stuck_after` | int (sec) | Override the idle-gap reaper. |
| `command` | string | The slash-command typed into the agent session (e.g. `/review-prs`). |
| `working_dir` | path | Directory the agent launches in (a trusted folder). May be a single repo, or a **parent directory containing several repos** — the agent `cd`s into the one a work item concerns, picking up that repo's `CLAUDE.md`/conventions/`gh` context on the way in. This is per-machine, so the committed `daemon.toml` omits it and **you set it in `daemon.local.toml`** (or the TUI); if unset it falls back to `install_root` and `daimon doctor` warns. Optionally scope which repos with an `[inputs].repos` allowlist (e.g. `["api"]`); empty = all repos under the directory. There is no separate `repo` setting — `gh` infers it from the repo the agent enters. |
| `mcp` | string[] | MCP servers for this daemon's session (overrides `[defaults].mcp`). Known: `codex` — also attaches the `references/codex-review.md` second-opinion protocol to the skill. Requires `danger = true`. |
| `tools` | string[] | Tool allowlist in Claude permission-rule syntax (e.g. `["Read", "Bash(git log:*)", "mcp__server__tool"]`). When set it **overrides `danger`**: the session runs `--permission-mode dontAsk` (anything unlisted is denied, never prompted) with `--setting-sources user`, so the target repo's own allow rules can't widen it. Name MCP tools one by one — a bare `mcp__server` rule would admit its write tools too. Claude-only: validation rejects `codex` as backend or fallback. Use it for daemons triggered by untrusted input (e.g. `slack-ask`). |
| `source` | string | Name of a [source profile](#source-profiles) (folder under `profiles/`) describing the work-item backend, e.g. `shortcut`. Optional; omit for daemons that only act on the repo (PR daemons). |
| `schedule` | table | One of: `{ interval = 1200 }` (seconds), `{ minutes = [8, 38] }` (minutes past each hour), or `{ daily = "13:02", tz = "UTC" }`. |

### `[inputs]` — task variables

Free-form key/value pairs specific to the daemon's job. They are interpolated
into `skill/SKILL.md` as `{{inputs.<key>}}` at `daimon sync` time and exported to
`discover.sh` as `DAIMON_INPUT_<KEY>`. Example for a PR-review daemon:

```toml
[inputs]
source = "github-prs"
access = "gh"
repo   = "OWNER/REPO"
filter = "review-requested:@me"
```

Reference `{{inputs.filter}}`, `{{inputs.ready_state}}`, etc. in the daemon's
`skill/SKILL.md` template; `daimon new` scaffolds both the config and a starter
template, and can rewrite the prompt prose for sources that don't fit the
default template.

## Local overrides (keep your config out of git)

The committed `daemon.toml` and `profile.toml` files are shareable templates with
placeholder values. Your real values go in gitignored `*.local.toml` siblings, so
you can configure freely and still push the repo:

| Committed (template) | Local override (gitignored) |
|----------------------|------------------------------|
| `daemons/<slug>/daemon.toml` | `daemons/<slug>/daemon.local.toml` |
| `profiles/<name>/profile.toml` | `profiles/<name>/profile.local.toml` |
| `config/daimon.toml.example` | `~/.config/daimon/daimon.toml` (outside the repo) |

Merge precedence (last wins): global `[defaults]` → profile `[defaults]` →
`profile.local.toml` → `daemon.toml` → `daemon.local.toml`. The TUI config screen
(`c`) writes to `daemon.local.toml`, so editing a daemon never touches a committed
file. Set workspace-wide values (e.g. your Shortcut workspace/labels) once in
`profiles/<name>/profile.local.toml`.

## Source profiles

A **source profile** describes a work-item backend (a task/story tracker) once,
so daemons don't each re-encode it. A daemon opts in with `[daemon].source =
"<name>"` (or `[daemon].sources = ["a", "b"]` for more than one), resolving to
`profiles/<name>/`:

| File | Purpose |
|------|---------|
| `profile.toml` | `[profile]` metadata + a `[defaults]` table of inputs (e.g. workspace, team, workflow-state names) merged **under** the daemon's `[inputs]` (the daemon overrides). |
| `reference.md` | CLI/API guidance (auth, how to list/claim/comment/transition items) appended to the rendered `SKILL.md`, with `{{inputs.*}}` substituted. |
| `lib.sh` *(optional)* | shared bash helpers a daemon's `discover.sh` can source (e.g. token resolution + search). |

`profiles/shortcut/` ships as the reference implementation (Shortcut stories via
the REST API). Its `[defaults]` are the **set-once-per-workspace** place for your
label names, the pipeline state to pull from (`triage_state`), `in_progress_state`,
`workspace`, `team`, etc. — edit them there and every Shortcut daemon inherits.
A daemon's own `[inputs]` override the profile `[defaults]` for that one daemon,
and the TUI config screen (`c`) edits the same values per daemon. Add a backend by
dropping in a new `profiles/<name>/` folder — no framework changes.

### Multiple sources

`sources = ["a", "b"]` composes more than one profile: each `[defaults]` table is
merged in list order (later wins on a key clash), the daemon's own `[inputs]`
override all of them, and every profile's `reference.md` is appended to the skill.
`source = "x"` is shorthand for `sources = ["x"]`; if both are set, `sources` wins.

This lets one daemon span backends — e.g. `review-prs` reviews GitHub PRs
(native) but also carries the `shortcut` source so a PR that references a story is
reviewed against that story's acceptance criteria.

### Read-only vs read-write

A source entry can be a plain string (read-only) or a table with `write = true`:

```toml
sources = ["shortcut"]                          # read-only
sources = [{ name = "shortcut", write = true }] # may mutate the source
```

A profile splits its guidance in two: `reference.md` is the read core (access,
read one item, linking) and is always appended; `reference.write.md` documents the
mutating operations (search/scope, comment, label, transition) and is appended
**only** to daemons that declare `write = true`. So `review-prs` (read-only) never
receives the comment/label/transition instructions, while the triage daemons
(`story-reviewer`, `work-queue`) do.
