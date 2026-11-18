#!/usr/bin/env bats
# daimon update: fast-forward only, to a green upstream, never a dirty or
# diverged checkout. A real git remote; a fake gh answers the CI question.

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  T="$(cd "$BATS_TEST_TMPDIR" && pwd -P)"
  export HOME="$T/home"; mkdir -p "$HOME" "$T/bin"
  git init -q --bare -b main "$T/origin.git"
  git clone -q "$T/origin.git" "$T/work" 2>/dev/null
  commit "$T/work" one
  git -C "$T/work" push -q origin main
  git clone -q "$T/origin.git" "$T/install"
  printf '[core]\nstate_dir = "%s/state"\nnamespace = "t"\ninstall_root = "%s/install"\n' "$T" "$T" > "$T/daimon.toml"
  export DAIMON_CONFIG="$T/daimon.toml"
  export DAIMON_UPDATE_POST="echo ran >> $T/post"
  cat > "$T/bin/gh" <<'GH'
#!/usr/bin/env bash
case "$1" in repo) echo o/r ;; api) echo "${FAKE_CI:-success}" ;; esac
GH
  chmod +x "$T/bin/gh"; export PATH="$T/bin:$PATH"
}

commit() {  # repo message
  echo "$2" >> "$1/f"; git -C "$1" add f
  git -C "$1" -c user.name=t -c user.email=t@t commit -qm "$2"
}

upstream_moves() { commit "$T/work" two; git -C "$T/work" push -q origin main; }
update() { run bash "$ROOT/lib/self_update.sh" "$@"; }
head_of() { git -C "$1" rev-parse HEAD; }

@test "current: nothing to do" {
  update
  [ "$status" -eq 0 ]; [[ "$output" == *"current at"* ]]
  [ ! -e "$T/post" ]
}

@test "behind a green upstream: fast-forwards, then installs and syncs" {
  upstream_moves
  update
  [ "$status" -eq 0 ]; [[ "$output" == *"updated"* ]]
  [ "$(head_of "$T/install")" = "$(head_of "$T/work")" ]
  [ "$(cat "$T/post")" = ran ]
  grep -q 'event=updated' "$T/state/logs/update.log"
}

@test "CI not green yet: waits" {
  upstream_moves; export FAKE_CI=pending
  update
  [[ "$output" == *"CI on"*"is pending"* ]]
  [ "$(head_of "$T/install")" != "$(head_of "$T/work")" ]; [ ! -e "$T/post" ]
}

@test "local changes: never touched" {
  upstream_moves; echo mine >> "$T/install/f"
  update
  [[ "$output" == *"local changes"* ]]; [ ! -e "$T/post" ]
}

@test "diverged: never touched" {
  upstream_moves; commit "$T/install" local-only
  update
  [[ "$output" == *"diverged"* ]]; [ ! -e "$T/post" ]
}

@test "a branch with no upstream says how to get back on main" {
  git -C "$T/install" switch -q -c feat/x
  update
  [[ "$output" == *"feat/x has no upstream"*"git switch main"* ]]
}

@test "opted out unless forced (no-auto-update beside daimon.toml)" {
  upstream_moves; touch "$T/no-auto-update"
  update
  [[ "$output" == *"opted out"* ]]; [ ! -e "$T/post" ]
  update --force
  [[ "$output" == *"updated"* ]]
}
