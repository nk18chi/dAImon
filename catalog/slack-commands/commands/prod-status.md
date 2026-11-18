---
name: prod-status
match: prod-status
mutating: false
description: What shipped to production recently — merged PRs and the default branch's deploy state.
---

Assumes the continuous-deployment convention: merges to the default branch
deploy to production via CI. If this repo deploys differently, adapt or
override this plugin locally.

Arguments: optional window — `today` (default), `yesterday`, or `Nd`.

1. `gh pr list --state merged --limit 50` filtered to the window.
2. `gh run list --branch <default branch> --limit 5` — the newest completed
   run's conclusion is prod's deploy state; note an in-progress deploy if
   one is running.
3. Reply: lead line `prod deploy <conclusion> ([run](https://run-link))`, then merged
   PRs as ticket-led bullets grouped by scope. If nothing merged in the
   window, say so in one line.
