#!/usr/bin/env bash
# Gate for review-trigger: launch when one of your open PRs sits on a commit that
# no reviewer has reviewed.
#
# This exists because two things are true at once. ACR never re-reviews a PR you
# authored on its own initiative (poller.ts: `if (isOwnPr) return false`), and the
# tools that fix review feedback — Claude Code Desktop's auto-fix, or a hand push
# — do not ask for a new review after pushing. So the head moves, every round on
# file describes replaced code, and the PR goes quiet: not approved, not blocked,
# just unseen. Nothing anywhere notices.
#
# One source, deliberately. Unlike acr-fixer this daemon does not read findings,
# fix anything, or push — so "is there an open finding" is none of its business.
# The only question is whether the current commit has been looked at, and by whom.
#
# "By whom" is the part that is easy to get wrong. Asking whether ANY instance
# reviewed the head leaves your own instance to drift: colleagues' instances
# re-queue themselves, yours never does, so a PR reads as covered while the one
# review you actually control is several commits stale. The check is per
# reviewer for that reason.
#
# There is no CI-status or head-age precondition on purpose. Every stuck PR in
# this system's history came from a gate that correctly found nothing because a
# precondition had quietly removed everything, and the cost of asking early is
# one stale round that the next fire heals. The schedule is the debounce: a burst
# of pushes inside one window is a single head by the time this runs.
#
# Runs inside working_dir, so gh targets the current repo. Fails closed (no gh,
# no auth) to "skip", except where noted in acr_prs_needing_review — an
# unanswerable question there means ask for the review rather than strand the PR.
set -uo pipefail

source "$(dirname "$0")/../../lib/common.sh"
source "$(dirname "$0")/../../profiles/github/lib.sh"
source "$(dirname "$0")/../../profiles/acr/lib.sh"

# Own, open, non-draft PRs. Two ways to opt one out, both honoured here: the
# repo-side label, which tells your teammates too, and `daimon skip
# review-trigger <pr>`, which stays on this machine.
skips="$(load_json_object "$(skips_file review-trigger)")"
prs="$(gh_pr_json --author @me --state open \
  --json number,headRefOid,isDraft,labels \
  | jq -c --arg skip "$DAIMON_INPUT_SKIP_LABEL" --argjson skips "$skips" '
      [ .[]
        | select((.isDraft | not)
                 and ([.labels[].name] | index($skip) == null)
                 and ($skips[.number | tostring] | not)) ]
    ' 2>/dev/null)"
[ -n "$prs" ] || prs='[]'

seen="$(load_seen_state "$(state_file review-trigger)")"

# Deduped on headSha, which is what stops it asking again every twenty minutes
# while a review sits queued. A new push produces a new head and asks again.
behind="$(acr_reviewers_behind_head "$prs" "$seen")"

printf '%s' "$behind" | jq -e 'length > 0' >/dev/null
