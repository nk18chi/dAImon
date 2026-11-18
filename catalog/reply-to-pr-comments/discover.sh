#!/usr/bin/env bash
# Discovery gate for reply-to-pr-comments. Exit 0 to launch, non-zero to skip.
# Coarse gate: launch when any open PR exists; the prompt does the precise
# "new human reply to a bot comment" filtering. gh targets the current repo.
set -uo pipefail

# dAImon exports this when it runs the gate; fall back to the `daimon` on PATH.
DAIMON_INSTALL_ROOT="${DAIMON_INSTALL_ROOT:-$(cd "$(dirname "$(readlink -f "$(command -v daimon)")")/.." && pwd)}"
source "$DAIMON_INSTALL_ROOT/profiles/github/lib.sh"

count=$(gh_pr_count --state open)

[ "${count:-0}" -gt 0 ]
