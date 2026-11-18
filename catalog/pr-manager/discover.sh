#!/usr/bin/env bash
# Gate for pr-manager: launch when a managed PR needs action — ready to merge
# (approved & green), conflicting, failing CI, change-requested, a green draft
# eligible for self-promotion, or a ready PR still missing its reviewers.
# Unhandled review feedback (see below) also counts, and can resume the session
# that wrote the PR so it keeps its context.
# Conflicts and failing CI count on drafts too: work-queue opens drafts and only
# a green draft is promoted, so a red draft would otherwise be stranded.
# "Managed" = a PR you authored on a daimon/* branch, or any PR carrying the
# manage label. Runs inside working_dir, so gh targets the current repo. Failing
# closed (no gh, no auth) means "skip", the safe default.
set -uo pipefail

# dAImon exports this when it runs the gate; fall back to the `daimon` on PATH.
DAIMON_INSTALL_ROOT="${DAIMON_INSTALL_ROOT:-$(cd "$(dirname "$(readlink -f "$(command -v daimon)")")/.." && pwd)}"
source "$DAIMON_INSTALL_ROOT/lib/common.sh"
source "$DAIMON_INSTALL_ROOT/profiles/github/lib.sh"

prs="$(gh_pr_json --author @me --state open \
  --json number,headRefName,reviewDecision,mergeable,isDraft,labels,statusCheckRollup,createdAt,reviewRequests,latestReviews)"


# Unhandled review feedback: a changes-requested review, or a findings comment
# from an automated reviewer (a comment containing findings_marker that doesn't
# match findings_none_regex), newer than the PR's recorded feedback_seen. It
# blocks merging, so it must launch a run even on an approved PR.
me="$(gh api user --jq .login 2>/dev/null)"
state="$(load_seen_state "$(state_file pr-manager)" 2>/dev/null)"
[ -n "$state" ] || state='{}'
pending="" deferred="" resume_id="" resume_pr=""
proj="$HOME/.claude/projects/$(pwd -P | sed 's#[^A-Za-z0-9]#-#g')"
for n in $(printf '%s' "$prs" | jq -r --arg label "$DAIMON_INPUT_MANAGE_LABEL" \
    '.[] | select((.headRefName | startswith("daimon/")) or ([.labels[].name] | index($label) != null)) | .number'); do
  latest="$(gh pr view "$n" --json reviews,comments 2>/dev/null | jq -r \
    --arg me "$me" --arg marker "${DAIMON_INPUT_FINDINGS_MARKER:-}" \
    --arg none "${DAIMON_INPUT_FINDINGS_NONE_REGEX:-}" '
    [ (.reviews[] | select(.state == "CHANGES_REQUESTED" and .author.login != $me) | .submittedAt),
      (.comments[] | select($marker != "" and .author.login != $me
        and (.body | contains($marker))
        and ($none == "" or (.body | test($none) | not))) | .createdAt) ]
    | max // ""')"
  [ -n "$latest" ] || continue
  seen="$(printf '%s' "$state" | jq -r --arg n "$n" '.prs[$n].feedback_seen // ""' 2>/dev/null)"
  [[ "$latest" > "$seen" ]] || continue
  # Resume the session that wrote the PR when its id is recorded in the body and
  # its transcript is on this machine. If that session is still running (the
  # work queue is mid-run), wait for it rather than handle the PR without it.
  sid=""
  if [ "${DAIMON_INPUT_RESUME_AUTHOR:-1}" = "1" ]; then
    sid="$(gh pr view "$n" --json body --jq .body 2>/dev/null \
      | sed -n 's/.*daimon-session: *\([0-9a-f-]\{36\}\).*/\1/p' | head -1)"
  fi
  if [ -n "$sid" ] && [ -f "$proj/$sid.jsonl" ]; then
    # Deferred PRs are also kept out of the merge check below, so they wait.
    if pgrep -f -- "$sid" >/dev/null 2>&1; then deferred="${deferred:+$deferred,}$n"; continue; fi
    [ -z "$resume_id" ] && { resume_id="$sid"; resume_pr="$n"; }
  fi
  pending="$pending #$n"
done

printf '%s' "$prs" | jq -e \
  --argjson deferred "[$deferred]" \
  --arg label "$DAIMON_INPUT_MANAGE_LABEL" \
  --arg reviewers "$DAIMON_INPUT_REVIEWERS" \
  --argjson promote "$DAIMON_INPUT_PROMOTE_DRAFTS" \
  --argjson automerge "$DAIMON_INPUT_AUTO_MERGE" \
  --argjson min_age "$DAIMON_INPUT_PROMOTE_MIN_AGE_HOURS" '
  ($reviewers | split(" ") | map(select(. != ""))) as $want
  | def managed: (.headRefName | startswith("daimon/")) or
                 ([.labels[].name] | index($label) != null);
  def checks: (.statusCheckRollup // []);
  def failing: any(checks[]; .conclusion as $c
    | ["FAILURE","CANCELLED","TIMED_OUT","ACTION_REQUIRED","STARTUP_FAILURE"]
    | index($c) != null);
  def pending: any(checks[]; (.conclusion // "") == "");
  def green: ((checks | length) > 0) and (failing | not) and (pending | not);
  def age_hours: (now - (.createdAt | fromdateiso8601)) / 3600;
  def seen: ([.reviewRequests[]?.login] + [.latestReviews[]?.author.login]);
  def actionable_ready: (.isDraft | not) and (
    (.reviewDecision == "APPROVED" and green) or
    ($automerge == 1 and green and .reviewDecision != "CHANGES_REQUESTED"
      and .mergeable != "CONFLICTING") or
    (.reviewDecision == "CHANGES_REQUESTED"));
  def needs_repair: (.mergeable == "CONFLICTING") or failing;
  def promotable_draft: ($promote == 1) and .isDraft and green
    and (.mergeable != "CONFLICTING")
    and (.reviewDecision != "CHANGES_REQUESTED")
    and (age_hours >= $min_age);
  def needs_reviewers: ($want | length > 0) and (.isDraft | not)
    and (seen as $s | any($want[]; . as $r | $s | index($r) == null));
  [ .[] | select((.number as $n | any($deferred[]; . == $n) | not) and managed and (actionable_ready or needs_repair or promotable_draft or needs_reviewers)) ]
  | length > 0
' >/dev/null
base_rc=$?

if [ -n "${DAIMON_GATE_RESUME:-}" ] && [ -n "$resume_id" ]; then
  printf '%s\n/pr-manager %s\n' "$resume_id" "$resume_pr" > "$DAIMON_GATE_RESUME"
fi
if [ -n "${DAIMON_GATE_NOTE:-}" ] && [ -n "$pending" ]; then
  printf 'feedback on%s%s' "$pending" "${resume_pr:+; resuming the author session for #$resume_pr}" > "$DAIMON_GATE_NOTE"
fi

[ "$base_rc" -eq 0 ] || [ -n "$pending" ]
