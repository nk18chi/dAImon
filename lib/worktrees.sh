#!/usr/bin/env bash
# Remove a daemon's finished worktrees. A worktree is removed only when its branch
# starts with the daemon's prefix, it has no uncommitted or untracked changes, and
# every commit on it is pushed (or there are none). Anything else is kept and
# reported, so an interrupted run's edits are never lost.
# Prints one line per worktree it removed or kept.

_sweep_one() {  # repo path branch prefix base
  local repo="$1" path="$2" branch="$3" prefix="$4" base="$5" ahead
  [ -n "$path" ] && [ -n "$branch" ] || return 0
  case "$branch" in "$prefix"*) ;; *) return 0 ;; esac
  [ -d "$path" ] || return 0
  if [ -n "$(git -C "$path" status --porcelain 2>/dev/null)" ]; then
    echo "kept ${path##*/} ($branch): uncommitted changes"; return 0
  fi
  if git -C "$path" rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
    ahead="$(git -C "$path" rev-list --count '@{u}..HEAD' 2>/dev/null || echo 1)"
  else
    ahead="$(git -C "$path" rev-list --count "origin/$base..HEAD" 2>/dev/null || echo 1)"
  fi
  if [ "${ahead:-1}" != "0" ]; then
    echo "kept ${path##*/} ($branch): $ahead unpushed commit(s)"; return 0
  fi
  if git -C "$repo" worktree remove --force "$path" >/dev/null 2>&1; then
    echo "removed worktree ${path##*/} ($branch)"
  else
    echo "kept ${path##*/} ($branch): git worktree remove failed"
  fi
}

sweep_repo_worktrees() {  # repo prefix [base]
  local repo="$1" prefix="$2" base="${3:-main}" line path="" branch=""
  [ -n "$prefix" ] || return 0
  git -C "$repo" rev-parse --git-dir >/dev/null 2>&1 || return 0
  while IFS= read -r line; do
    case "$line" in
      "worktree "*) path="${line#worktree }"; branch="" ;;
      "branch refs/heads/"*) branch="${line#branch refs/heads/}" ;;
      "") _sweep_one "$repo" "$path" "$branch" "$prefix" "$base"; path=""; branch="" ;;
    esac
  done < <(git -C "$repo" worktree list --porcelain 2>/dev/null; echo)
  git -C "$repo" worktree prune 2>/dev/null || true
}

sweep_worktrees() {  # dir prefix [base] -> the dir itself if it is a repo, else each repo directly under it
  local dir="$1" prefix="$2" base="${3:-main}" sub
  [ -n "$prefix" ] && [ -d "$dir" ] || return 0
  if git -C "$dir" rev-parse --show-toplevel >/dev/null 2>&1; then
    sweep_repo_worktrees "$(git -C "$dir" rev-parse --show-toplevel)" "$prefix" "$base"
    return 0
  fi
  for sub in "$dir"/*/; do
    [ -e "$sub/.git" ] && sweep_repo_worktrees "${sub%/}" "$prefix" "$base"
  done
  return 0
}
