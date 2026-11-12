# Writing a daemon

A daemon is a folder under `daemons/<slug>/` with three files. The framework
auto-discovers it; `daimon sync` regenerates its plist and renders its skill.

## 1. `daemon.toml`

```toml
[daemon]
backend = "claude"
# fallback_backend = "codex"      # only when Claude's provider cap is exhausted
working_dir = "~/code/my-repo"     # the repo the agent runs inside
schedule = { interval = 1800 }     # or { minutes = [8,38] } / { daily = "13:02" }
command = "/my-daemon"             # slash-command typed into the session
required_inputs = ["repo", "filter"]  # asserted non-empty before discover runs
# model / danger / stuck_after override [defaults] when set

[inputs]                           # task variables, your own keys
source = "github-issues"
access = "gh"
repo = "me/my-repo"
filter = "label:needs-triage"
```

## 2. `discover.sh`

The gate. Inputs arrive as `DAIMON_INPUT_*`. Keep it cheap. Exit codes are read as:

- `0` — work found; launch the agent this fire.
- `1` with no stderr — nothing to do; skip until the next run.
- any stderr output, or exit `≥2` — the gate itself errored. `run.sh` logs this as
  `discover_error` rather than silently treating it as "no work", so a broken gate
  surfaces instead of disabling the daemon invisibly. List the inputs the gate
  depends on in `required_inputs` so a missing one is caught before this runs.

```bash
#!/usr/bin/env bash
set -uo pipefail
source "$(dirname "$0")/../../profiles/github/lib.sh"
[ "$(gh_pr_count --search "$DAIMON_INPUT_FILTER")" -gt 0 ]
```

`profiles/github/lib.sh` provides fail-closed gate helpers (`gh_pr_json`,
`gh_pr_count`, `gh_search_pr_count`, `load_seen_state`); `profiles/shortcut/lib.sh`
is the equivalent for story gates. To wire up a new external system, see
[writing-a-source.md](writing-a-source.md).

## 3. `skill/SKILL.md`

The prompt, in Claude Code skill format. Reference inputs as `{{inputs.<key>}}`;
`daimon sync` renders them and installs the result to `~/.claude/skills/<command>`.

```markdown
---
name: my-daemon
description: What this daemon does.
---

# my-daemon
Find work in {{inputs.source}} via `{{inputs.access}}` matching {{inputs.filter}}.
For each item: <do the work>. Record what you handled so the next run skips it.
```

A daemon whose agent commits to a shared repo can declare an `allowed_paths` input
— a list of path prefixes — and call `daimon check-scope [base-ref]` from inside
its worktree. It exits non-zero if the branch reaches outside them. This matters
where CI derives its build/deploy set from the change: a stray edit turns one
change into a release of unrelated apps.

In a Turborepo it asks `turbo ls --affected`, so it judges the **affected
workspace graph** rather than the literal diff — that catches an edit confined to
allowed paths that still fans out into other apps through a shared dependency.
Elsewhere it falls back to matching changed files against the same prefixes;
`--paths` forces that mode. With no `allowed_paths` set it is a no-op, so it costs
nothing to call.

A limit only helps while the daemon that set it is alive, and a pull request
outlives the run that opened it. So a daemon that records `allowed_paths`
alongside a `pr_url` in its state makes that scope durable: any **other** daemon
later pushing to the same PR runs `daimon check-scope --pr <url>`, which resolves
the allowlist from whichever daemon recorded that PR. The shepherding daemon needs
no allowlist of its own — the scope belongs to the pull request and travels with
it. A PR nobody recorded declares no scope, and the check is a no-op.

Every rendered skill also gets `references/learning.md` appended — a protocol for
reading this project's Claude memory at the start of a run (to skip known false
positives) and writing lessons at the end (so the next run is smarter). Set
`learning = false` in `[daemon]` to opt a daemon out.

A daemon that posts comments (it has a `bot_marker` input) additionally gets
`references/skill-conventions.md` appended — the marker-every-comment and
durable-state-via-`daimon state` conventions — so you inherit them instead of
restating them in each skill.

## Activate

```bash
daimon config validate
daimon run my-daemon      # one gated run now
daimon sync               # regenerate plist + skill
make docs                 # regenerate the daemon's README (from daemon.toml + SKILL.md)
daimon tui                # enable scheduling with [e]
```

Each daemon's `README.md` is generated — never hand-edit it; edit `daemon.toml` /
`SKILL.md` and run `make docs`. CI fails if it's stale.

## Keeping a daemon out of the repo

A daemon that only makes sense on your machine — one wired to a private tracker,
epic, or repo — can stay out of git entirely. Add it to `.git/info/exclude`
(local, uncommitted) rather than `.gitignore`, which is shared:

```bash
echo 'daemons/<slug>/' >> "$(git rev-parse --git-dir)/info/exclude"
```

`make docs` leaves an excluded daemon out of the committed `daemons/README.md`
index, so generating docs never dirties a tracked file with a name that isn't in
the repo. It still writes that daemon's own `README.md`, which lives inside the
excluded folder and stays local. Everything else — discovery, `daimon sync`,
scheduling — treats it exactly like any other daemon.

## Tips

- One daemon targets one repo. Cover many repos with one daemon each.
- `/daimon-builder` scaffolds all three files interactively.
- `stuck_after` is the idle-gap reaper, not a runtime cap — set it to comfortably
  exceed the longest quiet stretch a healthy run goes through mid-task.
