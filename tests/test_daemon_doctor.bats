#!/usr/bin/env bats
# daimon doctor runs a registered daemon's own doctor.sh, with its inputs in env.

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  T="$(cd "$BATS_TEST_TMPDIR" && pwd -P)"
  export HOME="$T/home"; mkdir -p "$HOME/Library/LaunchAgents"
  for d in keyed plain; do
    mkdir -p "$T/install/catalog/$d/skill"
    printf '[daemon]\ncommand = "/%s"\nschedule = { interval = 600 }\n[inputs]\nitem = "cf-token"\n' "$d" \
      > "$T/install/catalog/$d/daemon.toml"
    touch "$T/install/catalog/$d/skill/SKILL.md"
    printf 'echo "no keychain item $DAIMON_INPUT_ITEM in $(basename "$DAIMON_DAEMON_DIR")"; exit %s\n' "${CODE:-1}" \
      > "$T/install/catalog/$d/doctor.sh"
  done
  ln -s "$ROOT/lib" "$T/install/lib"; ln -s "$ROOT/profiles" "$T/install/profiles"
  printf '[core]\nstate_dir = "%s/state"\nnamespace = "t"\ninstall_root = "%s/install"\n' "$T" "$T" > "$T/daimon.toml"
  export DAIMON_CONFIG="$T/daimon.toml"
  touch "$HOME/Library/LaunchAgents/t.keyed.plist" "$HOME/Library/LaunchAgents/com.t.keyed.plist"
}

@test "registered daemon's check runs with its inputs; unregistered one is skipped" {
  run bash "$ROOT/lib/doctor.sh"
  [[ "$output" == *"daemon checks"* ]]
  [[ "$output" == *"warn  keyed: no keychain item cf-token in keyed"* ]]
  [[ "$output" != *"plain: no keychain"* ]]
}

@test "exit 2 is a failure" {
  printf 'echo broken; exit 2\n' > "$T/install/catalog/keyed/doctor.sh"
  run bash "$ROOT/lib/doctor.sh"
  [[ "$output" == *"FAIL  keyed: broken"* ]]
  [ "$status" -eq 1 ]
}

@test "updates section reports auto-update off by default" {
  run bash "$ROOT/lib/doctor.sh"
  [[ "$output" == *"auto-update off ([update].auto)"* ]]
}

@test "notes an ejected copy whose upstream changed since the eject" {
  mkdir -p "$T/install/daemons"
  cp -R "$T/install/catalog/plain" "$T/install/daemons/plain"
  printf '{"source": "dAImon", "path": "catalog/plain", "hash": "sha256:old"}\n' \
    > "$T/install/daemons/plain/.origin.json"
  run bash "$ROOT/lib/doctor.sh"
  [[ "$output" == *"ejected daemons"* ]]
  [[ "$output" == *"note  plain (local): upstream changed — see: daimon diff plain"* ]]
}

@test "no ejected-daemons section when nothing is ejected" {
  run bash "$ROOT/lib/doctor.sh"
  [[ "$output" != *"ejected daemons"* ]]
}
