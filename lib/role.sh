#!/usr/bin/env bash
# Run a daemon on one machine only. A daemon with a `role` asks [roles].command
# on every run; sourced after common.sh. Sets ROLE_SKIP (1 = don't run here)
# and ROLE_REASON (for the log). Fails closed: if the answer can't be had, the
# daemon skips — two machines doing the same work is worse than a missed run.

role_check() {  # slug
  local slug="$1" cmd out rc
  ROLE_SKIP=0; ROLE_REASON=""; ROLE_EVENT=skip
  if ! cmd="$(cfg role-command "$slug" 2>&1)"; then
    ROLE_SKIP=1; ROLE_EVENT=config_error; ROLE_REASON="role: $cmd"; return
  fi
  [ -n "$cmd" ] || return 0
  out="$(bash -c "$cmd" 2>&1)" && rc=0 || rc=$?
  out="$(printf '%s' "$out" | head -n 1 | cut -c1-300)"
  case "$rc" in
    0) ;;
    1) ROLE_SKIP=1; ROLE_REASON="another machine runs this: ${out:-held elsewhere}" ;;
    *) ROLE_SKIP=1; ROLE_EVENT=role_error; ROLE_REASON="role check failed (exit $rc): ${out:-no output}" ;;
  esac
}
