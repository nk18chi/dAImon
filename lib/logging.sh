#!/usr/bin/env bash
# Structured operational logging, log rotation, and transcript retention.
# Sourced after common.sh (uses logs_dir / transcripts_dir / cfg).

log_event() {  # daemon event message... -> one structured line on the daemon's operational log
  local daemon="$1" event="$2"; shift 2
  # Local time, with the offset, to match every other surface: `daimon status`
  # and the TUI render "next run" from datetime.now(), and launchd fires clock
  # schedules on local time too. A UTC log was the only thing needing conversion
  # before you could line it up with the schedule that produced it.
  local ts; ts="$(date +%Y-%m-%dT%H:%M:%S%z)"
  printf '%s level=info daemon=%s event=%s msg="%s"\n' \
    "$ts" "$daemon" "$event" "$*"
}

rotate_if_large() {  # logfile
  local f="$1"
  [ -f "$f" ] || return 0
  local max keep bytes
  max="$(cfg get core.log_max_mb 2>/dev/null || echo 10)"
  keep="$(cfg get core.log_keep 2>/dev/null || echo 3)"
  bytes=$(stat -f %z "$f" 2>/dev/null || echo 0)
  if [ "$bytes" -gt $(( max * 1024 * 1024 )) ]; then
    local i
    for (( i=keep-1; i>=1; i-- )); do
      [ -f "$f.$i" ] && mv -f "$f.$i" "$f.$((i+1))"
    done
    mv -f "$f" "$f.1"
    : > "$f"
  fi
}

prune_old_transcripts() {  # delete transcripts older than core.log_retention_days
  local days dir
  days="$(cfg get core.log_retention_days 2>/dev/null || echo 14)"
  dir="$(transcripts_dir)"
  [ -d "$dir" ] || return 0
  find "$dir" -type f -mtime "+${days}" -delete 2>/dev/null || true
  # rotated operational logs past retention go too
  find "$(logs_dir)" -maxdepth 1 -type f -name '*.log.*' -mtime "+${days}" -delete 2>/dev/null || true
}

strip_chrome() {  # stdin -> stdout, drops interactive-CLI UI furniture from a transcript
  grep -vE '^(│|╭|╰|─|⏵|✻|·|\s*[⏺✓✗].*tokens|.*bypass permissions.*|.*esc to interrupt.*)' \
    2>/dev/null || cat
}
