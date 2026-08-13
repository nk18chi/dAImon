#!/usr/bin/env bash
# Shared helpers for the ACR source profile: read ACR's review verdict off a PR
# through the `acr:v1` comment contract, for discovery gates. Sourced by a
# daemon's discover.sh. Every helper fails closed (no gh, no auth, no ACR
# comment, bad JSON) to the "no work" answer, so a gate never launches blind.
#
# Why a profile at all: ACR posts a plain COMMENT review — never
# REQUEST_CHANGES — on a PR you authored, because GitHub forbids authors from
# approving or requesting changes on their own PRs. So `reviewDecision` is
# always null there and gates cannot read it. The verdict lives only in the
# line-1 JSON envelope of ACR's round-event comment, which is what these
# helpers parse.

# _acr_ver -> the contract marker to match on line 1 (e.g. "acr:v1").
_acr_ver() { printf '%s' "${DAIMON_INPUT_ACR_VERSION:-acr:v1}"; }

# acr_issue_comments <pr-number> -> JSON array of the PR's top-level comments
# ([] on failure). `gh api --paginate --slurp` yields an array of pages for an
# array endpoint, so flatten one level when that is what came back. Paginating
# matters: comments come back oldest-first, so an unpaginated read on a
# long-running PR returns the oldest 100 and misses every recent round.
acr_issue_comments() {
  local out
  out="$(gh api "repos/{owner}/{repo}/issues/$1/comments" --paginate --slurp 2>/dev/null)" \
    || { printf '[]'; return; }
  printf '%s' "$out" \
    | jq -c 'if type != "array" then [] elif (.[0]? | type) == "array" then add else . end' 2>/dev/null \
    || printf '[]'
}

# acr_round_envelopes <pr-number> -> JSON array of the round-event envelopes on
# the PR ([] on none/failure). Only line 1 of a body is inspected, per the
# contract's parse rule — an envelope quoted further down a comment is ignored.
# Each envelope is tagged with `reviewer` — the login of the account that posted
# the comment. Round numbers are per-instance, not per-PR: when several ACR
# instances review the same PR they each keep their own sequence, so schlenks's
# round 1 and your round 3 can sit on the same commit. Everything downstream
# keys on (reviewer, round) for that reason.
#
# The line-1 envelope carries kind/round/head_sha/final/state_comments — but NOT
# the verdict. That lives in the round comment's `<details>` payload block, so
# both halves have to be read and merged. Envelope keys win on the fields that
# appear in both (it sits at character 0 and survives truncation, which is the
# whole point of the contract's data-before-prose rule).
acr_round_envelopes() {
  acr_issue_comments "$1" | jq -c --arg ver "$(_acr_ver)" '
    def payload:
      (. / "```json") as $parts
      | if ($parts | length) < 2 then {}
        else (($parts | last) / "```" | first | fromjson? // {})
        end;
    [ .[]?
      | (.user.login // "") as $who
      | (.body // "") as $body
      | ($body | split("\n")[0])
      | capture("^<!-- " + $ver + " (?<j>\\{.*\\}) -->\\s*$")?
      | .j | fromjson?
      | select(.kind? == "round")
      | ($body | payload) + . + { reviewer: $who } ]
  ' 2>/dev/null || printf '[]'
}

# acr_latest_rounds <pr-number> -> JSON array holding each reviewer's most
# recent COMPLETE round envelope, one entry per reviewer ([] when there are
# none). `final: false` means ACR failed to update a state document mid-round;
# the contract says treat that round as incomplete and wait, so those are
# filtered out here.
acr_latest_rounds() {
  acr_round_envelopes "$1" | jq -c '
    [ .[] | select(.final == true) ]
    | group_by(.reviewer) | map(sort_by(.round) | last)
  ' 2>/dev/null || printf '[]'
}

# acr_actionable_prs <prs-json> <seen-json> -> JSON array of
# {number, headSha, rounds: [{reviewer, round, verdict}]} for every PR that
# needs a fix pass ([] on failure). <prs-json> is
# `gh pr list --json number,headRefOid` output; <seen-json> is the daemon's
# state record.
#
# A reviewer's round is open when its verdict is not `approve` AND it reviewed
# the commit the PR is on right now. The head_sha check is what makes the loop
# terminate: once a fix is pushed, every round on file is stale, so the gate
# goes quiet until an instance re-reviews the new commit. A PR is actionable
# when at least one reviewer has an open, unhandled round — so one pass can
# clear findings raised by several instances at once.
#
# A `parked` row does not count as seen. Parking means the round-cap stopped the
# work, not that it was done, and the cap is re-evaluated downstream by
# acr_under_round_cap. Were a park to dedup its own round, raising that PR's cap
# would do nothing until a new head arrived — the round would stay suppressed by
# the record of having been refused.
acr_actionable_prs() {
  local prs="$1" seen="${2:-[]}" out='[]' num head hit
  while IFS=$'\t' read -r num head; do
    [ -n "$num" ] || continue
    hit="$(acr_latest_rounds "$num" | jq -c \
      --argjson seen "$seen" --arg num "$num" --arg head "$head" '
        ($num | tonumber) as $n
        | [ .[]
            | select(.verdict != null and .verdict != "approve")
            | select(.head_sha == $head)
            | { reviewer: .reviewer, round: .round, verdict: .verdict }
            | select(. as $r | ($seen | any(
                (.number? == $n) and (.headSha? == $head)
                and (.reviewer? == $r.reviewer) and (.round? == $r.round)
                and (.outcome? != "parked")
              )) | not)
          ] as $open
        | if ($open | length) > 0
          then { number: $n, headSha: $head, rounds: $open }
          else empty end
      ' 2>/dev/null)" || hit=''
    [ -n "$hit" ] || continue
    out="$(printf '%s' "$out" | jq -c --argjson o "$hit" '. + [$o]' 2>/dev/null)" || out='[]'
  done < <(printf '%s' "$prs" | jq -r '.[]? | "\(.number)\t\(.headRefOid)"' 2>/dev/null)
  printf '%s' "$out"
}

# acr_actionable_count <prs-json> <seen-json> -> integer count of PRs (0 on
# failure). Counts PRs, not reviewer-rounds — one PR with three instances'
# findings open is still one unit of work.
acr_actionable_count() {
  acr_actionable_prs "$1" "${2:-[]}" | jq 'length' 2>/dev/null || echo 0
}

# acr_under_round_cap <actionable-json> <max-round> [overrides-json] -> the same
# array with PRs whose every open round is past the cap dropped ([] on failure).
#
# The cap is per reviewer: an instance stuck at round 9 is parked, but a second
# instance's round 1 on the same PR is fresh work and still keeps that PR in
# scope.
#
# <overrides-json> holds hand-set caps for PRs being watched, so one can be
# carried further without loosening the default for everything running
# unattended. Two key shapes, most specific first:
#
#   {"5175:nk18chi": 12}   this reviewer on this PR
#   {"5175": 10}           every reviewer on this PR
#
# The reviewer-level key exists because the cap is per reviewer: your own
# instance being nine rounds deep says nothing about a colleague's that has just
# opened its first.
acr_under_round_cap() {
  local caps="${3:-}"
  [ -n "$caps" ] || caps='{}'
  printf '%s' "$1" | jq -c --argjson max "${2:-0}" --argjson caps "$caps" '
    [ .[]
      | (.number | tostring) as $n
      | select([ .rounds[]?
                 | . as $r
                 | (($caps[$n + ":" + ($r.reviewer // "")])
                    // ($caps[$n]) // $max) as $limit
                 | select($r.round <= $limit) ] | length > 0) ]
  ' 2>/dev/null || printf '[]'
}

# acr_prs_needing_review <prs-json> <seen-json> -> JSON array of {number, headSha}
# for PRs where NO instance has a complete round at the current head ([] on
# failure).
#
# This is the hole every other check falls through. ACR never re-queues a
# completed review of a PR you authored (poller.ts: `if (isOwnPr) return false`),
# so a head that arrives without a re-trigger — a hand push, or one whose trigger
# did not land — is never reviewed. Every round on file is then stale, the
# head_sha check excludes them all, and the PR becomes permanently invisible: not
# approved, not blocked, just unseen.
#
# The answer is not to fix anything. It is to ask for the review that is missing.
# Deduped on headSha so a PR waiting for a queued review is asked once, not once
# every fire.
acr_prs_needing_review() {
  local prs="$1" seen="${2:-[]}" out='[]' num head hit
  while IFS=$'\t' read -r num head; do
    [ -n "$num" ] || continue
    hit="$(acr_latest_rounds "$num" | jq -c \
      --argjson seen "$seen" --arg num "$num" --arg head "$head" '
        ($num | tonumber) as $n
        | if any(.[]; .head_sha == $head) then empty
          elif ($seen | any((.number? == $n) and (.headSha? == $head)
                            and (.outcome? == "review_requested")))
          then empty
          else { number: $n, headSha: $head } end
      ' 2>/dev/null)" || hit=''
    [ -n "$hit" ] || continue
    out="$(printf '%s' "$out" | jq -c --argjson o "$hit" '. + [$o]' 2>/dev/null)" || out='[]'
  done < <(printf '%s' "$prs" | jq -r '.[]? | "\(.number)\t\(.headRefOid)"' 2>/dev/null)
  printf '%s' "$out"
}

# acr_dismissed_approvals <pr-number> -> JSON array of the logins whose most
# recent formal review on the PR was dismissed by GitHub ([] on none/failure).
#
# The one fact the `acr:v1` comments cannot carry. A round says what the reviewer
# concluded; whether GitHub still honours that conclusion is decided afterwards,
# by the repo's `dismiss-stale-reviews` setting, when the next commit lands. The
# round still reads `approve` forever, so a gate trusting it alone believes a PR
# has two approvals while GitHub reads REVIEW_REQUIRED and refuses the merge.
#
# Uses the REST reviews endpoint because DISMISSED is the state being looked for
# and `gh pr view --json latestReviews` keeps it, but the point is the same one
# gh_blocking_reviews makes about commit ids: this is the only view that carries
# the whole per-author history to pick a latest from.
acr_dismissed_approvals() {
  local out
  out="$(gh api "repos/{owner}/{repo}/pulls/$1/reviews" --paginate --slurp 2>/dev/null)" \
    || { printf '[]'; return; }
  printf '%s' "$out" \
    | jq -c 'if type != "array" then [] elif (.[0]? | type) == "array" then add else . end
             | group_by(.user.login // "")
             | [ .[] | sort_by(.submitted_at) | last
                 | select(.state == "DISMISSED") | .user.login ]' 2>/dev/null \
    || printf '[]'
}

# acr_reviewers_behind_head <prs-json> <seen-json> -> JSON array of
# {number, headSha, behind: [login…]} naming, per PR, exactly which instances
# should be asked to review the current commit ([] on failure).
#
# The per-reviewer counterpart to acr_prs_needing_review, and the one that
# matters once a PR has more than one instance on it. That helper asks whether
# ANYONE has reviewed the current head, so a PR stays quiet as long as a single
# colleague's instance keeps up — while YOUR instance, the one that will never
# re-queue itself, drifts further behind with every push. Observed on three of
# five open PRs at once: assiad and schlenks current, nk18chi eight rounds and
# several commits back, and nothing anywhere asking.
#
# Being behind is necessary but not sufficient. An instance whose last verdict
# was `approve` has said its piece, and re-asking it on every push while someone
# else is still holding the PR up buys nothing — the code it objected to is not
# the code being changed. So:
#
#   while any instance is a holdout   ask only the holdouts that are behind,
#                                     plus any approver GitHub has dismissed
#   once every instance has approved  ask the ones still behind (the sweep)
#
# The sweep is not a nicety; it is what makes the deferral safe. A reviewer who
# approved at head 1 has never seen the fixes made at heads 2-5, and without a
# pass against the final commit its approval would be of code that no longer
# exists. Deferring delays that reviewer's objection, it must never lose it.
# Measured over six real PRs this asks 110 reviews where the eager rule asks
# 140 — 21% fewer, and 37% on the twenty-head PR, since the saving grows with
# how long a PR drags on.
#
# The dismissal clause is what stops the deferral latching, and it costs none of
# that saving. On a repo with `dismiss-stale-reviews`, pushing voids every
# approval on the PR — GitHub has already thrown the review away, so there is
# nothing left to defer and re-asking spends nothing. Without it the sweep is
# the only exit, and the sweep needs every instance to have approved: one
# instance that keeps finding minor things (yours, on the PR you are pushing to)
# holds the gate shut forever while the approvers it defers drift arbitrarily
# far behind, and the PR sits at REVIEW_REQUIRED with nobody asked. Live on 5358
# at round 13, with two approvals dismissed eight rounds back.
#
# Narrow on purpose: the release key is GitHub's DISMISSED, not "not currently
# APPROVED". ACR reviews a PR you authored with a plain COMMENT review, since
# GitHub forbids authors approving their own — so an approving instance of your
# own never reads APPROVED, and keying on that would re-ask it on every push and
# give the saving straight back.
#
# `behind` is empty when no instance has reviewed the PR at all. That is still
# actionable — a PR nobody has looked at needs the same request — so the caller
# reads an empty list as "ask everyone" rather than "ask no one".
#
# Dedup is per {number, headSha, reviewer}, not per head. Per head would suppress
# the sweep outright: the holdout's own round arrives at a head already recorded
# as asked, so the moment the PR goes all-approve there would be nothing left
# that could ask the deferred reviewers.
acr_reviewers_behind_head() {
  local prs="$1" seen="${2:-[]}" out='[]' num head rounds dismissed hit
  while IFS=$'\t' read -r num head; do
    [ -n "$num" ] || continue
    rounds="$(acr_latest_rounds "$num")"
    # Only worth the extra call when a deferral is actually in force — a holdout
    # on file, and an approver behind the head for it to hold back. Every other
    # shape reaches the same answer without asking GitHub anything.
    dismissed='[]'
    if printf '%s' "$rounds" | jq -e --arg head "$head" '
         any(.[]; .verdict != "approve")
         and any(.[]; .verdict == "approve" and .head_sha != $head)
       ' >/dev/null 2>&1; then
      dismissed="$(acr_dismissed_approvals "$num")"
    fi
    hit="$(printf '%s' "$rounds" | jq -c \
      --argjson seen "$seen" --argjson dismissed "$dismissed" \
      --arg num "$num" --arg head "$head" '
        ($num | tonumber) as $n
        | . as $rounds
        | [ $rounds[] | select(.head_sha != $head) ] as $behind
        | [ $rounds[] | select(.verdict != "approve") ] as $holdouts
        # Already asked at this head, per reviewer.
        | [ $seen[]
            | select((.number? == $n) and (.headSha? == $head))
            | (.reviewers? // [])[] ] as $asked
        | (if ($rounds | length) == 0 then []
           elif ($holdouts | length) > 0
           then [ $behind[]
                  | select(.verdict != "approve"
                           or (.reviewer | IN($dismissed[])))
                  | .reviewer ]
           else [ $behind[] | .reviewer ]
           end) as $want
        | [ $want[] | select(. as $w | $asked | index($w) | not) ] as $ask
        | if ($rounds | length) == 0
          then (if ($seen | any((.number? == $n) and (.headSha? == $head)))
                then empty else { number: $n, headSha: $head, behind: [] } end)
          elif ($ask | length) == 0 then empty
          else { number: $n, headSha: $head, behind: ($ask | unique) } end
      ' 2>/dev/null)" || hit=''
    [ -n "$hit" ] || continue
    out="$(printf '%s' "$out" | jq -c --argjson o "$hit" '. + [$o]' 2>/dev/null)" || out='[]'
  done < <(printf '%s' "$prs" | jq -r '.[]? | "\(.number)\t\(.headRefOid)"' 2>/dev/null)
  printf '%s' "$out"
}

# acr_unparsed_rounds <pr-number> -> JSON array of complete rounds whose verdict
# could not be read ([] when all parsed). A gate treats a missing verdict as "no
# work", which is the safe default but looks identical to "approved" from the
# outside — so when the gate says nothing to do and you expected otherwise, run
# this first. A non-empty result means the payload block did not parse, not that
# the reviewer was happy.
acr_unparsed_rounds() {
  acr_latest_rounds "$1" | jq -c '
    [ .[] | select(.verdict == null) | { reviewer, round, head_sha } ]
  ' 2>/dev/null || printf '[]'
}

# acr_config -> ACR's own config as JSON, or {} when absent or unreadable. Used
# by doctor, not by gates — a daemon reads ACR's output off GitHub, never its
# local config.
acr_config() {
  local f="${ACR_CONFIG:-$HOME/.acr/config.json}"
  [ -f "$f" ] || { printf '{}'; return; }
  jq -c . "$f" 2>/dev/null || printf '{}'
}

# acr_watches <owner/name> -> 0 when ACR is configured to review that repo. A
# repo ACR does not watch never gets a verdict, so a daemon pointed at it would
# sit silent forever rather than fail — worth surfacing in doctor.
acr_watches() {
  acr_config | jq -e --arg nwo "$1" \
    '[ .repos[]? | "\(.owner)/\(.name)" ] | index($nwo) != null' >/dev/null 2>&1
}

# acr_repo_nwo <dir> -> "owner/name" from that checkout's origin remote (empty
# when there is none). Handles both ssh and https remote forms.
acr_repo_nwo() {
  local url
  url="$(git -C "$1" remote get-url origin 2>/dev/null)" || return 0
  url="${url%.git}"
  url="${url##*:}"
  printf '%s' "$url" | awk -F/ 'NF >= 2 { print $(NF-1) "/" $NF }'
}
