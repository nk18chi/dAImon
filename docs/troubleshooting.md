# Troubleshooting

Run `daimon doctor` first — it checks most of the below and points at the fix.

## `command not found: daimon`

`make install` symlinks `daimon` into `~/.local/bin`. Ensure that's on your `PATH`
(e.g. `export PATH="$HOME/.local/bin:$PATH"` in your shell profile).

## A daemon runs against the wrong repo (or dAImon itself)

`working_dir` isn't set or points at the wrong place. Each daemon needs it in
`~/.daimon/daemons/<slug>.toml`; unset, it defaults to the dAImon install root.
Run `daimon init <slug>` from the target repo and accept the prompt, or type the
target path when prompted. `daimon doctor` flags daemons whose `working_dir` is
unset or missing. If you intentionally want daemons to operate on dAImon itself,
accept the install-root prompt so `init` writes that directory explicitly.

## The agent never finishes / hangs

Completion is signaled by Claude's Stop hook touching a sentinel file. If the hooks
aren't installed, the run can only end via the `stuck_after` idle reaper. Re-run
`bin/daimon-install` (or `make install`) and confirm with `daimon doctor` that
"completion/heartbeat hooks installed" is green.

## `gh` / GitHub daemons do nothing

Authenticate: `gh auth login`, then `gh auth status`. The discovery gates use `gh`
and `jq` — make sure both are installed (`make doctor`).

## Shortcut daemons can't find stories

Set your API token (`export SHORTCUT_API_TOKEN=…` or `~/.config/shortcut-cli/config.json`)
and your `owner`/`team` in `~/.daimon/profiles/shortcut.toml`. Daemons are
scoped to the owner; a blank owner means all stories are in scope.

## Scheduling doesn't fire

launchd scheduling is macOS-only. Run `make install-load` to load the jobs, then
`daimon status` to see loaded/running state. On Linux, run daemons manually with
`daimon run <slug>` — launchd scheduling isn't available.

## CI fails on `pr-title`

PR titles must be [Conventional Commits](https://www.conventionalcommits.org/)
(`type(scope): summary`). Merges are squash-only and the squash commit uses the PR
title.

## CI fails on stale docs

Per-daemon READMEs are generated. Run `make docs` after changing a `daemon.toml` or
`SKILL.md`, and commit the result.
