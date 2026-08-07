#!/usr/bin/env bash
# Exercise the bash gate libraries (throttle / budget / inbox) against a temp
# config + state dir. Run from tests/run.sh.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cat > "$TMP/daimon.toml" <<EOF
[core]
install_root = "$ROOT"
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

DAEMON_NAME=foo source "$ROOT/lib/throttle.sh"
check "$SHOULD_SKIP" "0" "throttle off -> run"

python3 -c "import json;json.dump({'level':'halt'},open('$TMP/state/runtime/throttle.json','w'))"
DAEMON_NAME=foo source "$ROOT/lib/throttle.sh"
check "$SHOULD_SKIP" "1" "throttle halt -> skip"
DAEMON_NAME=exempted source "$ROOT/lib/throttle.sh"
check "$SHOULD_SKIP" "0" "throttle halt + exempt -> run"

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

# Without danger the mode must be pinned on the CLI. Inheriting the user default
# means `manual`, which stalls an unattended run on its first write; a project
# settings file cannot fix that, because defaultMode is honoured from user/policy
# settings only.
case "$(backend_cli_args opus 0 sess)" in *"--permission-mode auto"*) pm=1;; *) pm=0;; esac
check "$pm" "1" "claude backend pins --permission-mode auto when danger is off"
case "$(backend_cli_args opus 1 sess)" in *"--dangerously-skip-permissions"*) pm=1;; *) pm=0;; esac
check "$pm" "1" "claude backend uses --dangerously-skip-permissions when danger is on"
case "$(backend_cli_args opus 1 sess)" in *"--permission-mode"*) pm=1;; *) pm=0;; esac
check "$pm" "0" "claude backend does not pass both permission flags"
# The footer names the active mode, so pinning `auto` changes the text the
# launcher waits for. A miss here costs a full ready_timeout and a boot_fail with
# no command ever sent, which looks exactly like a dead agent.
ready_re="$(backend_ready_regex 0)"
footer="⏵⏵ auto mode on (shift+tab to cycle) · ← for agents"
if [[ "$footer" =~ $ready_re ]]; then pm=1; else pm=0; fi
check "$pm" "1" "ready regex matches the auto-mode footer"

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

exit "$fails"
