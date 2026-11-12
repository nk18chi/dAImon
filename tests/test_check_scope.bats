#!/usr/bin/env bats
# Unit tests for the allowed_paths scope guard. Each test builds a throwaway repo
# with a base commit and a branch, so the guard runs against real git plumbing.

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  GUARD="$ROOT/lib/check-scope.sh"
  REPO="$BATS_TEST_TMPDIR/repo"
  mkdir -p "$REPO"
  cd "$REPO" || return 1
  git init -q -b main .
  git config user.email t@t.t
  git config user.name t
  mkdir -p apps/web packages/ui apps/admin packages/shared
  echo base > apps/web/a.ts
  git add -A && git commit -qm base
  git checkout -qb work
  export DAIMON_INPUT_ALLOWED_PATHS="apps/web packages/ui"
}

commit_all() { git add -A && git commit -qm change; }

@test "no allowlist configured -> unrestricted" {
  unset DAIMON_INPUT_ALLOWED_PATHS
  echo x > apps/admin/m.ts
  commit_all
  run bash "$GUARD" main
  [ "$status" -eq 0 ]
}

@test "changes inside the allowed paths pass" {
  echo x > apps/web/b.ts
  echo y > packages/ui/m.ts
  commit_all
  run bash "$GUARD" main
  [ "$status" -eq 0 ]
}

@test "a change in another app fails and names it" {
  echo x > apps/web/b.ts
  echo y > apps/admin/m.ts
  commit_all
  run bash "$GUARD" main
  [ "$status" -eq 1 ]
  [[ "$output" == *"apps/admin/m.ts"* ]]
  [[ "$output" == *"apps/admin"* ]]
}

@test "a change in a shared package fails" {
  echo x > packages/shared/d.ts
  commit_all
  run bash "$GUARD" main
  [ "$status" -eq 1 ]
  [[ "$output" == *"packages/shared"* ]]
}

@test "a root-level change fails" {
  echo x > pnpm-lock.yaml
  commit_all
  run bash "$GUARD" main
  [ "$status" -eq 1 ]
  [[ "$output" == *"pnpm-lock.yaml"* ]]
}

@test "uncommitted out-of-scope work is caught too" {
  echo x > apps/admin/m.ts
  run bash "$GUARD" main
  [ "$status" -eq 1 ]
  [[ "$output" == *"apps/admin/m.ts"* ]]
}

@test "a prefix must match a path segment, not a substring" {
  mkdir -p apps/web-admin
  echo x > apps/web-admin/a.ts
  commit_all
  run bash "$GUARD" main
  [ "$status" -eq 1 ]
  [[ "$output" == *"apps/web-admin/a.ts"* ]]
}

@test "an unresolvable base ref is 'cannot tell', not 'in scope'" {
  run bash "$GUARD" origin/does-not-exist
  [ "$status" -eq 2 ]
}

@test "an unknown option is rejected rather than read as a base ref" {
  run bash "$GUARD" --nonsense
  [ "$status" -eq 2 ]
}

# --- --pr scope resolution --------------------------------------------------
# The allowlist comes from whichever daemon recorded that PR, so a shepherding
# daemon needs no allowlist of its own. Uses a throwaway state dir.

pr_setup() {
  export DAIMON_STATE_DIR="$BATS_TEST_TMPDIR/state"
  mkdir -p "$DAIMON_STATE_DIR/state"
  unset DAIMON_INPUT_ALLOWED_PATHS
  URL="https://github.com/o/r/pull/7"
}

write_record() { printf '%s' "$1" > "$DAIMON_STATE_DIR/state/producer.json"; }

@test "--pr with no matching record enforces nothing" {
  pr_setup
  write_record '[{"story":1,"pr_url":"https://github.com/o/r/pull/999","allowed_paths":["apps/web"]}]'
  echo x > apps/admin/m.ts
  commit_all
  run bash "$GUARD" main --pr "$URL"
  [ "$status" -eq 0 ]
  [[ "$output" == *"no daemon declared a scope"* ]]
}

@test "--pr picks up the recorded allowlist and enforces it" {
  pr_setup
  write_record "[{\"story\":1,\"pr_url\":\"$URL\",\"allowed_paths\":[\"apps/web\"]}]"
  echo x > apps/admin/m.ts
  commit_all
  run bash "$GUARD" main --pr "$URL"
  [ "$status" -eq 1 ]
  [[ "$output" == *"apps/admin"* ]]
}

@test "--pr passes when the change stays inside the recorded allowlist" {
  pr_setup
  write_record "[{\"story\":1,\"pr_url\":\"$URL\",\"allowed_paths\":[\"apps/web\"]}]"
  echo x > apps/web/b.ts
  commit_all
  run bash "$GUARD" main --pr "$URL"
  [ "$status" -eq 0 ]
}

@test "--pr overrides the caller's own allowlist" {
  pr_setup
  export DAIMON_INPUT_ALLOWED_PATHS="apps/admin"
  write_record "[{\"story\":1,\"pr_url\":\"$URL\",\"allowed_paths\":[\"apps/web\"]}]"
  echo x > apps/admin/m.ts
  commit_all
  run bash "$GUARD" main --pr "$URL"
  [ "$status" -eq 1 ]
}

@test "--pr survives a corrupt state file" {
  pr_setup
  write_record 'not json {'
  echo x > apps/admin/m.ts
  commit_all
  run bash "$GUARD" main --pr "$URL"
  [ "$status" -eq 0 ]
}

@test "--pr without a value is an error" {
  pr_setup
  run bash "$GUARD" main --pr
  [ "$status" -eq 2 ]
}

# --- turbo mode -------------------------------------------------------------
# Needs a real turbo on PATH; skipped where there isn't one (e.g. CI).

setup_turbo_repo() {
  command -v turbo >/dev/null 2>&1 || skip "turbo not installed"
  cd "$BATS_TEST_TMPDIR" || return 1
  rm -rf turbo-repo && mkdir -p turbo-repo/apps/web turbo-repo/apps/admin turbo-repo/packages/ui
  cd turbo-repo || return 1
  echo '{"name":"root","private":true,"workspaces":["apps/*","packages/*"],"packageManager":"npm@10.0.0"}' > package.json
  echo '{"tasks":{"build":{}}}' > turbo.json
  echo '{"name":"web","dependencies":{"ui":"workspace:*"},"scripts":{"build":"true"}}' > apps/web/package.json
  echo '{"name":"admin","scripts":{"build":"true"}}' > apps/admin/package.json
  echo '{"name":"ui","scripts":{"build":"true"}}' > packages/ui/package.json
  git init -q -b main .
  git config user.email t@t.t
  git config user.name t
  git add -A && git commit -qm base
  git checkout -qb work
  export DAIMON_INPUT_ALLOWED_PATHS="apps/web packages/ui"
}

@test "turbo mode: an in-scope change passes and reports the mode" {
  setup_turbo_repo
  echo x > apps/web/index.js
  run bash "$GUARD" main
  [ "$status" -eq 0 ]
  [[ "$output" == *"[turbo]"* ]]
}

@test "turbo mode: another app being affected fails" {
  setup_turbo_repo
  echo x > apps/admin/index.js
  run bash "$GUARD" main
  [ "$status" -eq 1 ]
  [[ "$output" == *"apps/admin"* ]]
}

@test "turbo mode: catches fan-out a path check would miss" {
  command -v turbo >/dev/null 2>&1 || skip "turbo not installed"
  cd "$BATS_TEST_TMPDIR" || return 1
  rm -rf fanout && mkdir -p fanout/apps/admin fanout/packages/ui
  cd fanout || return 1
  echo '{"name":"root","private":true,"workspaces":["apps/*","packages/*"],"packageManager":"npm@10.0.0"}' > package.json
  echo '{"tasks":{"build":{}}}' > turbo.json
  echo '{"name":"ui","scripts":{"build":"true"}}' > packages/ui/package.json
  # admin already depends on ui on main, so a branch touching only the
  # allowed packages/ui still drags admin into the build.
  echo '{"name":"admin","dependencies":{"ui":"workspace:*"},"scripts":{"build":"true"}}' > apps/admin/package.json
  git init -q -b main .
  git config user.email t@t.t
  git config user.name t
  git add -A && git commit -qm base
  git checkout -qb work
  export DAIMON_INPUT_ALLOWED_PATHS="packages/ui"

  echo x > packages/ui/index.js
  git add -A && git commit -qm edit

  run bash "$GUARD" main --paths
  [ "$status" -eq 0 ]

  run bash "$GUARD" main
  [ "$status" -eq 1 ]
  [[ "$output" == *"apps/admin"* ]]
}

@test "--paths forces the file-based mode even where turbo exists" {
  setup_turbo_repo
  echo x > apps/web/index.js
  run bash "$GUARD" main --paths
  [ "$status" -eq 0 ]
  [[ "$output" == *"[paths]"* ]]
}
