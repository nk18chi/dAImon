#!/usr/bin/env bats
# Unit tests for the source-agnostic gate helpers in lib/common.sh.

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  source "$ROOT/lib/common.sh"
}

@test "load_seen_state: missing file -> []" {
  run load_seen_state "$BATS_TEST_TMPDIR/nope.json"
  [ "$output" = "[]" ]
}

@test "load_seen_state: invalid json -> []" {
  printf 'not json {' > "$BATS_TEST_TMPDIR/s.json"
  run load_seen_state "$BATS_TEST_TMPDIR/s.json"
  [ "$output" = "[]" ]
}

@test "load_seen_state: valid json -> contents" {
  printf '[{"number":1,"headSha":"abc"}]' > "$BATS_TEST_TMPDIR/s.json"
  run load_seen_state "$BATS_TEST_TMPDIR/s.json"
  [ "$output" = '[{"number":1,"headSha":"abc"}]' ]
}

# A skill may keep its records in several named lists rather than one array.
# The gate iterates whatever comes back, so an un-normalised object hands it two
# arrays as elements and every lookup misses — no dedup, no watermarks.
@test "load_seen_state: object of arrays is flattened to one array" {
  printf '{"rounds":[{"number":1}],"watermarks":[{"number":2}]}' > "$BATS_TEST_TMPDIR/s.json"
  run load_seen_state "$BATS_TEST_TMPDIR/s.json"
  [ "$(printf '%s' "$output" | jq 'length')" = "2" ]
  [ "$(printf '%s' "$output" | jq -r '[.[].number] | sort | join(",")')" = "1,2" ]
}

@test "load_seen_state: object with no arrays -> []" {
  printf '{"note":"nothing here"}' > "$BATS_TEST_TMPDIR/s.json"
  run load_seen_state "$BATS_TEST_TMPDIR/s.json"
  [ "$output" = "[]" ]
}
