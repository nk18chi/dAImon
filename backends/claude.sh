#!/usr/bin/env bash
# Claude agent backend. Implements the contract in backends/README.md.

backend_bin() {
  echo "${DAIMON_CLAUDE_BIN:-$(command -v claude || echo claude)}"
}

backend_cli_args() {  # model danger(0/1) session_name -> args after the binary
  local model="$1" danger="$2" session_name="$3" flag="" mcp=""
  # Without danger, pin the permission mode explicitly rather than inheriting the
  # user's default. That default is `manual`, which cannot work unattended: the
  # first write raises a prompt no one is present to answer, the heartbeat stops,
  # and the run is reaped as stuck. `auto` classifies each call instead —
  # approving work inside the project and still refusing scope escalation and
  # irreversible destruction. `permissions.defaultMode` in a project settings file
  # does NOT do this; Claude Code honours it from user/policy settings only, so a
  # repo cannot widen its own permissions. A CLI flag is the one thing that wins.
  if [ "$danger" = "1" ]; then flag="--dangerously-skip-permissions"
  else flag="--permission-mode auto"; fi
  [ -n "${DAIMON_MCP_CONFIG:-}" ] && mcp="--mcp-config ${DAIMON_MCP_CONFIG} --strict-mcp-config"
  printf '%s --model %s -n %s %s' "$flag" "$model" "$session_name" "$mcp"
}

backend_ready_regex() {  # 1 if danger -> bypass banner, else the idle input prompt
  # Newer Claude Code UIs replace the "? for shortcuts" hint with a mode line
  # (e.g. "⏸ manual mode on · ← for agents"); accept either as the idle prompt.
  # The mode line names the active permission mode ("manual mode on", "auto mode
  # on", "plan mode on"), so a non-default `permissions.defaultMode` changes it.
  # Match the shared "mode on" suffix rather than enumerating each label — a mode
  # we fail to match makes the launcher wait out ready_timeout and boot_fail
  # without ever sending the command, which looks identical to a dead agent.
  if [ "${1:-1}" = "1" ]; then echo "bypass permissions"; else echo "for shortcuts|mode on|accept edits"; fi
}

backend_completion_mode() { echo "hook"; }
