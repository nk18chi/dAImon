#!/usr/bin/env bash
# Shared helpers for the GitHub source profile: PR queries and seen-state loading
# for discovery gates. Pure bash + gh/jq — sourced by a daemon's discover.sh.
# Every helper fails closed (no gh, no auth, bad json) to the "no work" answer.

# gh_pr_json <gh-pr-list-args...> -> a JSON array on stdout ([] on none/failure).
gh_pr_json() {
  local out
  out="$(gh pr list "$@" 2>/dev/null)"
  [ -n "$out" ] && printf '%s' "$out" || printf '[]'
}

# gh_pr_count <gh-pr-list-args...> -> integer count of matching PRs (0 on failure).
gh_pr_count() {
  gh pr list "$@" --json number --jq 'length' 2>/dev/null || echo 0
}

# gh_search_pr_count <gh-search-prs-args...> -> integer count (0 on failure).
gh_search_pr_count() {
  gh search prs "$@" --json number --jq 'length' 2>/dev/null || echo 0
}

# gh_pr_reviews <pr-number> -> JSON array of the PR's formal reviews ([] on
# failure). Uses the REST endpoint rather than `gh pr view --json latestReviews`,
# which returns an empty commit oid — and the commit a review was submitted
# against is the whole point of asking.
gh_pr_reviews() {
  local out
  out="$(gh api "repos/{owner}/{repo}/pulls/$1/reviews" --paginate --slurp 2>/dev/null)" \
    || { printf '[]'; return; }
  printf '%s' "$out" \
    | jq -c 'if type != "array" then [] elif (.[0]? | type) == "array" then add else . end' 2>/dev/null \
    || printf '[]'
}

# gh_blocking_reviews <pr-number> <head-sha> [body-marker] -> JSON array of
# {reviewer, reviewId} for each author whose latest non-dismissed review is
# CHANGES_REQUESTED and was submitted against <head-sha> ([] on failure).
#
# <body-marker> narrows to one format when given; an empty marker matches every
# review, which is the right default for a gate. Whether a daemon can *parse* a
# review is a separate question from whether that review is holding the PR: a
# human's "request changes" blocks just as hard as a bot's, and filtering it out
# because its shape is unfamiliar leaves the PR stuck with nobody looking.
#
# Dismissed reviews are dropped first — GitHub keeps them in the list, but they
# no longer block anything.
gh_blocking_reviews() {
  gh_pr_reviews "$1" | jq -c --arg head "$2" --arg marker "${3:-}" '
    [ .[]? | select(.state != "DISMISSED") ]
    | group_by(.user.login)
    | map(sort_by(.submitted_at) | last)
    | [ .[]
        | select(.state == "CHANGES_REQUESTED")
        | select(.commit_id == $head)
        | select((.body // "") | contains($marker))
        | { reviewer: .user.login, reviewId: .id } ]
  ' 2>/dev/null || printf '[]'
}

# gh_comment_watermark <pr-number> -> {issue, inline, review} of the highest
# comment id seen on each surface ({"issue":0,"inline":0,"review":0} on failure).
#
# A watermark rather than a count: a deleted comment lowers a count and the next
# one restores it, so a count can return to a value it already had and hide
# everything that happened in between. Ids only ever increase.
#
# Three surfaces because GitHub keeps three separate id sequences, and a reviewer
# may use any of them — a top-level comment, an inline note on the diff, or a
# formal review. Comparing across them would be meaningless, so they stay apart.
gh_comment_watermark() {
  local pr="$1" issue inline review
  issue="$(gh api "repos/{owner}/{repo}/issues/$pr/comments" --paginate --slurp 2>/dev/null \
    | jq -c 'if type != "array" then [] elif (.[0]? | type) == "array" then add else . end
             | ([ .[]?.id ] | max) // 0' 2>/dev/null)" || issue=0
  inline="$(gh api "repos/{owner}/{repo}/pulls/$pr/comments" --paginate --slurp 2>/dev/null \
    | jq -c 'if type != "array" then [] elif (.[0]? | type) == "array" then add else . end
             | ([ .[]?.id ] | max) // 0' 2>/dev/null)" || inline=0
  review="$(gh_pr_reviews "$pr" | jq -c '([ .[]?.id ] | max) // 0' 2>/dev/null)" || review=0
  jq -cn --argjson i "${issue:-0}" --argjson n "${inline:-0}" --argjson r "${review:-0}" \
    '{issue: $i, inline: $n, review: $r}' 2>/dev/null \
    || printf '{"issue":0,"inline":0,"review":0}'
}

# gh_prs_with_new_comments <prs-json> <seen-json> -> JSON array of
# {number, headSha, watermark} for PRs carrying comment activity past what was
# last recorded ([] on failure).
#
# This is the catch-all behind the format-specific paths: it does not care who
# commented or in what shape, only that something arrived that has not been read.
#
# A PR with **no** recorded watermark is NOT actionable. There is no baseline, so
# there is no change to detect — and treating "never seen" as "new" makes the
# gate fire on every PR on every run, forever, which is what happened when the
# skill stopped recording watermarks. Failing closed costs a delayed pickup of an
# unparseable review; failing open costs a permanent launch loop. The ACR and
# prose paths are unaffected either way.
gh_prs_with_new_comments() {
  local prs="$1" seen="${2:-[]}" out='[]' num head hit
  while IFS=$'\t' read -r num head; do
    [ -n "$num" ] || continue
    hit="$(gh_comment_watermark "$num" | jq -c \
      --argjson seen "$seen" --arg num "$num" --arg head "$head" '
        . as $now
        | ($num | tonumber) as $n
        | ([ $seen[] | select(.number? == $n) | .watermark? // empty ] | last) as $was
        | if $was == null then empty
          elif ($now.issue  > ($was.issue  // 0))
            or ($now.inline > ($was.inline // 0))
            or ($now.review > ($was.review // 0))
          then { number: $n, headSha: $head, watermark: $now }
          else empty end
      ' 2>/dev/null)" || hit=''
    [ -n "$hit" ] || continue
    out="$(printf '%s' "$out" | jq -c --argjson o "$hit" '. + [$o]' 2>/dev/null)" || out='[]'
  done < <(printf '%s' "$prs" | jq -r '.[]? | "\(.number)\t\(.headRefOid)"' 2>/dev/null)
  printf '%s' "$out"
}

# gh_unhandled_blocking_reviews <prs-json> <seen-json> <marker> -> JSON array of
# {number, headSha, reviewer, reviewId} not yet recorded in <seen-json> ([] on
# failure). Dedup is on the GitHub review id, which is stable and never reused —
# so unlike a content hash, re-wording a finding does not resurface it.
gh_unhandled_blocking_reviews() {
  local prs="$1" seen="${2:-[]}" marker="$3" out='[]' num head hit
  while IFS=$'\t' read -r num head; do
    [ -n "$num" ] || continue
    hit="$(gh_blocking_reviews "$num" "$head" "$marker" | jq -c \
      --argjson seen "$seen" --arg num "$num" --arg head "$head" '
        [ .[]
          | { number: ($num | tonumber), headSha: $head,
              reviewer: .reviewer, reviewId: .reviewId }
          | select(. as $r | ($seen | any(.reviewId? == $r.reviewId)) | not) ]
      ' 2>/dev/null)" || hit='[]'
    out="$(printf '%s' "$out" | jq -c --argjson h "${hit:-[]}" '. + $h' 2>/dev/null)" || out='[]'
  done < <(printf '%s' "$prs" | jq -r '.[]? | "\(.number)\t\(.headRefOid)"' 2>/dev/null)
  printf '%s' "$out"
}
