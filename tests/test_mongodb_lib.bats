#!/usr/bin/env bats
# Unit tests for the MongoDB source profile's gate helpers. curl is mocked, so
# these exercise the fail-closed and filtering behaviour without network or auth.

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  source "$ROOT/profiles/mongodb/lib.sh"
}

# A response shaped like the real one: two user shapes plus a system shape that
# outranks both on total time (Atlas's own internal traffic).
summaries_json() {
  cat <<'JSON'
{"summaries":[
  {"queryShapeHash":"AAA","namespace":"app.users","command":"find",
   "execCount":1350,"avgWorkingMillis":380,"totalWorkingMillis":514170,
   "docsExamined":140010270,"docsReturned":5426755,
   "docsExaminedRatio":25.8,"systemQuery":false},
  {"queryShapeHash":"BBB","namespace":"app.orders","command":"aggregate",
   "execCount":2,"avgWorkingMillis":10,"totalWorkingMillis":20,
   "docsExamined":200000,"docsReturned":4,
   "docsExaminedRatio":50000,"systemQuery":false},
  {"queryShapeHash":"SYS","namespace":"config.image_collection","command":"aggregate",
   "execCount":239565,"avgWorkingMillis":3.3,"totalWorkingMillis":796898,
   "docsExamined":239565,"docsReturned":239565,
   "docsExaminedRatio":1,"systemQuery":true}
]}
JSON
}

@test "mdb_query_shapes: no credentials -> []" {
  atlas_creds() { :; }
  run mdb_query_shapes proj Cluster0 24
  [ "$output" = "[]" ]
}

@test "mdb_query_shapes: token exchange fails -> []" {
  atlas_token() { :; }
  run mdb_query_shapes proj Cluster0 24
  [ "$output" = "[]" ]
}

@test "mdb_query_shapes: excludes systemQuery shapes" {
  atlas_token() { echo tok; }
  curl() { summaries_json; }
  run mdb_query_shapes proj Cluster0 24
  [ "$(printf '%s' "$output" | jq 'length')" = "2" ]
  [ "$(printf '%s' "$output" | jq -r '[.[].queryShapeHash] | join(",")')" = "AAA,BBB" ]
}

@test "mdb_query_shapes: malformed response -> []" {
  atlas_token() { echo tok; }
  curl() { printf 'not json {'; }
  run mdb_query_shapes proj Cluster0 24
  [ "$output" = "[]" ]
}

@test "mdb_query_shapes: error envelope without .summaries -> []" {
  atlas_token() { echo tok; }
  curl() { printf '{"error":404,"errorCode":"RESOURCE_NOT_FOUND"}'; }
  run mdb_query_shapes proj Cluster0 24
  [ "$output" = "[]" ]
}

# A non-numeric lookback must not reach the arithmetic: an error there writes to
# stderr, which run.sh reads as a broken gate rather than an honest "no work".
@test "mdb_query_shapes: non-numeric lookback falls back silently" {
  atlas_token() { echo tok; }
  curl() { summaries_json; }
  err="$BATS_TEST_TMPDIR/err"
  out="$(mdb_query_shapes proj Cluster0 "abc; rm -rf /" 2>"$err")"
  [ ! -s "$err" ]
  [ "$(printf '%s' "$out" | jq 'length')" = "2" ]
}

@test "mdb_slow_shapes: total-time rule catches a low-avg shape" {
  run mdb_slow_shapes "$(summaries_json | jq -c '[.summaries[] | select(.systemQuery == false)]')" 3000 120000 1000 1000
  # AAA averages 380ms — far under the 3s avg rule — but costs 514s in total.
  [ "$(printf '%s' "$output" | jq -r 'any(.queryShapeHash == "AAA")')" = "true" ]
}

@test "mdb_slow_shapes: examined-ratio rule catches a fast, cheap shape" {
  run mdb_slow_shapes "$(summaries_json | jq -c '[.summaries[] | select(.systemQuery == false)]')" 3000 120000 1000 1000000
  # BBB is 10ms and 20ms total — it trips neither timer, only the 50000:1 ratio.
  # per-exec is pinned high here so only the ratio rule can be responsible.
  [ "$(printf '%s' "$output" | jq -r 'any(.queryShapeHash == "BBB")')" = "true" ]
}

@test "mdb_slow_shapes: thresholds above everything -> []" {
  run mdb_slow_shapes "$(summaries_json | jq -c '[.summaries[]]')" 999999 999999999 99999999 99999999
  [ "$(printf '%s' "$output" | jq 'length')" = "0" ]
}

@test "mdb_slow_shapes: missing metric fields do not throw" {
  run mdb_slow_shapes '[{"queryShapeHash":"CCC"}]' 3000 120000 1000 1000
  [ "$(printf '%s' "$output" | jq 'length')" = "0" ]
}

@test "mdb_slow_shapes: garbage input -> []" {
  run mdb_slow_shapes 'not json {' 3000 120000 1000 1000
  [ "$output" = "[]" ]
}

# --- rule 3 guard: docsExaminedRatio is only meaningful for a real row count -----

@test "mdb_slow_shapes: ratio ignored when docsReturned is 0" {
  # Atlas reports a huge ratio for a query that returned nothing. 40 docs/exec, so
  # the per-exec rule must not rescue it either — this shape is genuinely cheap.
  local s='[{"queryShapeHash":"ZERO","avgWorkingMillis":1,"totalWorkingMillis":10,
             "docsExamined":200,"docsReturned":0,"execCount":5,"docsExaminedRatio":3613864}]'
  run mdb_slow_shapes "$s" 3000 120000 1000 1000
  [ "$(printf '%s' "$output" | jq 'length')" = "0" ]
}

@test "mdb_slow_shapes: ratio ignored when docsReturned == execCount (envelope)" {
  # $facet/$group emit one doc per run, so the "ratio" is already docs-per-exec.
  # 63 docs/exec here — under the per-exec rule, so nothing should fire.
  local s='[{"queryShapeHash":"FACET","avgWorkingMillis":2,"totalWorkingMillis":100,
             "docsExamined":6300,"docsReturned":100,"execCount":100,"docsExaminedRatio":63}]'
  run mdb_slow_shapes "$s" 3000 120000 1 1000
  [ "$(printf '%s' "$output" | jq 'length')" = "0" ]
}

@test "mdb_slow_shapes: envelope shape still caught when genuinely heavy per exec" {
  # Same envelope shape, but 52,536 docs per execution — the per-exec rule fires.
  local s='[{"queryShapeHash":"FACETHEAVY","avgWorkingMillis":2,"totalWorkingMillis":100,
             "docsExamined":157608,"docsReturned":3,"execCount":3,"docsExaminedRatio":52536}]'
  run mdb_slow_shapes "$s" 3000 120000 999999999 1000
  [ "$(printf '%s' "$output" | jq -r 'any(.queryShapeHash == "FACETHEAVY")')" = "true" ]
}

# --- rule 4: absolute scan cost per execution -----------------------------------

@test "mdb_slow_shapes: per-exec rule catches a healthy-looking ratio" {
  # 124,405 docs per execution at a 3:1 ratio — invisible to every other rule.
  local s='[{"queryShapeHash":"BIGSCAN","avgWorkingMillis":100,"totalWorkingMillis":1000,
             "docsExamined":248810,"docsReturned":82936,"execCount":2,"docsExaminedRatio":3}]'
  run mdb_slow_shapes "$s" 3000 120000 1000 1000
  [ "$(printf '%s' "$output" | jq -r 'any(.queryShapeHash == "BIGSCAN")')" = "true" ]
}

@test "mdb_slow_shapes: per-exec rule does not fire on a light shape" {
  local s='[{"queryShapeHash":"LIGHT","avgWorkingMillis":2,"totalWorkingMillis":100,
             "docsExamined":500,"docsReturned":250,"execCount":100,"docsExaminedRatio":2}]'
  run mdb_slow_shapes "$s" 3000 120000 1000 1000
  [ "$(printf '%s' "$output" | jq 'length')" = "0" ]
}

@test "mdb_slow_shapes: per-exec survives execCount 0 (no divide-by-zero)" {
  local s='[{"queryShapeHash":"NOEXEC","docsExamined":50,"docsReturned":0,"execCount":0}]'
  run mdb_slow_shapes "$s" 3000 120000 1000 1000
  [ "$(printf '%s' "$output" | jq 'length')" = "0" ]
}
