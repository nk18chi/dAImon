#!/usr/bin/env bash
# Per-item exclusions from a daemon's work.
#
# Some items should never be touched: a PR you are hand-editing, a spike you do
# not want committed to, one whose reviewer wants the last word. The daemon's
# repo-side opt-out label already says this, but saying it there means writing to
# something your teammates share, and the reason is usually nobody's business but
# yours. This says the same thing on this machine only.
#
# A skip is absolute — the gate drops the item before any of its sources look at
# it — which is the difference between this and a round cap of 0. A cap bounds
# one source; a skip removes the item.
#
# usage: skips.sh <slug>                  list current skips
#        skips.sh <slug> <item>           skip an item
#        skips.sh <slug> <item> --clear   stop skipping one
#        skips.sh <slug> --clear          stop skipping everything
set -uo pipefail

DAIMON_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DAIMON_LIB_DIR/common.sh"

SLUG="${1:?usage: skips.sh <slug> [<item> [--clear]|--clear]}"
FILE="$(skips_file "$SLUG")"
ITEM="${2:-}"
ARG3="${3:-}"

write_skips() {
  ensure_state_dirs
  printf '%s\n' "$1" > "$FILE"
}

if [ "$ITEM" = "--clear" ]; then
  rm -f "$FILE"
  echo "cleared all skips for $SLUG"
  exit 0
fi

if [ -z "$ITEM" ]; then
  skips="$(load_json_object "$FILE")"
  if [ "$skips" = "{}" ]; then
    echo "(no skips for $SLUG — every eligible item is in scope)"
  else
    printf '%s' "$skips" | jq -r 'keys_unsorted[] | "  \(.)"'
  fi
  exit 0
fi

case "$ITEM" in
  ''|*[!0-9]*)
    echo "item must be a positive integer, got: $ITEM" >&2
    exit 2 ;;
esac

if [ "$ARG3" = "--clear" ]; then
  write_skips "$(load_json_object "$FILE" | jq -c --arg k "$ITEM" 'del(.[$k])')"
  echo "$SLUG no longer skips $ITEM"
  exit 0
fi

write_skips "$(load_json_object "$FILE" | jq -c --arg k "$ITEM" '.[$k] = true')"
echo "$SLUG will skip $ITEM (undo with: daimon skip $SLUG $ITEM --clear)"
