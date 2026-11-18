#!/usr/bin/env bats
# Unit tests for the Shortcut source profile's owner-scoping gate helper.
# shortcut_count / shortcut_mention are mocked, so these exercise the scoping and
# fail-closed behaviour without network or a token.

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  source "$ROOT/profiles/shortcut/lib.sh"
}

@test "shortcut_exclusions: unset -> empty" {
  unset DAIMON_INPUT_EXCLUDE_EPICS DAIMON_INPUT_EXCLUDE_OBJECTIVES DAIMON_INPUT_EXCLUDE_LABELS
  run shortcut_exclusions
  [ "$status" -eq 0 ]
  [ "$output" = "" ]
}

@test "shortcut_exclusions: one epic -> one negated term" {
  export DAIMON_INPUT_EXCLUDE_EPICS="1234"
  run shortcut_exclusions
  [ "$output" = " !epic:1234" ]
}

@test "shortcut_exclusions: several epics -> one term each" {
  export DAIMON_INPUT_EXCLUDE_EPICS="1234 5678"
  run shortcut_exclusions
  [ "$output" = " !epic:1234 !epic:5678" ]
}

@test "shortcut_exclusions: objectives -> one negated term each, after epics" {
  export DAIMON_INPUT_EXCLUDE_EPICS="1234" DAIMON_INPUT_EXCLUDE_OBJECTIVES="42 43"
  run shortcut_exclusions
  [ "$output" = " !epic:1234 !objective:42 !objective:43" ]
}

@test "shortcut_exclusions: labels -> one quoted negated term each, after objectives" {
  export DAIMON_INPUT_EXCLUDE_OBJECTIVES="42" DAIMON_INPUT_EXCLUDE_LABELS="milestone release-blocking"
  unset DAIMON_INPUT_EXCLUDE_EPICS
  run shortcut_exclusions
  [ "$output" = ' !objective:42 !label:"milestone" !label:"release-blocking"' ]
}

@test "shortcut_owner_count: no owner -> workspace count" {
  unset DAIMON_INPUT_OWNER
  shortcut_count() { echo 5; }
  run shortcut_owner_count 'label:"x"'
  [ "$status" -eq 0 ]
  [ "$output" = "5" ]
}

@test "shortcut_owner_count: owner resolves -> owner + requester" {
  export DAIMON_INPUT_OWNER="123"
  shortcut_mention() { echo "me"; }
  shortcut_count() { case "$1" in owner:*) echo 3;; requester:*) echo 2;; *) echo 0;; esac; }
  run shortcut_owner_count 'label:"x"'
  [ "$status" -eq 0 ]
  [ "$output" = "5" ]
}

@test "shortcut_owner_count: requester match excludes stories the owner also owns" {
  export DAIMON_INPUT_OWNER="123"
  shortcut_mention() { echo "me"; }
  shortcut_count() { case "$1" in "requester:me !owner:me "*) echo 2;; owner:*) echo 3;; *) echo 99;; esac; }
  run shortcut_owner_count 'label:"x"'
  [ "$output" = "5" ]
}

@test "shortcut_owner_count: include_requested=0 -> owner only" {
  export DAIMON_INPUT_OWNER="123" DAIMON_INPUT_INCLUDE_REQUESTED=0
  shortcut_mention() { echo "me"; }
  shortcut_count() { case "$1" in owner:*) echo 3;; *) echo 2;; esac; }
  run shortcut_owner_count 'label:"x"'
  [ "$output" = "3" ]
}

@test "shortcut_owner_ids: include_requested=0 -> owner only" {
  export DAIMON_INPUT_OWNER="123" DAIMON_INPUT_INCLUDE_REQUESTED=0
  shortcut_mention() { echo "me"; }
  shortcut_search_ids() { case "$1" in owner:*) printf '1 a\n';; *) printf '3 c\n';; esac; }
  run shortcut_owner_ids 'label:"x"'
  [ "$output" = "1 a" ]
}

@test "shortcut_owner_count: owner set but unresolvable -> fails closed with stderr" {
  export DAIMON_INPUT_OWNER="123"
  shortcut_mention() { echo ""; }
  shortcut_count() { echo 99; }  # must NOT be consulted
  run shortcut_owner_count 'label:"x"'
  [ "$status" -eq 1 ]
  [[ "$output" == *"could not resolve owner mention for 123"* ]]
}

@test "shortcut_owner_ids: owner + requester merged and deduped" {
  export DAIMON_INPUT_OWNER="123"
  shortcut_mention() { echo "me"; }
  shortcut_search_ids() { case "$1" in owner:*) printf '1 a\n2 b\n';; requester:*) printf '2 b\n3 c\n';; esac; }
  run shortcut_owner_ids 'label:"x"'
  [ "$status" -eq 0 ]
  [ "$output" = "$(printf '1 a\n2 b\n3 c')" ]
}

@test "shortcut_owner_ids: owner set but unresolvable -> fails closed" {
  export DAIMON_INPUT_OWNER="123"
  shortcut_mention() { echo ""; }
  shortcut_search_ids() { echo "1 a"; }  # must NOT be consulted
  run shortcut_owner_ids 'label:"x"'
  [ "$status" -eq 1 ]
  [[ "$output" == *"could not resolve owner mention"* ]]
}

@test "shortcut_unseen: drops recorded-and-unchanged, keeps new and changed" {
  f="$BATS_TEST_TMPDIR/state.json"
  echo '{"1":{"updated_at":"2026-03-14T08:15:30Z"},"2":{"updated_at":"2026-10-01T00:00:00Z"}}' > "$f"
  run shortcut_unseen "$f" <<< "$(printf '1 2026-03-14T08:15:30Z\n2 2026-10-02T09:00:00Z\n3 2026-10-03T00:00:00Z')"
  [ "$status" -eq 0 ]
  [ "$output" = "$(printf '2\n3')" ]
}

@test "shortcut_unseen: fractional seconds compare as the same instant" {
  f="$BATS_TEST_TMPDIR/state.json"
  echo '{"1":{"updated_at":"2026-03-14T08:15:30Z"}}' > "$f"
  run shortcut_unseen "$f" <<< "1 2026-03-14T08:15:30.512Z"
  [ "$output" = "" ]
}

@test "shortcut_unseen: missing or array state file -> everything is unseen" {
  run shortcut_unseen "$BATS_TEST_TMPDIR/nope.json" <<< "7 2026-01-01T00:00:00Z"
  [ "$output" = "7" ]
  f="$BATS_TEST_TMPDIR/arr.json"; echo '[]' > "$f"
  run shortcut_unseen "$f" <<< "7 2026-01-01T00:00:00Z"
  [ "$output" = "7" ]
}

# --- marker-field mode: search results are filtered by the status field value.
_marker_fixture() {
  export SHORTCUT_API_TOKEN=t DAIMON_INPUT_STATUS_FIELD="Agent"
  unset DAIMON_INPUT_OWNER
  curl() {
    case "$*" in
      *custom-fields*) echo '[{"id":"F1","name":"Agent"},{"id":"F2","name":"Other"}]' ;;
      *) echo '{"data":[
        {"id":1,"updated_at":"a","custom_fields":[{"field_id":"F1","value":"Ready"}]},
        {"id":2,"updated_at":"b","custom_fields":[{"field_id":"F1","value":"Needs input"}]},
        {"id":3,"updated_at":"c","custom_fields":[{"field_id":"F2","value":"Ready"}]},
        {"id":4,"updated_at":"d"}]}' ;;
    esac
  }
}

@test "shortcut_search_ids: no SC_STATUS_KEEP -> every story" {
  _marker_fixture
  run shortcut_search_ids "q"
  [ "$(printf '%s\n' "$output" | wc -l | tr -d ' ')" = "4" ]
}

@test "shortcut_marked_ids: keeps only the named value of the named field" {
  _marker_fixture
  run shortcut_marked_ids "Ready" "q"
  [ "$output" = "1 a" ]
}

@test "shortcut_marked_ids: empty value means field unset" {
  _marker_fixture
  run shortcut_marked_ids "" "q"
  [ "$output" = "$(printf '3 c\n4 d')" ]
}

@test "shortcut_marked_ids: values with spaces, several at once" {
  _marker_fixture
  run shortcut_marked_ids "Needs input|Ready" "q"
  [ "$output" = "$(printf '1 a\n2 b')" ]
}

@test "shortcut_marked_ids: unknown field fails closed with stderr" {
  _marker_fixture
  export DAIMON_INPUT_STATUS_FIELD="Missing"
  run shortcut_marked_ids "Ready" "q"
  [ "$status" -eq 1 ]
  [[ "$output" == *"not found"* ]]
}

@test "shortcut_marker_mode: needs both the switch and a field name" {
  export DAIMON_INPUT_STATUS_IS_SOURCE=1 DAIMON_INPUT_STATUS_FIELD=""
  run shortcut_marker_mode; [ "$status" -ne 0 ]
  export DAIMON_INPUT_STATUS_FIELD="Agent"
  run shortcut_marker_mode; [ "$status" -eq 0 ]
  export DAIMON_INPUT_STATUS_IS_SOURCE=0
  run shortcut_marker_mode; [ "$status" -ne 0 ]
}

# --- include_epics: epics opted back in out of an excluded objective.
@test "_sc_queries: no objective exclusion -> just the query" {
  export DAIMON_INPUT_INCLUDE_EPICS="7001"
  run _sc_queries 'label:"x" !epic:9'
  [ "$output" = 'label:"x" !epic:9' ]
}

@test "_sc_queries: objective excluded -> one variant per opted-in epic, other exclusions kept" {
  export DAIMON_INPUT_INCLUDE_EPICS="7001 7002"
  run _sc_queries 'state:"To Do" !epic:9 !objective:9001 !label:"milestone"'
  [ "$output" = "$(printf '%s\n' \
    'state:"To Do" !epic:9 !objective:9001 !label:"milestone"' \
    'state:"To Do" !epic:9 !label:"milestone" epic:7001' \
    'state:"To Do" !epic:9 !label:"milestone" epic:7002')" ]
}

@test "_sc_queries: nothing opted in -> just the query" {
  unset DAIMON_INPUT_INCLUDE_EPICS
  run _sc_queries '!objective:9001'
  [ "$output" = '!objective:9001' ]
}

@test "shortcut_search_ids: merges opted-in epics' stories, deduped in order" {
  export DAIMON_INPUT_INCLUDE_EPICS="7"
  _sc_search_ids_once() {
    case "$1" in
      *epic:7*) printf '2 b\n3 c\n' ;;
      *) printf '1 a\n2 b\n' ;;
    esac
  }
  run shortcut_search_ids 'q !objective:5'
  [ "$output" = "$(printf '1 a\n2 b\n3 c')" ]
}

@test "shortcut_count: adds opted-in epics' counts" {
  export DAIMON_INPUT_INCLUDE_EPICS="7 8"
  _sc_count_once() { case "$1" in *epic:7*) echo 2 ;; *epic:8*) echo 0 ;; *) echo 3 ;; esac; }
  run shortcut_count 'q !objective:5'
  [ "$output" = "5" ]
}
