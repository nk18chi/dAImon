#!/usr/bin/env bats
# The role gate: a daemon with a `role` runs only where [roles].command says so.
# The command is a stub that answers from $T/answer, standing in for e.g. relay.

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  T="$BATS_TEST_TMPDIR"
  mkdir -p "$T/install/catalog/watch/skill" "$T/install/catalog/plain/skill" "$T/state" "$T/bin"
  ln -s "$ROOT/lib" "$T/install/lib"
  ln -s "$ROOT/profiles" "$T/install/profiles"
  cat > "$T/bin/holder" <<'STUB'
#!/usr/bin/env bash
echo "$@" >> "$ROLE_CALLS"
read -r code msg < "$ROLE_ANSWER"
echo "$msg"; exit "$code"
STUB
  chmod +x "$T/bin/holder"
  export ROLE_CALLS="$T/calls" ROLE_ANSWER="$T/answer" PATH="$T/bin:$PATH"
  write_config 'holder {role} {seconds}'
  printf '[daemon]\ncommand = "/watch"\nschedule = { interval = 120 }\nrole = "slack-issues"\n' \
    > "$T/install/catalog/watch/daemon.toml"
  printf '[daemon]\ncommand = "/plain"\nschedule = { minutes = [5] }\n' \
    > "$T/install/catalog/plain/daemon.toml"
  touch "$T/install/catalog/watch/skill/SKILL.md" "$T/install/catalog/plain/skill/SKILL.md"
}

write_config() {  # [roles].command
  printf '[core]\nstate_dir = "%s/state"\nnamespace = "t"\ninstall_root = "%s/install"\n[roles]\ncommand = "%s"\n' \
    "$T" "$T" "$1" > "$T/daimon.toml"
  export DAIMON_CONFIG="$T/daimon.toml"
}

check() {  # slug -> sets ROLE_* via the real lib
  source "$ROOT/lib/common.sh"
  source "$ROOT/lib/role.sh"
  role_check "$1"
}

@test "held here: the daemon runs, asking for twice its interval plus a minute" {
  echo "0 slack-issues: held by this machine" > "$T/answer"
  check watch
  [ "$ROLE_SKIP" -eq 0 ]
  [ "$(cat "$T/calls")" = "slack-issues 300" ]
}

@test "held elsewhere: skip, naming the holder" {
  echo "1 slack-issues: held by zed's daimon" > "$T/answer"
  check watch
  [ "$ROLE_SKIP" -eq 1 ]
  [ "$ROLE_EVENT" = skip ]
  [[ "$ROLE_REASON" == *"held by zed's daimon"* ]]
}

@test "the check itself failing skips loudly (fails closed)" {
  echo "2 relayd is not running" > "$T/answer"
  check watch
  [ "$ROLE_SKIP" -eq 1 ]
  [ "$ROLE_EVENT" = role_error ]
  [[ "$ROLE_REASON" == *"exit 2"*"relayd is not running"* ]]
}

@test "no role: nothing is asked and the daemon runs" {
  echo "1 should not be asked" > "$T/answer"
  check plain
  [ "$ROLE_SKIP" -eq 0 ]
  [ ! -e "$T/calls" ]
}

@test "a role without [roles].command is a config error" {
  write_config ""
  check watch
  [ "$ROLE_SKIP" -eq 1 ]
  [ "$ROLE_EVENT" = config_error ]
  [[ "$ROLE_REASON" == *"[roles].command is empty"* ]]
}

@test "role_hold overrides the default hold" {
  printf 'role_hold = 45\n' >> "$T/install/catalog/watch/daemon.toml"
  echo "0 ok" > "$T/answer"
  check watch
  [ "$(cat "$T/calls")" = "slack-issues 45" ]
}
