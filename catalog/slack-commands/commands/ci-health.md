---
name: ci-health
match: ci-health
mutating: false
description: Default-branch CI health — recent run outcomes and what's failing.
---

1. Resolve the default branch (`gh repo view --json defaultBranchRef`),
   then `gh run list --branch <default> --limit 15 --json displayTitle,conclusion,url,createdAt`.
2. Compute: success rate over those runs, current streak (consecutive
   passes or fails from the newest), and for the most recent failure pull
   the headline failing job (`gh run view <id> --log-failed`, first FAIL
   line only — don't dump logs).
3. Reply one-liner first — `<default> CI: N/15 green, streak: X` — then, only
   if something is red, a bullet per distinct failure: run title, failing
   job, one-clause cause, labeled run link.
