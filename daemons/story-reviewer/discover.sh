#!/usr/bin/env bash
# Gate for story-reviewer: launch when there are un-assessed stories in triage
# (no assessment label yet, not skipped) that belong to the configured owner.
set -uo pipefail

source "$(dirname "$0")/../../profiles/shortcut/lib.sh"

base="state:\"$DAIMON_INPUT_TRIAGE_STATE\" \
  !label:\"$DAIMON_INPUT_READY_LABEL\" !label:\"$DAIMON_INPUT_ASSIST_LABEL\" \
  !label:\"$DAIMON_INPUT_HUMAN_LABEL\" !label:\"$DAIMON_INPUT_SKIP_LABEL\"\
$(shortcut_exclusions)"

count=$(shortcut_owner_count "$base") || exit 1

[ "${count:-0}" -gt 0 ]
