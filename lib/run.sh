#!/usr/bin/env bash
# Generic per-daemon wrapper invoked by launchd (or `daimon run <slug>`):
# gate on throttle, check the inbox, gate on hourly budget, run the daemon's
# discovery step, and launch the agent only if there is work.
set -uo pipefail

SLUG="${1:?usage: run.sh <slug>}"
DAIMON_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DAIMON_LIB_DIR/common.sh"
source "$DAIMON_LIB_DIR/logging.sh"
source "$DAIMON_LIB_DIR/schedule.sh"
ensure_state_dirs
OPLOG="$(logs_dir)/$SLUG.log"

cd "$(cfg daemon "$SLUG" working_dir)" || cd "$DAIMON_INSTALL_ROOT" || exit 1

DAEMON_NAME="$SLUG" source "$DAIMON_LIB_DIR/throttle.sh"
if [ "$SHOULD_SKIP" -eq 1 ]; then log_event "$SLUG" skip "$SKIP_REASON" >> "$OPLOG"; exit 0; fi

# Circuit breaker: after STUCK_CIRCUIT_K consecutive reaped-as-stuck runs, stop
# launching until a human clears it. A run stalled on an unanswered permission
# prompt is reaped exactly like any other stall and leaves no state record, so
# the gate would find the same work and relaunch into the same wall every fire.
# Deliberately not self-healing — whatever blocked the agent needs a person.
# `daimon launch <slug>` still bypasses this, and a clean finish resets it.
# STUCK_CIRCUIT_K comes from common.sh; launch.sh notifies on the same threshold.
STUCK_FILE="$(stuck_file "$SLUG")"
if [ "$(cat "$STUCK_FILE" 2>/dev/null || echo 0)" -ge "$STUCK_CIRCUIT_K" ]; then
  log_event "$SLUG" skip "circuit open: $STUCK_CIRCUIT_K consecutive stuck runs; not launching. Clear with: rm $STUCK_FILE" >> "$OPLOG"
  exit 0
fi

DAEMON_NAME="$SLUG" source "$DAIMON_LIB_DIR/inbox.sh"
if [ "${HAS_INBOX_MESSAGES:-0}" -gt 0 ]; then
  log_event "$SLUG" inbox "$HAS_INBOX_MESSAGES message(s); launching" >> "$OPLOG"
  exec bash "$DAIMON_LIB_DIR/launch.sh" "$SLUG"
fi

# Soft hourly cost cap on autonomous (discovery-driven) launches. Sits after the
# inbox check so an explicitly queued message is never deferred; the count is
# recorded in launch.sh's budget_record.
source "$DAIMON_LIB_DIR/budget.sh"
budget_check "$SLUG"
if [ "${BUDGET_OVER:-0}" -eq 1 ]; then log_event "$SLUG" skip "$BUDGET_REASON" >> "$OPLOG"; exit 0; fi

# A daemon with a `role` runs on one machine at a time (e.g. one Datadog
# reviewer per team). After the inbox, so an explicitly queued command always
# runs; after the budget, so a machine over budget stops asking and lets go.
source "$DAIMON_LIB_DIR/role.sh"
role_check "$SLUG"
if [ "$ROLE_SKIP" -eq 1 ]; then
  log_event "$SLUG" "$ROLE_EVENT" "$ROLE_REASON" >> "$OPLOG"
  [ "$ROLE_EVENT" = config_error ] && exit 1
  exit 0
fi

# daemons/<slug>, daemons/<slug>.local, or a pack's daemons/ (config.py decides).
DDIR="$(cfg daemon-dir "$SLUG")"
DISCOVER="$DDIR/discover.sh"
# A gate outside the install root (a pack's) finds dAImon's libs through these.
export DAIMON_INSTALL_ROOT DAIMON_DAEMON_DIR="$DDIR"
if [ -f "$DISCOVER" ]; then
  set -a; eval "$(cfg env "$SLUG")"; set +a

  # Preflight: every required input must be configured (non-empty) before the
  # gate runs. A missing input otherwise crashes discover.sh under `set -u`,
  # which exits 1 — indistinguishable from "no work" — so the daemon would skip
  # silently and forever. Catch it here with a clear, loud reason instead. The
  # emptiness rule lives in config.py so it matches `daimon config validate`.
  if ! missing="$(cfg validate-inputs "$SLUG")"; then
    log_event "$SLUG" config_error "required input(s) empty: $missing; not launching" >> "$OPLOG"
    exit 1
  fi

  # Run the gate, separating a genuine failure from an honest "no work":
  #   exit 0                  -> work found, launch the agent
  #   exit 1 with clean stderr -> nothing to do, skip until next run
  #   any stderr, or exit >=2  -> the gate itself errored; surface it loudly
  derr="$(mktemp "${TMPDIR:-/tmp}/daimon-discover.XXXXXX")"
  # A gate may leave a one-line summary of what it found (ids, counts) in
  # $DAIMON_GATE_NOTE; it is appended to the decision logged below.
  DAIMON_GATE_NOTE="$(mktemp "${TMPDIR:-/tmp}/daimon-note.XXXXXX")"; export DAIMON_GATE_NOTE
  # A gate may ask to resume an earlier agent session: line 1 the session id,
  # line 2 the command to type into it.
  DAIMON_GATE_RESUME="$(mktemp "${TMPDIR:-/tmp}/daimon-resume.XXXXXX")"; export DAIMON_GATE_RESUME
  bash "$DISCOVER" 2>"$derr"; rc=$?
  errtext="$(cat "$derr")"; rm -f "$derr"
  note="$(head -c 600 "$DAIMON_GATE_NOTE" 2>/dev/null)"; rm -f "$DAIMON_GATE_NOTE"
  note="${note:+: $note}"
  resume_id="$(sed -n 1p "$DAIMON_GATE_RESUME" 2>/dev/null)"
  resume_cmd="$(sed -n 2p "$DAIMON_GATE_RESUME" 2>/dev/null)"; rm -f "$DAIMON_GATE_RESUME"
  case "$resume_id" in
    *[!0-9a-f-]*|"") resume_id="" ;;  # only a plain session uuid is accepted
  esac
  if [ -n "$errtext" ] || [ "$rc" -ge 2 ]; then
    log_event "$SLUG" discover_error "discover.sh failed (exit $rc): ${errtext:-no stderr}" >> "$OPLOG"
    exit 1
  fi
  if [ "$rc" -eq 0 ]; then
    log_event "$SLUG" launch_decision "discovery found work$note" >> "$OPLOG"
    if [ -n "$resume_id" ] && [ -n "$resume_cmd" ]; then
      DAIMON_RESUME_SESSION="$resume_id" DAIMON_RESUME_COMMAND="$resume_cmd" \
        exec bash "$DAIMON_LIB_DIR/launch.sh" "$SLUG"
    fi
    exec bash "$DAIMON_LIB_DIR/launch.sh" "$SLUG"
  fi
  log_event "$SLUG" skip "discovery found nothing$note; $(next_run_display "$SLUG")" >> "$OPLOG"
  exit 0
fi

log_event "$SLUG" launch_decision "no discovery step; launching" >> "$OPLOG"
exec bash "$DAIMON_LIB_DIR/launch.sh" "$SLUG"
