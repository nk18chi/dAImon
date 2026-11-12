---
name: reply-to-pr-comments
description: Respond to replies on your bot comments on GitHub PRs, and re-trigger review when feedback is addressed.
---

# reply-to-pr-comments

Respond to anyone who replied to comments you previously posted on a GitHub pull
request. You run inside the target repo, so `gh` targets it automatically.

## 1. Discover

Find comment threads where:

- a comment you authored carries the bot marker `{{inputs.bot_marker}}`, and
- a reply from **someone other than you** appeared after your last comment in that
  thread. "You" is your own GitHub login (`gh api user --jq .login`); a reply from
  any other login counts, whether human or another bot. (Comparing against your
  login also stops you replying to your own bot comments.)

Track the last processed comment id per thread in your state (JSON, via
`daimon state get`/`set`) so re-runs only pick up genuinely new replies.

## 2. Respond to each thread

For every thread with a new reply:

1. Read the full thread for context.
2. If the reply asks a question or requests a change, address it directly — make
   the change if it is within scope, or explain clearly why not.
3. Post your response, prefixed with the bot marker `{{inputs.bot_marker}}`, opening
   with the intent prefix from the reply taxonomy in **Output conventions** below —
   `Fixed — …`, `Acknowledged — …`, or `Respectfully disagree — …`. Detail follows
   `{{inputs.verbosity}}`: `full` — when you made a change, name the files/changes
   touched and give a brief rationale; `compact` — a terse one-line outcome.
   **Timing:** a reply that claims a code change is posted only *after* the commit
   is pushed; explanation-only replies post immediately.

## 3. Re-trigger review when a finding is addressed

If the reply is on one of your `{{inputs.bot_marker}}` **code-review** comments
(a review finding) and it indicates the finding was addressed, disputes it, or
asks for a re-review — **and** the author has not pushed new commits (a new commit
re-triggers review-prs on its own) — clear that PR's entry from review-prs's state
so it re-reviews and re-decides at the current head:

```bash
cur="$(daimon state get review-prs)"
[ -n "$cur" ] && printf '%s' "$cur" | jq 'map(select(.number != <N>))' | daimon state set review-prs
```

On its next run (every 60s) review-prs sees the PR as unreviewed and posts an
updated `APPROVE` / `REQUEST_CHANGES`. Don't do this for purely conversational
replies (thanks, acknowledgements) — only when the verdict could actually change.

## 4. Finish

Write the latest processed comment id per thread back with `daimon state set`.
Summarize how many threads you replied to and any PRs you queued for re-review.
