#!/usr/bin/env bash
# Gate for dependency-reviewer: fire when a dependency-bot PR (from bot_author)
# is open and hasn't been handled at its current head commit. The skill records
# each acted-on PR as {number, headSha} in the state file; those are skipped, so
# a lingering bump PR left for a human doesn't relaunch the agent every tick.
# Runs inside working_dir, so gh targets the current repo. Fails closed (no gh,
# no auth) to "skip", the safe default.
set -uo pipefail

# dAImon exports this when it runs the gate; fall back to the `daimon` on PATH.
DAIMON_INSTALL_ROOT="${DAIMON_INSTALL_ROOT:-$(cd "$(dirname "$(readlink -f "$(command -v daimon)")")/.." && pwd)}"
source "$DAIMON_INSTALL_ROOT/lib/common.sh"
source "$DAIMON_INSTALL_ROOT/profiles/github/lib.sh"

seen="$(load_seen_state "$(state_file dependency-reviewer)")"
prs="$(gh_pr_json --author "$DAIMON_INPUT_BOT_AUTHOR" --state open --json number,headRefOid)"

printf '%s' "$prs" | jq -e --argjson seen "$seen" '
  [ .[] | select(. as $p
    | ($seen | any((.number == $p.number) and (.headSha == $p.headRefOid))) | not)
  ] | length > 0
' >/dev/null
