#!/usr/bin/env bats
# Every catalog gate finds dAImon's libraries through $DAIMON_INSTALL_ROOT (or,
# unset, the `daimon` on PATH), so it runs from catalog/, an ejected copy in
# daemons/, or a pack: never through a path relative to its own folder.

setup() {
  ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  T="$BATS_TEST_TMPDIR"
  mkdir -p "$T/bin" "$T/state" "$T/home" "$T/elsewhere"
  printf '[core]\nstate_dir = "%s/state"\nnamespace = "t"\n[daemons]\ninstalled = []\n' "$T" > "$T/daimon.toml"
  export DAIMON_CONFIG="$T/daimon.toml" HOME="$T/home"
  # Every external tool a gate might reach for fails fast: what is under test
  # is that the gate loads, not what it finds.
  for tool in gh pup curl jq launchctl tmux; do
    printf '#!/usr/bin/env bash\nexit 3\n' > "$T/bin/$tool"
    chmod +x "$T/bin/$tool"
  done
  ln -s "$ROOT/bin/daimon" "$T/bin/daimon"
  export PATH="$T/bin:$PATH"
}

gates() { ls "$ROOT"/catalog/*/discover.sh; }

loads() {  # gate-path: run it, fail on a missing library
  run bash "$1"
  if [ "$status" -eq 127 ] || [[ "$output" == *"No such file or directory"* ]]; then
    echo "$1: $output" >&2
    return 1
  fi
}

@test "no catalog gate sources a path relative to its own folder" {
  ! grep -n '\.\./\.\./' "$ROOT"/catalog/*/discover.sh
}

@test "every catalog gate loads from catalog/ with DAIMON_INSTALL_ROOT set" {
  export DAIMON_INSTALL_ROOT="$ROOT"
  for g in $(gates); do loads "$g"; done
}

@test "every catalog gate loads from a copy outside the install root" {
  export DAIMON_INSTALL_ROOT="$ROOT"
  for g in $(gates); do
    slug="$(basename "$(dirname "$g")")"
    cp -R "$(dirname "$g")" "$T/elsewhere/$slug"
    loads "$T/elsewhere/$slug/discover.sh"
  done
}

@test "with DAIMON_INSTALL_ROOT unset a gate finds dAImon through the daimon on PATH" {
  unset DAIMON_INSTALL_ROOT
  for g in $(gates); do
    slug="$(basename "$(dirname "$g")")"
    cp -R "$(dirname "$g")" "$T/elsewhere/$slug"
    loads "$T/elsewhere/$slug/discover.sh"
  done
}
