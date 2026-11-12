#!/usr/bin/env bash
# Discovery gate for slack-standup. Exit 0 to launch, non-zero to skip.
# The schedule fires once daily; this gate adds the two conditions the
# schedule can't express: weekdays only, and at-most-once per day (launchd
# re-fires missed jobs on wake). The skill records the date it posted in the
# state file; DAIMON_INPUT_TZ must match the schedule's tz.
set -uo pipefail

source "$(dirname "$0")/../../lib/common.sh"

tz="${DAIMON_INPUT_TZ:-America/New_York}"

dow="$(TZ="$tz" date +%u)"
[ "$dow" -le 5 ] || exit 1

today="$(TZ="$tz" date +%F)"
last="$(jq -r '.last_posted // empty' "$(state_file slack-standup)" 2>/dev/null)"
[ "$last" != "$today" ]
