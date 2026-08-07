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

# acr_under_round_cap <actionable-json> <max-round> -> the same array with PRs
# whose every open round is past the cap dropped ([] on failure). The cap is per
# reviewer: an instance stuck at round 9 is parked, but a second instance's round
# 1 on the same PR is fresh work and still keeps that PR in scope.
acr_under_round_cap() {
  printf '%s' "$1" | jq -c --argjson max "${2:-0}" '
    [ .[] | select([ .rounds[]? | select(.round <= $max) ] | length > 0) ]
  ' 2>/dev/null || printf '[]'
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
