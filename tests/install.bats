#!/usr/bin/env bats
# Integration test for bin/daimon-install, run against a throwaway $HOME so it never
# touches the real ~/.config, ~/.claude, ~/.local/bin, or ~/Library/LaunchAgents.
# The TUI venv (network) step is skipped via DAIMON_SKIP_TUI_VENV; launchctl is not
# invoked because --load is omitted.

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  SBOX="$BATS_TEST_TMPDIR/home"
  mkdir -p "$SBOX/.config/daimon" "$SBOX/Library/LaunchAgents"
  # Seed a valid global config: no install_root (defaults to the repo), state + plists
  # land under the sandbox, and a test namespace keeps plist labels distinct.
  cat > "$SBOX/.config/daimon/daimon.toml" <<TOML
[core]
state_dir = "$SBOX/state"
namespace = "daimon-test"
timezone = "UTC"
[defaults]
backend = "claude"
model = "opus"
danger = true
stuck_after = 2700
ready_timeout = 20
TOML
}

run_install() {
  run env HOME="$SBOX" DAIMON_SKIP_TUI_VENV=1 bash "$ROOT/bin/daimon-install"
}

@test "install: completes without touching the real HOME" {
  run_install
  [ "$status" -eq 0 ]
}

@test "install: creates state dirs" {
  run_install
  [ -d "$SBOX/state/logs/transcripts" ]
}

@test "install: merges the agent hooks into settings.json" {
  run_install
  [ -f "$SBOX/.claude/settings.json" ]
  grep -q 'DAIMON_' "$SBOX/.claude/settings.json"
}

@test "install: links management skills and symlinks the CLI" {
  run_install
  [ -e "$SBOX/.claude/skills/daimon-builder" ]
  [ -L "$SBOX/.local/bin/daimon" ]
}

@test "install: renders daemon skills and generates plists" {
  run_install
  [ -f "$SBOX/.claude/skills/review-prs/SKILL.md" ]
  [ -f "$SBOX/Library/LaunchAgents/com.daimon-test.review-prs.plist" ]
}

@test "install: is idempotent (second run also succeeds)" {
  run_install
  [ "$status" -eq 0 ]
  run_install
  [ "$status" -eq 0 ]
}

@test "install: --worklog links the hook and merges SessionEnd once" {
  run env HOME="$SBOX" DAIMON_SKIP_TUI_VENV=1 bash "$ROOT/bin/daimon-install" --worklog
  [ "$status" -eq 0 ]
  [ -L "$SBOX/.claude/hooks/standup-worklog.sh" ]
  grep -q 'standup-worklog.sh' "$SBOX/.claude/settings.json"
  run env HOME="$SBOX" DAIMON_SKIP_TUI_VENV=1 bash "$ROOT/bin/daimon-install" --worklog
  [ "$status" -eq 0 ]
  count="$(grep -c 'standup-worklog.sh' "$SBOX/.claude/settings.json")"
  [ "$count" -eq 1 ]
}

@test "install: without --worklog the hook is not installed" {
  run_install
  [ ! -e "$SBOX/.claude/hooks/standup-worklog.sh" ]
  ! grep -q 'standup-worklog' "$SBOX/.claude/settings.json"
}
