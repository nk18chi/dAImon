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
