#!/usr/bin/env bats
# pr-manager gate: unhandled review feedback launches a run, and a PR that
# records its authoring session asks to resume that session. gh is a stub.

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  T="$BATS_TEST_TMPDIR"
  mkdir -p "$T/bin" "$T/state/state" "$T/repo" "$T/home"
  printf '[core]\nstate_dir = "%s/state"\nnamespace = "t"\n' "$T" > "$T/daimon.toml"
  export DAIMON_CONFIG="$T/daimon.toml" HOME="$T/home"
  export DAIMON_INPUT_MANAGE_LABEL=manage DAIMON_INPUT_REVIEWERS="" \
    DAIMON_INPUT_PROMOTE_DRAFTS=0 DAIMON_INPUT_AUTO_MERGE=0 \
    DAIMON_INPUT_PROMOTE_MIN_AGE_HOURS=2 DAIMON_INPUT_RESUME_AUTHOR=1 \
    DAIMON_INPUT_FINDINGS_MARKER='"kind":"findings"' \
    DAIMON_INPUT_FINDINGS_NONE_REGEX='\*\*0 findings'
  export DAIMON_GATE_NOTE="$T/note" DAIMON_GATE_RESUME="$T/resume"
  SID=0f0e0d0c-1111-2222-3333-444455556666
  # One green managed PR awaiting review (not otherwise actionable) with an automated reviewer's findings comment.
  cat > "$T/bin/gh" <<STUB
#!/usr/bin/env bash
case "\$*" in
  "api user --jq .login") echo me ;;
  "pr list"*) echo '[{"number":7,"headRefName":"daimon/sc-1","reviewDecision":"'"\${DECISION:-REVIEW_REQUIRED}"'","mergeable":"MERGEABLE","isDraft":false,"labels":[],"statusCheckRollup":[{"conclusion":"SUCCESS"}],"createdAt":"2026-01-01T00:00:00Z","reviewRequests":[],"latestReviews":[]}]' ;;
  "pr view 7 --json reviews,comments") cat "$T/feedback.json" ;;
  "pr view 7 --json body --jq .body") printf 'Implements x\n\n<!-- daimon-session: $SID -->\n' ;;
esac
STUB
  chmod +x "$T/bin/gh"
  export PATH="$T/bin:$PATH"
  echo '{"reviews":[{"state":"APPROVED","author":{"login":"rev"},"submittedAt":"2026-01-02T00:00:00Z"}],"comments":[{"author":{"login":"rev"},"createdAt":"2026-01-02T00:01:00Z","body":"<!-- x {\"kind\":\"findings\"} -->\n**1 findings:** 1 minor"}]}' > "$T/feedback.json"
  PROJ="$T/home/.claude/projects/$(cd "$T/repo" && pwd -P | sed 's#[^A-Za-z0-9]#-#g')"
  mkdir -p "$PROJ"
}

gate() { cd "$T/repo" && DAIMON_INSTALL_ROOT="$ROOT" bash "$ROOT/catalog/pr-manager/discover.sh"; }

@test "unhandled findings launch a run" {
  run gate
  [ "$status" -eq 0 ]
  grep -q "feedback on #7" "$T/note"
}

@test "recorded session with a local transcript is resumed for that PR" {
  touch "$PROJ/$SID.jsonl"
  run gate
  [ "$status" -eq 0 ]
  [ "$(sed -n 1p "$T/resume")" = "$SID" ]
  [ "$(sed -n 2p "$T/resume")" = "/pr-manager 7" ]
}

@test "no transcript on this machine: run without resuming" {
  run gate
  [ "$status" -eq 0 ]
  [ ! -s "$T/resume" ]
}

@test "feedback already handled (feedback_seen) does not launch" {
  echo '{"prs":{"7":{"feedback_seen":"2026-01-02T00:01:00Z"}}}' > "$T/state/state/pr-manager.json"
  run gate
  [ "$status" -ne 0 ]
}

@test "a zero-findings comment is not feedback" {
  echo '{"reviews":[],"comments":[{"author":{"login":"rev"},"createdAt":"2026-01-02T00:01:00Z","body":"{\"kind\":\"findings\"} **0 findings:**"}]}' > "$T/feedback.json"
  run gate
  [ "$status" -ne 0 ]
}

@test "the authoring session still running: wait rather than act without it" {
  touch "$PROJ/$SID.jsonl"
  ( exec -a "claude --session-id $SID" sleep 30 ) &
  pid=$!
  run gate
  kill "$pid" 2>/dev/null
  [ "$status" -ne 0 ]
}

@test "an approved PR waiting on its busy authoring session is not merged meanwhile" {
  touch "$PROJ/$SID.jsonl"
  ( exec -a "claude --session-id $SID" sleep 30 ) &
  pid=$!
  DECISION=APPROVED run gate
  kill "$pid" 2>/dev/null
  [ "$status" -ne 0 ]
}

@test "an approved PR with no pending feedback still launches to merge" {
  echo '{"reviews":[],"comments":[]}' > "$T/feedback.json"
  DECISION=APPROVED run gate
  [ "$status" -eq 0 ]
}
