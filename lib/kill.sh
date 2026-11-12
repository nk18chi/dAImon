#!/usr/bin/env bash
# Hard-kill a daemon's run: agent session(s) + descendant tree + wrappers.
set -uo pipefail
DAIMON_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DAIMON_LIB_DIR/common.sh"
source "$DAIMON_LIB_DIR/reap.sh"

TARGET="${1:?usage: kill.sh <slug|all>}"

kill_slug() {
  local slug="$1" sess
  for sess in $(daemon_session_names "$slug"); do
    tmux has-session -t "$sess" 2>/dev/null || continue
    echo "reaping $sess"
    reap_session "$sess"
    rm -f "$(sentinel_file "$sess")" "$(heartbeat_file "$sess")" "$(wait_file "$sess")"
  done
  for pid in $(pgrep -f "lib/(run|launch)\.sh ${slug}\$" 2>/dev/null || true); do
    echo "killing wrapper pid=$pid"
    kill "$pid" 2>/dev/null
  done
}

if [ "$TARGET" = "all" ]; then
  for slug in $(cfg daemons); do kill_slug "$slug"; done
else
  kill_slug "$TARGET"
fi
