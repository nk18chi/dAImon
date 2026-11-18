#!/usr/bin/env bats
# A pack daemon's gate runs from the pack, finding dAImon's libs through the
# DAIMON_INSTALL_ROOT / DAIMON_DAEMON_DIR that run.sh exports.

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  T="$(cd "$BATS_TEST_TMPDIR" && pwd -P)"
  mkdir -p "$T/install/catalog" "$T/pack/daemons/report/skill" "$T/state"
  ln -s "$ROOT/lib" "$T/install/lib"
  ln -s "$ROOT/profiles" "$T/install/profiles"
  printf '[core]\nstate_dir = "%s/state"\nnamespace = "t"\ninstall_root = "%s/install"\n[packs]\npaths = ["%s/pack"]\n' \
    "$T" "$T" "$T" > "$T/daimon.toml"
  export DAIMON_CONFIG="$T/daimon.toml"
  printf '[daemon]\ncommand = "/report"\nschedule = { interval = 600 }\n' > "$T/pack/daemons/report/daemon.toml"
  touch "$T/pack/daemons/report/skill/SKILL.md"
  cat > "$T/pack/daemons/report/discover.sh" <<'GATE'
source "$DAIMON_INSTALL_ROOT/lib/common.sh"
echo "$DAIMON_DAEMON_DIR $(session_name report)" > "$GATE_OUT"
exit 1
GATE
  export GATE_OUT="$T/gate.out"
}

@test "run.sh finds a pack daemon's gate and it can source dAImon's libs" {
  run bash "$ROOT/lib/run.sh" report
  [ "$(cat "$GATE_OUT")" = "$T/pack/daemons/report t-report" ]
}

@test "config resolves the pack folder" {
  [ "$(python3 "$ROOT/lib/config.py" daemon-dir report)" = "$T/pack/daemons/report" ]
}
