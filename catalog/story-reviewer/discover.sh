#!/usr/bin/env bash
# Gate for story-reviewer: launch when an un-assessed story belonging to the
# configured owner sits in the intake and hasn't already been reviewed unchanged.
#
# Intake (union, each owner-scoped, open, not skipped, no assessment label yet):
#   1. stories in the triage state;
#   2. stories carrying any of $DAIMON_INPUT_INTAKE_LABELS (any state but
#      in-progress), minus those carrying any $DAIMON_INPUT_INTAKE_EXCLUDE_LABELS;
#   3. every story in an open epic labelled with the ready label (epic opt-in);
#   4. when $DAIMON_INPUT_INTAKE_UNSTARTED is on, every not-yet-started story,
#      minus the excluded labels.
#
# A story already recorded in the state file with the same updated_at is dropped:
# the skill reviewed it and nothing changed since (e.g. a human removed the
# label on purpose). Without that, such a story keeps the gate open every run.
set -uo pipefail

# dAImon exports this when it runs the gate; fall back to the `daimon` on PATH.
DAIMON_INSTALL_ROOT="${DAIMON_INSTALL_ROOT:-$(cd "$(dirname "$(readlink -f "$(command -v daimon)")")/.." && pwd)}"
source "$DAIMON_INSTALL_ROOT/lib/common.sh"
source "$DAIMON_INSTALL_ROOT/profiles/shortcut/lib.sh"

if shortcut_marker_mode; then
  # Un-assessed = status field unset; searches can't see it, so filter results.
  open="!label:\"$DAIMON_INPUT_SKIP_LABEL\" !is:done !is:archived$(shortcut_exclusions)"
  ids() { shortcut_marked_ids "" "$1"; }
else
  open="!label:\"$DAIMON_INPUT_READY_LABEL\" !label:\"$DAIMON_INPUT_ASSIST_LABEL\" \
    !label:\"$DAIMON_INPUT_HUMAN_LABEL\" !label:\"$DAIMON_INPUT_SKIP_LABEL\" \
    !is:done !is:archived$(shortcut_exclusions)"
  ids() { shortcut_owner_ids "$1"; }
fi
active="$open !state:\"$DAIMON_INPUT_IN_PROGRESS_STATE\""

drop=""
for l in ${DAIMON_INPUT_INTAKE_EXCLUDE_LABELS:-}; do drop="$drop !label:\"$l\""; done

candidates="$(
  {
    ids "state:\"$DAIMON_INPUT_TRIAGE_STATE\" $open" || exit 1
    for l in ${DAIMON_INPUT_INTAKE_LABELS:-}; do
      ids "label:\"$l\" $active$drop" || exit 1
    done
    for e in $(shortcut_labelled_epics "$DAIMON_INPUT_READY_LABEL"); do
      ids "epic:$e $active" || exit 1
    done
    if [ "${DAIMON_INPUT_INTAKE_UNSTARTED:-0}" = "1" ]; then
      ids "!is:started $open$drop" || exit 1
    fi
  } | sort -u
)" || exit 1

unseen="$(printf '%s\n' "$candidates" | shortcut_unseen "$(state_file story-reviewer)")"
n=$(printf '%s' "$unseen" | grep -c .)
[ -n "${DAIMON_GATE_NOTE:-}" ] && printf '%s to review, %s per run' "$n" \
  "${DAIMON_INPUT_MAX_PER_RUN:-?}" > "$DAIMON_GATE_NOTE"
[ -n "$unseen" ]
