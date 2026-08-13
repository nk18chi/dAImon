#!/usr/bin/env bash
# Per-item overrides of a daemon's round cap.
#
# The cap exists so an unattended run cannot loop forever on one item. That is
# the right default overnight, and the wrong one when you are sitting in front
# of it and want a particular PR carried further. This raises the cap for one
# item only, on this machine only, and leaves the daemon's default untouched.
#
# An override may name a reviewer, because the cap itself is per reviewer: your
# own instance being nine rounds deep says nothing about a colleague's that has
# just started. Keys are "<item>" for every reviewer on it, or "<item>:<who>" for
# one. The more specific key wins.
#
# usage: round-caps.sh <slug>                          list current overrides
#        round-caps.sh <slug> <item> <max>             set, all reviewers
#        round-caps.sh <slug> <item> <who> <max>       set, one reviewer
#        round-caps.sh <slug> <item> [<who>] --clear   remove one
#        round-caps.sh <slug> --clear                  remove all
set -uo pipefail

DAIMON_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DAIMON_LIB_DIR/common.sh"

SLUG="${1:?usage: round-caps.sh <slug> [<item> [<who>] <max>|--clear]}"
FILE="$(round_caps_file "$SLUG")"
ITEM="${2:-}"
ARG3="${3:-}"
ARG4="${4:-}"

read_caps() {
  [ -f "$FILE" ] || { printf '{}'; return; }
  jq -c 'if type == "object" then . else {} end' "$FILE" 2>/dev/null || printf '{}'
}

write_caps() {
  ensure_state_dirs
  printf '%s\n' "$1" > "$FILE"
}

if [ "$ITEM" = "--clear" ]; then
  rm -f "$FILE"
  echo "cleared all round-cap overrides for $SLUG"
  exit 0
fi

if [ -z "$ITEM" ]; then
  caps="$(read_caps)"
  if [ "$caps" = "{}" ]; then
    echo "(no round-cap overrides for $SLUG — using the daemon's max_rounds)"
  else
    printf '%s' "$caps" | jq -r 'to_entries[] | "  \(.key)\t\(.value)"'
  fi
  exit 0
fi

# Four arguments means a reviewer was named; three means the whole item.
KEY="$ITEM"
VALUE="$ARG3"
if [ -n "$ARG4" ]; then
  KEY="$ITEM:$ARG3"
  VALUE="$ARG4"
fi

if [ "$VALUE" = "--clear" ]; then
  write_caps "$(read_caps | jq -c --arg k "$KEY" 'del(.[$k])')"
  echo "cleared round-cap override for $SLUG $KEY"
  exit 0
fi

case "$VALUE" in
  ''|*[!0-9]*)
    echo "max must be a positive integer, got: ${VALUE:-<missing>}" >&2
    exit 2 ;;
esac
[ "$VALUE" -gt 0 ] || { echo "max must be greater than 0" >&2; exit 2; }

write_caps "$(read_caps | jq -c --arg k "$KEY" --argjson v "$VALUE" '.[$k] = $v')"
echo "$SLUG $KEY: round cap set to $VALUE (clear with: daimon rounds $SLUG ${KEY/:/ } --clear)"
