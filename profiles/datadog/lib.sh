#!/usr/bin/env bash
# Shared helpers for the Datadog source profile: log search via the `pup` CLI, for
# discovery gates. Sourced by a daemon's discover.sh.
#
# These helpers do NOT fail closed silently. An unanswerable search and an empty
# window are both "no events" on stdout, and a gate that cannot tell them apart
# reports "nothing to do" on the day Datadog rate-limits it — logging a reassuring
# "discovery found nothing" while real work sits unseen. Observed: three searches
# in quick succession, the third answered HTTP 429, and the gate went quiet with
# two live failures in the window.
#
# So every helper still prints the safe empty value on stdout, but ALSO writes the
# reason to stderr and returns non-zero. run.sh treats any stderr from a gate as
# `discover_error` (lib/run.sh:67), so the failure surfaces loudly instead of
# looking like a quiet day. Gates need no change to benefit: their stdout
# comparison still evaluates false, and the stderr is what run.sh keys on.
#
# This matters more the less often a daemon runs. An hourly gate that loses one
# fire retries in an hour; a daily one loses the day, and the next run's lookback
# does not reach back far enough to recover what the skipped run would have seen.

# dd_log_json "<query>" "<lookback>" -> JSON array of matching log events on
# stdout; `[]` plus a stderr reason and a non-zero return when the search could
# not be answered (transport failure, auth lapse, rate limit, unparseable body).
#
# pup may print a status line — "Access token refreshed automatically" — before
# the payload, so parsing starts at the first JSON delimiter rather than at byte
# zero. Left unhandled, that banner alone makes every search on a token-refresh
# run look like an empty window: jq fails on the leading text and the old code
# swallowed it as `[]`.
dd_log_json() {
  local out body
  # --no-agent: pup auto-enables "agent mode" for AI assistants, which reshapes
  # output; the gate parses the plain JSON, so pin it off for a stable envelope.
  # stderr is folded in so a diagnostic can quote what actually came back.
  if ! out="$(pup logs search --query="$1" --from="$2" --output json --no-agent 2>&1)"; then
    printf '[]'
    printf 'dd_log_json: search failed: %s\n' "$(_dd_snip "$out")" >&2
    return 1
  fi
  body="$(printf '%s' "$out" | sed -n '/[[{]/,$p')"
  if [ -z "$body" ]; then
    printf '[]'
    printf 'dd_log_json: no JSON in search output: %s\n' "$(_dd_snip "$out")" >&2
    return 1
  fi
  if ! printf '%s' "$body" \
    | jq -ce 'if type == "array" then . elif type == "object" then (.data // []) else [] end' 2>/dev/null; then
    printf '[]'
    printf 'dd_log_json: unparseable search output: %s\n' "$(_dd_snip "$out")" >&2
    return 1
  fi
}

# dd_log_count "<query>" "<lookback>" -> integer count on stdout; `0` plus a
# non-zero return when the search could not be answered. The reason is already on
# stderr from dd_log_json, which passes through command substitution untouched.
dd_log_count() {
  local events
  events="$(dd_log_json "$1" "$2")" || { printf '0'; return 1; }
  printf '%s' "$events" | jq 'length' 2>/dev/null && return 0
  printf '0'
  printf 'dd_log_count: could not count events\n' >&2
  return 1
}

# _dd_snip <text> -> a one-line, bounded excerpt for a stderr diagnostic. Bounded
# because run.sh puts this straight into a log line, and an unbounded HTML error
# page from a proxy would bury every other event in the file.
_dd_snip() {
  printf '%s' "$1" | tr '\n' ' ' | cut -c1-200
}
