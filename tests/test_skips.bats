#!/usr/bin/env bats
# Unit tests for `daimon skip` (lib/skips.sh) and the gate filter it feeds.
#
# The filter is exercised here rather than only inside discover.sh because a
# skip that silently fails to apply is invisible: the daemon just works a PR you
# told it not to, and nothing anywhere says why.

# common.sh resolves DAIMON_STATE_DIR from config.py and overwrites whatever the
# environment had, so pointing the variable at a tmpdir does nothing — these
# tests would write to the real state directory and clobber live skips. Redirect
# the config instead, which is the only input config.py reads from the env.
setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  export DAIMON_CONFIG="$BATS_TEST_TMPDIR/daimon.toml"
  printf '[core]\nstate_dir = "%s/state"\n' "$BATS_TEST_TMPDIR" > "$DAIMON_CONFIG"
  source "$ROOT/lib/common.sh"
  # config.py resolve()s the path, so on macOS /var becomes /private/var — match
  # the tail, not the whole string. The guard stays because the failure it
  # catches is silent: tests that write to the real state dir still pass.
  case "$DAIMON_STATE_DIR" in
    */state) ;;
    *) echo "test isolation failed: state dir is $DAIMON_STATE_DIR" >&2; return 1 ;;
  esac
  [ "$DAIMON_STATE_DIR" != "$HOME/.local/state/daimon" ] || {
    echo "test isolation failed: would write to the real state dir" >&2
    return 1
  }
  mkdir -p "$DAIMON_STATE_DIR/runtime"
  SKIPS="$ROOT/lib/skips.sh"
}

skips_json() { load_json_object "$(skips_file acr-fixer)"; }

@test "skip: no file -> nothing skipped" {
  run bash "$SKIPS" acr-fixer
  [ "$status" -eq 0 ]
  [[ "$output" == *"no skips"* ]]
}

@test "skip: an item is recorded" {
  run bash "$SKIPS" acr-fixer 5412
  [ "$status" -eq 0 ]
  [ "$(skips_json)" = '{"5412":true}' ]
}

@test "skip: a second item joins the first" {
  bash "$SKIPS" acr-fixer 5412
  bash "$SKIPS" acr-fixer 5358
  [ "$(skips_json | jq -r 'keys | sort | join(",")')" = "5358,5412" ]
}

@test "skip: setting the same item twice is idempotent" {
  bash "$SKIPS" acr-fixer 5412
  bash "$SKIPS" acr-fixer 5412
  [ "$(skips_json | jq 'length')" = "1" ]
}

@test "skip: --clear removes one and leaves the rest" {
  bash "$SKIPS" acr-fixer 5412
  bash "$SKIPS" acr-fixer 5358
  run bash "$SKIPS" acr-fixer 5412 --clear
  [ "$status" -eq 0 ]
  [ "$(skips_json)" = '{"5358":true}' ]
}

@test "skip: clearing an item that was never skipped is not an error" {
  run bash "$SKIPS" acr-fixer 5412 --clear
  [ "$status" -eq 0 ]
  [ "$(skips_json)" = "{}" ]
}

@test "skip: --clear on the daemon removes every skip" {
  bash "$SKIPS" acr-fixer 5412
  run bash "$SKIPS" acr-fixer --clear
  [ "$status" -eq 0 ]
  [ ! -f "$(skips_file acr-fixer)" ]
}

@test "skip: listing shows what is skipped" {
  bash "$SKIPS" acr-fixer 5412
  run bash "$SKIPS" acr-fixer
  [[ "$output" == *"5412"* ]]
}

@test "skip: a non-numeric item is rejected" {
  run bash "$SKIPS" acr-fixer not-a-pr
  [ "$status" -eq 2 ]
  [ ! -f "$(skips_file acr-fixer)" ]
}

@test "skip: a corrupt file is treated as empty, not fatal" {
  printf 'not json {' > "$(skips_file acr-fixer)"
  run bash "$SKIPS" acr-fixer 5412
  [ "$status" -eq 0 ]
  [ "$(skips_json)" = '{"5412":true}' ]
}

@test "skip: skips are per daemon" {
  bash "$SKIPS" acr-fixer 5412
  [ "$(load_json_object "$(skips_file pr-manager)")" = "{}" ]
}

# The filter discover.sh applies to `gh pr list` output. Draft, label and skip
# are three independent reasons to drop a PR; each has to hold on its own.
filter() {
  jq -c --arg skip acr-no-autofix --argjson skips "$1" '
    [ .[]
      | select((.isDraft | not)
               and ([.labels[].name] | index($skip) == null)
               and ($skips[.number | tostring] | not)) ]
  '
}

PRS='[{"number":5412,"isDraft":false,"labels":[]},
      {"number":5358,"isDraft":false,"labels":[]},
      {"number":5331,"isDraft":true,"labels":[]},
      {"number":5342,"isDraft":false,"labels":[{"name":"acr-no-autofix"}]}]'

@test "gate filter: a skipped PR is dropped" {
  run bash -c "printf '%s' '$PRS' | jq -c --arg skip acr-no-autofix --argjson skips '{\"5412\":true}' '
    [ .[] | select((.isDraft | not) and ([.labels[].name] | index(\$skip) == null) and (\$skips[.number | tostring] | not)) ]'"
  [ "$(printf '%s' "$output" | jq -c '[.[].number]')" = "[5358]" ]
}

@test "gate filter: no skips leaves label and draft handling unchanged" {
  run bash -c "printf '%s' '$PRS' | jq -c --arg skip acr-no-autofix --argjson skips '{}' '
    [ .[] | select((.isDraft | not) and ([.labels[].name] | index(\$skip) == null) and (\$skips[.number | tostring] | not)) ]'"
  [ "$(printf '%s' "$output" | jq -c '[.[].number]')" = "[5412,5358]" ]
}

# A JSON object keys on strings; a PR number arrives as a jq number. Forget the
# tostring and every lookup misses, and the skip does nothing at all.
@test "gate filter: the skip key is matched as a string, not a number" {
  run bash -c "printf '%s' '$PRS' | jq -c --argjson skips '{\"5358\":true}' '
    [ .[] | select(\$skips[.number | tostring] | not) | .number ]'"
  [ "$(printf '%s' "$output" | jq -c '.')" = "[5412,5331,5342]" ]
}
