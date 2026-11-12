#!/usr/bin/env bash
# Discovery gate for slack-channel-watch.
#
# Scripted path (token_command configured): the gate itself polls the watched
# channels via forward.py, appends any trigger-prefixed commands to the target
# daemon's inbox, nudges the engine in the background, and reports "no work" —
# the watcher agent never launches. Errors (bad token, Slack API failure)
# surface loudly via stderr / exit >= 2.
#
# Agent fallback (token_command empty): exit 0 every tick so the session
# polls via the Slack MCP per SKILL.md.
set -uo pipefail

source "$(dirname "$0")/../../lib/common.sh"

[ -n "${DAIMON_INPUT_TOKEN_COMMAND:-}" ] || exit 0

SLACK_TOKEN="$(bash -c "$DAIMON_INPUT_TOKEN_COMMAND")" || {
  echo "token_command failed" >&2
  exit 2
}
export SLACK_TOKEN

forwarded="$(python3 "$(dirname "$0")/forward.py" \
  "$(state_file slack-channel-watch)" "$(runtime_dir)/inbox.json")" || exit 2

if [ "$forwarded" -gt 0 ]; then
  target="${DAIMON_INPUT_TARGET:-slack-commands}"
  # Double-fork: the subshell exits immediately so the nudge reparents to
  # init and survives this process (and any enclosing session) being
  # reaped — the nudge's launch.sh must outlive us to reap the engine.
  ( nohup "$DAIMON_INSTALL_ROOT/bin/daimon" run "$target" >/dev/null 2>&1 & )
fi
exit 1
