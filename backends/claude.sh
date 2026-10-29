#!/usr/bin/env bash
# Claude agent backend. Implements the contract in backends/README.md.

backend_bin() {
  echo "${DAIMON_CLAUDE_BIN:-$(command -v claude || echo claude)}"
}

backend_cli_args() {  # model danger(0/1) session_name -> args after the binary
  local model="$1" danger="$2" session_name="$3" flag="" mcp=""
  [ "$danger" = "1" ] && flag="--dangerously-skip-permissions"
  # A tools allowlist overrides danger: dontAsk denies anything unlisted instead
  # of prompting, and user-only settings keep the target repo's allow rules out.
  # DAIMON_D_TOOLS is already shell-quoted words (see config.py).
  [ -n "${DAIMON_D_TOOLS:-}" ] && flag="--permission-mode dontAsk --setting-sources user --allowedTools ${DAIMON_D_TOOLS}"
  [ -n "${DAIMON_MCP_CONFIG:-}" ] && mcp="--mcp-config ${DAIMON_MCP_CONFIG} --strict-mcp-config"
  printf '%s --model %s -n %s %s' "$flag" "$model" "$session_name" "$mcp"
}

backend_ready_regex() {  # the mode banner (allowlist, then danger), else the idle input prompt
  if [ -n "${DAIMON_D_TOOLS:-}" ]; then echo "don't ask on"
  elif [ "${1:-1}" = "1" ]; then echo "bypass permissions"
  else echo "for shortcuts"; fi
}

backend_completion_mode() { echo "hook"; }

backend_exhausted_regex() {
  echo "you('ve| have) hit your ((weekly|monthly)[[:space:]]+)?((usage|spend)[[:space:]]+)?limit"
}
