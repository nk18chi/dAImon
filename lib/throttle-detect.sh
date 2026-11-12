#!/usr/bin/env bash
# Post-run quota auto-throttle: if the captured transcript shows the agent hit a
# usage limit, set throttle=halt until the reset time (or one hour out).
# Reads $DAIMON_TRANSCRIPT. Sourced/run after common.sh is available on PATH.
set -uo pipefail

DAIMON_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DAIMON_LIB_DIR/common.sh"
source "$DAIMON_LIB_DIR/backend-status.sh"

BACKEND="${1:-unknown}"
[ -f "${DAIMON_TRANSCRIPT:-}" ] || exit 0

if backend_is_exhausted "$BACKEND" "$DAIMON_TRANSCRIPT"; then
  ensure_state_dirs
  f="$(runtime_dir)/throttle.json"; now="$(now_epoch)"
  rm -f "$f"
  json_state set "$f" level halt
  json_state set "$f" set_at "$now"
  json_state set "$f" expires_at "$(( now + 3600 ))"
  json_state set "$f" reason "$BACKEND usage limit detected in transcript"
fi
