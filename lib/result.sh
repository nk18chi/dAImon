#!/usr/bin/env bash
# Record one outcome line (event=result) on a daemon's operational log, so the log
# says what a run actually did, not just that it ran. Agents call it once per item.
# usage: result.sh [--slug <slug>] <message...>   (slug defaults to $DAIMON_SLUG)
set -uo pipefail
DAIMON_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DAIMON_LIB_DIR/common.sh"
source "$DAIMON_LIB_DIR/logging.sh"

slug="${DAIMON_SLUG:-}"
if [ "${1:-}" = "--slug" ]; then slug="${2:-}"; shift 2 || true; fi
[ -n "$slug" ] || { echo "log: no slug given and \$DAIMON_SLUG is unset" >&2; exit 2; }
[ "$#" -gt 0 ] || { echo "usage: daimon log [--slug <slug>] <message>" >&2; exit 2; }

ensure_state_dirs
log_event "$slug" result "$*" >> "$(logs_dir)/$slug.log"
