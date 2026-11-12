#!/usr/bin/env bash
# Throttle gate. Caller sets DAEMON_NAME, then sources this; reads SHOULD_SKIP /
# SKIP_REASON. Levels: off | moderate | severe | halt (in runtime/throttle.json).

_throttle_file() { echo "$(runtime_dir)/throttle.json"; }
_fires_file()    { echo "$(runtime_dir)/throttle-fires.json"; }

throttle_level() {  # echoes the active level, honoring expiry
  local file level exp
  file="$(_throttle_file)"
  level="$(json_state get "$file" level off)"
  exp="$(json_state get "$file" expires_at 0)"; exp="${exp%.*}"
  case "$exp" in ''|*[!0-9]*) exp=0 ;; esac  # any non-numeric reads as "no expiry"
  if [ "${exp:-0}" -gt 0 ] && [ "$(now_epoch)" -gt "$exp" ]; then echo off; else echo "$level"; fi
}

_in_list() {  # value cfg-key
  local v="$1" key="$2" item
  for item in $(cfg get "$key" 2>/dev/null); do [ "$item" = "$v" ] && return 0; done
  return 1
}

_bump_fire() {  # daemon -> echoes the new fire count
  json_state incr "$(_fires_file)" "$1"
}

SHOULD_SKIP=0
SKIP_REASON=""
{
  level="$(throttle_level)"
  if _in_list "$DAEMON_NAME" throttle.exempt; then
    :
  elif [ "$level" = "off" ]; then
    :
  elif [ "$level" = "halt" ]; then
    # A provider-cap halt predating fallback configuration must not prevent the
    # fallback path from ever launching. Only bypass the matching detector-made
    # halt; manual and unrelated halt reasons retain their normal behavior.
    primary="$(cfg daemon "$DAEMON_NAME" backend 2>/dev/null || true)"
    fallback="$(cfg daemon "$DAEMON_NAME" fallback_backend 2>/dev/null || true)"
    reason="$(json_state get "$(_throttle_file)" reason "")"
    if [ -n "$fallback" ] && [ "$reason" = "$primary usage limit detected in transcript" ]; then
      :
    else
      SHOULD_SKIP=1; SKIP_REASON="throttle=halt: skipping $DAEMON_NAME"
    fi
  else
    mod="$(cfg get throttle.moderate_mod)"
    if [ "$level" = "severe" ] && ! _in_list "$DAEMON_NAME" throttle.severe_critical; then
      mod="$(cfg get throttle.severe_mod)"
    fi
    count="$(_bump_fire "$DAEMON_NAME")"
    if [ $(( count % mod )) -ne 0 ]; then
      SHOULD_SKIP=1; SKIP_REASON="throttle=$level: $DAEMON_NAME fire $count not a multiple of $mod"
    fi
  fi
}
