# Configuration reference

dAImon reads one global file — `~/.daimon/daimon.toml` (override with
`$DAIMON_CONFIG`) — plus one `daemon.toml` per daemon folder: in dAImon's
`catalog/`, a pack's `daemons/`, or your own `daemons/` ([catalog](catalog.md)).
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
| `ready_timeout` | int (sec) | `20` | How long to wait for the backend's ready banner before driving input. Unused by `claude`, which gets the command at start-up. |
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
| `exempt` | string[] | Daemons that must always be available. They never defer on the cap, and their launches never count toward it. |

### `[roles]`

| Key | Type | Meaning |
|-----|------|---------|
| `command` | string | How a daemon with a `role` asks whether to run on this machine. `{role}` and `{seconds}` are filled in (shell-quoted); exit 0 = run here, 1 = another machine runs it (its first line of output is logged), anything else = the check failed, so the daemon skips (fails closed). See [Run a daemon on one machine only](#run-a-daemon-on-one-machine-only). |

### `[status]`

| Key | Type | Meaning |
|-----|------|---------|
| `command` | string | Optional. Receives this machine's daemon status as one JSON document on stdin after every watchdog sweep and when an agent run starts and ends. `{seconds}` is filled in (shell-quoted) with how long the report should be trusted (900). Best-effort: a failure is logged to `logs/agent-status.log` and never affects a run. Empty (default) = no report. See [Report agent status](#report-agent-status). |

### `[update]`

| Key | Type | Meaning |
|-----|------|---------|
| `auto` | bool | Default false. When true, `daimon sync` loads `com.<ns>.update`, which runs `daimon update` at login and hourly. An update only fast-forwards this checkout to its upstream, only to a commit whose CI check runs all passed, and never touches a checkout with local changes or switch branches. It then runs `daimon install` and `daimon sync`, which also fast-forwards clean packs and reloads only daemons that are already registered. Log: `logs/update.log`. To opt one machine out, `touch ~/.daimon/no-auto-update`. To update now, `daimon update`. |

### `[packs]`

| Key | Type | Meaning |
|-----|------|---------|
| `paths` | string[] | Folders (`~` expanded) that add daemons, team overrides, profile defaults and slack-commands runbooks, so a team can commit its setup in its own repo. See [packs](packs.md). |

### `[daemons]`

| Key | Type | Meaning |
|-----|------|---------|
| `installed` | string[] | The daemons this machine has, from `daimon catalog`. `daimon add` / `daimon remove` / `daimon init` edit it; installing registers nothing. Your own daemons in `daemons/` are active without an entry. Absent (an install from before the catalog): every catalog daemon counts as installed, and `daimon migrate` writes that set once. See [catalog](catalog.md). |
| `disabled` | string[] | Installed (or your own) daemons to skip, without uninstalling or deleting them. |

## Per-daemon file: `<slug>/daemon.toml`

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
| `source` | string | Name of a [source profile](#source-profiles) (folder under `profiles/`) describing the work-item backend, e.g. `shortcut`. Optional; omit for daemons that only act on the repo (PR daemons). |
| `role` | string | Run this daemon on one machine at a time across a team: on each run it asks `[roles].command` and skips unless this machine holds the role. Lowercase letters, digits and `-`. Usually set in `daemon.local.toml`. |
| `role_hold` | int (sec) | How long one run's claim on the role lasts. Defaults to twice the interval plus a minute; required for `minutes`/`daily` schedules. |
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
placeholder values. Your real values live outside the repo, in `~/.daimon/`
beside the global config (the folder holding `$DAIMON_CONFIG`, when that is set),
so you can configure freely, update dAImon, and still push the repo:

| Committed (template) | Your settings (outside the repo) |
|----------------------|----------------------------------|
| `daemons/<slug>/daemon.toml` | `~/.daimon/daemons/<slug>.toml` (`[daemon]`, `[inputs]`) |
| `profiles/<name>/profile.toml` | `~/.daimon/profiles/<name>.toml` (`[defaults]`) |
| `config/daimon.toml.example` | `~/.daimon/daimon.toml` |

Merge precedence (last wins): global `[defaults]` → profile `[defaults]` →
a pack's `profiles/<name>.toml` → legacy `profile.local.toml` →
`~/.daimon/profiles/<name>.toml` → `daemon.toml` → a pack's
`overrides/<slug>.toml` → legacy `daemon.local.toml` →
`~/.daimon/daemons/<slug>.toml` ([packs](packs.md)). The TUI config screen
(`c`) writes to `~/.daimon/daemons/<slug>.toml`, so editing a daemon never
touches the repo. Set workspace-wide values (e.g. your Shortcut workspace/labels)
once in `~/.daimon/profiles/<name>.toml`.

**Legacy files.** Older installs kept these settings in gitignored
`daemons/<slug>/daemon.local.toml` and `profiles/<name>/profile.local.toml` files
inside the repo (or a pack). When dAImon's daemons moved to `catalog/`, those
files stayed in `daemons/<slug>/`. They are still read, under the new files, and
`daimon migrate` moves them: the text is copied verbatim (comments kept), or merged
key by key when the new file already exists (its values win; overridden legacy
values are kept as comments), and the old file is reduced to a one-line
`# moved to … by daimon migrate` comment. A `daemons/<slug>/` folder left with
nothing but such stubs (and caches) is then removed. It is idempotent, and `daimon install`
(so every self-update) and `daimon init` run it for you. The tracked
`*.local.toml.example` files stay where they are: `daimon init` copies them into
`~/.daimon/`.

**`~/.config/daimon`.** Until this release the personal dir was
`~/.config/daimon`. `daimon migrate` (so `daimon install`, every self-update, and
`daimon init`) moves it to `~/.daimon`: every file is copied verbatim with its
mode, `daimon.toml` last, then removed from the old folder, which keeps only a
one-line `MOVED` pointer. Paths in the moved `.toml` files that point into
`~/.config/daimon` are re-pointed. Until the move, dAImon keeps reading
`~/.config/daimon/daimon.toml` whenever `~/.daimon/daimon.toml` does not exist, so
a scheduled job that fires between an update's `git merge` and its install runs as
before. Anything already in `~/.daimon` that isn't part of this layout (state
files from an older dAImon) is moved aside to `~/.daimon/legacy-<YYYYMMDD>/`, not
deleted; a dAImon checkout at `~/.daimon/app` (where a team pack's setup may clone
it) stays where it is. If both folders hold a `daimon.toml`, `~/.daimon` wins and the old folder
is left alone, with a warning. With `$DAIMON_CONFIG` set nothing moves.

## Run a daemon on one machine only

Some daemons should run once per team, not once per teammate: a Datadog error
reviewer run on three laptops files every story three times. Give such a daemon
a `role`, and point `[roles].command` at whatever coordinates your machines:

```toml
# ~/.daimon/daimon.toml
[roles]
command = "my-coordinator hold {role} --for {seconds}"

# ~/.daimon/daemons/datadog-log-reviewer.toml
[daemon]
role = "datadog-errors"
```

Each run asks the command right after the throttle, inbox and budget checks.
The command answers for this machine: exit 0 runs the daemon, exit 1 skips it
because another machine holds the role. A machine that stops asking (the daemon
is disabled, throttled or over budget) should lose the role once `{seconds}`
pass, so the coordinator can hand it to another machine. An explicitly queued
inbox command always runs, role or not.

dAImon ships no coordinator. Anything that hands out leases works: a lock in a
shared key-value store, or an internal service your team already runs.

## Report agent status

dAImon has no long-running process, so nothing outside it can ask which daemons
are up. Set `[status].command` and dAImon tells it instead:

```toml
# ~/.daimon/daimon.toml
[status]
command = "my-coordinator status --ttl {seconds}"
```

The command runs with `bash -c` at the end of every watchdog sweep (every 5
minutes) and when an agent run starts and ends, and gets one JSON document on
stdin:

```json
{"agents":[
  {"name":"review-prs","state":"working"},
  {"name":"datadog-log-reviewer","state":"idle","role":"datadog-errors"},
  {"name":"story-reviewer","state":"blocked","note":"throttled"}
]}
```

- One entry per enabled daemon that is loaded in launchd; unloaded daemons are
  left out. At most 32 entries.
- `state`: `working` while the daemon has an agent session, `blocked` (note
  `throttled`) when the throttle is at `halt` and the daemon is not exempt,
  otherwise `idle`.
- `role` appears only for a daemon with a `role`; `note` only when there is one
  (at most 40 characters).
- `{seconds}` (900) is how long a report should be trusted: a receiver that
  hears nothing for that long should treat the machine as gone.

A report is best-effort: a failing command is logged (with its exit code) to
`logs/agent-status.log`, one that hangs is abandoned after 30 seconds, and
neither ever blocks or fails a run. dAImon ships no receiver.

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
