---
name: work-queue
description: Autonomously implement ready stories end-to-end on isolated branches and open a pull request for each.
---

# work-queue

Pick up a ready story, implement it in isolation, verify it, and open a pull
request. Handle up to `{{inputs.stories_per_run}}` stories this run, one after
another: after step 8, go back to step 1 for the next, and stop once that many
are done (a resumed story counts as one), none are left, or the open-PR cap
`{{inputs.max_open_prs}}` for `daimon/` branches is reached. The "Source" section below
explains how to find, read, and move stories.

## 1. Pick a stalled claim back up first

A run that dies mid-story (crash, sleep, a prompt nobody answered) leaves its
story in `{{inputs.in_progress_state}}` still labelled `{{inputs.ready_label}}`;
step 8 removes that label, so a finished run never leaves this combination.
(When the field is the marker, see Source, the signature is the field still at
`{{inputs.status_claimed}}` while the story sits in `{{inputs.in_progress_state}}`.)
Search for stories in exactly that state (`label:"{{inputs.ready_label}}"
state:"{{inputs.in_progress_state}}"`, without `{{inputs.skip_label}}`), apply
the same scope rules and safety net as step 2, and order them by the **Priority
order** from Source. If none remain, go to step 2.

Take the first one and decide how to resume it. Read your record with
`daimon state get` (see the state notes below); it keeps a `resumes` object
mapping story id to the number of times a run has picked it back up.

- **It already has a PR** (search `gh pr list --state all --search "<id>"` for a
  `daimon/` branch naming the story): the earlier run got that far. Remove
  `{{inputs.ready_label}}`, set the status field to `{{inputs.status_done}}` (see
  Source), summarize the PR, and count it as this run's story.
- **It has been picked back up twice already** (`resumes[<id>] >= 2`): stop
  retrying. Comment on the story saying the queue tried it three times without
  getting to a PR, name the branch or worktree it left, swap
  `{{inputs.ready_label}}` for `{{inputs.assist_label}}`, and move on to step 2.
- **Otherwise** add one to `resumes[<id>]` and save the record **before** doing
  anything else, so a run that dies again still counts. Then find the earlier
  run's work in the repository the story targets: a worktree under `.worktrees/`
  on a `daimon/` branch naming the story (`git worktree list`), or a pushed
  `daimon/` branch for it (`git ls-remote --heads origin 'daimon/*<id>*'`).
  - Worktree found: `cd` into it, read `git status` and `git diff` alongside the
    story, keep the earlier edits that are right, and carry on from step 4.
  - Only a pushed branch: add a worktree on that branch and carry on from step 4.
  - Nothing found: the run died before isolating. Start over from step 3 with a
    fresh worktree.

Never discard the earlier run's edits wholesale; they may be the only copy.
When the story finishes (step 8), drop its entry from `resumes`.

## 2. Claim one story

**Scope is a hard gate, not a preference.** Only ever claim, move, implement, or
otherwise touch a story that `{{inputs.owner}}` owns — or requested, when Source
says the requester counts (if `{{inputs.owner}}` is blank, all stories are in
scope). A `{{inputs.ready_label}}`
story belonging to anyone else, or in an excluded epic or objective, or carrying an excluded label (see Source),
is off-limits — never claim it, even though it carries the ready label.

Find stories labelled `{{inputs.ready_label}}` that haven't started
(`!is:started !is:done` — backlog and unstarted states only; anything in
progress or review is someone's active work), excluding any tagged
`{{inputs.skip_label}}`, **already scoped to `{{inputs.owner}}` on the server**
(see the Source section). Before acting on a candidate, apply the **safety net**
from Source: re-read it and drop it if it is out of scope, logging
`[out-of-scope skip] sc-{id} …`. If no in-scope ready stories remain, stop.

Among the survivors, pick the first in the **Priority order** from Source. Read it in full and **check it is still current**:
the code it names still exists, and no merged PR, done story, or newer story has
already delivered or superseded it. If it is stale, don't claim it — comment with
the evidence, swap `{{inputs.ready_label}}` for `{{inputs.assist_label}}` (see
Source for label edits), and move on to the next candidate. Otherwise **claim
it** by moving it to `{{inputs.in_progress_state}}` so a later run won't pick it
up again, and set the status field to `{{inputs.status_claimed}}` (see Source).

## 3. Pick the repository and isolate

You start in a directory that may contain several repositories. **Scope:**
restrict to these repositories: `{{inputs.repos}}` — if blank, any repository
under the directory is fair game. Determine which one the story targets and `cd`
into it (its `CLAUDE.md`, conventions, and `gh` context apply once inside). Never work in the main checkout — create a worktree
and branch off `{{inputs.base}}`, kept **inside** that repo (under `.worktrees/`)
so it stays within the trusted project. Exclude it locally so it never shows in
`git status`:

```bash
ROOT="$(git rev-parse --show-toplevel)"
EXCLUDE="$(git rev-parse --git-dir)/info/exclude"
grep -qxF '.worktrees/' "$EXCLUDE" 2>/dev/null || echo '.worktrees/' >> "$EXCLUDE"
git fetch origin {{inputs.base}}
git -C "$ROOT" worktree add ".worktrees/story-<id>" -b daimon/story-<id> "origin/{{inputs.base}}"
cd "$ROOT/.worktrees/story-<id>"
```

If a `daimon/` branch or worktree for this story already exists (an earlier
attempt), reuse it instead of creating a new one, keeping its edits that are right.

## 4. Implement

Implement the story within the worktree, following the repo's conventions and any
rules files. Keep the change scoped to the story. The story is approved: never
stop to wait for an approval or sign-off it mentions. When the surface is built in
more than one place (an app midway through a migration), use the repository's
migration docs and records to find every implementation that still serves users,
and fix each one. If the assessment lists
**Chosen defaults**, follow them and repeat each one, with its reason, in the PR
description.

## 5. Self-review

Re-read your diff against the story's description and acceptance criteria. Fix
anything missing before continuing.

## 6. Verify

Run the repository's own checks (tests, linter, type-check, build). Fix failures.
Do not open a PR with a broken build.

## 7. Open a pull request

Commit, push, and open the PR. `gh` targets the current repo automatically, so
there's no need to name it. Put the story id and `app_url` in the body so the
story and PR are linked, and end the body with this session's id, from
`echo "$DAIMON_AGENT_SESSION"`, as a hidden line:

```
<!-- daimon-session: <the id> -->
```

pr-manager uses it to resume this session when the PR gets review feedback, so
the context behind the change isn't lost.

`open_as_draft` is `{{inputs.open_as_draft}}`:

- `True`: open it as a **draft** (keep `--draft` below). pr-manager promotes it
  once CI is green.
- `False`: drop `--draft`, so the PR opens **ready for review** straight away and
  repository reviewer automation (CODEOWNERS, team auto-assignment) runs on it.

```bash
git add -A && git commit -m "<concise summary>"
git push -u origin daimon/story-<id>
gh pr create --base {{inputs.base}} --draft --title "<title>" \
  --body "Implements Shortcut story <id> — <app_url>

<what changed and why, and how it was verified>

<!-- daimon-session: $DAIMON_AGENT_SESSION -->"
```

## 8. Finish

Remove the `{{inputs.ready_label}}` label (it's been picked up), set the status
field to `{{inputs.status_done}}` (see Source), and leave the story in
`{{inputs.in_progress_state}}`. Summarize: the story id, the branch, and
the PR URL.

Then remove the story's worktree, from the repository root, since the branch is
pushed and the PR holds the work:

```bash
cd "$ROOT" && git worktree remove --force ".worktrees/<name>"
```

Only remove a worktree whose changes are all committed and pushed. Then go back
to step 1 for the next story, or stop when the run's limit is reached.

## State

Your record holds only `{"resumes": {"<story id>": <count>}}`. Read it with
`daimon state get` (empty output means `{}`) and write the whole object back with
`printf '%s' "$json" | daimon state set`. Never write it anywhere else.
