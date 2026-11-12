#!/usr/bin/env bash
# Read, write, show, or clear a daemon's durable work-tracking record. The record
# lives at the configured state dir ($DAIMON_STATE_DIR/state/<slug>.json); this is
# the single utility that resolves that path, so a daemon's agent passes JSON, not
# a path, and can never write state into the repo it runs in.
# usage:
#   state.sh get [slug]           # raw JSON to stdout (empty if none)
#   state.sh set [slug]           # JSON from stdin, validated, atomic write
#   state.sh <slug> [--clear]     # human-readable show, or clear
set -uo pipefail
DAIMON_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DAIMON_LIB_DIR/common.sh"

_slug() {  # explicit arg, else the session's own $DAIMON_SLUG
  local s="${1:-${DAIMON_SLUG:-}}"
  [ -n "$s" ] || { echo "state: no slug given and \$DAIMON_SLUG is unset" >&2; exit 2; }
  echo "$s"
}

case "${1:-}" in
  get)
    file="$(state_file "$(_slug "${2:-}")")"
    [ -f "$file" ] && cat "$file" || true
    ;;
  set)
    file="$(state_file "$(_slug "${2:-}")")"
    input="$(cat)"
    printf '%s' "$input" | python3 -c 'import json,sys; json.load(sys.stdin)' 2>/dev/null \
      || { echo "state: refusing to write — stdin is not valid JSON" >&2; exit 2; }
    mkdir -p "$(dirname "$file")"
    tmp="$(mktemp "${file}.XXXXXX")"
    printf '%s' "$input" > "$tmp" && mv -f "$tmp" "$file"
    ;;
  "")
    echo "usage: state <slug> [--clear] | state get [slug] | state set [slug]" >&2
    exit 2
    ;;
  *)
    file="$(state_file "$1")"
    if [ "${2:-}" = "--clear" ]; then rm -f "$file" && echo "cleared $file"; exit 0; fi
    if [ -f "$file" ]; then cat "$file"; else echo "(no state yet for $1 — $file)"; fi
    ;;
esac
