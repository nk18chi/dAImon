#!/usr/bin/env bash
# Shared bootstrap sourced by every dAImon bash component. Resolves paths from
# config.py, exports the namespace, and defines runtime-file helpers.

DAIMON_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DAIMON_CONFIG_PY="$DAIMON_LIB_DIR/config.py"

# Loads DAIMON_INSTALL_ROOT / DAIMON_STATE_DIR / DAIMON_NS / DAIMON_TIMEZONE.
eval "$(python3 "$DAIMON_CONFIG_PY" paths)"

cfg()        { python3 "$DAIMON_CONFIG_PY" "$@"; }
json_state() { python3 "$DAIMON_LIB_DIR/json_state.py" "$@"; }

session_name() {  # slug [backend]
  local slug="$1" be="${2:-}"
  if [ -n "$be" ]; then echo "${DAIMON_NS}-${slug}-${be}"; else echo "${DAIMON_NS}-${slug}"; fi
}
sentinel_file()  { echo "/tmp/${DAIMON_NS}-done-$1"; }
heartbeat_file() { echo "/tmp/${DAIMON_NS}-hb-$1"; }
wait_file()      { echo "/tmp/${DAIMON_NS}-wait-$1"; }

logs_dir()        { echo "$DAIMON_STATE_DIR/logs"; }
transcripts_dir() { echo "$DAIMON_STATE_DIR/logs/transcripts"; }
queues_dir()      { echo "$DAIMON_STATE_DIR/queues"; }
runtime_dir()     { echo "$DAIMON_STATE_DIR/runtime"; }
records_dir()     { echo "$DAIMON_STATE_DIR/state"; }
state_file()      { echo "$DAIMON_STATE_DIR/state/$1.json"; }
mcp_dir()         { echo "$DAIMON_STATE_DIR/mcp"; }
mcp_config_file() { echo "$(mcp_dir)/$1.json"; }
restricted_dir()  { echo "$(runtime_dir)/restricted/$1"; }
prompts_dir()     { echo "$DAIMON_STATE_DIR/prompts"; }

daemon_session_names() {  # slug -> bare legacy/single name, then backend-qualified names
  local slug="$1" be
  session_name "$slug"
  for be in $(cfg backends-all); do session_name "$slug" "$be"; done
}

ensure_state_dirs() {
  mkdir -p "$(logs_dir)" "$(transcripts_dir)" "$(queues_dir)" "$(runtime_dir)" "$(records_dir)" "$(mcp_dir)" "$(prompts_dir)"
}

now_epoch() { date +%s; }
