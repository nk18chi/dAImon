#!/usr/bin/env bash
# SessionEnd hook: append one line per ended Claude session to the standup
# worklog (~/.claude/standup/worklog.jsonl). A standup skill can read this to
# surface work that never became a PR or ticket — the transcript_path lets it
# open the session for a gist. Daemon sessions are excluded (DAIMON_SENTINEL
# is exported by dAImon's launcher), so the worklog holds only the operator's
# own sessions. Installed by `daimon install --worklog`.
set -uo pipefail

[ -n "${DAIMON_SENTINEL:-}" ] && exit 0

input="$(cat)"
cwd="$(jq -r '.cwd // empty' <<<"$input")"
branch="$(git -C "${cwd:-/}" branch --show-current 2>/dev/null || true)"

dir="$HOME/.claude/standup"
mkdir -p "$dir"
jq -c --arg ts "$(date -u +%FT%TZ)" --arg branch "$branch" \
  '{ts: $ts, cwd: .cwd, branch: $branch, session_id: .session_id, transcript_path: .transcript_path}' \
  <<<"$input" >> "$dir/worklog.jsonl"
