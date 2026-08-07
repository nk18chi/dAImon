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
