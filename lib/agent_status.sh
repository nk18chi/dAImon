#!/usr/bin/env bash
# Report this machine's daemon status to [status].command (JSON on its stdin; see
# lib/agent_status.py). Sourced after common.sh and logging.sh. Best-effort: a
# failing or slow command is logged and abandoned, never fails its caller.

: "${AGENT_STATUS_TIMEOUT:=30}"  # seconds before a hung command is abandoned

_bounded() {  # seconds cmd... -> runs cmd (stdin passed through), killed after seconds
  local secs="$1" pid guard rc; shift
  "$@" <&0 & pid=$!
  ( sleep "$secs"; kill "$pid" 2>/dev/null ) >/dev/null 2>&1 & guard=$!
  wait "$pid" && rc=0 || rc=$?
  kill "$guard" 2>/dev/null || true
  return "$rc"
}

report_agent_status() {
  local cmd rc log
  log="$(logs_dir)/agent-status.log"
  cmd="$(cfg status-command 2>/dev/null)" || cmd=""
  [ -n "$cmd" ] || return 0
  python3 "$DAIMON_LIB_DIR/agent_status.py" \
    | _bounded "$AGENT_STATUS_TIMEOUT" bash -c "$cmd" >/dev/null 2>&1 && rc=0 || rc=$?
  if [ "$rc" -ne 0 ]; then
    log_event status report_error "status command failed (exit $rc)" >> "$log" 2>/dev/null || true
  fi
  return 0
}
