#!/usr/bin/env bats
# Unit tests for the GitHub source profile's gate helpers. gh is mocked, so these
# exercise the fail-closed and pass-through behaviour without network or auth.

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  source "$ROOT/profiles/github/lib.sh"
}

@test "gh_pr_json: gh failure -> []" {
  gh() { return 1; }
  run gh_pr_json --state open
  [ "$output" = "[]" ]
}

@test "gh_pr_json: empty output -> []" {
  gh() { printf ''; }
  run gh_pr_json --state open
  [ "$output" = "[]" ]
}

@test "gh_pr_json: passes json through" {
  gh() { printf '[{"number":7}]'; }
  run gh_pr_json --state open
  [ "$output" = '[{"number":7}]' ]
}

@test "gh_pr_count: gh failure -> 0" {
  gh() { return 1; }
  run gh_pr_count --state open
  [ "$output" = "0" ]
}

@test "gh_pr_count: returns gh's count" {
  gh() { printf '3'; }
  run gh_pr_count --state open
  [ "$output" = "3" ]
}

@test "gh_search_pr_count: gh failure -> 0" {
  gh() { return 1; }
  run gh_search_pr_count --author=@me --state=open
  [ "$output" = "0" ]
}

# --- blocking prose reviews (non-acr:v1 reviewers) --------------------------
#
# A PR can carry reviews from several bots at once. These pin that only the
# marked format is picked up, that a dismissed or stale-commit review is not,
# and that dedup is on the GitHub review id rather than on content.

MARKER="## PR Review: #"

# mk_review <id> <login> <state> <commit> <body>
mk_review() {
  jq -cn --argjson id "$1" --arg login "$2" --arg state "$3" \
        --arg commit "$4" --arg body "$5" --arg at "2026-08-07T$1:00:00Z" \
    '{id: $id, user: {login: $login}, state: $state, commit_id: $commit,
      submitted_at: $at, body: $body}'
}

mk_reviews() {
  local out='[]' r
  for r in "$@"; do
    out="$(printf '%s' "$out" | jq -c --argjson r "$r" '. + [$r]')"
  done
  printf '%s' "$out"
}

@test "gh_pr_reviews: gh failure -> []" {
  gh() { return 1; }
  run gh_pr_reviews 1
  [ "$output" = "[]" ]
}

@test "gh_blocking_reviews: marked CHANGES_REQUESTED at head is blocking" {
  local c
  c="$(mk_reviews "$(mk_review 11 effekt CHANGES_REQUESTED abc123 "$MARKER 4975 blah")")"
  gh() { printf '%s' "$c"; }
  run gh_blocking_reviews 4975 abc123 "$MARKER"
  [ "$(printf '%s' "$output" | jq -r '.[0].reviewer')" = "effekt" ]
  [ "$(printf '%s' "$output" | jq -r '.[0].reviewId')" = "11" ]
}

@test "gh_blocking_reviews: an ACR review is not mistaken for one" {
  local c
  c="$(mk_reviews "$(mk_review 12 assiad CHANGES_REQUESTED abc123 "Round 1: ACR: request_changes")")"
  gh() { printf '%s' "$c"; }
  run gh_blocking_reviews 4975 abc123 "$MARKER"
  [ "$output" = "[]" ]
}

@test "gh_blocking_reviews: a review against an older commit is stale" {
  local c
  c="$(mk_reviews "$(mk_review 13 effekt CHANGES_REQUESTED old999 "$MARKER 4975")")"
  gh() { printf '%s' "$c"; }
  run gh_blocking_reviews 4975 abc123 "$MARKER"
  [ "$output" = "[]" ]
}

@test "gh_blocking_reviews: a dismissed review no longer blocks" {
  local c
  c="$(mk_reviews "$(mk_review 14 effekt DISMISSED abc123 "$MARKER 4975")")"
  gh() { printf '%s' "$c"; }
  run gh_blocking_reviews 4975 abc123 "$MARKER"
  [ "$output" = "[]" ]
}

@test "gh_blocking_reviews: only the author's latest review counts" {
  local c
  c="$(mk_reviews \
    "$(mk_review 15 effekt CHANGES_REQUESTED abc123 "$MARKER 4975")" \
    "$(mk_review 16 effekt APPROVED abc123 "$MARKER 4975")")"
  gh() { printf '%s' "$c"; }
  run gh_blocking_reviews 4975 abc123 "$MARKER"
  [ "$output" = "[]" ]
}

@test "gh_unhandled_blocking_reviews: a recorded review id is skipped" {
  local c
  c="$(mk_reviews "$(mk_review 17 effekt CHANGES_REQUESTED abc123 "$MARKER 4975")")"
  gh() { printf '%s' "$c"; }
  run gh_unhandled_blocking_reviews '[{"number":4975,"headRefOid":"abc123"}]' \
    '[{"number":4975,"reviewId":17,"outcome":"fixed"}]' "$MARKER"
  [ "$output" = "[]" ]
}

@test "gh_unhandled_blocking_reviews: an unrecorded review id is returned" {
  local c
  c="$(mk_reviews "$(mk_review 18 effekt CHANGES_REQUESTED abc123 "$MARKER 4975")")"
  gh() { printf '%s' "$c"; }
  run gh_unhandled_blocking_reviews '[{"number":4975,"headRefOid":"abc123"}]' \
    '[{"number":4975,"reviewId":17,"outcome":"fixed"}]' "$MARKER"
  [ "$(printf '%s' "$output" | jq '.[0].reviewId')" = "18" ]
  [ "$(printf '%s' "$output" | jq '.[0].number')" = "4975" ]
}

@test "gh_unhandled_blocking_reviews: gh failure -> [] (fails closed)" {
  gh() { return 1; }
  run gh_unhandled_blocking_reviews '[{"number":4975,"headRefOid":"abc123"}]' '[]' "$MARKER"
  [ "$output" = "[]" ]
}

# --- comment watermark (the catch-all path) ---------------------------------
#
# The gate's last resort: notice that *something* was said, without needing to
# parse who said it or in what format. These pin that a watermark only ever
# moves forward, that a PR never seen before surfaces, and that a quiet PR does
# not wake the daemon every fire.

# gh returns whichever surface was asked for; route by the path argument.
mock_gh_surfaces() {
  gh() {
    case "$*" in
      *"/issues/"*)      printf '%s' "$MOCK_ISSUE"  ;;
      *"/pulls/"*"/comments"*) printf '%s' "$MOCK_INLINE" ;;
      *"/pulls/"*"/reviews"*)  printf '%s' "$MOCK_REVIEW" ;;
      *) printf '[]' ;;
    esac
  }
}

@test "gh_comment_watermark: highest id per surface" {
  MOCK_ISSUE='[{"id":10},{"id":30},{"id":20}]'
  MOCK_INLINE='[{"id":7}]'
  MOCK_REVIEW='[{"id":99}]'
  mock_gh_surfaces
  run gh_comment_watermark 4967
  [ "$(printf '%s' "$output" | jq '.issue')" = "30" ]
  [ "$(printf '%s' "$output" | jq '.inline')" = "7" ]
  [ "$(printf '%s' "$output" | jq '.review')" = "99" ]
}

@test "gh_comment_watermark: empty surfaces -> zeroes" {
  MOCK_ISSUE='[]'; MOCK_INLINE='[]'; MOCK_REVIEW='[]'
  mock_gh_surfaces
  run gh_comment_watermark 4967
  [ "$(printf '%s' "$output" | jq '.issue')" = "0" ]
}

@test "gh_comment_watermark: gh failure -> zeroes (fails closed)" {
  gh() { return 1; }
  run gh_comment_watermark 4967
  [ "$(printf '%s' "$output" | jq '.review')" = "0" ]
}

# Fails closed with no baseline. Treating "never seen" as "new" made the gate
# fire on every PR on every run — the daemon relaunched every 20 minutes and
# posted a fresh comment each time on a PR it had already parked.
@test "gh_prs_with_new_comments: no recorded watermark is NOT actionable" {
  MOCK_ISSUE='[{"id":10}]'; MOCK_INLINE='[]'; MOCK_REVIEW='[]'
  mock_gh_surfaces
  run gh_prs_with_new_comments '[{"number":4967,"headRefOid":"abc"}]' '[]'
  [ "$output" = "[]" ]
}

@test "gh_prs_with_new_comments: a record without a watermark is NOT actionable" {
  MOCK_ISSUE='[{"id":10}]'; MOCK_INLINE='[]'; MOCK_REVIEW='[]'
  mock_gh_surfaces
  run gh_prs_with_new_comments '[{"number":4967,"headRefOid":"abc"}]' \
    '[{"number":4967,"reviewer":"schlenks","round":9,"outcome":"parked"}]'
  [ "$output" = "[]" ]
}

@test "gh_prs_with_new_comments: nothing new -> quiet" {
  MOCK_ISSUE='[{"id":10}]'; MOCK_INLINE='[{"id":7}]'; MOCK_REVIEW='[{"id":99}]'
  mock_gh_surfaces
  run gh_prs_with_new_comments '[{"number":4967,"headRefOid":"abc"}]' \
    '[{"number":4967,"watermark":{"issue":10,"inline":7,"review":99}}]'
  [ "$output" = "[]" ]
}

@test "gh_prs_with_new_comments: a new inline comment alone wakes it" {
  MOCK_ISSUE='[{"id":10}]'; MOCK_INLINE='[{"id":8}]'; MOCK_REVIEW='[{"id":99}]'
  mock_gh_surfaces
  run gh_prs_with_new_comments '[{"number":4967,"headRefOid":"abc"}]' \
    '[{"number":4967,"watermark":{"issue":10,"inline":7,"review":99}}]'
  [ "$(printf '%s' "$output" | jq '.[0].watermark.inline')" = "8" ]
}

# The xaosaki case: a review posted with no round event. The ACR path cannot see
# it, so the watermark is what keeps it from being silently dropped.
@test "gh_prs_with_new_comments: a review with no round event still surfaces" {
  MOCK_ISSUE='[{"id":10}]'; MOCK_INLINE='[{"id":7}]'; MOCK_REVIEW='[{"id":120}]'
  mock_gh_surfaces
  run gh_prs_with_new_comments '[{"number":4967,"headRefOid":"abc"}]' \
    '[{"number":4967,"watermark":{"issue":10,"inline":7,"review":99}}]'
  [ "$(printf '%s' "$output" | jq '.[0].watermark.review')" = "120" ]
}

@test "gh_prs_with_new_comments: a deleted comment does not lower the mark" {
  MOCK_ISSUE='[{"id":10}]'; MOCK_INLINE='[]'; MOCK_REVIEW='[]'
  mock_gh_surfaces
  run gh_prs_with_new_comments '[{"number":4967,"headRefOid":"abc"}]' \
    '[{"number":4967,"watermark":{"issue":30,"inline":0,"review":0}}]'
  [ "$output" = "[]" ]
}

@test "gh_prs_with_new_comments: gh failure -> [] (fails closed)" {
  gh() { return 1; }
  run gh_prs_with_new_comments '[{"number":4967,"headRefOid":"abc"}]' \
    '[{"number":4967,"watermark":{"issue":1,"inline":1,"review":1}}]'
  [ "$output" = "[]" ]
}

# A human pressing "Request changes" writes no recognisable format at all. The
# gate must still see it — 5174 sat blocked by exactly this while both ACR
# instances approved.
@test "gh_blocking_reviews: an empty marker matches any format" {
  local c
  c="$(mk_reviews "$(mk_review 21 a-human CHANGES_REQUESTED abc123 "please rename this")")"
  gh() { printf '%s' "$c"; }
  run gh_blocking_reviews 5174 abc123 ""
  [ "$(printf '%s' "$output" | jq -r '.[0].reviewer')" = "a-human" ]
}

@test "gh_blocking_reviews: an omitted marker matches any format" {
  local c
  c="$(mk_reviews "$(mk_review 22 a-human CHANGES_REQUESTED abc123 "please rename this")")"
  gh() { printf '%s' "$c"; }
  run gh_blocking_reviews 5174 abc123
  [ "$(printf '%s' "$output" | jq -r '.[0].reviewId')" = "22" ]
}

@test "gh_blocking_reviews: an approval is still not blocking" {
  local c
  c="$(mk_reviews "$(mk_review 23 a-human APPROVED abc123 "lgtm")")"
  gh() { printf '%s' "$c"; }
  run gh_blocking_reviews 5174 abc123 ""
  [ "$output" = "[]" ]
}

# The 5174 shape: two ACR instances approving alongside one blocking review.
@test "gh_blocking_reviews: an approving reviewer does not clear another's block" {
  local c
  c="$(mk_reviews \
    "$(mk_review 24 nk18chi APPROVED abc123 "ACR: approve")" \
    "$(mk_review 25 assiad APPROVED abc123 "ACR: approve")" \
    "$(mk_review 26 effekt CHANGES_REQUESTED abc123 "blocking, correctness")")"
  gh() { printf '%s' "$c"; }
  run gh_blocking_reviews 5174 abc123 ""
  [ "$(printf '%s' "$output" | jq 'length')" = "1" ]
  [ "$(printf '%s' "$output" | jq -r '.[0].reviewer')" = "effekt" ]
}
