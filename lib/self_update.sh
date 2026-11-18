#!/usr/bin/env bash
# Keep this install current: `daimon update`, and hourly from the com.<ns>.update
# LaunchAgent when [update].auto is on. Same rules as the other self-updaters it
# sits beside: only a fast-forward, only to a commit whose CI passed, never a
# checkout with local changes, never a branch switch. After moving it re-runs
# `daimon install` and `daimon sync` (which also fast-forwards clean packs and
# reloads only jobs already registered), so it never schedules anything new.
# Opt out on one machine: touch ~/.daimon/no-auto-update
set -uo pipefail
DAIMON_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$DAIMON_LIB_DIR/common.sh"
# shellcheck source=logging.sh
source "$DAIMON_LIB_DIR/logging.sh"

LOG="$(logs_dir)/update.log"
mkdir -p "$(logs_dir)"
say() { log_event update "$1" "${*:2}" >> "$LOG"; echo "${*:2}"; }

# What runs after a fast-forward; tests replace it.
after_update() {
  if [ -n "${DAIMON_UPDATE_POST:-}" ]; then
    bash -c "$DAIMON_UPDATE_POST"
    return
  fi
  bash "$DAIMON_INSTALL_ROOT/bin/daimon-install" >/dev/null &&
    (cd "$DAIMON_INSTALL_ROOT" && PYTHONPATH="$DAIMON_INSTALL_ROOT" python3 -m daimon.sync >/dev/null)
}

# Packs move even when dAImon doesn't: sync fast-forwards each clean one.
sync_packs() {
  (cd "$DAIMON_INSTALL_ROOT" && PYTHONPATH="$DAIMON_INSTALL_ROOT" python3 -m daimon.sync 2>&1 | grep '^pack ' || true)
}

g() { git -C "$DAIMON_INSTALL_ROOT" "$@"; }

# All check runs on a commit finished and none failed: success, else why not.
ci_state() {  # sha
  local repo
  repo="$(cd "$DAIMON_INSTALL_ROOT" && gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)" \
    || { echo "unknown (gh unavailable)"; return; }
  # shellcheck disable=SC2016  # $c is jq's variable, not the shell's
  cd "$DAIMON_INSTALL_ROOT" && gh api "repos/$repo/commits/$1/check-runs" --jq '
    [.check_runs[] | .conclusion // "pending"] as $c
    | if ($c | length) == 0 then "missing"
      elif any($c[]; . == "pending") then "pending"
      elif all($c[]; . == "success" or . == "skipped" or . == "neutral") then "success"
      else "failed" end' 2>/dev/null || echo "unknown"
}

# Why this checkout can't move to $target, or nothing when it can.
blocker() {  # head target
  [ -z "$(g status --porcelain)" ] || { echo "local changes"; return; }
  g merge-base --is-ancestor "$1" "$2" || { echo "diverged from upstream"; return; }
  local ci; ci="$(ci_state "$2")"
  [ "$ci" = success ] || echo "CI on ${2:0:7} is $ci"
}

opted_out() {  # [--force]
  [ -e "$DAIMON_PERSONAL_DIR/no-auto-update" ] && [ "${1:-}" != "--force" ]
}

# Sets UPSTREAM to the tracking ref, or says why there is none and fails.
resolve_upstream() {
  local branch
  g rev-parse --git-dir >/dev/null 2>&1 || { say skip "install root is not a git checkout"; return 1; }
  branch="$(g rev-parse --abbrev-ref HEAD)"
  UPSTREAM="$(g rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null)" && return 0
  say skip "$branch has no upstream (merged and deleted?): git switch main to keep updating"
  return 1
}

apply_update() {  # head target
  g merge --ff-only --quiet "$2" || { say error "fast-forward failed"; return 1; }
  after_update && { say updated "updated ${1:0:7} → ${2:0:7}"; return 0; }
  say error "updated to ${2:0:7}, but install/sync failed: run daimon install && daimon sync"
  return 1
}

main() {
  if opted_out "$@"; then say skip "opted out ($DAIMON_PERSONAL_DIR/no-auto-update)"; return 0; fi
  resolve_upstream || return 0
  g fetch --quiet 2>/dev/null || { say skip "fetch failed"; return 0; }
  local head target why
  head="$(g rev-parse HEAD)"; target="$(g rev-parse "$UPSTREAM")"
  if [ "$head" = "$target" ]; then
    say current "current at ${head:0:7} ($UPSTREAM)"; sync_packs; return 0
  fi
  why="$(blocker "$head" "$target")"
  if [ -n "$why" ]; then
    say wait "not updating ${head:0:7} → ${target:0:7}: $why"; sync_packs; return 0
  fi
  apply_update "$head" "$target"
}

main "$@"
