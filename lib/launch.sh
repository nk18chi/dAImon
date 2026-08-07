#!/usr/bin/env bash
# Generic launcher: drive a daemon's command through its configured backend(s)
# inside detached tmux sessions, blocking until each run completes or goes stuck.
# There is intentionally NO wall-clock cap — only an idle-gap (stuck_after) reaper.
set -uo pipefail

SLUG="${1:?usage: launch.sh <slug>}"
DAIMON_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DAIMON_LIB_DIR/common.sh"
source "$DAIMON_LIB_DIR/logging.sh"
source "$DAIMON_LIB_DIR/reap.sh"
source "$DAIMON_LIB_DIR/budget.sh"

ensure_state_dirs
OPLOG="$(logs_dir)/$SLUG.log"
eval "$(cfg daemon-env "$SLUG")"
COMMAND="$DAIMON_D_COMMAND"
DANGER="$DAIMON_D_DANGER"
STUCK_AFTER="$DAIMON_D_STUCK_AFTER"
WORKING_DIR="$DAIMON_D_WORKING_DIR"
READY_TIMEOUT="$DAIMON_READY_TIMEOUT"
MCP="$DAIMON_D_MCP"
read -r -a BACKENDS <<< "$DAIMON_D_BACKENDS"
MULTI=0; [ "${#BACKENDS[@]}" -gt 1 ] && MULTI=1

pane_heartbeat() {  # session heartbeat — touch heartbeat whenever the pane changes
  local sess="$1" hb="$2" prev="" cur
  while tmux has-session -t "$sess" 2>/dev/null; do
    cur=$(tmux capture-pane -p -t "$sess" 2>/dev/null | cksum)
    [ "$cur" != "$prev" ] && { : > "$hb"; prev="$cur"; }
    sleep 5
  done
}

run_one_backend() {
  local be="$1"
  # shellcheck source=/dev/null
  source "$DAIMON_INSTALL_ROOT/backends/$be.sh"
  local model session model_var
  model_var="DAIMON_D_MODEL_$(printf '%s' "$be" | tr '[:lower:]' '[:upper:]')"
  model="${!model_var}"
  if [ "$MULTI" = "1" ]; then session="$(session_name "$SLUG" "$be")"; else session="$(session_name "$SLUG")"; fi
  local mode; mode="$(backend_completion_mode)"

  local SENTINEL HEARTBEAT WAITF
  SENTINEL="$(sentinel_file "$session")"
  HEARTBEAT="$(heartbeat_file "$session")"
  WAITF="$(wait_file "$session")"
  export DAIMON_SENTINEL="$SENTINEL" DAIMON_HEARTBEAT="$HEARTBEAT" DAIMON_WAIT="$WAITF"

  budget_record "$SLUG"

  if tmux has-session -t "$session" 2>/dev/null; then
    log_event "$SLUG" skip "session $session already running" >> "$OPLOG"
    return 0
  fi

  local HBPID="" PROMPTF=""
  cleanup_be() {
    [ -n "$HBPID" ] && kill "$HBPID" 2>/dev/null
    reap_session "$session"
    rm -f "$SENTINEL" "$HEARTBEAT" "$WAITF" "$PROMPTF"
  }
  trap cleanup_be RETURN

  rm -f "$SENTINEL" "$WAITF"; : > "$HEARTBEAT"

  local mcp_file=""
  if [ -n "$MCP" ]; then
    mcp_file="$(mcp_config_file "$SLUG")"
    cfg mcp-config "$SLUG" > "$mcp_file"
  fi
  export DAIMON_MCP_CONFIG="$mcp_file"

  local bin args stdin=""
  bin="$(backend_bin)"
  args="$(backend_cli_args "$model" "$DANGER" "$session")"
  if [ "$mode" = "oneshot" ]; then
    PROMPTF="$(prompts_dir)/${SLUG}-${be}.prompt"
    cfg render-skill "$SLUG" > "$PROMPTF"
    stdin="< '$PROMPTF'"
  fi
  local tfile; tfile="$(transcripts_dir)/${SLUG}-${be}-$(date -u +%Y%m%dT%H%M%SZ).log"
  tmux new-session -d -s "$session" -c "$WORKING_DIR" -x 220 -y 50 \
    "DAIMON_SENTINEL='$SENTINEL' DAIMON_HEARTBEAT='$HEARTBEAT' DAIMON_WAIT='$WAITF' DAIMON_STATE_DIR='$DAIMON_STATE_DIR' DAIMON_SLUG='$SLUG' DAIMON_STATE_FILE='$DAIMON_STATE_DIR/state/$SLUG.json' exec '$bin' $args $stdin"
  tmux set-option -t "$session" prefix2 C-a 2>/dev/null || true
  # A oneshot process can exit before the completion loop's final capture, so
  # stream the pane to the transcript live instead of grabbing it at the end.
  if [ "$mode" = "oneshot" ]; then
    tmux pipe-pane -t "$session" "cat >> '$tfile'" 2>/dev/null || true
  fi
  log_event "$SLUG" launch "backend=$be session=$session model=$model danger=$DANGER stuck_after=$STUCK_AFTER" >> "$OPLOG"

  local regex booted=0 i
  regex="$(backend_ready_regex "$DANGER")"
  if [ "$mode" = "oneshot" ]; then
    tmux has-session -t "$session" 2>/dev/null && booted=1
  elif [ -n "$regex" ]; then
    for (( i=0; i<READY_TIMEOUT; i++ )); do
      tmux has-session -t "$session" 2>/dev/null || break
      if tmux capture-pane -p -t "$session" 2>/dev/null | grep -qE "$regex"; then booted=1; break; fi
      sleep 1
    done
  else
    sleep "$READY_TIMEOUT"
    tmux has-session -t "$session" 2>/dev/null && booted=1
  fi

  if [ "$booted" -ne 1 ]; then
    log_event "$SLUG" boot_fail "backend=$be session=$session" >> "$OPLOG"
    tmux capture-pane -p -S - -t "$session" 2>/dev/null > "$tfile"
    return 1
  fi

  rm -f "$SENTINEL" "$WAITF"; : > "$HEARTBEAT"
  if [ "$mode" = "oneshot" ]; then
    log_event "$SLUG" running "backend=$be oneshot" >> "$OPLOG"
  else
    tmux send-keys -t "$session" "$COMMAND"; sleep 0.5; tmux send-keys -t "$session" Enter
    log_event "$SLUG" running "backend=$be command=$COMMAND" >> "$OPLOG"
  fi

  if [ "$mode" = "idle" ] || [ "$mode" = "oneshot" ]; then
    pane_heartbeat "$session" "$HEARTBEAT" & HBPID=$!
  fi

  while true; do
    if [ "$mode" = "hook" ] && [ -f "$SENTINEL" ]; then
      # A clean finish clears the circuit breaker; only consecutive stucks trip it.
      rm -f "$(stuck_file "$SLUG")"
      log_event "$SLUG" "done" "sentinel backend=$be" >> "$OPLOG"; break
    fi
    tmux has-session -t "$session" 2>/dev/null || { log_event "$SLUG" "done" "session ended backend=$be" >> "$OPLOG"; break; }
    local hb_mtime hb_age
    hb_mtime=$(stat -f %m "$HEARTBEAT" 2>/dev/null || now_epoch)
    hb_age=$(( $(now_epoch) - hb_mtime ))
    if [ "$hb_age" -ge "$STUCK_AFTER" ]; then
      if [ "$mode" = "idle" ]; then log_event "$SLUG" "done" "idle ${hb_age}s backend=$be" >> "$OPLOG"
      else
        # Count consecutive stucks so run.sh can stop relaunching into the same
        # wall — an unanswered permission prompt looks exactly like this and
        # would otherwise repeat every fire, forever.
        local sf n
        sf="$(stuck_file "$SLUG")"
        n=$(( $(cat "$sf" 2>/dev/null || echo 0) + 1 ))
        echo "$n" > "$sf"
        log_event "$SLUG" stuck "no activity ${hb_age}s backend=$be consecutive=$n" >> "$OPLOG"
        # Alert once, on the run that trips it — not on every later skip, which
        # would be a notification every fire for as long as it stays open.
        if [ "$n" -eq "$STUCK_CIRCUIT_K" ]; then
          notify "dAImon: $SLUG stopped — $n consecutive stuck runs, no longer launching. Clear with: rm $sf"
        fi
      fi
      break
    fi
    sleep 15
  done

  # oneshot already streamed its transcript via pipe-pane; capturing now (session
  # gone) would only clobber it with an empty grab.
  if [ "$mode" != "oneshot" ]; then
    tmux capture-pane -p -S - -t "$session" 2>/dev/null | strip_chrome > "$tfile"
  fi
  DAIMON_TRANSCRIPT="$tfile" bash "$DAIMON_LIB_DIR/throttle-detect.sh" "$be" 2>/dev/null || true
  rotate_if_large "$OPLOG"
  return 0
}

for be in "${BACKENDS[@]}"; do
  run_one_backend "$be" || { log_event "$SLUG" chain_stop "backend $be failed" >> "$OPLOG"; break; }
done
