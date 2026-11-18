#!/usr/bin/env bats
# Integration test for bin/daimon-install, run against a throwaway $HOME so it never
# touches the real ~/.daimon, ~/.config, ~/.claude, ~/.local/bin, or ~/Library/LaunchAgents.
# The TUI venv (network) step is skipped via DAIMON_SKIP_TUI_VENV; launchctl is not
# invoked because --load is omitted. install_root points at a scratch copy of the
# repo (without any *.local.toml), so the settings migration install runs can never
# move a developer's real in-repo settings into the throwaway HOME.

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  SBOX="$BATS_TEST_TMPDIR/home"
  INST="$BATS_TEST_TMPDIR/install"
  mkdir -p "$SBOX/.daimon" "$SBOX/Library/LaunchAgents"
  rsync -a --exclude .git --exclude .venv --exclude '*.local.toml' \
    --include 'daemons/README.md' --exclude 'daemons/*' \
    "$ROOT/" "$INST/"
  # Seed a valid global config: install_root is the scratch copy, state + plists
  # land under the sandbox, and a test namespace keeps plist labels distinct.
  cat > "$SBOX/.daimon/daimon.toml" <<TOML
[core]
install_root = "$INST"
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

@test "install: renders daemon skills but registers no daemon" {
  run_install
  [ -f "$SBOX/.claude/skills/review-prs/SKILL.md" ]
  # A plist would be loaded at the next login: install must not create one.
  [ ! -e "$SBOX/Library/LaunchAgents/com.daimon-test.review-prs.plist" ]
}

@test "install: refreshes a daemon that is already registered" {
  mkdir -p "$SBOX/Library/LaunchAgents"
  echo stale > "$SBOX/Library/LaunchAgents/com.daimon-test.review-prs.plist"
  run_install
  grep -q "<plist" "$SBOX/Library/LaunchAgents/com.daimon-test.review-prs.plist"
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

@test "install: moves legacy in-repo settings to ~/.daimon" {
  # As left by the git merge that moved daemons/ to catalog/: the gitignored
  # daemon.local.toml stays behind in daemons/<slug>/.
  mkdir -p "$INST/daemons/review-prs"
  printf '# mine\n[inputs]\nrepos = ["api"]\n' > "$INST/daemons/review-prs/daemon.local.toml"
  printf '[defaults]\nowner = "me"\n' > "$INST/profiles/shortcut/profile.local.toml"
  run_install
  [ "$status" -eq 0 ]
  grep -q '# mine' "$SBOX/.daimon/daemons/review-prs.toml"
  grep -q 'owner = "me"' "$SBOX/.daimon/profiles/shortcut.toml"
  # the leftover folder held only the migrated file, so it is gone
  [ ! -e "$INST/daemons/review-prs" ]
  [ -f "$INST/daemons/README.md" ]
  # the tracked example is never touched
  diff -q "$ROOT/catalog/review-prs/daemon.local.toml.example" "$INST/catalog/review-prs/daemon.local.toml.example"
}

@test "install: a config from before the catalog gets today's active set as installed" {
  printf '\n[daemons]\n# skip this one\ndisabled = ["slack-standup"]\n' >> "$SBOX/.daimon/daimon.toml"
  run_install
  [ "$status" -eq 0 ]
  conf="$SBOX/.daimon/daimon.toml"
  grep -q '# skip this one' "$conf"
  installed="$(python3 -c 'import sys,tomllib; print(" ".join(tomllib.load(open(sys.argv[1],"rb"))["daemons"]["installed"]))' "$conf")"
  expected="$(ls "$INST/catalog" | grep -v -e README.md -e daemon.schema.json | grep -vx slack-standup | tr '\n' ' ' | sed 's/ $//')"
  [ "$installed" = "$expected" ]
  cp "$conf" "$BATS_TEST_TMPDIR/after-first"
  run_install
  [ "$status" -eq 0 ]
  diff "$BATS_TEST_TMPDIR/after-first" "$conf"
}

@test "install: a fresh config installs no daemons" {
  rm "$SBOX/.daimon/daimon.toml"
  run_install
  [ "$status" -eq 0 ]
  grep -q '^installed = \[\]' "$SBOX/.daimon/daimon.toml"
}

@test "install: moves ~/.config/daimon to ~/.daimon, keeping modes, and sets old state aside" {
  mkdir -p "$SBOX/.config"
  mv "$SBOX/.daimon" "$SBOX/.config/daimon"
  mkdir -p "$SBOX/.config/daimon/daemons" "$SBOX/.daimon/state"
  printf '[inputs]\nq = "mine"\n' > "$SBOX/.config/daimon/daemons/review-prs.toml"
  chmod 600 "$SBOX/.config/daimon/daemons/review-prs.toml"
  touch "$SBOX/.config/daimon/no-auto-update"
  echo '{}' > "$SBOX/.daimon/state.json"
  run_install
  [ "$status" -eq 0 ]
  grep -q "install_root = \"$INST\"" "$SBOX/.daimon/daimon.toml"
  grep -q 'q = "mine"' "$SBOX/.daimon/daemons/review-prs.toml"
  [ "$(python3 -c 'import os,sys; print(oct(os.stat(sys.argv[1]).st_mode & 0o777))' "$SBOX/.daimon/daemons/review-prs.toml")" = 0o600 ]
  [ -e "$SBOX/.daimon/no-auto-update" ]
  ls "$SBOX"/.daimon/legacy-*/state.json
  ls -d "$SBOX"/.daimon/legacy-*/state
  [ "$(ls -A "$SBOX/.config/daimon")" = MOVED ]
  [ -d "$SBOX/state/logs" ]  # state_dir came from the moved daimon.toml
  run_install
  [ "$status" -eq 0 ]
  [ "$(ls -A "$SBOX/.config/daimon")" = MOVED ]
  [ "$(ls -d "$SBOX"/.daimon/legacy-* | wc -l | tr -d ' ')" = 1 ]
}
