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
# Consecutive-stuck counter for the launch circuit breaker. Written by launch.sh,
# read by run.sh, cleared by deleting the file.
stuck_file()      { echo "$DAIMON_STATE_DIR/runtime/$1.stuck"; }
# Per-item overrides of a daemon's round cap, as {"<item>": <max>}. Machine-local
# and set by hand — the point is to loosen the cap on one PR while you are
# watching it, without raising it for everything overnight.
round_caps_file() { echo "$DAIMON_STATE_DIR/runtime/$1.round-caps.json"; }
# Per-item exclusions, as {"<item>": true}. The counterpart to a repo-side opt-out
# label: same effect, but it stays on this machine and needs no write access to
# anything shared. A daemon that reads one should honour both.
skips_file()      { echo "$DAIMON_STATE_DIR/runtime/$1.skips.json"; }

# load_json_object <path> -> the file's JSON object on stdout, or {} when the
# file is missing, unreadable, or not an object. The object counterpart to
# load_seen_state, whose {} is [].
load_json_object() {
  [ -f "$1" ] || { printf '{}'; return; }
  jq -c 'if type == "object" then . else {} end' "$1" 2>/dev/null || printf '{}'
}
# Consecutive stuck runs that open the breaker. Shared so launch.sh notifies on
# the same threshold run.sh refuses to launch on.
STUCK_CIRCUIT_K=2

# notify <message> -> best-effort out-of-band alert. Runs the optional executable
# at ~/.config/daimon/notify (Slack webhook, osascript, ntfy — whatever you put
# there) with the message as $1. A silent no-op when absent, and never fails the
# caller: a broken notifier must not take a daemon down with it. Used where a
# human would otherwise never learn something stopped.
notify() {
  local hook="${DAIMON_NOTIFY_HOOK:-$HOME/.config/daimon/notify}"
  [ -x "$hook" ] || return 0
  "$hook" "$1" >/dev/null 2>&1 || true
}
records_dir()     { echo "$DAIMON_STATE_DIR/state"; }
state_file()      { echo "$DAIMON_STATE_DIR/state/$1.json"; }
mcp_dir()         { echo "$DAIMON_STATE_DIR/mcp"; }
mcp_config_file() { echo "$(mcp_dir)/$1.json"; }
prompts_dir()     { echo "$DAIMON_STATE_DIR/prompts"; }

ensure_state_dirs() {
  mkdir -p "$(logs_dir)" "$(transcripts_dir)" "$(queues_dir)" "$(runtime_dir)" "$(records_dir)" "$(mcp_dir)" "$(prompts_dir)"
}

# load_seen_state <state-file-path> -> the file's JSON array on stdout, or [] if the
# file is missing or not valid JSON. A daemon's skill writes this record; its gate
# reads it to skip work already handled. Source-agnostic, so it lives here next to
# state_file() rather than in any one profile.
load_seen_state() {
  local f="$1"
  [ -f "$f" ] || { printf '[]'; return; }
  # Always hand back a FLAT ARRAY of records. A skill may keep one list or
  # several — acr-fixer writes {"rounds": [...], "watermarks": [...]} — and a
  # gate that iterates the object instead gets its two arrays as elements, so
  # every `.number` lookup silently misses and nothing is ever deduped. The
  # framework does not dictate the file's shape, so it normalises here instead.
  jq -c '
    if type == "array" then .
    elif type == "object" then ([ .[] | select(type == "array") ] | add // [])
    else [] end
  ' "$f" 2>/dev/null || printf '[]'
}

now_epoch() { date +%s; }
