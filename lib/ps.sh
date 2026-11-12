#!/usr/bin/env bash
# Show the process tree(s) under a daemon's agent session(s).
set -uo pipefail
DAIMON_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DAIMON_LIB_DIR/common.sh"
source "$DAIMON_LIB_DIR/reap.sh"

TARGET="${1:?usage: ps.sh <slug|all>}"

show_slug() {
  local slug="$1" sess pane
  for sess in $(daemon_session_names "$slug"); do
    tmux has-session -t "$sess" 2>/dev/null || continue
    pane=$(tmux list-panes -t "$sess" -F '#{pane_pid}' 2>/dev/null | head -1)
    echo "== $sess (pane pid $pane) =="
    for p in $(_descendants "$pane"); do
      ps -o pid,ppid,etime,%cpu,%mem,command -p "$p" 2>/dev/null | tail -n +2
    done
  done
}

if [ "$TARGET" = "all" ]; then
  for slug in $(cfg daemons); do show_slug "$slug"; done
else
  show_slug "$TARGET"
fi
