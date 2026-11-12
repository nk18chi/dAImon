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
`{number, headSha, reviewer, round}`, and any whose `round` exceeds that PR's
**effective cap** (that instance goes to §7; the others still get worked).

The effective cap is `{{inputs.max_rounds}}` unless an override exists. Read them
with your file tools from `<state_dir>/runtime/acr-fixer.round-caps.json` —
`~/.local/state/daimon/runtime/acr-fixer.round-caps.json` by default — an object
that is absent when none are set:

```json
{"4913": 13, "5175:nk18chi": 12}
```

Two key shapes, and the more specific one wins. For a round by reviewer `R` on
PR `N`, take the first that exists:

1. `"<N>:<R>"` — that reviewer on that PR
2. `"<N>"` — every reviewer on that PR
3. `{{inputs.max_rounds}}`

An entry is a human saying *"I am watching this one, carry it further"*. Honour
it, here and in §7. Everything else stays at the default, which is what keeps an
unattended overnight run bounded.

A PR is in scope if it has at least one open round left. Work at most
`{{inputs.max_prs_per_run}}` PRs this run, `request_changes` verdicts before
`comment` ones. Leave the rest; the next fire picks them up.

### Before you may record `no_action` on any PR

Two named checks, both mandatory. Neither may be skipped, and **neither can be
answered by the watermark**:

1. Every ACR instance's latest complete round at the current head is `approve`.
2. Every `CHANGES_REQUESTED` review at the current head has its `id` recorded in
   `$DAIMON_STATE_FILE`.

If you cannot state both in your summary, the PR is **not** finished. Say which
one failed and work it.

**The watermark answers "is anything new?" — never "is anything open?"** They are
different questions, and confusing them is how a PR sits blocked for days. A
blocking review you read last week and never acted on is *below* the watermark
and *still holding the PR*. An unchanged watermark rules out a new round; it
rules out nothing else. Never use it to skip check 2.

**ACR approving is not the same as the PR being clean.** ACR is one reviewer
among several. A PR where every ACR instance approves while a human's review sits
at `CHANGES_REQUESTED` is **blocked**, and calling that `no_action` is the single
easiest way to leave a PR stuck forever — nothing will raise it again, because
nothing has changed and nothing will.

### Blocking reviews that are not ACR

A PR can also be held by a reviewer that is not ACR at all — dAImon's own
`review-prs` daemon (its body carries `{{inputs.prose_review_marker}}`), another
tool, or **a person**. Fetch formal reviews on every PR:

```bash
gh api repos/{owner}/{repo}/pulls/<n>/reviews --paginate --slurp
```

Keep the latest non-`DISMISSED` review per author. One is in scope when it is
`CHANGES_REQUESTED`, its `commit_id` equals the PR's current head, and its `id`
is not already in your state record. **Do not filter on the marker here** — the
marker tells you how to *read* a review, not whether it counts. A teammate who
pressed "Request changes" without writing in any known format is blocking the PR
exactly as much as a bot is.

A human's review deserves more care than a tool's, not less: read it in full,
answer questions directly, and where you disagree say so plainly rather than
quietly declining. If what it asks for is a judgement call about scope or intent,
that is theirs to make — reply, say what you understood, and leave it.

These behave differently from ACR findings in three ways, and §3–§6 change
accordingly:

- **No finding ids.** The review body is a markdown table plus prose. Treat the
  **whole review as one unit of work** — you fix or decline the whole thing, and
  record it under its review `id`. Do not invent `ACR-` style ids for its rows.
- **No reply protocol.** `/acr` commands mean nothing to it. Reply with an
  ordinary PR comment prefixed `{{inputs.bot_marker}}`, quoting which numbered
  finding you are answering.
- **No rounds.** `{{inputs.max_rounds}}` does not apply. Instead: if the same
  reviewer blocks the same PR a third time, park it and escalate.

Read such a review carefully before acting. Its findings are as likely to be
about scope, acceptance criteria, or a judgement call as about a defect — and
§4's rules apply with more force here, not less. A review arguing that a PR
deviates from its story's acceptance criteria wants a human decision, not a
patch. Decline it, say why in your reply, and name it in your summary.

### A head nobody has reviewed

If a PR has **no complete round at its current head from any instance**, it is
not clean and it is not blocked — it is *unreviewed*. Every round on file
describes code that has been replaced.

This happens whenever the head moves without a re-trigger: you pushed by hand, or
a previous run's re-trigger did not land. It matters because ACR **never**
re-reviews a PR you authored on its own initiative, so nothing will ever ask on
your behalf. Left alone, the PR sits invisible forever — not approved, not
blocked, just unseen. It is the most common way a PR gets stuck.

The work here is not to fix anything. There are no findings to act on yet. Do
exactly one thing:

```bash
mise exec -C {{inputs.acr_repo}} -- pnpm review <owner>/<repo>#<n>
```

and re-request any non-self reviewer whose latest review is against an older
commit (`gh pr edit <n> --add-reviewer <login>`). Then record
`{number, headSha, outcome: "review_requested"}` and move on — that record is
what stops you asking again every fire while the review is queued. Pick the PR up
properly on the next fire, once a round exists at that head.

### Anything else that has been said

ACR is the source to act on when it is present, and the two paths above cover the
formats you know. But a PR can carry comments from a reviewer whose shape you do
not recognise — a colleague's ACR that posted findings without a round event, a
different tool, or a person simply writing a sentence. **None of that should be
invisible just because it is unfamiliar.**

So also check whether anything new has been said since your last run. Your state
record holds a `watermark` per PR — the highest comment id seen on each of the
three surfaces:

```bash
gh api repos/{owner}/{repo}/issues/<n>/comments --paginate --slurp   # top-level
gh api repos/{owner}/{repo}/pulls/<n>/comments  --paginate --slurp   # inline
gh api repos/{owner}/{repo}/pulls/<n>/reviews   --paginate --slurp   # reviews
```

Anything with an id above the recorded watermark arrived since you last looked.
Ignore your own (they carry `{{inputs.bot_marker}}`) and anything you have
already handled as an ACR finding or a prose review. Read what remains.

This check only ever *adds* work. An unchanged watermark means nothing new
arrived — it does not mean nothing is open, and it never satisfies check 2 above.

Then use judgement, and lean towards restraint:

- **A human's comment is not a work order.** A question wants an answer, not a
  commit. Reply and move on.
- **An unrecognised tool's finding** — treat it exactly like a prose review: read
  it, apply §4, fix only what is a real production defect, decline the rest with
  a reason.
- **Anything ambiguous stays with the human.** Say what you saw in your summary
  and leave it. A wrong guess here costs more than a slow answer, because nobody
  asked you to act in the first place.

Record the new watermark in §8 whether or not you did anything — otherwise the
same comments wake you every fire.

## 2. Recover stale worktrees

A previous run may have been reaped mid-fix. Reconcile leftovers before starting:

```bash
git worktree list
```

Read the output yourself and pick out the entries under `.worktrees/af-`. Every
command in this skill is a **single** command — no pipes, no `&&`, no `||`, no
`;`. Repos here deny compound shell commands outright, so a pipeline is refused
rather than queued for approval. When you need to filter, filter in your head.

**A worktree being present does not make it abandoned.** Another acr-fixer run
can be working in one right now — a scheduled fire and a manual one overlap
easily, and the two cannot tell each other apart from the filesystem. Deleting a
live worktree destroys uncommitted work that its owner is midway through and
cannot recover. This has already happened once, costing about forty minutes.

So before touching any `af-*` worktree, establish it is not in use:

```bash
tmux has-session -t daimon-acr-fixer
```

If that session exists and is **not yours**, another run is in flight: reconcile
nothing, remove nothing, and work only your own `af-<n>`. Say so in your summary.

Otherwise, for each `af-*` worktree: if its work is committed and already pushed,
just remove it; if it has un-pushed commits on the PR's branch and the remote
hasn't moved, push them; if it has uncommitted changes, **commit them to the
branch rather than discarding them** — a partial fix you did not make is still
someone's work, and a commit is recoverable where a discard is not. Only then
`git worktree remove --force`.

Leave `pm-*`, `story-*`, and other daemons' worktrees alone.

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

Every finding gets a decision before you touch any code. `severity` and
`blocking` are separate fields — a finding can be `important` without being
blocking — so read both:

- **`blocking: true`** — fix it, whatever its severity. This is what holds the
  verdict at `request_changes`.
- **`critical` or `important`** — fix it. If you think one is wrong, say so with
  a specific technical reason; "not worth it" is not one.
- **`minor`** — fix only if it is a defect that can actually occur in
  production. If nobody could hit it, `/acr wontfix <id> <reason>`.
- **`suggestion`**, and follow-ups (`ACR-F-…`) — your call, and the default is
  no. Take one only when it is small, obviously right, and touches code you are
  already changing. A suggestion is not a defect, and a diff that grows to
  satisfy taste is how a reviewer's next round finds three more.
- **About code a previous round added** — overrides everything above. That is a
  signal to *revert that code*, not to guard it. Check `git log -p` on the
  branch: if the finding is against machinery you added answering an earlier
  finding, removing the machinery is the fix. Adding a guard on top is how three
  rounds become seven.

### When the verdict is already `approve`

An approved PR is **finished**. Pushing to it un-finishes it: the head moves,
every instance's approval is invalidated, each re-reviews the new code, and each
can raise something new. A minor finding costs one small diff; acting on it costs
a full round from every reviewer on the PR.

That does not put minor findings off limits — it raises the bar for taking one.
Judge each on its merits, and ask the same question every time:

> **Is this worth a full review round from every instance on the PR?**

- **Worth it** — it is a defect a user could hit, it makes the code meaningfully
  clearer or safer, or it is something you would be uncomfortable leaving in.
  Fix it, and take the round.
- **Not worth it** — it is taste, a rename, a comment reword, a preference the
  formatter does not enforce. `/acr wontfix <id> <reason>`, and say plainly that
  the verdict is already `approve` and this does not justify reopening it.

Severity is the reviewer's estimate, not a fact. A `minor` that turns out to be a
real defect gets fixed like any other defect; a `minor` that is genuinely minor
gets declined. What decides it is the code, not the label.

**Whatever you conclude, conclude something.** Leaving a finding unjudged is the
worst of both: not fixed, and re-raised in full on every subsequent round — which
is exactly how a PR accumulates dozens of comments repeating themselves.

Findings that are genuinely for a human — a blocking one you declined on a
judgement call, or an argument about scope — stay unjudged on purpose, so the
human inherits a checked finding rather than a suppressed one. That is a
different case from a minor nit on an approved PR.

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
git -C <toplevel> worktree add --detach .worktrees/af-<n> origin/<branch>
```

Both details matter. Check out **`origin/<branch>`**, not `<branch>`: the fetch
moves the remote-tracking ref but never fast-forwards a stale local branch, so
the plain name can hand you code older than what is on the PR — including any
commit the author pushed by hand since the last run. And **`--detach`**, because
these branches are routinely checked out in another worktree already, which makes
a branch-name checkout fail outright.

Working detached means the branch name is not attached to your commits, so push
with the explicit refspec in §6.

Work inside `<toplevel>/.worktrees/af-<n>` from here. Remove it when done:
`git -C <toplevel> worktree remove --force .worktrees/af-<n>`.

## 6. Verify, push, and reply

**Verify first.** Run the repo's own checks (its Makefile target, test script, or
whatever `AGENTS.md`/`CLAUDE.md` documents) before pushing. A fix that breaks CI
turns one red round into two.

**Push** with an explicit refspec, since §5 left you on a detached HEAD:

```bash
git push origin HEAD:<branch>
```

Run it as a **standalone** command (not chained), allowing a long timeout —
pre-push hooks can legitimately take a minute or more. Treat the push as failed
only on `remote: Permission to … denied` (real auth failure — report, don't
retry), `! [rejected]` (pull/rebase and retry once), or a `fatal:` line. A
trailing `To https://…` with a `<sha>..<sha>` line is the only reliable success
signal. Never force-push. Retry a transient failure once, no more.

A `! [rejected]` here means someone pushed to the branch after your fetch. Fetch
again and rebase your commits onto the new `origin/<branch>` — never resolve it
by forcing, and never by discarding their commit.

**Then reply** — only after the push succeeds, so `fixed` is true when ACR reads
it. On each finding's inline thread where there is one, otherwise batched into a
single top-level comment:

- `/acr fixed <id>` for each finding you fixed.
- `/acr wontfix <id> <reason>` for each you declined, with the real reason.
- `/acr done <id>` / `/acr declined <id> <reason>` for follow-ups.

For a **prose review** there are no ids and no `/acr` verbs. Reply once, as an
ordinary comment prefixed `{{inputs.bot_marker}}`, walking its numbered findings
in order and saying for each whether you fixed it or declined it and why. Then
re-request that reviewer with `gh pr edit <n> --add-reviewer <login>` — that is
the only way it re-reads the PR, since it has no queue to trigger.

For ACR findings, reply with **every** id in a merged group, including the ones
from other instances. Each instance only recognises its own ids: it applies the commands
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
that PR's **effective cap** — `{{inputs.max_rounds}}`, or the per-PR override
from §1 when one is set — stop working that instance's findings and record
`outcome: "parked"` for its `{reviewer, round}` — but keep fixing the other
instances' open rounds on the same PR. A second reviewer arriving at its round 1
on a PR you're at round 6 with is fresh work, not a stalled loop.

When you park, post a `{{inputs.bot_marker}}`-prefixed comment naming the
instance, its round number, the findings still open, and what you already tried.
Park the same way when one finding id has regressed twice — a fix that keeps
failing needs a human, not a third attempt.

**Post that comment once, not once per round.** If `$DAIMON_STATE_FILE` already
records `outcome: "parked"` for this reviewer at this `headSha`, the notice is
already on the PR — record the new round and say nothing. A parked instance goes
on producing rounds (the cap stops *you*, not ACR), and a fresh "still parked"
comment on each one buries the original under noise and tells the human nothing
new. Post again only when the head has moved, which means there is genuinely new
code to have parked on.

If ACR's own comment is a pipeline failure (an `acr:failure:v1` marker, no
verdict), don't touch the code at all. Report it and move on — that's ACR broken,
not the PR.

## 8. Finish

Write one record per **reviewer-round** you acted on back to
`$DAIMON_STATE_FILE` — `{number, headSha, reviewer, round, verdict, outcome}`,
where `outcome` is `fixed`, `parked`, or `no_action`. One PR worked across two
instances produces two records.

**Record a `reviewId` for every blocking review you dispositioned**, whatever its
format and whoever wrote it — `{number, headSha, reviewer, reviewId, outcome}`.
That id is what the gate dedups on, and the gate no longer filters by format, so
an ACR instance's own `CHANGES_REQUESTED` review needs one too. Omit it and that
review is picked up again on the very next fire, forever. Keying on the PR alone would make one instance's
round mask another's and silently skip its findings.

**Record a `watermark` for every PR you looked at**, whether or not you changed
anything — `{number, watermark: {issue, inline, review}}`, each the highest
comment id on that surface. Take it **after** your own comments have posted, so
your replies do not wake the next run. A PR you inspected and left alone still
needs one — **especially** one you left alone, since that is the case with no
other record to show you were there.

Without it the gate has no baseline to compare against, so the catch-all in §1
is silently dead for that PR: a reviewer whose format you cannot parse will never
surface. The ACR and prose paths keep working, so nothing breaks loudly — it just
stops noticing.

**Prune closed and merged PRs while you are here.** Drop every record whose PR
is not in the open list you fetched in §1 — merged and closed PRs will never be
worked again, so their records are dead weight that accumulates run after run
and buries the live ones. Use the **unfiltered** open list for this: a PR that is
open but a draft, or carries `{{inputs.skip_label}}`, is still live and keeps its
record. If §1's fetch failed, prune nothing rather than guessing.

Remove every `af-*` worktree **you created this run** — see §2 for why that
qualifier matters. Then summarize: per PR, which instance raised what, the
findings you fixed, the ones you declined and why, and anything left for the next
round.

For any PR you are reporting as needing nothing, state both §1 checks explicitly:
every instance approves at the current head, **and** every `CHANGES_REQUESTED`
review at that head has a recorded `reviewId`. Naming them is what stops "the
watermark was unchanged" standing in for "I checked".
