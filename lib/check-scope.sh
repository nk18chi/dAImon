#!/usr/bin/env bash
# Fails if a branch affects workspaces outside $DAIMON_INPUT_ALLOWED_PATHS
# (space-separated path prefixes). Run from inside the worktree being checked.
#
# A monorepo that derives its build/deploy set from changed files will widen a
# release to unrelated apps on a stray edit. Such deploys run on pushes to release
# branches, not pull requests, so failing before a human merges is what prevents
# them — hence a guard rather than a post-merge report.
#
# Two ways to answer "what does this branch affect":
#   turbo — `turbo ls --affected` walks the dependency graph, so it also catches
#           an in-scope edit that fans out through a shared package into apps that
#           would then deploy. Comparing file paths alone cannot see that.
#   paths — changed files vs the allowlist. The fallback for repos without turbo.
#
# Usage: daimon check-scope [base-ref] [--paths] [--pr <url>]
#        base-ref defaults to origin/main
# Exit:  0 in scope · 1 out of scope (offending paths on stderr) · 2 cannot tell
#
# --pr takes the allowlist from whichever daemon recorded that PR in its state,
# rather than from the caller's own config. A daemon that shepherds other
# daemons' pull requests has no business-wide allowlist of its own — the scope
# belongs to the PR, so it travels with the PR.
set -uo pipefail

base=""
force_paths=0
pr=""
while [ $# -gt 0 ]; do
  case "$1" in
    --paths) force_paths=1 ;;
    --pr) shift; [ $# -gt 0 ] || { echo "check-scope: --pr needs a value" >&2; exit 2; }; pr="$1" ;;
    -*) echo "check-scope: unknown option '$1'" >&2; exit 2 ;;
    *) [ -n "$base" ] || base="$1" ;;
  esac
  shift
done
base="${base:-origin/main}"

allowed="${DAIMON_INPUT_ALLOWED_PATHS:-}"

if [ -n "$pr" ]; then
  # launch.sh exports DAIMON_STATE_DIR into every daemon session, so prefer it.
  # Sourcing common.sh re-resolves config and would overwrite an explicit value.
  if [ -n "${DAIMON_STATE_DIR:-}" ]; then
    records="$DAIMON_STATE_DIR/state"
  else
    # shellcheck source=/dev/null
    source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
    records="$(records_dir)"
  fi
  allowed="$(
    python3 - "$pr" "$records" <<'PY'
import json, pathlib, sys

pr, records = sys.argv[1], pathlib.Path(sys.argv[2])
for path in sorted(records.glob("*.json")):
    try:
        entries = json.loads(path.read_text())
    except (OSError, ValueError):
        continue
    if not isinstance(entries, list):
        continue
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("pr_url") != pr:
            continue
        scope = entry.get("allowed_paths")
        if scope:
            print(" ".join(scope) if isinstance(scope, list) else str(scope))
            sys.exit(0)
PY
  )"
  if [ -z "$allowed" ]; then
    echo "check-scope: no daemon declared a scope for $pr — nothing to enforce"
    exit 0
  fi
fi

[ -n "$allowed" ] || exit 0

merge_base="$(git merge-base "$base" HEAD 2>/dev/null)" || {
  echo "check-scope: cannot resolve a merge-base with '$base' — refusing to guess" >&2
  exit 2
}

in_scope() {
  local candidate="$1" prefix
  for prefix in $allowed; do
    case "$candidate" in "$prefix" | "$prefix"/*) return 0 ;; esac
  done
  return 1
}

TURBO=()
if [ "$force_paths" -eq 0 ] && [ -f turbo.json ] && command -v jq >/dev/null 2>&1; then
  if command -v turbo >/dev/null 2>&1; then
    TURBO=(turbo)
  elif command -v pnpm >/dev/null 2>&1; then
    TURBO=(pnpm exec turbo)
  fi
fi

if [ ${#TURBO[@]} -gt 0 ]; then
  mode="turbo"
  # The root package reports itself as "." and is not a deployable workspace.
  subjects="$(
    TURBO_TELEMETRY_DISABLED=1 TURBO_SCM_BASE="$merge_base" \
      "${TURBO[@]}" ls --affected --output json 2>/dev/null |
      jq -r '.packages.items[]?.path | select(. != "." and . != "//")' 2>/dev/null
  )" || subjects=""
  if [ -z "$subjects" ] && ! TURBO_TELEMETRY_DISABLED=1 TURBO_SCM_BASE="$merge_base" \
    "${TURBO[@]}" ls --affected --output json >/dev/null 2>&1; then
    echo "check-scope: turbo is present but failed to report affected packages" >&2
    exit 2
  fi
  noun="affected workspaces"
else
  mode="paths"
  subjects="$(
    {
      git diff --name-only "$merge_base" HEAD
      git status --porcelain -uall |
        awk '{ if ($0 ~ / -> /) { sub(/^.* -> /, ""); print } else { print substr($0, 4) } }'
    } 2>/dev/null | sort -u
  )"
  noun="changed files"
fi

violations=""
while IFS= read -r subject; do
  [ -n "$subject" ] || continue
  in_scope "$subject" || violations="$violations$subject
"
done <<< "$subjects"

if [ -n "$violations" ]; then
  echo "check-scope: FAIL [$mode] — $noun outside the allowed paths ($allowed):" >&2
  printf '%s' "$violations" | sed 's/^/  /' >&2
  if [ "$mode" = "paths" ]; then
    workspaces="$(printf '%s' "$violations" |
      awk -F/ '$1 == "apps" || $1 == "packages" { print $1"/"$2 }' | sort -u)"
    if [ -n "$workspaces" ]; then
      echo "check-scope: these workspaces would be pulled into the build:" >&2
      printf '%s' "$workspaces" | sed 's/^/  /' >&2
    fi
  fi
  exit 1
fi

echo "check-scope: OK [$mode] — nothing outside: $allowed"
