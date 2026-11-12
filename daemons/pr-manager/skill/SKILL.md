---
name: pr-manager
description: Shepherd your open pull requests to merge — merge approved ones, resolve conflicts, fix failing CI, and address change requests.
---

# pr-manager

Drive your open pull requests toward merge. You run inside the target repo, so
`gh` targets it automatically. This is **unattended** — never use AskUserQuestion,
and never stop short with "waiting on permission": you run with permissions
skipped, so no approval is coming. Do the work within the bounds below. The only
legitimate reasons to stop short of an action are: a real `remote: Permission to
… denied` push failure (report it, don't loop), or having already spent
`{{inputs.max_fix_cycles}}` fix cycles on a PR this run.

## 1. Find managed PRs

A PR is **managed** if it is on a `daimon/*` branch (work-queue created it) or it
carries the `{{inputs.manage_label}}` label (you opted a hand-authored PR in).

```bash
gh pr list --author @me --state open \
  --json number,title,headRefName,reviewDecision,mergeable,isDraft,labels,statusCheckRollup,url
```

Keep only managed PRs. Your durable JSON memory (via `daimon state get`/`set`) spans
runs — read it now. For each managed PR it records the last action, fix-cycle
count, and (for parked PRs) `ci_blocked_at`. **Skip** any PR marked `ci_blocked`
whose `ci_blocked_at` is less than `{{inputs.blocked_recheck_hours}}` hours ago —
its cause has not changed. If you removed a PR's `{{inputs.manage_label}}` opt-in,
or it no longer exists, drop its entry.

For a labeled (opt-in) PR you did not author the branch for, never rebase,
force-push, or close it — only help it along.

## 2. Recover stale worktrees

A previous run may have been reaped mid-fix. List leftovers and reconcile:

```bash
git worktree list | grep -E '/\.worktrees/pm-' || true
```

For each `pm-*` worktree: if it has only committed-and-already-pushed work, just
remove it; if it has un-pushed commits matching the PR's branch and the remote
hasn't moved, push them; if it has uncommitted changes, discard them (a partial
fix can't be trusted). Always `git worktree remove --force` when done. Leave
`story-*` / other daemons' worktrees alone.

## 3. Act on each PR (priority order)

Process in this order; stop at the first that applies, then move to the next PR.

### 3.0 Promote a ready draft

Skip this phase if `{{inputs.promote_drafts}}` is `0`. work-queue opens its PRs as
drafts; this step takes a finished one off draft so it can be reviewed and merged.

If a managed PR is a draft, all checks pass (no FAILURE/PENDING), it is not
`CONFLICTING`, it is not `CHANGES_REQUESTED`, and it has been open at least
`{{inputs.promote_min_age_hours}}` hours:

- `gh pr ready <n>`, then request the reviewers (§3.5).
- Post `{{inputs.bot_marker}} Auto-promoted from draft — CI green, no conflicts.
  Flagging for review.` and record `promoted` with `daimon state set`.

Promotion does **not** merge — the PR still needs an approving review to reach
§3.1. Leave it ready and move on.

### 3.1 Merge

Merge when all checks pass (no FAILURE/PENDING in `statusCheckRollup`),
`mergeable != "CONFLICTING"`, it is not a draft, and **either**:

- `reviewDecision == "APPROVED"`, or
- `{{inputs.auto_merge}}` is `1` and `reviewDecision != "CHANGES_REQUESTED"` —
  unattended merge without an approving review. (Never merge over requested
  changes; address them in §3.4 first.)

When the merge condition holds:

- **Merge window:** if `{{inputs.merge_window_tz}}`, `{{inputs.merge_window_start}}`
  and `{{inputs.merge_window_end}}` are all set, check
  `TZ={{inputs.merge_window_tz}} date +%H`; if the hour is outside
  `[{{inputs.merge_window_start}}, {{inputs.merge_window_end}}]`, **do not merge**
  this run — log it and leave the PR ready. (Window gates merging only; keep
  doing 3.2–3.4 on other PRs regardless of time.)
- Otherwise merge: `gh pr merge <n> --{{inputs.merge_method}} --delete-branch`,
  then record `merged` with `daimon state set`.

### 3.2 Resolve conflicts

If `mergeable == "CONFLICTING"`: do the merge in an isolated worktree (§4),
`git merge origin/{{inputs.base}}`, resolve each conflict by understanding what
changed on `{{inputs.base}}`, commit, and push (§5).

### 3.3 Fix failing CI

If any check is a FAILURE: **read the log before touching anything.**

```bash
gh pr checks <n> --json name,state,conclusion,detailsUrl   # find the failed run_id from detailsUrl
gh run view <run_id> --log-failed
```

Classify the failure:

- **Caused by this PR** (assume this unless proven otherwise) — the failing
  file/test is in the diff, or the error names a symbol this PR added, changed, or
  removed. Fix it directly in a worktree (§4): read the failing file, make the
  real fix (don't speculatively merge `{{inputs.base}}` hoping it helps), commit,
  push (§5).
- **Pre-existing on `{{inputs.base}}`** — the failing target isn't in the diff and
  the same failure is on `{{inputs.base}}`'s latest runs
  (`gh run list --branch {{inputs.base}} --limit 3 --json conclusion,workflowName`).
  Don't change this PR's behavior. Merge `{{inputs.base}}` in to stay current,
  comment that the failure is upstream (cite both run ids), and move on.
- **Flake** (timeouts, runner errors) — retry once; if it recurs, treat as
  caused-by-this-PR.

Budget: at most `{{inputs.max_fix_cycles}}` fix cycles per PR per run. If still
red after that and it isn't pre-existing, comment the failure, then record
`ci_blocked` with `ci_blocked_at` = now (ISO-8601 UTC) via `daimon state set`
and move on.

### 3.4 Address change requests

If `reviewDecision == "CHANGES_REQUESTED"`, fetch the review comments
(`gh api repos/{owner}/{repo}/pulls/<n>/comments`) and triage each:

- **Valid** (real bug, missing handling, genuine concern) — fix it in a worktree
  (§4). Then reply on the thread: `{{inputs.bot_marker}} Fixed — <what & why> (<sha>)`.
- **Question** — answer it in a reply, prefixed with `{{inputs.bot_marker}}`; no
  code change.
- **Disagree** (would worsen the code, contradicts the repo's rules files, or a
  style nit the formatter owns) — reply respectfully with the reason, cite the
  rule if there is one, and don't make the change.

Follow the repo's own conventions and rules files for any fix. After addressing
all comments, run the repo's checks, push (§5), and re-request the reviewers who
asked for changes: `gh pr edit <n> --add-reviewer <logins>`.

### 3.5 Request reviewers

The configured reviewers are `{{inputs.reviewers}}` (blank = skip this step). For
every managed PR that is **not** a draft, request each configured reviewer who is
not already a requested reviewer and has not already reviewed the PR — e.g.
`gh pr edit <n> --add-reviewer alice,bob` with only the missing logins. Don't
re-request someone who already reviewed (it spams them). This also runs as part of
promotion (§3.0), so a just-promoted PR gets its reviewers immediately.

## 4. Isolated worktrees

Never modify the main checkout. For any fix, work in a per-PR worktree under
`.worktrees/`, kept inside the repo so it stays trusted, and excluded locally so
it never shows in `git status`:

```bash
ROOT="$(git rev-parse --show-toplevel)"
EXCLUDE="$(git rev-parse --git-dir)/info/exclude"
grep -qxF '.worktrees/' "$EXCLUDE" 2>/dev/null || echo '.worktrees/' >> "$EXCLUDE"
git fetch origin <branch>
git -C "$ROOT" worktree add ".worktrees/pm-<n>" "<branch>"
cd "$ROOT/.worktrees/pm-<n>"
```

Remove the worktree when done: `git -C "$ROOT" worktree remove --force ".worktrees/pm-<n>"`.

## 5. Pushing

### Check the PR's declared scope first

Some PRs are opened by a daemon that recorded which paths the change is allowed to
affect, because this repo derives what it builds and deploys from the change
itself. You have no allowlist of your own — the scope belongs to the PR, so ask
for it by PR. From inside the worktree, before pushing:

```bash
daimon check-scope --pr <pr-url> origin/{{inputs.base}}
```

- **exit 0** — the PR declares no scope (the common case, nothing to enforce), or
  your fix stayed inside it. Push normally.
- **exit 1** — your fix reaches outside what this PR may affect. **Do not push.**
  Drop the out-of-scope edits and re-run the check. If the fix genuinely cannot be
  made without them, leave the PR untouched, comment with the exact `check-scope`
  output prefixed by `{{inputs.bot_marker}}`, and move on to the next PR.
- **exit 2** — it could not tell. Treat that as a refusal to push and say why.

Pushing past a failed check is how one migration becomes a release of unrelated
apps. Never edit or work around the guard to get a push through.

### Then push

Run `git push` as a **standalone** command (not chained), allowing a long timeout
— pre-push hooks can legitimately take a minute or more. Treat the push as failed
only on `remote: Permission to … denied` (real auth failure — report, don't
retry), `! [rejected]` (pull/rebase and retry once), or a `fatal:` line. A trailing
`To https://…` with a `<sha>..<sha>` line is the only reliable success signal;
don't conclude "denied" without that exact wording in the output. Never
force-push. Retry a transient failure once, no more.

## 6. Finish

Write each managed PR's current state back with `daimon state set`, remove any
leftover `pm-*` worktrees, and summarize: which PRs you merged, fixed, or parked,
and why.
