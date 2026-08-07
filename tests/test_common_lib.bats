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
