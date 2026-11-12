---
name: review-trigger
description: Ask for a review on your open PRs whose current commit nobody has reviewed — trigger your own ACR instance, re-request the others, and record the head so you don't ask twice.
---

# review-trigger

Some of your open PRs sit on a commit no reviewer has looked at. Your job is to
ask for the review, once per commit.

That is the whole job. **You do not fix anything.** You do not create a
worktree, edit a file, commit, or push. Something else — Claude Code Desktop's
auto-fix, or you by hand — is doing the fixing, and this daemon exists precisely
so those pushes don't vanish unreviewed. If you find yourself reading a finding
to decide whether it's worth acting on, you have left your job: that decision
belongs to whoever is fixing, and doing it here means two agents editing one
branch.

You run inside the target repo, so `gh` targets it automatically. This is
**unattended** — never use AskUserQuestion, and never stop short waiting on
someone. The only legitimate reasons to stop short are a tool call this session
isn't permitted to make (report exactly which one) or a repeated command failure
(report it; don't loop).

## 1. Find the PRs on an unreviewed commit

`$DAIMON_STATE_FILE` is your durable memory across runs — read it first. It holds
one record per commit you've asked about: `{number, headSha, outcome, askedAt}`.

Read and write it with your platform's file tools at the literal path —
`<state_dir>/state/review-trigger.json`, which is
`~/.local/state/daimon/state/review-trigger.json` unless `state_dir` was changed
in `~/.config/daimon/daimon.toml`. Do **not** run a shell command to expand
`$DAIMON_STATE_FILE` and discover it: a command containing a variable expansion
cannot be matched against the permission allowlist, so it prompts every time and
stalls an unattended run. If neither path exists, say so and carry on without the
dedup memory — asking twice is a small cost, and going looking for the file is a
larger one.

```bash
gh pr list --author @me --state open --json number,title,headRefOid,isDraft,labels,url
```

Drop drafts and anything labelled `{{inputs.skip_label}}`.

For each surviving PR, read the ACR round comments and group them by the posting
account's `user.login` — **more than one ACR instance may review the same PR**,
each under its own GitHub account, with its own finding ids and its own round
numbers. Take each instance's latest complete round (`final == true`, highest
`round` for that login).

**The question is per reviewer, not per PR.** An instance is *behind* when its
latest complete round has a `head_sha` other than the PR's current `headRefOid`.

This distinction is the whole point of the daemon. Colleagues' instances re-queue
themselves when the head moves; yours never will, because ACR refuses to
re-review a PR you authored. So a PR where two colleagues are current and your
own instance is eight rounds back reads as perfectly healthy, and the one review
you actually control quietly stops happening. That state was live on three of
five open PRs when this was written.

Being behind is necessary but not sufficient. Sort the instances by their latest
verdict:

- a **holdout** — latest verdict is anything other than `approve`
- an **approver** — latest verdict is `approve`

Then pick who to ask:

| Situation | Ask |
|---|---|
| Any holdout exists | **the holdouts that are behind** — plus any behind approver whose approval GitHub has dismissed |
| Every instance has approved | **everyone still behind** — the sweep |
| No instance has ever reviewed | everyone you can (see §2) |
| A holdout **on the current head** whose latest round you have since answered in a reply | **that holdout** — up to `{{inputs.max_reply_retriggers}}` times per commit |

An approver has said its piece. While someone else is still holding the PR up,
the code under change is the holdout's objection, not theirs — re-asking them on
every push spends a review to be told the same thing. Over six real PRs this
rule asks 110 reviews where asking everyone asks 140.

**The sweep is not optional.** A reviewer that approved at head 1 has never seen
the fixes made at heads 2 through 5, and its approval is of code that no longer
exists. Deferring an approver is only safe because the sweep guarantees it
eventually reviews the final commit. If you skip the sweep you have not saved a
review, you have lost one.

**A dismissed approval is not an approval.** The round comment says `approve`
forever, but on a repo with `dismiss-stale-reviews` the next push voids the
review, and GitHub is the one keeping score: the PR reads `REVIEW_REQUIRED` and
will not merge. So check the live state too —

```bash
gh pr view <n> --json reviewDecision,latestReviews
```

— and treat an approver whose latest review is `DISMISSED` as askable, holdout
or no holdout. There is nothing left to defer; GitHub has already discarded the
review, so asking costs nothing and not asking strands the PR.

Without this the deferral latches, and the sweep cannot save you: the sweep needs
*every* instance to have approved, so one instance that keeps finding minor
things — normally yours, on the PR you are pushing to — holds the gate shut
indefinitely while the approvers it defers drift arbitrarily far behind. PR 5358
sat at round 13 that way, two dismissed approvals eight rounds back and nobody
requested.

Read `DISMISSED` specifically, not "anything that isn't `APPROVED`". ACR reviews
a PR you authored with a plain `COMMENT` review — GitHub forbids authors
approving their own — so your own approving instance never shows `APPROVED`, and
the looser test would re-ask it on every push and spend the whole saving.

**An answered finding needs a review that no push will trigger.** A finding that
gets declined rather than fixed produces no commit. The head does not move, so
the instance that raised it is not behind — it has reviewed this exact commit —
and every rule above reads the PR as covered. But the thread has moved: there is
now a reply that instance has never read, and it is the only party that can
retire the finding or push back on the decline. Nobody asks it to look, and the
PR sits at `CHANGES_REQUESTED` indefinitely.

Declining is the normal outcome of a round, not a rare one, so this is not an
edge case. PR 5501 sat this way: schlenks round 4 `request_changes` on the
current head, `ACR-cad724` declined in a reply, and no commit that could ever
arrive to unstick it.

So also ask a holdout **on the current head** when the author has replied to its
findings **since its latest round was posted**. Three qualifiers, all load-bearing:

- **Since that round**, not just "at some point". ACR re-raises an open finding
  in every round, so the reply you wrote to round 3 is already answered by round
  4 existing at all.
- **On that instance's threads.** A reply is attributed to whoever posted the
  comment it replies to. Replying to schlenks says nothing to mulvster.
- **Your reply, not the bot's.** Your own instance posts under your own account,
  so login cannot tell ACR's "verified addressed" note from your reply — the
  `acr:v1` marker on line 1 can. Bot comments carry it; yours does not. Get this
  wrong and the bot answers its own rounds forever.

**Cap this at `{{inputs.max_reply_retriggers}}` asks per reviewer per commit.**
Every other loop in this daemon ends because a fix moves the head. A decline
never moves it, so this one has no natural stop: 5501 declined `ACR-cad724` and
got the identical finding back as round 4. Two exchanges is a stable
disagreement, not a convergence — past the cap, say so in your summary and leave
it for a human. That is the right destination for two agents that disagree.

Two things that are not the same as behind, and must not be treated as it:

- **A holdout sitting on the current head that you have not answered.** It has
  seen this commit and the findings are somebody else's job; asking again just
  repeats the round. Once you *have* answered it, the rule above applies.
- **A reviewer you already asked at this head.** If `$DAIMON_STATE_FILE` holds a
  record with this `number` and `headSha` listing that login in `reviewers`, the
  review is queued and has not arrived. Asking again does not make it come
  sooner. Note this is per reviewer — a record naming only the holdout must not
  stop the sweep asking the approvers at that same head.

An approval counts only against the commit it was submitted on. If an instance
approved at `abc123` and the head is now `def456`, that instance is behind — an
approval of code that has since been replaced approves nothing.

## 2. Ask for the review

For each PR from §1, both mechanisms:

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
- **Any other instance that is behind** — `gh pr edit <n> --add-reviewer <login>`,
  which puts it back in `requested_reviewers` and lets its daemon re-queue the
  PR. You cannot request yourself, which is why your own instance needs the
  command above.

Trigger only the instances §1 named. Pinging one whose latest round is already
at the current head — and which you have not answered since — just costs it a
review.

When a PR has no rounds at all, there is no behind-list to work from: trigger
your own instance and re-request whoever is already in `reviewRequests`.

## 3. Record what you asked

Append one record per PR to `$DAIMON_STATE_FILE`:

```json
{"number": 5412, "headSha": "25d72b8402…", "outcome": "review_requested",
 "askedAt": "2026-08-12", "reviewers": ["nk18chi", "schlenks"],
 "answeredRounds": [{"reviewer": "schlenks", "round": 4}]}
```

`reviewers` is **required and load-bearing** — it is the dedup key, together with
`headSha`. List exactly the logins you triggered on this run and no others. Name
one you did not trigger and that instance is silently never asked at this head;
omit one you did and it gets asked again in three minutes.

`answeredRounds` is the dedup key for the reply path, and it is a **separate**
key on purpose: it carries the round number, and it accumulates rather than
replacing. Add one entry per reviewer you triggered because you had answered its
findings, alongside that login in `reviewers`.

It cannot share the `reviewers` key, because that reviewer is normally already
listed there — you asked it at this head, it reviewed, and the reply came
afterwards — so a login-level check would suppress exactly the case §1 added.
And it must keep every earlier entry at this `headSha`: the count of entries for
one login is what enforces the `{{inputs.max_reply_retriggers}}` cap, and a head
that never moves is the only thing bounding that loop. Overwrite the list instead
of appending and the cap silently becomes infinite.

Record the **full** sha, and record even a partial success: a partial ask is
still an ask, and the next push produces a new head and a fresh chance.

Use these `outcome` values and no others, so the TUI can render them:

- `review_requested` — you asked, at least one mechanism succeeded.
- `trigger_failed` — every mechanism failed for this PR. Say what the error was
  in your summary. Recording this still dedups the head, so a broken ACR
  checkout costs one wasted run per push rather than one every three minutes.

Then **drop records for PRs that are now closed or merged** — the file is a
working set, not a log, and a closed PR will never produce another head.

## 4. Report

One short summary: which PRs you asked about, which reviewers each went to, and
anything that failed. Say when a request was a **sweep** — "all three approved;
asked assiad and nk18chi to confirm against the final commit" tells a human the
PR is one round from done, which "asked 2 reviewers" does not.

Say the same for a reply-triggered ask — "answered schlenks's ACR-cad724 with a
decline; asked it to re-read" — and name any reviewer that hit the
`{{inputs.max_reply_retriggers}}` cap explicitly. That one is not a quiet skip:
it means an instance and a human have disagreed twice about the same finding on
the same commit and the PR needs someone to settle it.

If you asked about nothing, say which PRs you considered and why each was
already covered. "3 PRs open, all reviewed at their current head" is a useful
answer and a silent run is not — every stuck PR in this system's history looked
exactly like a quiet one.
