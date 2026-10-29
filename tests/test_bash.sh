#!/usr/bin/env bash
# Exercise the bash gate libraries (throttle / budget / inbox) against a temp
# config + state dir. Run from tests/run.sh.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Sandbox install root with one daemon carrying its own hourly_cap, so the
# per-daemon budget branch has something to resolve against.
mkdir -p "$TMP/inst/daemons/capped"
cat > "$TMP/inst/daemons/capped/daemon.toml" <<EOF
[daemon]
schedule = { interval = 60 }
command = "/capped"
fallback_backend = "codex"
hourly_cap = 2
EOF

cat > "$TMP/daimon.toml" <<EOF
[core]
install_root = "$TMP/inst"
state_dir = "$TMP/state"
namespace = "datest"
[defaults]
stuck_after = 100
[throttle]
exempt = ["exempted"]
moderate_mod = 2
severe_mod = 4
[budget]
hourly_cap = 12
defer_at_pct = 80
exempt = ["cheap-poller"]
[daemons]
disabled = []
EOF
export DAIMON_CONFIG="$TMP/daimon.toml"

source "$ROOT/lib/common.sh"
source "$ROOT/lib/budget.sh"
ensure_state_dirs

fails=0
check() { if [ "$1" = "$2" ]; then echo "  ok  $3"; else echo "  FAIL $3 ($1 != $2)"; fails=1; fi }

budget_record foo
budget_record foo
check "$(budget_total_this_hour)" "2" "budget counts launches"

budget_check
check "$BUDGET_OVER" "0" "budget under cap -> run"
for _ in 1 2 3 4 5 6 7; do budget_record foo; done   # 9 launches == 80% of cap 12
budget_check
check "$BUDGET_OVER" "1" "budget at defer threshold -> skip"
budget_check foo
check "$BUDGET_OVER" "1" "budget over + non-exempt slug -> skip"
budget_check cheap-poller
check "$BUDGET_OVER" "0" "budget over + exempt slug -> run"
budget_check capped   # own hourly_cap=2, has 0 launches; global pool is over
check "$BUDGET_OVER" "0" "own-cap daemon under its cap -> run despite global"
budget_record capped
budget_record capped
budget_check capped
check "$BUDGET_OVER" "1" "own-cap daemon at its cap -> skip"

DAEMON_NAME=foo source "$ROOT/lib/throttle.sh"
check "$SHOULD_SKIP" "0" "throttle off -> run"

python3 -c "import json;json.dump({'level':'halt'},open('$TMP/state/runtime/throttle.json','w'))"
DAEMON_NAME=foo source "$ROOT/lib/throttle.sh"
check "$SHOULD_SKIP" "1" "throttle halt -> skip"
DAEMON_NAME=exempted source "$ROOT/lib/throttle.sh"
check "$SHOULD_SKIP" "0" "throttle halt + exempt -> run"

python3 -c "import json;json.dump({'level':'halt','reason':'claude usage limit detected in transcript'},open('$TMP/state/runtime/throttle.json','w'))"
DAEMON_NAME=capped source "$ROOT/lib/throttle.sh"
check "$SHOULD_SKIP" "0" "matching provider halt + configured fallback -> run"
DAEMON_NAME=foo source "$ROOT/lib/throttle.sh"
check "$SHOULD_SKIP" "1" "matching provider halt + no fallback -> skip"

# A null expires_at (written by the TUI) must read as "no expiry", not "None".
python3 -c "import json;json.dump({'level':'halt','expires_at':None},open('$TMP/state/runtime/throttle.json','w'))"
check "$(json_state get "$TMP/state/runtime/throttle.json" expires_at 0)" "0" "json_state get: null -> default"
DAEMON_NAME=foo source "$ROOT/lib/throttle.sh" 2>"$TMP/throttle.err"
check "$SHOULD_SKIP" "1" "throttle halt with null expiry -> skip"
check "$(wc -c <"$TMP/throttle.err" | tr -d ' ')" "0" "throttle emits no stderr on null expiry"

python3 -c "import json;json.dump({'messages':[{'to':'foo'},{'to':'bar'}]},open('$TMP/state/runtime/inbox.json','w'))"
DAEMON_NAME=foo source "$ROOT/lib/inbox.sh"
check "$HAS_INBOX_MESSAGES" "1" "inbox counts messages for daemon"

source "$ROOT/backends/claude.sh"
unset DAIMON_MCP_CONFIG
case "$(backend_cli_args opus 1 sess)" in *--mcp-config*) mcp=1;; *) mcp=0;; esac
check "$mcp" "0" "claude backend omits --mcp-config when unset"
export DAIMON_MCP_CONFIG="$TMP/mcp.json"
case "$(backend_cli_args opus 1 sess)" in *"--mcp-config $TMP/mcp.json --strict-mcp-config"*) mcp=1;; *) mcp=0;; esac
check "$mcp" "1" "claude backend appends --mcp-config + --strict when set"
unset DAIMON_MCP_CONFIG
export DAIMON_D_TOOLS="Read 'Bash(git log:*)'"
A="$(backend_cli_args opus 1 sess)"
case "$A" in *--dangerously-skip-permissions*) d=1;; *) d=0;; esac
check "$d" "0" "claude tools allowlist overrides danger"
case "$A" in *"--permission-mode dontAsk"*) d=1;; *) d=0;; esac
check "$d" "1" "claude tools allowlist runs dontAsk"
# each rule must reach claude as one argv word after tmux's `sh -c`
if sh -c "printf '%s\n' $A" | grep -qxF 'Bash(git log:*)'; then t=1; else t=0; fi
check "$t" "1" "claude allowlist rule survives sh -c as one word"
check "$(backend_ready_regex 1)" "don't ask on" "claude ready banner follows dontAsk"
unset DAIMON_D_TOOLS

export DAIMON_D_WORKING_DIR="/tmp/x.y/repo"
source "$ROOT/backends/codex.sh"
check "$(backend_completion_mode)" "oneshot" "codex backend is oneshot"
check "$(backend_ready_regex 1)" "" "codex backend has no ready banner"
A="$(backend_cli_args gpt-5.3-codex 1 sess)"
# the trust arg must survive tmux's `sh -c` as one arg with TOML quotes intact,
# even for a path containing a dot
if sh -c "printf '%s\n' $A" | grep -qxF 'projects."/tmp/x.y/repo".trust_level="trusted"'; then t=1; else t=0; fi
check "$t" "1" "codex trust arg survives sh -c quoted"
case "$(backend_cli_args opus 1 sess)" in *"-m "*) m=1;; *) m=0;; esac
check "$m" "0" "codex drops -m for a claude-model default"
case "$A" in *"-m gpt-5.3-codex"*) m=1;; *) m=0;; esac
check "$m" "1" "codex passes -m for a codex model"
unset DAIMON_D_WORKING_DIR

source "$ROOT/lib/backend-status.sh"
status_install_root="$DAIMON_INSTALL_ROOT"
DAIMON_INSTALL_ROOT="$ROOT"
printf "%s\n" "You've hit your monthly spend limit." > "$TMP/exhausted.log"
printf "%s\n" "If you hit your limit, you can continue with usage credits." > "$TMP/advisory.log"
backend_is_exhausted claude "$TMP/exhausted.log"; check "$?" "0" "claude cap is classified as exhausted"
backend_is_exhausted claude "$TMP/advisory.log"; check "$?" "1" "claude advisory is not classified as exhausted"
printf "%s\n" "Authentication failed" > "$TMP/auth.log"
backend_is_exhausted claude "$TMP/auth.log"; check "$?" "1" "non-cap failure does not trigger fallback"
DAIMON_INSTALL_ROOT="$status_install_root"

echo '[{"n":1}]' | DAIMON_SLUG=st bash "$ROOT/lib/state.sh" set
check "$(DAIMON_SLUG=st bash "$ROOT/lib/state.sh" get)" '[{"n":1}]' "state set/get roundtrip"
echo 'not json' | DAIMON_SLUG=st bash "$ROOT/lib/state.sh" set 2>/dev/null
check "$?" "2" "state set rejects invalid json"
check "$(DAIMON_SLUG=st bash "$ROOT/lib/state.sh" get)" '[{"n":1}]' "state unchanged after rejected set"
echo '{"a":2}' | bash "$ROOT/lib/state.sh" set other
check "$(bash "$ROOT/lib/state.sh" get other)" '{"a":2}' "state get/set honors an explicit slug"

exit "$fails"
