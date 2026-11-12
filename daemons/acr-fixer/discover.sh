#!/usr/bin/env bash
# Gate for acr-fixer: launch when ACR has published a non-approve verdict on the
# commit one of your open PRs is on right now, and that verdict hasn't been acted
# on yet. Deliberately precise rather than coarse — this daemon commits and
# pushes, so it should not wake up on a PR it has nothing to do to.
#
# ACR reviews your own PRs as a plain COMMENT (GitHub won't let an author
# request changes on their own PR), so `reviewDecision` is always null here and
# the verdict has to be read off the round comment itself — out of its <details>
# payload block, not the line-1 envelope, which does not carry one. See
# profiles/acr/lib.sh.
#
# Three sources, in descending order of precision:
#   1. an open ACR round      — the contract; ids, verdicts, a reply protocol
#   2. a marked prose review  — a known format with none of the above
#   3. new comment activity   — anything else that arrived and has not been read
# ACR is the one to act on when present. The others exist so that a reviewer we
# cannot parse is still noticed rather than silently dropped.
#
# Runs inside working_dir, so gh targets the current repo. Fails closed (no gh,
# no auth, no ACR comments) to "skip".
set -uo pipefail

source "$(dirname "$0")/../../lib/common.sh"
source "$(dirname "$0")/../../profiles/github/lib.sh"
source "$(dirname "$0")/../../profiles/acr/lib.sh"

# Own, open, non-draft PRs — the set ACR reviews. Two ways to opt one out, both
# honoured here so the exclusion holds for every source below rather than for
# whichever one happens to look first: the repo-side label, which tells your
# teammates too, and `daimon skip acr-fixer <pr>`, which stays on this machine.
skips="$(load_json_object "$(skips_file acr-fixer)")"
prs="$(gh_pr_json --author @me --state open \
  --json number,headRefOid,isDraft,labels \
  | jq -c --arg skip "$DAIMON_INPUT_SKIP_LABEL" --argjson skips "$skips" '
      [ .[]
        | select((.isDraft | not)
                 and ([.labels[].name] | index($skip) == null)
                 and ($skips[.number | tostring] | not)) ]
    ' 2>/dev/null)"
[ -n "$prs" ] || prs='[]'

seen="$(load_seen_state "$(state_file acr-fixer)")"

# Park anything past max_rounds: a PR that has not converged by then needs a
# human, and re-firing on it burns a run every cycle without changing anything.
# The cap is per reviewer, because round numbers are per-instance — a second
# instance's round 1 on a PR you are already at round 5 with is fresh work, not
# a stalled loop.
# A per-PR override (`daimon rounds acr-fixer <pr> <max>`) loosens the cap for one
# PR you are watching, without raising it for everything that runs overnight.
caps="$(load_json_object "$(round_caps_file acr-fixer)")"

acr_open="$(acr_under_round_cap \
  "$(acr_actionable_prs "$prs" "$seen")" "$DAIMON_INPUT_MAX_ROUNDS" "$caps")"

# Second source: any CHANGES_REQUESTED review at the current head that has not
# been dispositioned, whatever its format — a colleague's ACR, another tool, or a
# person. No marker filter here on purpose: whether the skill can parse a review
# is a separate question from whether that review is holding the PR, and a human
# pressing "request changes" blocks just as hard as a bot does. The skill uses
# {{inputs.prose_review_marker}} to decide how to READ one; the gate only decides
# whether one is outstanding. Dedup is on the GitHub review id.
prose_open="$(gh_unhandled_blocking_reviews "$prs" "$seen" "")"

# Catch-all: any comment activity past the last recorded watermark. Not every
# reviewer speaks acr:v1 — a colleague's ACR may post findings without a round
# event, a human may just leave a note — and none of that should be invisible
# merely because its shape is unfamiliar. The skill decides what, if anything,
# it means; the gate only notices that something arrived.
new_comments="$(gh_prs_with_new_comments "$prs" "$seen")"

# Fourth source, and the one that unsticks a PR nothing else can see: a head with
# no complete round on it at all. ACR does not re-review your own PRs on its own,
# so a hand push leaves every round stale and the PR invisible to all three checks
# above. Here the work is to ASK for the review, not to fix anything.
needs_review="$(acr_prs_needing_review "$prs" "$seen")"

printf '%s\n%s\n%s\n%s' "$acr_open" "$prose_open" "$new_comments" "$needs_review" \
  | jq -se 'map(length) | add > 0' >/dev/null
