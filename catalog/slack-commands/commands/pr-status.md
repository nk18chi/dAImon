---
name: pr-status
match: pr-status
mutating: false
description: Open PRs with review + CI state (this machine's owner by default; `pr-status all` for everyone's).
---

Arguments: optional `all` — everyone's open PRs instead of just the
machine owner's.

1. `gh pr list --state open --author "@me" --json number,title,url,isDraft,reviewDecision,statusCheckRollup`
   (drop `--author` for `all`; keep `--limit 30`).
2. Reply one bullet per PR, ticket-led format, each with a compact state
   clause: draft / review: approved|changes-requested|waiting / CI:
   green|red|running. Order: ready-to-merge first, then blocked, then
   drafts. Skip drafts untouched for over a week and note them in one
   trailing italic aside.
