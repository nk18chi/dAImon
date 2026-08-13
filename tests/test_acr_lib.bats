#!/usr/bin/env bats
# Unit tests for the ACR source profile's gate helpers. gh is mocked, so these
# exercise envelope parsing and the fail-closed paths without network or auth.
# The head_sha and already-seen checks are what stop the fix loop from running
# away, so they get explicit coverage here.

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  source "$ROOT/profiles/acr/lib.sh"
}

# mk_comments <login> <envelope-json>... -> a GitHub issue-comments array shaped
# the way ACR posts round events: the envelope on line 1, and the verdict/counts
# in a <details> payload block at the bottom. The two halves are deliberately
# split here — a fixture that puts the verdict on line 1 passes against a parser
# that never reads the payload, which is exactly the bug this suite missed.
#
# Any key in the envelope arg that is NOT an envelope field per the contract
# (verdict, counts, deltas) is moved into the payload block automatically.
mk_comments() {
  local who="$1" out='[]' env i=1
  shift
  for env in "$@"; do
    out="$(printf '%s' "$out" | jq -c --arg env "$env" --arg who "$who" --argjson i "$i" '
      ($env | fromjson) as $all
      | ["kind","pr","round","head_sha","part","of","obsolete","final","error","state_comments","schema_url"] as $envkeys
      | ($all | with_entries(select(.key | IN($envkeys[])))) as $head
      | ($all | with_entries(select(.key | IN($envkeys[]) | not))) as $body
      | . + [{
          id: $i,
          user: { login: $who },
          body: ("<!-- acr:v1 " + ($head | tojson) + " -->\n\n## Round\n\nprose\n\n"
                 + "<details>\n<summary>Expand payload</summary>\n\n```json\n"
                 + ($body | tojson) + "\n```\n</details>")
        }]')"
    i=$((i + 1))
  done
  printf '%s' "$out"
}

# mk_multi <json-array>... -> concatenate comment arrays from several instances.
mk_multi() {
  local out='[]' a
  for a in "$@"; do
    out="$(printf '%s' "$out" | jq -c --argjson a "$a" '. + $a')"
  done
  printf '%s' "$out"
}

# mk_reviews <login> <state>... -> a GitHub pulls-reviews array, one review per
# login/state pair, submitted in the order given. States are GitHub's, not
# ACR's: APPROVED, DISMISSED, COMMENTED, CHANGES_REQUESTED.
mk_reviews() {
  local out='[]' i=1
  while [ "$#" -ge 2 ]; do
    out="$(printf '%s' "$out" | jq -c --arg who "$1" --arg st "$2" --argjson i "$i" '
      . + [{ id: $i, state: $st, user: { login: $who },
             submitted_at: ("2026-08-12T0" + ($i | tostring) + ":00:00Z") }]')"
    shift 2
    i=$((i + 1))
  done
  printf '%s' "$out"
}

# stub_gh <comments-json> [reviews-json] -> mock gh dispatching on the API path,
# so one test can serve both the round comments and the formal reviews. Globals,
# not locals: the mock is called long after this function has returned.
stub_gh() {
  _GH_COMMENTS="$1"
  _GH_REVIEWS="${2:-[]}"
  gh() {
    case "${2:-}" in
      *reviews) printf '%s' "$_GH_REVIEWS" ;;
      *) printf '%s' "$_GH_COMMENTS" ;;
    esac
  }
}

@test "acr_issue_comments: gh failure -> []" {
  gh() { return 1; }
  run acr_issue_comments 1
  [ "$output" = "[]" ]
}

@test "acr_issue_comments: non-json output -> []" {
  gh() { printf 'gh: not logged in'; }
  run acr_issue_comments 1
  [ "$output" = "[]" ]
}

@test "acr_issue_comments: --slurp array-of-pages is flattened" {
  gh() { printf '[[{"id":1,"body":"a"}],[{"id":2,"body":"b"}]]'; }
  run acr_issue_comments 1
  [ "$(printf '%s' "$output" | jq -c '[.[].id]')" = "[1,2]" ]
}

@test "acr_round_envelopes: parses round envelopes, ignores other kinds" {
  local c
  c="$(mk_comments nk18chi '{"kind":"round","round":1,"verdict":"request_changes","final":true}' \
                           '{"kind":"findings","round":1}')"
  gh() { printf '%s' "$c"; }
  run acr_round_envelopes 1
  [ "$(printf '%s' "$output" | jq 'length')" = "1" ]
  [ "$(printf '%s' "$output" | jq -r '.[0].verdict')" = "request_changes" ]
}

@test "acr_round_envelopes: tags each envelope with the posting account" {
  local c
  c="$(mk_comments schlenks '{"kind":"round","round":1,"verdict":"request_changes","final":true}')"
  gh() { printf '%s' "$c"; }
  run acr_round_envelopes 1
  [ "$(printf '%s' "$output" | jq -r '.[0].reviewer')" = "schlenks" ]
}

@test "acr_round_envelopes: an envelope below line 1 is ignored" {
  gh() { printf '%s' '[{"id":1,"user":{"login":"nk18chi"},"body":"quoting a review:\n<!-- acr:v1 {\"kind\":\"round\",\"round\":9} -->"}]'; }
  run acr_round_envelopes 1
  [ "$output" = "[]" ]
}

@test "acr_round_envelopes: no ACR comments -> []" {
  gh() { printf '%s' '[{"id":1,"user":{"login":"someone"},"body":"lgtm"}]'; }
  run acr_round_envelopes 1
  [ "$output" = "[]" ]
}

@test "acr_latest_rounds: takes the highest complete round" {
  local c
  c="$(mk_comments nk18chi '{"kind":"round","round":1,"verdict":"request_changes","final":true,"head_sha":"aaa"}' \
                           '{"kind":"round","round":2,"verdict":"comment","final":true,"head_sha":"bbb"}')"
  gh() { printf '%s' "$c"; }
  run acr_latest_rounds 1
  [ "$(printf '%s' "$output" | jq 'length')" = "1" ]
  [ "$(printf '%s' "$output" | jq -r '.[0].verdict')" = "comment" ]
}

@test "acr_latest_rounds: an incomplete round is skipped" {
  local c
  c="$(mk_comments nk18chi '{"kind":"round","round":1,"verdict":"request_changes","final":true,"head_sha":"aaa"}' \
                           '{"kind":"round","round":2,"verdict":"approve","final":false,"head_sha":"aaa"}')"
  gh() { printf '%s' "$c"; }
  run acr_latest_rounds 1
  [ "$(printf '%s' "$output" | jq -r '.[0].round')" = "1" ]
}

@test "acr_latest_rounds: one entry per instance, each at its own round" {
  local c
  c="$(mk_multi \
    "$(mk_comments nk18chi '{"kind":"round","round":3,"verdict":"approve","final":true,"head_sha":"abc123"}')" \
    "$(mk_comments schlenks '{"kind":"round","round":1,"verdict":"request_changes","final":true,"head_sha":"abc123"}')")"
  gh() { printf '%s' "$c"; }
  run acr_latest_rounds 1
  [ "$(printf '%s' "$output" | jq 'length')" = "2" ]
  [ "$(printf '%s' "$output" | jq -r '[.[] | select(.reviewer == "schlenks")][0].round')" = "1" ]
  [ "$(printf '%s' "$output" | jq -r '[.[] | select(.reviewer == "nk18chi")][0].round')" = "3" ]
}

@test "acr_latest_rounds: no rounds -> []" {
  gh() { printf '%s' '[]'; }
  run acr_latest_rounds 1
  [ "$output" = "[]" ]
}

@test "acr_actionable_prs: non-approve verdict at current head -> actionable" {
  local c
  c="$(mk_comments nk18chi '{"kind":"round","round":2,"verdict":"request_changes","final":true,"head_sha":"abc123"}')"
  gh() { printf '%s' "$c"; }
  run acr_actionable_prs '[{"number":42,"headRefOid":"abc123"}]' '[]'
  [ "$(printf '%s' "$output" | jq -c '.')" = '[{"number":42,"headSha":"abc123","rounds":[{"reviewer":"nk18chi","round":2,"verdict":"request_changes"}]}]' ]
}

@test "acr_actionable_prs: approve verdict -> nothing to do" {
  local c
  c="$(mk_comments nk18chi '{"kind":"round","round":2,"verdict":"approve","final":true,"head_sha":"abc123"}')"
  gh() { printf '%s' "$c"; }
  run acr_actionable_prs '[{"number":42,"headRefOid":"abc123"}]' '[]'
  [ "$output" = "[]" ]
}

@test "acr_actionable_prs: review of an older commit is stale, not actionable" {
  local c
  c="$(mk_comments nk18chi '{"kind":"round","round":2,"verdict":"request_changes","final":true,"head_sha":"old999"}')"
  gh() { printf '%s' "$c"; }
  run acr_actionable_prs '[{"number":42,"headRefOid":"abc123"}]' '[]'
  [ "$output" = "[]" ]
}

@test "acr_actionable_prs: a reviewer-round already handled is skipped" {
  local c
  c="$(mk_comments nk18chi '{"kind":"round","round":2,"verdict":"request_changes","final":true,"head_sha":"abc123"}')"
  gh() { printf '%s' "$c"; }
  run acr_actionable_prs '[{"number":42,"headRefOid":"abc123"}]' \
    '[{"number":42,"headSha":"abc123","reviewer":"nk18chi","round":2,"outcome":"fixed"}]'
  [ "$output" = "[]" ]
}

# hub#5358: schlenks parked at round 7 under the default cap of 5, which wrote
# {5358, f533648, schlenks, 7} into state. Raising the PR's cap to 15 then did
# nothing — the round was suppressed by the record of having been refused, and
# no new head was coming because nobody was fixing anything. A park is the cap
# speaking, and the cap is re-read every fire; only real work is durable.
@test "acr_actionable_prs: a parked round is not treated as handled" {
  local c
  c="$(mk_comments schlenks '{"kind":"round","round":7,"verdict":"request_changes","final":true,"head_sha":"abc123"}')"
  gh() { printf '%s' "$c"; }
  run acr_actionable_prs '[{"number":42,"headRefOid":"abc123"}]' \
    '[{"number":42,"headSha":"abc123","reviewer":"schlenks","round":7,"outcome":"parked"}]'
  [ "$(printf '%s' "$output" | jq '.[0].rounds[0].round')" = "7" ]
}

@test "acr_actionable_prs: a new round on the same commit is actionable again" {
  local c
  c="$(mk_comments nk18chi '{"kind":"round","round":3,"verdict":"request_changes","final":true,"head_sha":"abc123"}')"
  gh() { printf '%s' "$c"; }
  run acr_actionable_prs '[{"number":42,"headRefOid":"abc123"}]' \
    '[{"number":42,"headSha":"abc123","reviewer":"nk18chi","round":2,"outcome":"fixed"}]'
  [ "$(printf '%s' "$output" | jq '.[0].rounds[0].round')" = "3" ]
}

# The hub#4918 case: your instance is done, a colleague's has just raised its
# first round on the same commit. Keyed on the PR alone this looks handled.
@test "acr_actionable_prs: another instance's open round is picked up when yours is clean" {
  local c
  c="$(mk_multi \
    "$(mk_comments nk18chi '{"kind":"round","round":3,"verdict":"approve","final":true,"head_sha":"abc123"}')" \
    "$(mk_comments schlenks '{"kind":"round","round":1,"verdict":"request_changes","final":true,"head_sha":"abc123"}')")"
  gh() { printf '%s' "$c"; }
  run acr_actionable_prs '[{"number":4918,"headRefOid":"abc123"}]' \
    '[{"number":4918,"headSha":"abc123","reviewer":"nk18chi","round":3,"outcome":"fixed"}]'
  [ "$(printf '%s' "$output" | jq '.[0].rounds | length')" = "1" ]
  [ "$(printf '%s' "$output" | jq -r '.[0].rounds[0].reviewer')" = "schlenks" ]
}

# Round numbers collide across instances; only the matching (reviewer, round)
# pair counts as handled.
@test "acr_actionable_prs: a same-numbered round from another instance is not deduped away" {
  local c
  c="$(mk_multi \
    "$(mk_comments nk18chi '{"kind":"round","round":1,"verdict":"request_changes","final":true,"head_sha":"abc123"}')" \
    "$(mk_comments assiad-aldebiyat '{"kind":"round","round":1,"verdict":"request_changes","final":true,"head_sha":"abc123"}')")"
  gh() { printf '%s' "$c"; }
  run acr_actionable_prs '[{"number":4918,"headRefOid":"abc123"}]' \
    '[{"number":4918,"headSha":"abc123","reviewer":"nk18chi","round":1,"outcome":"fixed"}]'
  [ "$(printf '%s' "$output" | jq '.[0].rounds | length')" = "1" ]
  [ "$(printf '%s' "$output" | jq -r '.[0].rounds[0].reviewer')" = "assiad-aldebiyat" ]
}

@test "acr_actionable_prs: two instances open at once are both reported" {
  local c
  c="$(mk_multi \
    "$(mk_comments nk18chi '{"kind":"round","round":2,"verdict":"request_changes","final":true,"head_sha":"abc123"}')" \
    "$(mk_comments schlenks '{"kind":"round","round":1,"verdict":"comment","final":true,"head_sha":"abc123"}')")"
  gh() { printf '%s' "$c"; }
  run acr_actionable_prs '[{"number":4918,"headRefOid":"abc123"}]' '[]'
  [ "$(printf '%s' "$output" | jq 'length')" = "1" ]
  [ "$(printf '%s' "$output" | jq '.[0].rounds | length')" = "2" ]
}

@test "acr_actionable_prs: an approving instance contributes no open round" {
  local c
  c="$(mk_multi \
    "$(mk_comments nk18chi '{"kind":"round","round":2,"verdict":"approve","final":true,"head_sha":"abc123"}')" \
    "$(mk_comments schlenks '{"kind":"round","round":1,"verdict":"request_changes","final":true,"head_sha":"abc123"}')")"
  gh() { printf '%s' "$c"; }
  run acr_actionable_prs '[{"number":4918,"headRefOid":"abc123"}]' '[]'
  [ "$(printf '%s' "$output" | jq '.[0].rounds | length')" = "1" ]
  [ "$(printf '%s' "$output" | jq -r '.[0].rounds[0].reviewer')" = "schlenks" ]
}

@test "acr_actionable_prs: gh failure -> [] (fails closed)" {
  gh() { return 1; }
  run acr_actionable_prs '[{"number":42,"headRefOid":"abc123"}]' '[]'
  [ "$output" = "[]" ]
}

@test "acr_actionable_prs: no PRs -> []" {
  gh() { printf '%s' '[]'; }
  run acr_actionable_prs '[]' '[]'
  [ "$output" = "[]" ]
}

# Regression: the verdict is NOT an envelope field. A parser that reads only
# line 1 returns null here, and null read as "approve" silently reports a PR
# with open findings as clean — which is what hub#4931 exposed.
@test "acr_round_envelopes: verdict comes from the <details> payload, not line 1" {
  gh() { printf '%s' '[{"id":1,"user":{"login":"nk18chi"},"body":"<!-- acr:v1 {\"kind\":\"round\",\"round\":2,\"head_sha\":\"abc123\",\"final\":true} -->\n\n## Round 2 — request_changes\n\n<details>\n<summary>Expand payload</summary>\n\n```json\n{\"verdict\":\"request_changes\",\"counts\":{\"critical\":1}}\n```\n</details>"}]'; }
  run acr_round_envelopes 1
  [ "$(printf '%s' "$output" | jq -r '.[0].verdict')" = "request_changes" ]
  [ "$(printf '%s' "$output" | jq -r '.[0].round')" = "2" ]
  [ "$(printf '%s' "$output" | jq -r '.[0].counts.critical')" = "1" ]
}

@test "acr_round_envelopes: envelope wins over payload on shared keys" {
  gh() { printf '%s' '[{"id":1,"user":{"login":"nk18chi"},"body":"<!-- acr:v1 {\"kind\":\"round\",\"round\":2,\"head_sha\":\"abc123\",\"final\":true} -->\n\n<details>\n\n```json\n{\"verdict\":\"comment\",\"final\":false}\n```\n</details>"}]'; }
  run acr_round_envelopes 1
  [ "$(printf '%s' "$output" | jq -r '.[0].final')" = "true" ]
}

@test "acr_round_envelopes: a round with no payload block yields a null verdict" {
  gh() { printf '%s' '[{"id":1,"user":{"login":"nk18chi"},"body":"<!-- acr:v1 {\"kind\":\"round\",\"round\":2,\"head_sha\":\"abc123\",\"final\":true} -->\n\nprose only"}]'; }
  run acr_round_envelopes 1
  [ "$(printf '%s' "$output" | jq -r '.[0].verdict')" = "null" ]
}

# Fail closed, but visibly: an unreadable verdict must not launch a daemon that
# pushes code, and must not be mistaken for an approval either.
@test "acr_actionable_prs: an unreadable verdict is not actionable" {
  gh() { printf '%s' '[{"id":1,"user":{"login":"nk18chi"},"body":"<!-- acr:v1 {\"kind\":\"round\",\"round\":2,\"head_sha\":\"abc123\",\"final\":true} -->\n\nprose only"}]'; }
  run acr_actionable_prs '[{"number":42,"headRefOid":"abc123"}]' '[]'
  [ "$output" = "[]" ]
}

@test "acr_unparsed_rounds: surfaces the round whose verdict did not parse" {
  gh() { printf '%s' '[{"id":1,"user":{"login":"nk18chi"},"body":"<!-- acr:v1 {\"kind\":\"round\",\"round\":2,\"head_sha\":\"abc123\",\"final\":true} -->\n\nprose only"}]'; }
  run acr_unparsed_rounds 42
  [ "$(printf '%s' "$output" | jq 'length')" = "1" ]
  [ "$(printf '%s' "$output" | jq -r '.[0].reviewer')" = "nk18chi" ]
}

@test "acr_unparsed_rounds: [] when every verdict parsed" {
  local c
  c="$(mk_comments nk18chi '{"kind":"round","round":1,"verdict":"approve","final":true,"head_sha":"abc"}')"
  gh() { printf '%s' "$c"; }
  run acr_unparsed_rounds 42
  [ "$output" = "[]" ]
}

@test "acr_under_round_cap: a PR under the cap is kept" {
  run acr_under_round_cap \
    '[{"number":42,"headSha":"abc","rounds":[{"reviewer":"nk18chi","round":2}]}]' 5
  [ "$(printf '%s' "$output" | jq 'length')" = "1" ]
}

@test "acr_under_round_cap: a PR whose only instance is past the cap is dropped" {
  run acr_under_round_cap \
    '[{"number":42,"headSha":"abc","rounds":[{"reviewer":"nk18chi","round":9}]}]' 5
  [ "$output" = "[]" ]
}

# The cap counts one instance's sequence, not the PR's total review history.
@test "acr_under_round_cap: a fresh instance keeps a PR whose other instance is parked" {
  run acr_under_round_cap \
    '[{"number":4918,"headSha":"abc","rounds":[{"reviewer":"nk18chi","round":9},{"reviewer":"schlenks","round":1}]}]' 5
  [ "$(printf '%s' "$output" | jq 'length')" = "1" ]
}

@test "acr_under_round_cap: malformed input -> []" {
  run acr_under_round_cap 'not json' 5
  [ "$output" = "[]" ]
}

@test "acr_config: missing file -> {}" {
  ACR_CONFIG="$BATS_TEST_TMPDIR/nope.json"
  run acr_config
  [ "$output" = "{}" ]
}

@test "acr_config: invalid json -> {}" {
  ACR_CONFIG="$BATS_TEST_TMPDIR/c.json"
  printf 'not json {' > "$ACR_CONFIG"
  run acr_config
  [ "$output" = "{}" ]
}

@test "acr_watches: a configured repo matches" {
  ACR_CONFIG="$BATS_TEST_TMPDIR/c.json"
  printf '%s' '{"repos":[{"owner":"acme","name":"web"},{"owner":"acme","name":"api"}]}' > "$ACR_CONFIG"
  run acr_watches acme/api
  [ "$status" -eq 0 ]
}

@test "acr_watches: an unconfigured repo does not match" {
  ACR_CONFIG="$BATS_TEST_TMPDIR/c.json"
  printf '%s' '{"repos":[{"owner":"acme","name":"web"}]}' > "$ACR_CONFIG"
  run acr_watches acme/api
  [ "$status" -ne 0 ]
}

@test "acr_watches: no config -> no match" {
  ACR_CONFIG="$BATS_TEST_TMPDIR/nope.json"
  run acr_watches acme/api
  [ "$status" -ne 0 ]
}

@test "acr_repo_nwo: ssh and https remotes both resolve" {
  git() { printf 'git@github.com:acme/api.git'; }
  run acr_repo_nwo /tmp
  [ "$output" = "acme/api" ]
  git() { printf 'https://github.com/acme/api.git'; }
  run acr_repo_nwo /tmp
  [ "$output" = "acme/api" ]
}

@test "acr_repo_nwo: no origin -> empty" {
  git() { return 1; }
  run acr_repo_nwo /tmp
  [ "$output" = "" ]
}

@test "acr_actionable_count: counts the actionable PRs" {
  local c
  c="$(mk_comments nk18chi '{"kind":"round","round":1,"verdict":"comment","final":true,"head_sha":"abc123"}')"
  gh() { printf '%s' "$c"; }
  run acr_actionable_count '[{"number":42,"headRefOid":"abc123"}]' '[]'
  [ "$output" = "1" ]
}

# --- per-PR round-cap overrides ---------------------------------------------
#
# `daimon rounds acr-fixer <pr> <max>` loosens the cap for one PR being watched,
# without raising it for everything running unattended.

@test "acr_under_round_cap: an override carries a PR past the default cap" {
  run acr_under_round_cap \
    '[{"number":4964,"headSha":"abc","rounds":[{"reviewer":"vivanov1410","round":7}]}]' \
    5 '{"4964":12}'
  [ "$(printf '%s' "$output" | jq 'length')" = "1" ]
}

@test "acr_under_round_cap: an override below the round still parks it" {
  run acr_under_round_cap \
    '[{"number":4964,"headSha":"abc","rounds":[{"reviewer":"vivanov1410","round":7}]}]' \
    5 '{"4964":6}'
  [ "$output" = "[]" ]
}

@test "acr_under_round_cap: an override applies only to its own PR" {
  run acr_under_round_cap \
    '[{"number":4964,"headSha":"abc","rounds":[{"reviewer":"a","round":7}]},
      {"number":4975,"headSha":"abc","rounds":[{"reviewer":"a","round":7}]}]' \
    5 '{"4964":12}'
  [ "$(printf '%s' "$output" | jq 'length')" = "1" ]
  [ "$(printf '%s' "$output" | jq '.[0].number')" = "4964" ]
}

@test "acr_under_round_cap: no overrides behaves as before" {
  run acr_under_round_cap \
    '[{"number":4964,"headSha":"abc","rounds":[{"reviewer":"a","round":7}]}]' 5 '{}'
  [ "$output" = "[]" ]
}

@test "acr_under_round_cap: overrides argument is optional" {
  run acr_under_round_cap \
    '[{"number":4964,"headSha":"abc","rounds":[{"reviewer":"a","round":2}]}]' 5
  [ "$(printf '%s' "$output" | jq 'length')" = "1" ]
}

# --- a head nobody has reviewed ---------------------------------------------
#
# The 5175/5180 case: the head moved, every round on file is stale, so all the
# other checks see nothing and the PR goes invisible. ACR will not re-review an
# own PR unprompted, so nothing recovers it without this.

@test "acr_prs_needing_review: no round at the current head is actionable" {
  local c
  c="$(mk_comments nk18chi '{"kind":"round","round":6,"verdict":"request_changes","final":true,"head_sha":"old111"}')"
  gh() { printf '%s' "$c"; }
  run acr_prs_needing_review '[{"number":5175,"headRefOid":"new222"}]' '[]'
  [ "$(printf '%s' "$output" | jq '.[0].number')" = "5175" ]
  [ "$(printf '%s' "$output" | jq -r '.[0].headSha')" = "new222" ]
}

@test "acr_prs_needing_review: a round at the current head is not" {
  local c
  c="$(mk_comments nk18chi '{"kind":"round","round":6,"verdict":"request_changes","final":true,"head_sha":"new222"}')"
  gh() { printf '%s' "$c"; }
  run acr_prs_needing_review '[{"number":5175,"headRefOid":"new222"}]' '[]'
  [ "$output" = "[]" ]
}

@test "acr_prs_needing_review: one instance at head is enough" {
  local c
  c="$(mk_multi \
    "$(mk_comments nk18chi '{"kind":"round","round":6,"verdict":"comment","final":true,"head_sha":"old111"}')" \
    "$(mk_comments assiad '{"kind":"round","round":1,"verdict":"comment","final":true,"head_sha":"new222"}')")"
  gh() { printf '%s' "$c"; }
  run acr_prs_needing_review '[{"number":5175,"headRefOid":"new222"}]' '[]'
  [ "$output" = "[]" ]
}

@test "acr_prs_needing_review: an already-requested head is not asked again" {
  local c
  c="$(mk_comments nk18chi '{"kind":"round","round":6,"verdict":"request_changes","final":true,"head_sha":"old111"}')"
  gh() { printf '%s' "$c"; }
  run acr_prs_needing_review '[{"number":5175,"headRefOid":"new222"}]' \
    '[{"number":5175,"headSha":"new222","outcome":"review_requested"}]'
  [ "$output" = "[]" ]
}

@test "acr_prs_needing_review: a request for an older head does not suppress this one" {
  local c
  c="$(mk_comments nk18chi '{"kind":"round","round":6,"verdict":"request_changes","final":true,"head_sha":"old111"}')"
  gh() { printf '%s' "$c"; }
  run acr_prs_needing_review '[{"number":5175,"headRefOid":"new222"}]' \
    '[{"number":5175,"headSha":"old111","outcome":"review_requested"}]'
  [ "$(printf '%s' "$output" | jq '.[0].number')" = "5175" ]
}

@test "acr_prs_needing_review: a PR with no rounds at all is actionable" {
  gh() { printf '%s' '[]'; }
  run acr_prs_needing_review '[{"number":5180,"headRefOid":"new222"}]' '[]'
  [ "$(printf '%s' "$output" | jq '.[0].number')" = "5180" ]
}

@test "acr_prs_needing_review: gh failure -> actionable (asks for a review)" {
  gh() { return 1; }
  run acr_prs_needing_review '[{"number":5180,"headRefOid":"new222"}]' '[]'
  [ "$(printf '%s' "$output" | jq 'length')" = "1" ]
}

# --- per-reviewer cap overrides ---------------------------------------------
#
# The cap is per reviewer, so an override should be able to be too: your own
# instance nine rounds deep says nothing about a colleague's that just started.

@test "acr_under_round_cap: a reviewer key beats the PR key" {
  run acr_under_round_cap \
    '[{"number":5175,"headSha":"abc","rounds":[{"reviewer":"nk18chi","round":8}]}]' \
    5 '{"5175":6,"5175:nk18chi":12}'
  [ "$(printf '%s' "$output" | jq 'length')" = "1" ]
}

@test "acr_under_round_cap: a reviewer key does not apply to another reviewer" {
  run acr_under_round_cap \
    '[{"number":5175,"headSha":"abc","rounds":[{"reviewer":"schlenks","round":8}]}]' \
    5 '{"5175:nk18chi":12}'
  [ "$output" = "[]" ]
}

@test "acr_under_round_cap: the PR key still covers reviewers without their own" {
  run acr_under_round_cap \
    '[{"number":5175,"headSha":"abc","rounds":[{"reviewer":"schlenks","round":8}]}]' \
    5 '{"5175":10,"5175:nk18chi":12}'
  [ "$(printf '%s' "$output" | jq 'length')" = "1" ]
}

@test "acr_under_round_cap: a reviewer key can be lower than the PR key" {
  run acr_under_round_cap \
    '[{"number":5175,"headSha":"abc","rounds":[{"reviewer":"nk18chi","round":8}]}]' \
    5 '{"5175":12,"5175:nk18chi":6}'
  [ "$output" = "[]" ]
}

# One reviewer over its cap must not drag down another still under theirs.
@test "acr_under_round_cap: a capped reviewer does not park a PR another can still work" {
  run acr_under_round_cap \
    '[{"number":5175,"headSha":"abc","rounds":[
        {"reviewer":"nk18chi","round":20},
        {"reviewer":"schlenks","round":2}]}]' \
    5 '{"5175:nk18chi":6}'
  [ "$(printf '%s' "$output" | jq 'length')" = "1" ]
}

# --- a reviewer behind the head ----------------------------------------------
#
# The per-reviewer counterpart to acr_prs_needing_review, and the case that
# helper is blind to: colleagues' instances re-queue themselves when the head
# moves, yours never does. Two colleagues current and nk18chi eight rounds back
# looks healthy to a per-PR check, and the review you actually control has
# silently stopped happening. Live on 5358, 5331 and 4913 at once.

@test "acr_reviewers_behind_head: a reviewer at an older head is behind" {
  local c
  c="$(mk_comments nk18chi '{"kind":"round","round":11,"verdict":"comment","final":true,"head_sha":"old111"}')"
  gh() { printf '%s' "$c"; }
  run acr_reviewers_behind_head '[{"number":5358,"headRefOid":"new222"}]' '[]'
  [ "$(printf '%s' "$output" | jq '.[0].number')" = "5358" ]
  [ "$(printf '%s' "$output" | jq -r '.[0].behind | join(",")')" = "nk18chi" ]
}

@test "acr_reviewers_behind_head: every reviewer at the head is quiet" {
  local c
  c="$(mk_multi \
    "$(mk_comments nk18chi '{"kind":"round","round":6,"verdict":"approve","final":true,"head_sha":"new222"}')" \
    "$(mk_comments assiad '{"kind":"round","round":1,"verdict":"approve","final":true,"head_sha":"new222"}')")"
  gh() { printf '%s' "$c"; }
  run acr_reviewers_behind_head '[{"number":5358,"headRefOid":"new222"}]' '[]'
  [ "$output" = "[]" ]
}

# The whole reason this helper exists: acr_prs_needing_review returns [] here.
@test "acr_reviewers_behind_head: one instance at head does NOT cover a lagging one" {
  local c
  c="$(mk_multi \
    "$(mk_comments nk18chi '{"kind":"round","round":11,"verdict":"comment","final":true,"head_sha":"old111"}')" \
    "$(mk_comments assiad '{"kind":"round","round":7,"verdict":"approve","final":true,"head_sha":"new222"}')")"
  gh() { printf '%s' "$c"; }
  run acr_reviewers_behind_head '[{"number":5358,"headRefOid":"new222"}]' '[]'
  [ "$(printf '%s' "$output" | jq -r '.[0].behind | join(",")')" = "nk18chi" ]
  run acr_prs_needing_review '[{"number":5358,"headRefOid":"new222"}]' '[]'
  [ "$output" = "[]" ]
}

@test "acr_reviewers_behind_head: only the lagging reviewers are listed" {
  local c
  c="$(mk_multi \
    "$(mk_comments nk18chi '{"kind":"round","round":11,"verdict":"comment","final":true,"head_sha":"old111"}')" \
    "$(mk_comments schlenks '{"kind":"round","round":2,"verdict":"comment","final":true,"head_sha":"old111"}')" \
    "$(mk_comments assiad '{"kind":"round","round":7,"verdict":"approve","final":true,"head_sha":"new222"}')")"
  gh() { printf '%s' "$c"; }
  run acr_reviewers_behind_head '[{"number":5358,"headRefOid":"new222"}]' '[]'
  [ "$(printf '%s' "$output" | jq -r '.[0].behind | sort | join(",")')" = "nk18chi,schlenks" ]
}

# An approval is only ever an approval of the commit it was submitted on.
@test "acr_reviewers_behind_head: an approval at an older head is still behind" {
  local c
  c="$(mk_comments nk18chi '{"kind":"round","round":8,"verdict":"approve","final":true,"head_sha":"old111"}')"
  gh() { printf '%s' "$c"; }
  run acr_reviewers_behind_head '[{"number":5365,"headRefOid":"new222"}]' '[]'
  [ "$(printf '%s' "$output" | jq 'length')" = "1" ]
}

# behind == [] means nobody has reviewed at all, which the skill reads as
# "ask everyone" — not as "nothing to do".
@test "acr_reviewers_behind_head: a PR with no rounds is actionable with an empty list" {
  gh() { printf '%s' '[]'; }
  run acr_reviewers_behind_head '[{"number":5415,"headRefOid":"new222"}]' '[]'
  [ "$(printf '%s' "$output" | jq '.[0].number')" = "5415" ]
  [ "$(printf '%s' "$output" | jq -c '.[0].behind')" = "[]" ]
}

@test "acr_reviewers_behind_head: a reviewer already asked at this head is not asked again" {
  local c
  c="$(mk_comments nk18chi '{"kind":"round","round":11,"verdict":"comment","final":true,"head_sha":"old111"}')"
  gh() { printf '%s' "$c"; }
  run acr_reviewers_behind_head '[{"number":5358,"headRefOid":"new222"}]' \
    '[{"number":5358,"headSha":"new222","outcome":"review_requested","reviewers":["nk18chi"]}]'
  [ "$output" = "[]" ]
}

# A failed trigger still dedups that reviewer: a broken ACR checkout should cost
# one wasted run per push, not one every twenty minutes for as long as it stays
# broken.
@test "acr_reviewers_behind_head: a failed trigger also dedups the reviewer" {
  local c
  c="$(mk_comments nk18chi '{"kind":"round","round":11,"verdict":"comment","final":true,"head_sha":"old111"}')"
  gh() { printf '%s' "$c"; }
  run acr_reviewers_behind_head '[{"number":5358,"headRefOid":"new222"}]' \
    '[{"number":5358,"headSha":"new222","outcome":"trigger_failed","reviewers":["nk18chi"]}]'
  [ "$output" = "[]" ]
}

# Dedup is per reviewer, not per head. Per head would suppress the sweep: the
# holdout's round lands at a head already recorded as asked, so nothing would
# ever be left to ask the deferred reviewers once the PR goes all-approve.
@test "acr_reviewers_behind_head: asking one reviewer does not suppress another at the same head" {
  local c
  c="$(mk_multi \
    "$(mk_comments nk18chi '{"kind":"round","round":11,"verdict":"comment","final":true,"head_sha":"old111"}')" \
    "$(mk_comments schlenks '{"kind":"round","round":2,"verdict":"comment","final":true,"head_sha":"old111"}')")"
  gh() { printf '%s' "$c"; }
  run acr_reviewers_behind_head '[{"number":5358,"headRefOid":"new222"}]' \
    '[{"number":5358,"headSha":"new222","outcome":"review_requested","reviewers":["nk18chi"]}]'
  [ "$(printf '%s' "$output" | jq -r '.[0].behind | join(",")')" = "schlenks" ]
}

# --- deferring reviewers who already approved --------------------------------
#
# An instance whose last verdict was `approve` has said its piece. Re-asking it
# on every push while someone else is still holding the PR up buys nothing: the
# code it objected to is not the code being changed. Measured over six real PRs
# this asks 110 reviews where the eager rule asks 140.

@test "acr_reviewers_behind_head: an approver is not re-asked while a holdout remains" {
  local c
  c="$(mk_multi \
    "$(mk_comments assiad '{"kind":"round","round":4,"verdict":"approve","final":true,"head_sha":"old111"}')" \
    "$(mk_comments schlenks '{"kind":"round","round":5,"verdict":"request_changes","final":true,"head_sha":"old111"}')")"
  gh() { printf '%s' "$c"; }
  run acr_reviewers_behind_head '[{"number":5358,"headRefOid":"new222"}]' '[]'
  [ "$(printf '%s' "$output" | jq -r '.[0].behind | join(",")')" = "schlenks" ]
}

# Two holdouts, one approver: both holdouts go, the approver waits. This is the
# A-approves/B-and-C-reject case.
@test "acr_reviewers_behind_head: every holdout is asked, the approver is not" {
  local c
  c="$(mk_multi \
    "$(mk_comments assiad '{"kind":"round","round":4,"verdict":"approve","final":true,"head_sha":"old111"}')" \
    "$(mk_comments schlenks '{"kind":"round","round":5,"verdict":"request_changes","final":true,"head_sha":"old111"}')" \
    "$(mk_comments nk18chi '{"kind":"round","round":9,"verdict":"comment","final":true,"head_sha":"old111"}')")"
  gh() { printf '%s' "$c"; }
  run acr_reviewers_behind_head '[{"number":5358,"headRefOid":"new222"}]' '[]'
  [ "$(printf '%s' "$output" | jq -r '.[0].behind | sort | join(",")')" = "nk18chi,schlenks" ]
}

# The sweep. Everyone has approved, but two of them approved older commits and
# have never seen the fixes made since. Without this the deferral would turn an
# approval of replaced code into a final answer.
@test "acr_reviewers_behind_head: once all approve, the stale approvers are swept" {
  local c
  c="$(mk_multi \
    "$(mk_comments assiad '{"kind":"round","round":4,"verdict":"approve","final":true,"head_sha":"old111"}')" \
    "$(mk_comments nk18chi '{"kind":"round","round":9,"verdict":"approve","final":true,"head_sha":"old222"}')" \
    "$(mk_comments schlenks '{"kind":"round","round":8,"verdict":"approve","final":true,"head_sha":"new333"}')")"
  gh() { printf '%s' "$c"; }
  run acr_reviewers_behind_head '[{"number":5358,"headRefOid":"new333"}]' '[]'
  [ "$(printf '%s' "$output" | jq -r '.[0].behind | sort | join(",")')" = "assiad,nk18chi" ]
}

# All approved AND all at the current head is the terminal state. Nothing to ask.
@test "acr_reviewers_behind_head: an all-approved PR at one head is finished" {
  local c
  c="$(mk_multi \
    "$(mk_comments assiad '{"kind":"round","round":4,"verdict":"approve","final":true,"head_sha":"new333"}')" \
    "$(mk_comments schlenks '{"kind":"round","round":8,"verdict":"approve","final":true,"head_sha":"new333"}')")"
  gh() { printf '%s' "$c"; }
  run acr_reviewers_behind_head '[{"number":5358,"headRefOid":"new333"}]' '[]'
  [ "$output" = "[]" ]
}

# A holdout sitting ON the current head is not asked — it has seen this commit
# and its findings are the fixer's job. Asking again would just repeat the round.
@test "acr_reviewers_behind_head: a holdout at the current head is left alone" {
  local c
  c="$(mk_multi \
    "$(mk_comments assiad '{"kind":"round","round":4,"verdict":"approve","final":true,"head_sha":"old111"}')" \
    "$(mk_comments schlenks '{"kind":"round","round":5,"verdict":"request_changes","final":true,"head_sha":"new222"}')")"
  gh() { printf '%s' "$c"; }
  run acr_reviewers_behind_head '[{"number":5358,"headRefOid":"new222"}]' '[]'
  [ "$output" = "[]" ]
}

# The sweep must survive the holdout's own round having been asked at this head,
# which is exactly what a per-head dedup would have broken.
@test "acr_reviewers_behind_head: the sweep fires at a head the holdout was asked about" {
  local c
  c="$(mk_multi \
    "$(mk_comments assiad '{"kind":"round","round":4,"verdict":"approve","final":true,"head_sha":"old111"}')" \
    "$(mk_comments schlenks '{"kind":"round","round":8,"verdict":"approve","final":true,"head_sha":"new222"}')")"
  gh() { printf '%s' "$c"; }
  run acr_reviewers_behind_head '[{"number":5358,"headRefOid":"new222"}]' \
    '[{"number":5358,"headSha":"new222","outcome":"review_requested","reviewers":["schlenks"]}]'
  [ "$(printf '%s' "$output" | jq -r '.[0].behind | join(",")')" = "assiad" ]
}

# --- approvals GitHub has already thrown away --------------------------------
#
# The round comment says `approve` forever; whether GitHub still honours it is
# decided afterwards by dismiss-stale-reviews. Deferring on the round alone lets
# the deferral latch: the sweep needs everyone to have approved, so a single
# instance that keeps finding minor things holds the gate shut while the
# approvers it defers drift arbitrarily far behind. Live on 5358 at round 13.

@test "acr_reviewers_behind_head: a dismissed approver is asked despite the holdout" {
  local c
  c="$(mk_multi \
    "$(mk_comments assiad '{"kind":"round","round":4,"verdict":"approve","final":true,"head_sha":"old111"}')" \
    "$(mk_comments schlenks '{"kind":"round","round":5,"verdict":"request_changes","final":true,"head_sha":"old111"}')")"
  stub_gh "$c" "$(mk_reviews assiad DISMISSED)"
  run acr_reviewers_behind_head '[{"number":5358,"headRefOid":"new222"}]' '[]'
  [ "$(printf '%s' "$output" | jq -r '.[0].behind | sort | join(",")')" = "assiad,schlenks" ]
}

# PR 5358 itself. The only holdout sits ON the current head, so it is not behind
# and not asked; both approvers are behind but deferred. Before the dismissal
# clause this whole PR returned [] and the gate never launched.
@test "acr_reviewers_behind_head: a current holdout does not strand dismissed approvers" {
  local c
  c="$(mk_multi \
    "$(mk_comments nk18chi '{"kind":"round","round":13,"verdict":"comment","final":true,"head_sha":"new222"}')" \
    "$(mk_comments schlenks '{"kind":"round","round":8,"verdict":"approve","final":true,"head_sha":"old111"}')" \
    "$(mk_comments assiad '{"kind":"round","round":7,"verdict":"approve","final":true,"head_sha":"old111"}')")"
  stub_gh "$c" "$(mk_reviews schlenks DISMISSED assiad DISMISSED)"
  run acr_reviewers_behind_head '[{"number":5358,"headRefOid":"new222"}]' '[]'
  [ "$(printf '%s' "$output" | jq -r '.[0].behind | sort | join(",")')" = "assiad,schlenks" ]
}

# The saving this rule exists for: an approval GitHub still honours is still
# deferred. A repo without dismiss-stale-reviews behaves exactly as before.
@test "acr_reviewers_behind_head: an approval that still stands is still deferred" {
  local c
  c="$(mk_multi \
    "$(mk_comments assiad '{"kind":"round","round":4,"verdict":"approve","final":true,"head_sha":"old111"}')" \
    "$(mk_comments schlenks '{"kind":"round","round":5,"verdict":"request_changes","final":true,"head_sha":"old111"}')")"
  stub_gh "$c" "$(mk_reviews assiad APPROVED)"
  run acr_reviewers_behind_head '[{"number":5358,"headRefOid":"new222"}]' '[]'
  [ "$(printf '%s' "$output" | jq -r '.[0].behind | join(",")')" = "schlenks" ]
}

# Why the key is DISMISSED and not "anything but APPROVED". ACR reviews a PR you
# authored with a plain COMMENT review, so your own approving instance never
# reads APPROVED — the looser test would re-ask it on every push.
@test "acr_reviewers_behind_head: a COMMENT review is not read as a dismissal" {
  local c
  c="$(mk_multi \
    "$(mk_comments nk18chi '{"kind":"round","round":9,"verdict":"approve","final":true,"head_sha":"old111"}')" \
    "$(mk_comments schlenks '{"kind":"round","round":5,"verdict":"request_changes","final":true,"head_sha":"old111"}')")"
  stub_gh "$c" "$(mk_reviews nk18chi COMMENTED schlenks COMMENTED)"
  run acr_reviewers_behind_head '[{"number":5358,"headRefOid":"new222"}]' '[]'
  [ "$(printf '%s' "$output" | jq -r '.[0].behind | join(",")')" = "schlenks" ]
}

# A re-approval after a dismissal is a live approval again, so the deferral
# returns. Latest per author, not "was ever dismissed".
@test "acr_reviewers_behind_head: a re-approval after a dismissal defers again" {
  local c
  c="$(mk_multi \
    "$(mk_comments assiad '{"kind":"round","round":4,"verdict":"approve","final":true,"head_sha":"old111"}')" \
    "$(mk_comments schlenks '{"kind":"round","round":5,"verdict":"request_changes","final":true,"head_sha":"old111"}')")"
  stub_gh "$c" "$(mk_reviews assiad DISMISSED assiad APPROVED)"
  run acr_reviewers_behind_head '[{"number":5358,"headRefOid":"new222"}]' '[]'
  [ "$(printf '%s' "$output" | jq -r '.[0].behind | join(",")')" = "schlenks" ]
}

# Unreadable reviews leave the deferral exactly where it was. This one fails to
# the quiet answer rather than the eager one: not knowing whether an approval
# still stands is not evidence that it doesn't.
@test "acr_reviewers_behind_head: unreadable reviews leave the deferral in place" {
  local c
  c="$(mk_multi \
    "$(mk_comments assiad '{"kind":"round","round":4,"verdict":"approve","final":true,"head_sha":"old111"}')" \
    "$(mk_comments schlenks '{"kind":"round","round":5,"verdict":"request_changes","final":true,"head_sha":"old111"}')")"
  stub_gh "$c" 'gh: not logged in'
  run acr_reviewers_behind_head '[{"number":5358,"headRefOid":"new222"}]' '[]'
  [ "$(printf '%s' "$output" | jq -r '.[0].behind | join(",")')" = "schlenks" ]
}

# A dismissed approver is still deduped like any other — released from the
# deferral is not exempt from "already asked at this head".
@test "acr_reviewers_behind_head: a dismissed approver already asked is not asked again" {
  local c
  c="$(mk_multi \
    "$(mk_comments assiad '{"kind":"round","round":4,"verdict":"approve","final":true,"head_sha":"old111"}')" \
    "$(mk_comments schlenks '{"kind":"round","round":5,"verdict":"request_changes","final":true,"head_sha":"old111"}')")"
  stub_gh "$c" "$(mk_reviews assiad DISMISSED)"
  run acr_reviewers_behind_head '[{"number":5358,"headRefOid":"new222"}]' \
    '[{"number":5358,"headSha":"new222","outcome":"review_requested","reviewers":["assiad","schlenks"]}]'
  [ "$output" = "[]" ]
}

# --- acr_dismissed_approvals -------------------------------------------------

@test "acr_dismissed_approvals: gh failure -> []" {
  gh() { return 1; }
  run acr_dismissed_approvals 5358
  [ "$output" = "[]" ]
}

@test "acr_dismissed_approvals: non-json output -> []" {
  gh() { printf 'gh: not logged in'; }
  run acr_dismissed_approvals 5358
  [ "$output" = "[]" ]
}

@test "acr_dismissed_approvals: names only the authors whose latest review is dismissed" {
  local r
  r="$(mk_reviews schlenks DISMISSED assiad APPROVED nk18chi COMMENTED)"
  gh() { printf '%s' "$r"; }
  run acr_dismissed_approvals 5358
  [ "$(printf '%s' "$output" | jq -c .)" = '["schlenks"]' ]
}

@test "acr_dismissed_approvals: --slurp array-of-pages is flattened" {
  gh() { printf '%s' '[[{"id":1,"state":"DISMISSED","user":{"login":"schlenks"},"submitted_at":"a"}],
                       [{"id":2,"state":"DISMISSED","user":{"login":"assiad"},"submitted_at":"b"}]]'; }
  run acr_dismissed_approvals 5358
  [ "$(printf '%s' "$output" | jq -c 'sort')" = '["assiad","schlenks"]' ]
}

@test "acr_reviewers_behind_head: an ask for an older head does not suppress this one" {
  local c
  c="$(mk_comments nk18chi '{"kind":"round","round":11,"verdict":"comment","final":true,"head_sha":"old111"}')"
  gh() { printf '%s' "$c"; }
  run acr_reviewers_behind_head '[{"number":5358,"headRefOid":"new222"}]' \
    '[{"number":5358,"headSha":"old111","outcome":"review_requested"}]'
  [ "$(printf '%s' "$output" | jq '.[0].number')" = "5358" ]
}

@test "acr_reviewers_behind_head: gh failure -> actionable (asks for a review)" {
  gh() { return 1; }
  run acr_reviewers_behind_head '[{"number":5415,"headRefOid":"new222"}]' '[]'
  [ "$(printf '%s' "$output" | jq 'length')" = "1" ]
}

@test "acr_reviewers_behind_head: no PRs -> []" {
  run acr_reviewers_behind_head '[]' '[]'
  [ "$output" = "[]" ]
}

@test "acr_reviewers_behind_head: several PRs are reported independently" {
  local c
  c="$(mk_comments nk18chi '{"kind":"round","round":11,"verdict":"comment","final":true,"head_sha":"old111"}')"
  gh() { printf '%s' "$c"; }
  run acr_reviewers_behind_head \
    '[{"number":5358,"headRefOid":"new222"},{"number":5331,"headRefOid":"new333"}]' '[]'
  [ "$(printf '%s' "$output" | jq -r '[.[].number] | join(",")')" = "5358,5331" ]
}
