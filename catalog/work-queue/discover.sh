#!/usr/bin/env bash
# Gate for work-queue: launch when there's an AI-ready story (labelled, not
# skipped, not yet started — so nothing in progress or review — and not done)
# owned by the configured owner, OR a stalled claim to pick back up (still
# labelled ready but sitting in the in-progress state: a finished run removes
# the label, so one that still has it died before opening its PR), AND
# the queue's own open PRs are under the cap. Story search comes from the source
# profile. The PR cap counts only daimon/* branches in the current repo
# (working_dir), so hand-authored PRs — and stale PRs in unrelated repos — never
# starve the queue.
set -uo pipefail
ready_ids="" stalled_ids=""

# dAImon exports this when it runs the gate; fall back to the `daimon` on PATH.
DAIMON_INSTALL_ROOT="${DAIMON_INSTALL_ROOT:-$(cd "$(dirname "$(readlink -f "$(command -v daimon)")")/.." && pwd)}"
source "$DAIMON_INSTALL_ROOT/profiles/shortcut/lib.sh"
source "$DAIMON_INSTALL_ROOT/profiles/github/lib.sh"

if shortcut_marker_mode; then
  # The status field carries the markers: ready = status_ready, a stalled claim
  # = still status_claimed while in the in-progress state.
  ready_ids=$(shortcut_marked_ids "$DAIMON_INPUT_STATUS_READY" \
    "!label:\"$DAIMON_INPUT_SKIP_LABEL\" !state:\"$DAIMON_INPUT_IN_PROGRESS_STATE\" \
    !is:started !is:done !is:archived$(shortcut_exclusions)") || exit 1
  stalled_ids=$(shortcut_marked_ids "$DAIMON_INPUT_STATUS_CLAIMED" \
    "!label:\"$DAIMON_INPUT_SKIP_LABEL\" state:\"$DAIMON_INPUT_IN_PROGRESS_STATE\" \
    !is:archived$(shortcut_exclusions)") || exit 1
  ready=$(printf '%s' "$ready_ids" | grep -c .)
  stalled=$(printf '%s' "$stalled_ids" | grep -c .)
else
base="label:\"$DAIMON_INPUT_READY_LABEL\" \
  !label:\"$DAIMON_INPUT_SKIP_LABEL\" !state:\"$DAIMON_INPUT_IN_PROGRESS_STATE\" \
  !is:started !is:done !is:archived\
$(shortcut_exclusions)"

ready=$(shortcut_owner_count "$base") || exit 1

stalled_q="label:\"$DAIMON_INPUT_READY_LABEL\" \
  !label:\"$DAIMON_INPUT_SKIP_LABEL\" state:\"$DAIMON_INPUT_IN_PROGRESS_STATE\" \
  !is:archived\
$(shortcut_exclusions)"
stalled=$(shortcut_owner_count "$stalled_q") || exit 1
fi

open_prs=$(gh_pr_json --author @me --state open --json headRefName \
  | jq '[.[] | select(.headRefName | startswith("daimon/"))] | length' 2>/dev/null)

note="ready ${ready:-0}${ready_ids:+ ($(printf '%s\n' "$ready_ids" | awk 'NF {printf "%ssc-%s", (n++ ? " " : ""), $1}'))}"
note="$note, stalled ${stalled:-0}${stalled_ids:+ ($(printf '%s\n' "$stalled_ids" | awk 'NF {printf "%ssc-%s", (n++ ? " " : ""), $1}'))}"
[ -n "${DAIMON_GATE_NOTE:-}" ] && printf '%s, open PRs %s/%s' "$note" "${open_prs:-0}" \
  "${DAIMON_INPUT_MAX_OPEN_PRS:-2}" > "$DAIMON_GATE_NOTE"

[ $(( ${ready:-0} + ${stalled:-0} )) -gt 0 ] && [ "${open_prs:-0}" -lt "${DAIMON_INPUT_MAX_OPEN_PRS:-2}" ]
