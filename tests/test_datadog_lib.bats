#!/usr/bin/env bats
# Unit tests for the Datadog source profile's gate helpers. `pup` is mocked, so
# these exercise the envelope-unwrapping and the failure-reporting contract
# without the CLI, auth, or network.
#
# The contract these pin: a helper that cannot answer still prints the safe empty
# value, but returns non-zero AND says why on stderr. Printing the empty value
# alone is what let a rate-limited search read as a quiet window.

# `run --separate-stderr` is the whole point here — stdout and stderr carry
# different halves of the contract, so they must be asserted apart.
bats_require_minimum_version 1.5.0

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  source "$ROOT/profiles/datadog/lib.sh"
}

@test "dd_log_count: {data:[...]} envelope -> count of data" {
  pup() { printf '{"data":[{"id":1},{"id":2},{"id":3}],"meta":{}}'; }
  run dd_log_count "status:error" "30m"
  [ "$status" -eq 0 ]
  [ "$output" = "3" ]
}

@test "dd_log_count: bare array -> its length" {
  pup() { printf '[{"id":1},{"id":2}]'; }
  run dd_log_count "status:error" "30m"
  [ "$status" -eq 0 ]
  [ "$output" = "2" ]
}

# An empty window is a real answer, not a failure: exit 0, nothing on stderr.
# This is the case a broken search must never be confused with.
@test "dd_log_count: empty result -> 0 and success" {
  pup() { printf '{"data":[]}'; }
  run --separate-stderr dd_log_count "status:error" "30m"
  [ "$status" -eq 0 ]
  [ "$output" = "0" ]
  [ -z "$stderr" ]
}

@test "dd_log_count: pup failure -> 0, non-zero status, reason on stderr" {
  pup() { return 1; }
  run --separate-stderr dd_log_count "status:error" "30m"
  [ "$status" -ne 0 ]
  [ "$output" = "0" ]
  [[ "$stderr" == *"search failed"* ]]
}

# The 429 that started this. A rate-limited search must not read as "no events".
@test "dd_log_count: rate limit is reported, not swallowed" {
  pup() { printf 'Error: POST /api/v2/logs failed (HTTP 429): Too many requests'; return 1; }
  run --separate-stderr dd_log_count "status:error" "30m"
  [ "$status" -ne 0 ]
  [ "$output" = "0" ]
  [[ "$stderr" == *"429"* ]]
}

@test "dd_log_count: non-json output -> 0, non-zero status, reason on stderr" {
  pup() { printf 'error: not authenticated'; }
  run --separate-stderr dd_log_count "status:error" "30m"
  [ "$status" -ne 0 ]
  [ "$output" = "0" ]
  [ -n "$stderr" ]
}

@test "dd_log_json: pup failure -> [], non-zero status" {
  pup() { return 1; }
  run --separate-stderr dd_log_json "status:error" "30m"
  [ "$status" -ne 0 ]
  [ "$output" = "[]" ]
  [ -n "$stderr" ]
}

# pup prints this banner before the payload when it renews its token mid-run.
# Unhandled, it made jq fail and every search that day look like an empty window.
@test "dd_log_json: a token-refresh banner before the payload is skipped" {
  pup() { printf '🔄 Access token refreshed automatically.\n{"data":[{"id":1},{"id":2}]}'; }
  run --separate-stderr dd_log_json "status:error" "30m"
  [ "$status" -eq 0 ]
  [ "$(printf '%s' "$output" | jq 'length')" = "2" ]
  [ -z "$stderr" ]
}

@test "dd_log_count: counts through a token-refresh banner" {
  pup() { printf '🔄 Access token refreshed automatically.\n{"data":[{"id":1}]}'; }
  run --separate-stderr dd_log_count "status:error" "30m"
  [ "$status" -eq 0 ]
  [ "$output" = "1" ]
}

# A gate reads stdout only, so it still evaluates false on failure — the loudness
# comes from stderr, which run.sh turns into discover_error. Pin both halves.
@test "gate shape: a failed search is false on stdout but noisy on stderr" {
  pup() { return 1; }
  run --separate-stderr bash -c '
    source "'"$ROOT"'/profiles/datadog/lib.sh"
    pup() { return 1; }
    [ "$(dd_log_count "q" "30m")" -gt 0 ]
  '
  [ "$status" -ne 0 ]
  [ -n "$stderr" ]
}
