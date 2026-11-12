#!/usr/bin/env bash
# Gate for work-queue: launch when there's an AI-ready story (labelled, not
# skipped, not already in progress) owned by the configured owner AND open PRs
# are under the cap. Story search comes from the source profile; PR count from
# gh (current repo).
set -uo pipefail

source "$(dirname "$0")/../../profiles/shortcut/lib.sh"
source "$(dirname "$0")/../../profiles/github/lib.sh"

base="label:\"$DAIMON_INPUT_READY_LABEL\" \
  !label:\"$DAIMON_INPUT_SKIP_LABEL\" !state:\"$DAIMON_INPUT_IN_PROGRESS_STATE\"\
$(shortcut_exclusions)"

ready=$(shortcut_owner_count "$base") || exit 1

open_prs=$(gh_search_pr_count --author=@me --state=open)

[ "${ready:-0}" -gt 0 ] && [ "${open_prs:-0}" -lt "${DAIMON_INPUT_MAX_OPEN_PRS:-2}" ]
