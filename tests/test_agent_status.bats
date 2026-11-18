#!/usr/bin/env bats
# report_agent_status: pipes this machine's daemon status JSON into
# [status].command, best-effort. launchctl and tmux are stubs.

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  T="$BATS_TEST_TMPDIR"
  mkdir -p "$T/install/catalog/watch/skill" "$T/install/catalog/quiet/skill" "$T/state/logs" "$T/bin"
  ln -s "$ROOT/lib" "$T/install/lib"
  ln -s "$ROOT/profiles" "$T/install/profiles"
  printf '#!/usr/bin/env bash\nprintf -- "-\\t0\\tcom.t.watch\\n"\n' > "$T/bin/launchctl"
  printf '#!/usr/bin/env bash\necho t-watch-claude\n' > "$T/bin/tmux"
  chmod +x "$T/bin/launchctl" "$T/bin/tmux"
  export PATH="$T/bin:$PATH"
  for d in watch quiet; do
    printf '[daemon]\ncommand = "/%s"\nschedule = { interval = 120 }\n' "$d" \
      > "$T/install/catalog/$d/daemon.toml"
    touch "$T/install/catalog/$d/skill/SKILL.md"
  done
}

write_config() {  # [status].command
  printf '[core]\nstate_dir = "%s/state"\nnamespace = "t"\ninstall_root = "%s/install"\n[status]\ncommand = "%s"\n' \
    "$T" "$T" "$1" > "$T/daimon.toml"
  export DAIMON_CONFIG="$T/daimon.toml"
}

report() {
  source "$ROOT/lib/common.sh"
  source "$ROOT/lib/logging.sh"
  source "$ROOT/lib/agent_status.sh"
  report_agent_status
}

@test "the command gets the status JSON on stdin and {seconds} filled in" {
  write_config "cat > $T/got; echo {seconds} > $T/secs"
  report
  [ "$(cat "$T/got")" = '{"agents":[{"name":"watch","state":"working"}]}' ]
  [ "$(cat "$T/secs")" = 900 ]
}

@test "a failing command is logged and never fails the caller" {
  write_config "exit 3"
  set -e
  report
  grep -q 'event=report_error msg="status command failed (exit 3)"' "$T/state/logs/agent-status.log"
}

@test "a hung command is abandoned after the timeout" {
  write_config "sleep 20"
  AGENT_STATUS_TIMEOUT=1
  start=$(date +%s)
  report
  [ $(( $(date +%s) - start )) -lt 10 ]
  grep -q 'report_error' "$T/state/logs/agent-status.log"
}

@test "no [status].command: nothing runs" {
  write_config ""
  report
  [ ! -e "$T/state/logs/agent-status.log" ]
}
