#!/usr/bin/env bash
# Backend-neutral transcript classification. Each backend owns the regex for
# messages that mean provider capacity is exhausted, keeping provider-specific
# UI text out of the launcher and throttle policy.

backend_is_exhausted() {  # backend transcript -> 0 only for a capacity failure
  local backend="$1" transcript="$2" regex
  [ -f "$transcript" ] || return 1
  regex="$({
    unset -f backend_exhausted_regex 2>/dev/null || true
    # shellcheck source=/dev/null
    source "$DAIMON_INSTALL_ROOT/backends/$backend.sh" || exit 1
    declare -F backend_exhausted_regex >/dev/null || exit 1
    backend_exhausted_regex
  })" || return 1
  [ -n "$regex" ] && grep -qiE -- "$regex" "$transcript"
}
