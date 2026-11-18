#!/usr/bin/env bash
# Discovery gate for review-prs. Exit 0 to launch (work found), non-zero to skip.
# Fires only for a PR matching the filter that hasn't already been reviewed at its
# current head commit — the skill records reviewed PRs as {number, headSha} in the
# state file, and we skip those. This keeps the gate cheap at a tight cadence: a
# review-requested PR that lingers (flag not cleared) won't relaunch the agent every
# tick. Runs inside working_dir, so gh targets the current repo automatically.
set -uo pipefail

# dAImon exports this when it runs the gate; fall back to the `daimon` on PATH.
DAIMON_INSTALL_ROOT="${DAIMON_INSTALL_ROOT:-$(cd "$(dirname "$(readlink -f "$(command -v daimon)")")/.." && pwd)}"
source "$DAIMON_INSTALL_ROOT/lib/common.sh"
source "$DAIMON_INSTALL_ROOT/profiles/github/lib.sh"

seen="$(load_seen_state "$(state_file review-prs)")"
prs="$(gh_pr_json --search "$DAIMON_INPUT_FILTER" --json number,headRefOid)"

printf '%s' "$prs" | jq -e --argjson seen "$seen" '
  [ .[] | select(. as $p
    | ($seen | any((.number == $p.number) and (.headSha == $p.headRefOid))) | not)
  ] | length > 0
' >/dev/null
