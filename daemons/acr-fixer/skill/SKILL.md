---
name: acr-fixer
description: Close out ACR review findings on your open PRs — fix each one on the PR branch, reply through the ACR protocol, and push so the next review round verifies the work.
---

# acr-fixer

ACR reviewed your PRs and did not approve them. Your job is to act on every
finding it raised, push the result, and tell ACR what you did — so its next round
either approves or comes back with something new.

You run inside the target repo, so `gh` targets it automatically. This is
**unattended** — never use AskUserQuestion, and never stop short with "waiting on
approval": there is no human in this session to answer. The only legitimate
reasons to stop short are a real `remote: Permission to … denied` push failure
(report it, don't loop), a tool call this session isn't permitted to make (report
exactly which one), or a budget in this document being spent.

Read the ACR reference sections below before you start. In particular: the
verdict is in the round comment's `<details>` payload — **not** in the line-1
envelope, and **not** in `reviewDecision`, which is always null on your own PRs.
A round whose verdict you cannot read is a parse failure, not an approval; say
so rather than treating that PR as clean.

## 1. Pick the PRs to work

`$DAIMON_STATE_FILE` is your durable memory across runs — read it first. It holds
one record per reviewer-round you've acted on: `{number, headSha, reviewer,
round, verdict, outcome}`.

Read and write it with your platform's file tools at the literal path —
`<state_dir>/state/acr-fixer.json`, which is
`~/.local/state/daimon/state/acr-fixer.json` unless `state_dir` was changed in
`~/.config/daimon/daimon.toml`. Do **not** run a shell command to expand
`$DAIMON_STATE_FILE` and discover it: a command containing a variable expansion
cannot be matched against the permission allowlist, so it prompts every time and
stalls an unattended run. If neither path exists, say so and carry on without
the dedup memory rather than going looking for it.

```bash
gh pr list --author @me --state open --json number,title,headRefOid,isDraft,labels,url
```

Drop drafts and anything labelled `{{inputs.skip_label}}`.

**More than one ACR instance may review the same PR.** Each runs under its own
GitHub account, keeps its own finding ids, and numbers its own rounds — so one
PR can carry `nk18chi` at round 3 and `schlenks` at round 1 on the same commit.
The posting comment's `user.login` is the instance identity; the envelope has no
field for it. Group every round envelope by that login and treat each instance's
sequence separately.

For each surviving PR, take **each reviewer's** latest complete round
(`final == true`, highest `round` for that login). A reviewer's round is open
when both hold:

- `verdict` is not `approve` — that instance is satisfied; nothing to do for it.
- `head_sha` equals the PR's current `headRefOid`. If it doesn't, that review is
  of an older commit and its findings may already be fixed. **Skip it** — acting
  on a stale review is how you end up re-fixing code that moved.

Then drop any open round already recorded in `$DAIMON_STATE_FILE` under the same
`{number, headSha, reviewer, round}`, and any whose `round` exceeds
`{{inputs.max_rounds}}` (that instance goes to §7; the others still get worked).

A PR is in scope if it has at least one open round left. Work at most
`{{inputs.max_prs_per_run}}` PRs this run, `request_changes` verdicts before
`comment` ones. Leave the rest; the next fire picks them up.

## 2. Recover stale worktrees

A previous run may have been reaped mid-fix. Reconcile leftovers before starting:

```bash
git worktree list
```

Read the output yourself and pick out the entries under `.worktrees/af-`. Every
command in this skill is a **single** command — no pipes, no `&&`, no `||`, no
`;`. Repos here deny compound shell commands outright, so a pipeline is refused
rather than queued for approval. When you need to filter, filter in your head.

For each `af-*` worktree: if its work is committed and already pushed, just
remove it; if it has un-pushed commits on the PR's branch and the remote hasn't
moved, push them; if it has uncommitted changes, discard them — a partial fix
can't be trusted, and you're about to redo it properly. Always `git worktree
remove --force` when done. Leave `pm-*`, `story-*`, and other daemons' worktrees
alone.

"No stale `af-*` worktrees" means you have nothing to reconcile — it does **not**
mean you may adopt whatever other worktrees the listing shows. §5 applies either
way: you create your own, inside the repo.

## 3. Read the findings

Each open round has its own `state_comments.findings` id. Fetch **every** one of
them and parse its JSON payload — one instance's findings document says nothing
about another's. Also pull the inline finding comments (`gh api
repos/{owner}/{repo}/pulls/<n>/comments --paginate --slurp`) — they carry the
same ids and often a GitHub `suggestion` block with a concrete patch.

Keep each finding tagged with the reviewer whose document it came from. You need
that at reply time (§6) and in your state record (§8).

**Merge across instances before you start fixing.** Two instances that spot the
same problem give it two unrelated ids. Group by `file` plus `symbol`/`snippet`,
not by id: one code change clears the whole group, and each id in it gets its own
reply. Fixing the same line twice because it arrived under two ids is the main
way this goes wrong.

Order the merged groups: `regressed` first, then `critical`, `important`,
`minor`, `suggestion`. Include the follow-ups (`ACR-F-xxxx`) so every finding
gets a decision — but a decision is not the same as a fix. §4 says which get
fixed and which get declined.

Cap the work at `{{inputs.max_findings_per_pr}}` findings for this PR this run.
If there are more, take them in the order above and leave the tail for the next
round — one push of twenty coherent fixes beats one push of sixty sprawling ones.

**A `regressed` finding means your last fix didn't work.** Don't reapply it. Read
what you actually changed (`git log -p` on the branch) and work out why ACR still
sees the problem before touching anything.

## 4. Decide each finding, then fix the ones that earn it

Fixing every finding is how this goes wrong. Each fix is new code, new code draws
new findings, and the loop runs away — measured on real PRs here: 15 findings, 15
fixes, zero declines, seven rounds, and 2,589 insertions for a bug whose actual
fix was three lines. Two or three rounds is the target. Zero findings is not.

Apply this rule to every finding before touching the code:

- **Blocking** (`blocking: true`) — fix it.
- **Minor** — fix only if it is a defect that can actually occur in production.
  Otherwise `/acr wontfix <id> <reason>`.
- **About code a previous round added** — that is a signal to *revert that code*,
  not to guard it. Check `git log -p` on the branch: if the finding is against
  machinery you added answering an earlier finding, removing the machinery is the
  fix. Adding a guard on top is how three rounds become seven.

Declining is the normal case, not the exception. A finding you silently ignore is
re-raised every round; `/acr wontfix` is the only thing that retires it.

Work in a per-PR worktree (§5), never the main checkout. For each finding you
decided to fix:

- Open the file at `file`/`line`. If the line has drifted, re-locate by `symbol`
  or `snippet` — never patch a line number blindly.
- Understand the finding against the actual code before changing anything. A
  finding is a claim, and ACR's `confidence` is its own estimate, not a fact.
- Make the real fix, following the repo's conventions and rules files. If ACR
  supplied a `suggestion` block, treat it as a starting point you verify, not a
  patch to apply unread — suggestions are generated against a single line and
  routinely miss context two lines away.
- Keep the change scoped to the finding. Do not refactor around it, and do not
  fix things ACR didn't raise; an unexplained diff is what makes a human stop
  trusting this loop.

Decline the rest with `/acr wontfix <id> <reason>`, naming the real reason:

- **Wrong** — the finding misreads the code, or the "bug" can't happen given a
  guarantee upstream.
- **Contradicts the repo** — it fights a rules file, a documented convention, or
  the formatter. Cite the rule.
- **Too large to do safely here** — it calls for an architectural change, a
  migration, or code outside this PR's scope. Say it needs its own PR, and repeat
  that in your summary.
- **Not a production defect** — a minor or suggestion-severity point that no user
  could hit. Say that plainly rather than fixing it to clear the board.

Commit per finding or per coherent group, with the finding id in the message:
`fix(acr): <what changed> (ACR-a3f9)`.

## 5. Isolated worktrees

**Every file you touch must live under this repo's toplevel.** Create your own
worktree at `<toplevel>/.worktrees/af-<n>` and work only there.

This is a hard constraint, not a preference. Sessions here run in `auto`
permission mode, which auto-approves file operations *within project scope* and
treats a path outside the repo — another checkout, a shared worktree directory,
anywhere under `~/` — as scope escalation. An edit outside the toplevel raises an
approval prompt that no one is present to answer, so the run hangs until it is
reaped and the work is lost.

So: do not modify the main checkout, and **do not reuse an existing worktree**,
however convenient. A worktree already sitting on the branch at current head is
still the wrong answer — it is outside the repo, it belongs to someone else, and
it may hold uncommitted work you would build on top of. Make your own.

One command at a time. Shell variables do **not** survive between commands here,
so substitute the real paths yourself rather than assigning them:

```bash
git rev-parse --show-toplevel
```

Do **not** touch `.git/info/exclude` or any other file under `.git/` — writes
there are not auto-approved and will stall the run. Keeping `.worktrees/` out of
`git status` is a one-time local setup step for a human, not your job. If the
directory shows up as untracked, ignore it and carry on.

Then create it, substituting the toplevel path from the first command:

```bash
git fetch origin <branch>
```

```bash
git -C <toplevel> worktree add .worktrees/af-<n> <branch>
```

Work inside `<toplevel>/.worktrees/af-<n>` from here. Remove it when done:
`git -C <toplevel> worktree remove --force .worktrees/af-<n>`.

## 6. Verify, push, and reply

**Verify first.** Run the repo's own checks (its Makefile target, test script, or
whatever `AGENTS.md`/`CLAUDE.md` documents) before pushing. A fix that breaks CI
turns one red round into two.

**Push** as a **standalone** command (not chained), allowing a long timeout —
pre-push hooks can legitimately take a minute or more. Treat the push as failed
only on `remote: Permission to … denied` (real auth failure — report, don't
retry), `! [rejected]` (pull/rebase and retry once), or a `fatal:` line. A
trailing `To https://…` with a `<sha>..<sha>` line is the only reliable success
signal. Never force-push. Retry a transient failure once, no more.

**Then reply** — only after the push succeeds, so `fixed` is true when ACR reads
it. On each finding's inline thread where there is one, otherwise batched into a
single top-level comment:

- `/acr fixed <id>` for each finding you fixed.
- `/acr wontfix <id> <reason>` for each you declined, with the real reason.
- `/acr done <id>` / `/acr declined <id> <reason>` for follow-ups.

Reply with **every** id in a merged group, including the ones from other
instances. Each instance only recognises its own ids: it applies the commands
that match its database and reacts 😕 to the rest, with no state change. Those
😕 reactions are expected on a multi-instance PR and are not a failure — do not
retry them, reword them, or drop the ids that earned them. Dropping a foreign id
is what leaves that instance's thread open forever.

Then post one top-level summary comment prefixed `{{inputs.bot_marker}}`: what
you fixed, what you declined and why, and anything deferred to the next round.
When several instances reviewed, say which findings came from which — a human
reading one instance's threads otherwise can't tell why an unfamiliar id appears.

**Then re-trigger the review.** Nothing starts the next round on its own — a
completed review is never re-queued by the poller for a PR you authored. Without
this step you fix once and the loop stops. Do it only after the push succeeded,
so the new round reviews the new code.

Two mechanisms, one per reviewer with an open round:

- **Your own instance** —
  `mise exec -C {{inputs.acr_repo}} -- pnpm review <owner>/<repo>#<n>`.
  Run it from *inside* the ACR checkout like this, not with `pnpm -C` from here:
  `pnpm` is usually a version-manager shim rather than a binary on `PATH`, and
  ACR pins a newer Node than the surrounding repo. If `mise` isn't what manages
  your toolchain, substitute whatever makes `pnpm` resolvable there — the
  requirement is that it runs in the ACR checkout with ACR's Node. Never go
  hunting for an absolute `node` path; that breaks on the next upgrade.

  Always the qualified `<owner>/<repo>#<n>` form: a bare number is refused when
  ACR has several repos configured. Never pass `--force` — if a round is already
  in flight, leaving it alone is correct. A clean exit means the job is queued,
  not that a review ran. Skip this entirely if `{{inputs.acr_repo}}` is blank.
- **Any other instance** — `gh pr edit <n> --add-reviewer <login>`, which puts it
  back in `requested_reviewers` and lets its daemon re-queue the PR. You cannot
  request yourself, which is why your own instance needs the command above.

Re-trigger only the reviewers whose rounds you actually worked. Pinging an
instance that already approved at the current head just costs it a review.

## 7. Park a PR that isn't converging

Parking is **per reviewer**, not per PR. If one instance's latest round is past
`{{inputs.max_rounds}}`, stop working that instance's findings and record
`outcome: "parked"` for its `{reviewer, round}` — but keep fixing the other
instances' open rounds on the same PR. A second reviewer arriving at its round 1
on a PR you're at round 6 with is fresh work, not a stalled loop.

When you park, post a `{{inputs.bot_marker}}`-prefixed comment naming the
instance, its round number, the findings still open, and what you already tried.
Park the same way when one finding id has regressed twice — a fix that keeps
failing needs a human, not a third attempt.

If ACR's own comment is a pipeline failure (an `acr:failure:v1` marker, no
verdict), don't touch the code at all. Report it and move on — that's ACR broken,
not the PR.

## 8. Finish

Write one record per **reviewer-round** you acted on back to
`$DAIMON_STATE_FILE` — `{number, headSha, reviewer, round, verdict, outcome}`,
where `outcome` is `fixed`, `parked`, or `no_action`. One PR worked across two
instances produces two records. Keying on the PR alone would make one instance's
round mask another's and silently skip its findings.

Remove every `af-*` worktree you created. Then summarize: per PR, which instance
raised what, the findings you fixed, the ones you declined and why, and anything
left for the next round.
