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
# Runs inside working_dir, so gh targets the current repo. Fails closed (no gh,
# no auth, no ACR comments) to "skip".
set -uo pipefail

source "$(dirname "$0")/../../lib/common.sh"
source "$(dirname "$0")/../../profiles/github/lib.sh"
source "$(dirname "$0")/../../profiles/acr/lib.sh"

# Own, open, non-draft PRs — the set ACR reviews. Drop any opted out by label.
prs="$(gh_pr_json --author @me --state open \
  --json number,headRefOid,isDraft,labels \
  | jq -c --arg skip "$DAIMON_INPUT_SKIP_LABEL" '
      [ .[] | select((.isDraft | not) and ([.labels[].name] | index($skip) == null)) ]
    ' 2>/dev/null)"
[ -n "$prs" ] || prs='[]'

seen="$(load_seen_state "$(state_file acr-fixer)")"

# Park anything past max_rounds: a PR that has not converged by then needs a
# human, and re-firing on it burns a run every cycle without changing anything.
# The cap is per reviewer, because round numbers are per-instance — a second
# instance's round 1 on a PR you are already at round 5 with is fresh work, not
# a stalled loop.
acr_under_round_cap "$(acr_actionable_prs "$prs" "$seen")" "$DAIMON_INPUT_MAX_ROUNDS" \
  | jq -e 'length > 0' >/dev/null
