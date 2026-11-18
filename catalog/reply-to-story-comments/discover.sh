#!/usr/bin/env bash
# Gate for reply-to-story-comments: launch when an owner-scoped story is sitting in
# the awaiting-input state (carries the assist label) — that's the canonical "a
# human reply is expected on a bot comment" signal. Coarse on purpose: the prompt
# does the precise "new human reply after my last bot comment, not yet processed"
# filtering against the state file. Story search comes from the shortcut profile;
# excluded epics, objectives and labels never open the gate.
set -uo pipefail

# dAImon exports this when it runs the gate; fall back to the `daimon` on PATH.
DAIMON_INSTALL_ROOT="${DAIMON_INSTALL_ROOT:-$(cd "$(dirname "$(readlink -f "$(command -v daimon)")")/.." && pwd)}"
source "$DAIMON_INSTALL_ROOT/profiles/shortcut/lib.sh"

if shortcut_marker_mode; then
  ids=$(shortcut_marked_ids "$DAIMON_INPUT_STATUS_ASSIST" \
    "!label:\"$DAIMON_INPUT_SKIP_LABEL\" !is:done !is:archived$(shortcut_exclusions)") || exit 1
  count=$(printf '%s' "$ids" | grep -c .)
else
  base="label:\"$DAIMON_INPUT_ASSIST_LABEL\" !label:\"$DAIMON_INPUT_SKIP_LABEL\"$(shortcut_exclusions)"
  count=$(shortcut_owner_count "$base") || exit 1
fi

[ "${count:-0}" -gt 0 ]
