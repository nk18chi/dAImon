---
name: dependency-reviewer
description: Triage dependency-bot PRs — auto-merge only low-risk bumps, and leave everything risky with a summary for a human.
---

# dependency-reviewer

Triage open dependency-update PRs and act on each. You run inside the target
repo, so `gh` targets it automatically. This is **unattended** — never use
AskUserQuestion and never stop with "waiting on permission"; you run with
permissions skipped. The core rule: **auto-merge only genuinely low-risk bumps;
everything else gets a risk summary and waits for a human.**

## 1. Discover

Find open PRs from the dependency bot `{{inputs.bot_author}}`:

```bash
gh pr list --author "{{inputs.bot_author}}" --state open \
  --json number,title,headRefName,headRefOid,mergeable,labels,statusCheckRollup,url
```

Your durable record is the JSON array from `daimon state get`
(`[{number, headSha, action}]`). Read it first and skip any PR whose number +
head SHA you have already recorded — a bump left for a human must not re-trigger
every run. Write back every PR you act on this run.

## 2. Classify each PR

For each not-yet-handled PR, determine two things:

1. **Bump level.** Parse the updated package and version range from the title
   (Dependabot: `Bump <pkg> from <X> to <Y>`, or `chore(deps): bump <pkg> …`; a
   grouped PR updates several — treat the group at the **highest** level and
   **most risky** package in it). Compare `X`→`Y` as semver:
   `major` (X.*.* changed), `minor`, or `patch`.
2. **CI state.** Green only if `statusCheckRollup` has checks and none are
   failing/pending.

## 3. Risk gate — may this PR auto-merge?

A PR is **auto-mergeable** only when ALL hold:

- Its bump level is in `{{inputs.automerge_levels}}` (so a `major` bump never
  qualifies).
- No updated package matches `{{inputs.high_risk_packages}}` (auth, session,
  crypto, and framework/runtime cores are deliberately excluded — a bump there
  can change behavior in ways CI won't catch).
- `mergeable` is not `CONFLICTING`.
- CI is green — required when `{{inputs.require_green}}` is true.
- The diff is confined to dependency manifests / lockfiles
  (`package.json`, `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`,
  `requirements*.txt`, `poetry.lock`, `go.mod`, `go.sum`, `Cargo.toml`,
  `Cargo.lock`, etc.). Check with `gh pr diff <n> --name-only`; unexpected source
  churn disqualifies it.

If any condition fails, the PR is **review-only** — never merge it.

## 4. Act

**Auto-mergeable →** approve and merge:

```bash
gh pr review <n> --approve --body "{{inputs.bot_marker}} Low-risk <level> bump of <pkg> — CI green, manifest-only. Auto-merging."
gh pr merge <n> --{{inputs.merge_method}} --auto
```

**Review-only →** post exactly one comment (do not merge, do not approve), then
leave it. State the specific reason a human is needed:

```markdown
{{inputs.bot_marker}} ## Dependency review: #<n> — <pkg> <X> → <Y>

**Level:** <patch|minor|major> · **CI:** <green|failing|pending> · **Risk:** <why held>

<One or two sentences: which rule held it — high-risk package, major bump,
non-manifest changes, red/pending CI, or conflict — and what a human should check
before merging (changelog/breaking-changes link if you can find it).>
```

Re-post nothing you already said on an earlier run for the same head SHA.

## 5. Finish

Record each acted-on PR as `{number, headSha, action}` (`action` = `merged` or
`held`) with `daimon state set`. Keep the summary short: one line per PR — its
package, level, and what you did.
