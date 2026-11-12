---
name: review-prs
description: Review open pull requests assigned to you and cast a risk-gated decision — approve, request changes, or comment.
---

# review-prs

Autonomously review pull requests that need your attention and cast a review
decision gated on risk. You run inside the target repo, so `gh` targets it
automatically.

## 1. Discover

Find pull requests matching the filter `{{inputs.filter}}`:

```bash
gh pr list --search "{{inputs.filter}}" --json number,title,headRefName,headRefOid
```

Skip any PR you have already reviewed at its current head commit. Your durable
record is the JSON array from `daimon state get` (`[{number, headSha, verdict}]`)
— read it at the start, skip PRs whose number + head SHA you've already recorded,
and write back the ones you act on this run. (Submitting a review also clears the
`review-requested` flag, so most already-done PRs simply won't appear. A removed
entry — e.g. reply-to-pr-comments cleared it after a reply — makes a PR reappear for
re-review even at an unchanged SHA.)

## 2. Announce pickup immediately

For each PR you select, post a visible PR conversation comment **before** reading
the diff, work item, or repository context. Do not use a pending review for this:
pending reviews are not visible to the author. The comment body is:

```markdown
{{inputs.bot_marker}} Reviewing this PR now. I'll update this comment when the review is complete.
<!-- daimon:review-prs:<headSha> -->
```

Use the issue-comments API (`repos/{owner}/{repo}/issues/<n>/comments`) and retain
the returned comment `id`. On a retry or a same-SHA re-review, first look for a
self-authored comment carrying the exact hidden `daimon:review-prs:<headSha>`
marker and edit that comment back to the pickup body instead of creating a
duplicate. The hidden marker must remain in every edit.

After submitting the review in §5, edit the pickup comment via
`repos/{owner}/{repo}/issues/comments/<id>` to:

```markdown
{{inputs.bot_marker}} Review complete — <VERDICT> · <blocking> blocking, <suggestion> suggestions. See the submitted review below.
<!-- daimon:review-prs:<headSha> -->
```

If you cannot complete or submit the review, edit the pickup comment to say that
the review could not be completed, include a brief reason, and that it will be
retried. Do not leave a stale “Reviewing” notice, and do not record the PR as
reviewed in state.

## 3. Review each PR

1. Read the diff (`gh pr diff <number>`).
2. **Check intent.** If the PR references a work item in one of your configured
   sources — see **Source** below for how items are identified and read (typically
   an id or tracker URL in the title or body) — look it up and review the diff
   against its description and acceptance criteria, flagging scope gaps and unmet
   criteria, not only code defects. Treat every source as **read-only**: only read
   the item; never comment on, label, or transition it. If no Source section
   appears below, no source is configured — just review the diff.
3. Check it against the repository's conventions and any rules files in the repo.
4. Identify correctness bugs, security issues, and clear quality problems. Prefer
   a few high-confidence findings over many speculative ones. Tag each finding as
   **Blocking** or **Suggestion** (see the severity tiers in **Output
   conventions** below) — this drives the verdict in §5.

## 4. Classify risk

- **INERT** — every change is copy / strings / comments / markdown / test-only:
  no logic, imports, config, or schema.
- **HIGH** — the diff touches a sensitive area: any changed path
  (`gh pr diff <n> --name-only`) matching `{{inputs.high_risk_globs}}` (auth,
  payments, migrations, infra, secrets). Err toward not-HIGH; HIGH is the
  exception, for changes where a human sign-off genuinely adds value beyond
  automated checks.
- **LOW / MEDIUM** — everything else.

## 5. Cast one review decision

Submit **exactly one** review per PR (`gh pr review`, or the reviews API for
inline comments). Post **one inline comment per finding** — Blocking and
Suggestion alike — each tagged with its tier (see **Output conventions** below for
the finding shape). Every comment is prefixed with `{{inputs.bot_marker}}` so
reply-to-pr-comments can pick up responses. Re-resolve any earlier comment the
author has since fixed.

The verdict is gated on `{{inputs.review_mode}}`:

- **`comment`** — always `COMMENT`, whatever the findings. Never APPROVE or
  REQUEST_CHANGES. (Review-only mode.)
- **`request_changes`**:
  - Any **Blocking** finding → `REQUEST_CHANGES`.
  - No Blocking finding (clean, or Suggestions only) → `COMMENT`.
- **`approve`** (full ladder):
  - Any **Blocking** finding → `REQUEST_CHANGES`.
  - No Blocking, but **Suggestions** exist, risk INERT/LOW/MEDIUM → `APPROVE`; the
    suggestions ride along as non-blocking inline followups (the body says so).
  - No Blocking, Suggestions exist, risk **HIGH** → `COMMENT` (human sign-off).
  - Clean + HIGH → `COMMENT`: `Automated review — no rule violations found.
    HIGH-risk change; human approval recommended. Verify: <areas>.`
  - Clean + INERT/LOW/MEDIUM → `APPROVE` with a note on what's good.

### Review body

Write the body per `{{inputs.verbosity}}`:

- **`compact`** — a single ≤140-char line summarizing the verdict and finding
  counts.
- **`full`** — a structured body:

  ```markdown
  {{inputs.bot_marker}} ## PR Review: #<n> — <title>

  **Summary:** <2–3 sentences: what the PR does, what area it touches, key changes.>

  <files reviewed> · risk: <INERT|LOW|MEDIUM|HIGH> · <blocking> blocking, <suggestion> suggestions

  ### Findings

  | # | Severity | File | Issue |
  |---|----------|------|-------|
  | 1 | Blocking | `path:line` | [<category>] <problem> |
  | 2 | Suggestion | `path:line` | [<category>] <problem> |

  <Below the table, expand each finding with its full description and fix block —
  the same content as the inline comments.>
  ```

  On a clean review, replace the table with a single `Clean — no findings.` line.
  Add a `### Resolved without fix` section (one line per thread: `path:line —
  original concern — why unaddressed`) only when re-resolving prior comments.

## 6. Finish

Record each acted-on PR as `{number, headSha, verdict}` with `daimon state set`.
Keep the summary short: each PR, its verdict, and its blocking/suggestion counts.
