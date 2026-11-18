# Writing a daemon

A daemon is a folder `<slug>/` with three files. Where it lives decides who gets
it ([catalog](catalog.md)):

- your own `daemons/<slug>/` in the dAImon install: gitignored, just for you,
  and active as soon as it exists (`daimon scaffold <slug>`);
- a [pack](packs.md)'s `daemons/<slug>/`: shared with a team, installed by each
  person with `daimon add <slug>` (`daimon scaffold <slug> --pack`). Team-specific
  daemons always go here;
- dAImon's `catalog/<slug>/`: generic, contributed upstream by PR
  (`daimon scaffold <slug> --catalog`).

`daimon sync` renders its skill and refreshes its plist once it is registered.

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

To make the log say what the gate saw, write a one-line summary (ids, counts) to
the file named by `$DAIMON_GATE_NOTE`. `run.sh` appends it to the
`launch_decision` or `skip` line.

A gate can also ask to **resume an earlier agent session** instead of starting a
fresh one, so the agent keeps the context it built: write the session id on line
1 and the command to type into it on line 2 of `$DAIMON_GATE_RESUME`. The backend
must support resuming (see backends/README.md); otherwise the command runs in a
fresh session. pr-manager uses this to hand review feedback back to the
work-queue session that wrote the PR.

```bash
#!/usr/bin/env bash
set -uo pipefail
source "$DAIMON_INSTALL_ROOT/profiles/github/lib.sh"  # exported by dAImon; works in a pack too
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

A daemon that works in git worktrees can set `clean_worktrees = "<branch prefix>"`
in `[daemon]`. After every run, `launch.sh` removes worktrees on branches with that
prefix whose changes are committed and pushed, and logs any it keeps (uncommitted
files or unpushed commits) as `event=cleanup`.

Every rendered skill also gets `references/unattended.md`: no one answers a
permission prompt during a scheduled run, so the agent must avoid commands the
operator's settings make ask-first (`rm`, `git reset`, `git rebase`…) instead of
stalling on them.

It also gets `references/results.md`, which has the agent record one
`event=result` line per item it handled with `daimon log '<outcome> <id> <link> —
<title>'`, so the operational log says what each run did, not just that it ran.

A daemon that posts comments (it has a `bot_marker` input) additionally gets
`references/skill-conventions.md` appended — the marker-every-comment and
durable-state-via-`daimon state` conventions — so you inherit them instead of
restating them in each skill.

## 4. `doctor.sh` (optional)

What only this daemon knows it needs, such as a keychain item, a login, or a
personal setting, can be checked by `daimon doctor`. Add `doctor.sh`: it runs
for registered daemons, with the daemon's inputs as `DAIMON_INPUT_*` and its
folder as `DAIMON_DAEMON_DIR`. Exit 0 = ok, 1 = warn, 2 = fail. The first line
of output is the message.

```bash
security find-generic-password -s "$DAIMON_INPUT_CF_TOKEN_SERVICE" >/dev/null 2>&1 \
  && echo "Cloudflare token in keychain" \
  || { echo "no Cloudflare token in keychain ($DAIMON_INPUT_CF_TOKEN_SERVICE)"; exit 2; }
```

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

Everything in `daemons/` (apart from its README) is gitignored, so a daemon you
scaffold there never reaches git: it is yours, on this machine. It is active
without `daimon add`, and takes precedence over a catalog daemon with the same
slug.

A folder named `<slug>.local` works the same way. The suffix is not part of the
slug: `daemons/<slug>.local` loads as `<slug>`, with the same command, plist,
skill and state names. Having both `daemons/<slug>` and `daemons/<slug>.local` is
a validation error.

`make docs` documents `catalog/` only, so your own daemons never reach the
committed `catalog/README.md` index.

## Tips

- One daemon targets one repo. Cover many repos with one daemon each.
- `/daimon-builder` scaffolds all three files interactively.
- `stuck_after` is the idle-gap reaper, not a runtime cap — set it to comfortably
  exceed the longest quiet stretch a healthy run goes through mid-task.
