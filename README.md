<p align="center">
  <img src="assets/logo.jpeg" alt="dAImon" width="240">
</p>

<h1 align="center">dAImon</h1>

<p align="center">
  <a href="https://github.com/toursbylocals/dAImon/actions/workflows/ci.yml"><img src="https://github.com/toursbylocals/dAImon/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
</p>

**dAImon runs a fleet of Claude Code agents on a schedule to automate your
software-development lifecycle** — triaging issues, implementing them, reviewing
pull requests, answering review feedback, and merging — each stage an autonomous
daemon pointed at a repo you own.

Under the hood, each daemon fires on a schedule, launches an interactive Claude CLI
inside a detached tmux session pointed at its target repository, drives it with a
slash-command, and blocks until the run finishes or goes idle — no wall-clock cap,
just an idle-gap reaper. A watchdog sweeps orphans and leaked MCP servers; a Textual
TUI is the control panel.

<p align="center">
  <img src="assets/tui.png" alt="dAImon control panel — daemon list with live status, config, processes, and log" width="900">
</p>

> **Upgrading from before the catalog (Nov 2026)?** Your next `daimon install` migrates you automatically; see [docs/migrating.md](docs/migrating.md) for what moved and the few cases that need you.

## Concepts

- **Daemon** — a self-contained folder `<slug>/` with `daemon.toml`
  (settings + task `[inputs]`), `discover.sh` (a gate: should this fire do work?),
  and `skill/SKILL.md` (the prompt).
- **Catalog** — the daemons you can install: dAImon's own `catalog/`, plus each
  [pack](docs/packs.md)'s `daemons/`. dAImon is the shell; you pick daemons from a
  catalog with `daimon add` ([docs/catalog.md](docs/catalog.md)). Installing
  schedules nothing: registering a daemon (a launchd job) is a separate step.
  Your own daemons live in `daemons/`, gitignored, and are always installed.
  An installed daemon is linked (it runs from its catalog, so updates reach it)
  until you `daimon eject` it into `daemons/` to edit; `daimon outdated` and
  `daimon diff` then show what changed upstream since.
- **Backend** — the agent CLI that drives the session. Claude and Codex ship
  today; provider-specific capacity classifiers allow an opt-in Codex fallback
  only when Claude is actually capped. Backends remain pluggable via
  `backends/<name>.sh`.
- **working_dir** — the repository a daemon operates in. The agent runs *inside*
  that trusted folder so it gets project context, MCP servers, and project skills.
  One daemon targets one repo; run many repos by registering one daemon per repo.
- **Completion/liveness** — Claude signals done via a Stop hook (a sentinel file);
  liveness via a heartbeat touched on every tool call. A backend without such a
  hook can fall back to idle detection backed by a pane-activity heartbeat.

## Prerequisites

- **macOS** for scheduled runs — daemons are scheduled with `launchd`. On Linux you
  can clone and `daimon run <slug>` manually, but `install --load` (launchd) and the
  TUI's scheduling controls won't work. (systemd support isn't there yet.)
- **Python 3.12+** — the core runtime is stdlib-only (no pip needed for it).
- **tmux** — each run drives the agent inside a detached tmux session.
- **Claude CLI** (`claude`) — the default backend. Set `DAIMON_CLAUDE_BIN` if it's off PATH.
- **gh** — for the GitHub daemons (`gh auth login`).
- **jq** — used by the GitHub discovery gates.

macOS: `brew install python@3.12 tmux gh jq` (plus the [Claude CLI](https://docs.claude.com/en/docs/claude-code/overview)).
`make doctor` verifies all of the above.

## Quick start

```bash
git clone <your-fork> ~/dev/dAImon
cd ~/dev/dAImon
make install                 # the shell: hooks, TUI venv, skills; puts `daimon` on PATH; installs no daemon
daimon catalog               # every daemon you can install, and where it comes from
daimon add review-prs        # install one: scaffolds ~/.daimon/daemons/review-prs.toml, syncs
$EDITOR ~/.daimon/daemons/review-prs.toml   # working_dir = the repo it operates on
daimon doctor                # verify tools, gh auth, hooks, config
daimon validate
daimon run review-prs        # one gated run, now — watch with `daimon tui`
daimon tui                   # select it and press r to register (schedule) it via launchd (macOS only)
```

`make install` symlinks `daimon`/`daimonctl` into `~/.local/bin` (ensure it's on your
PATH); `make help` lists targets.

### Shared vs machine-local config

Each daemon splits its config in two: **`daemon.toml`** (committed — shared defaults,
schedule, task inputs) and **`~/.daimon/daemons/<slug>.toml`** (outside the
repo — your `working_dir` and any per-machine overrides). Source-wide settings (e.g.
your Shortcut `owner`/`team`) live the same way in
`~/.daimon/profiles/<name>.toml`. Older installs kept these as gitignored
`*.local.toml` files in the repo; those are still read, and `daimon install` (every
update) moves them for you — or run `daimon migrate`
([details](docs/configuration.md#local-overrides-keep-your-config-out-of-git)). API
tokens are never stored in these files — use `gh auth login` and
`$SHORTCUT_API_TOKEN`.

`daimon add <slug>…` installs daemons one at a time; `daimon init` chooses the
whole set at once. Name the ones you want and they become `[daemons].installed`
in `daimon.toml`; the chosen ones get their settings in `~/.daimon/`
scaffolded from the tracked `*.local.toml.example` files. It prompts once for
`working_dir`, defaulting to the current directory; press Enter to use it for all
selected daemons with placeholder paths, or type a different repo or workspace
path. Neither registers anything: `r` in `daimon tui` does.

```bash
daimon init story-reviewer reply-to-story-comments   # install exactly these two
daimon init                                          # interactive multi-select from the catalog
daimon remove story-reviewer                         # unregister + uninstall (settings kept)
```

## Daemons

The reference daemons cover the development lifecycle end to end:

- **story-reviewer** — triage incoming stories; label the AI-completable ones.
- **work-queue** — implement a ready story on a branch and open a pull request.
- **review-prs** — risk-gated code review on open PRs.
- **reply-to-pr-comments** / **reply-to-story-comments** — answer feedback on the
  bot's comments and re-trigger review/triage when it's addressed.
- **pr-manager** — shepherd approved PRs to merge (resolve conflicts, fix CI,
  handle change requests).

They're reference implementations in dAImon's catalog — install the ones you want
(`daimon add <slug>…`) or copy one as a starting point. See the
[catalog index](catalog/README.md) for each daemon's schedule, inputs, and config
(every daemon has its own generated README).

## Adding a daemon

Three ways, all producing a `<slug>/` folder in your own `daemons/` (gitignored,
active at once) or, with `--pack`, a [pack](docs/packs.md)'s. Team-specific
daemons belong in a pack; `--catalog` (scaffold only) is for a generic daemon you
mean to contribute to dAImon:

1. **Interactive:** `daimon new [--pack]` opens `/daimon-builder` in Claude. It
   interviews you, scaffolds the folder and writes it.
2. **Skeleton:** `daimon scaffold <slug> [--pack [dir] | --catalog]` writes `daemon.toml`,
   `skill/SKILL.md` and a gate that skips until you write it, so nothing runs
   half-finished. Fill them in following [writing a daemon](docs/writing-a-daemon.md).
3. **By hand:** copy an existing daemon folder and edit it.

Then (`daimon add <slug>` for one in a pack or the catalog) `daimon validate`,
`daimon run <slug>` to try it once, and `daimon sync`.

## CLI

```
daimon run <slug>        gated run (throttle/inbox/discovery) then launch
daimon launch <slug>     launch now, bypass gates
daimon catalog           every daemon you can install: source, installed/ejected
daimon add <slug>…       install (+ personal settings, sync); registers nothing
daimon remove <slug>…    unregister (asks if loaded; --yes) + uninstall
daimon eject <slug>      copy into daemons/ to edit (--pack: into your pack)
daimon outdated          ejected copies whose upstream or copy changed
daimon diff <slug>       diff -ru upstream against your copy
daimon uneject <slug>    delete your copy; the daemon is linked again
daimon daemons           list active daemons (installed + your own, minus disabled)
daimon status            launchd + running-session state
daimon models <backend>  available models (live API or bundled fallback)
daimon mcp setup slack   create/connect Codex fallback to Slack via OAuth
daimon mcp share slack   print the setup command for teammates
daimon config <args>     config core (validate|get|daemon|schedule|...)
daimon sync              regenerate plists + render skills (reloads changed, idle jobs)
daimon kill <slug|all>   hard-kill a run
daimon ps <slug|all>     process tree
daimon watchdog          sweep orphans + leaked MCP + old logs
daimon check-scope [ref] fail if the branch reaches outside allowed_paths
                         (--pr <url> takes the scope from the PR's own record)
daimon tui               control panel
```

## Configuration

Global settings in `~/.daimon/daimon.toml`; per-daemon in
`<slug>/daemon.toml` in its catalog, and yours in `~/.daimon/daemons/<slug>.toml`. Full field reference: [docs/configuration.md](docs/configuration.md). Share a team setup from its own repo: [docs/packs.md](docs/packs.md).
Run-dangerous, model, schedule, backend, capacity fallback, and idle timeout are
all configurable globally and per daemon. Set `fallback_backend = "codex"` under
`[defaults]` to fall back fleet-wide only when Claude reports a provider cap.

## Troubleshooting

Run `daimon doctor` first; for common setup issues and fixes see
[docs/troubleshooting.md](docs/troubleshooting.md).

## Logging

Per daemon, under `state_dir/logs/`: a structured operational log (`<slug>.log`)
and per-run agent transcripts (`transcripts/<slug>-<backend>-<ts>.log`).
Transcripts are pruned after `log_retention_days`; operational logs rotate at
`log_max_mb`. Cleanup runs in the watchdog cycle.

## Testing

```bash
bash tests/run.sh
```

Covers config merge/validation/rendering, model discovery, the skills validator,
and bash syntax across all libs.

## Layout

`lib/` framework · `backends/` agent CLIs · `catalog/` dAImon's daemons ·
`daemons/` your own (gitignored) · `daimon/`
sync (plists + skills) · `tui/` control panel · `skills/` management commands ·
`config/` defaults + hooks · `docs/`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the dev setup and workflow,
[docs/writing-a-daemon.md](docs/writing-a-daemon.md) to build your own daemon,
and [docs/slack-commands.md](docs/slack-commands.md) to drive your environment
from Slack (`?pr-status 42`) and write your own command plugins.

## License

MIT — see [LICENSE](LICENSE).
