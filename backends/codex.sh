#!/usr/bin/env bash
# Codex agent backend (one-shot). Runs `codex exec` non-interactively: the
# launcher pipes the rendered skill in as the prompt over stdin and treats
# process exit as completion. Implements the contract in backends/README.md.

backend_bin() {
  echo "${DAIMON_CODEX_BIN:-$(command -v codex || echo codex)}"
}

backend_cli_args() {  # model danger(0/1) session_name -> args after the binary
  local model="$1" danger="$2" flag="" model_flag=""
  [ "$danger" = "1" ] && flag="--dangerously-bypass-approvals-and-sandbox"
  # A claude-model name (the framework default) means the daemon never set a
  # codex model; fall through to codex's own configured default rather than
  # pass an -m codex would reject.
  case "$model" in opus | sonnet | haiku | "") ;; *) model_flag="-m $model" ;; esac
  # `'"..."'` keeps the TOML quotes intact through tmux's `sh -c` so the trusted
  # path (dots/slashes) and value reach codex quoted — avoids a boot trust prompt.
  local sq="'" dq='"'
  local trust="projects.${sq}${dq}${DAIMON_D_WORKING_DIR}${dq}${sq}.trust_level=${sq}${dq}trusted${dq}${sq}"
  printf 'exec %s -c %s %s' "$flag" "$trust" "$model_flag"
}

backend_ready_regex() { echo ""; }  # one-shot: no interactive banner to wait for

backend_completion_mode() { echo "oneshot"; }

backend_exhausted_regex() {
  echo "(usage limit|rate limit|quota) (reached|exceeded)|insufficient_quota|you('ve| have) hit your ((weekly|monthly)[[:space:]]+)?((usage|rate)[[:space:]]+)?limit"
}
