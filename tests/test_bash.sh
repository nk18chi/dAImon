#!/usr/bin/env bash
# Exercise the bash gate libraries (throttle / budget / inbox) against a temp
# config + state dir. Run from tests/run.sh.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Sandbox install root with one daemon carrying its own hourly_cap, so the
# per-daemon budget branch has something to resolve against.
mkdir -p "$TMP/inst/catalog/capped"
cat > "$TMP/inst/catalog/capped/daemon.toml" <<EOF
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
before="$(budget_total_this_hour)"
budget_record cheap-poller
check "$(budget_total_this_hour)" "$before" "exempt slug's launches don't consume the pool"
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
export DAIMON_AGENT_SESSION="0f0e0d0c-0000-4000-8000-000000000001"
case "$(backend_cli_args opus 1 sess)" in *"--session-id $DAIMON_AGENT_SESSION"*) sid=1;; *) sid=0;; esac
check "$sid" "1" "claude backend pins --session-id when DAIMON_AGENT_SESSION is set"
unset DAIMON_AGENT_SESSION
# The command goes in at start-up, not typed once the pane shows a ready banner
# whose text depends on the user's permission mode.
if backend_initial_prompt; then ip=1; else ip=0; fi
check "$ip" "1" "claude backend takes the command as its first prompt"
# It must reach the CLI as one argv word after tmux's shell, quotes and all.
for c in "/review-prs" "/pr-manager resume 'PR 12' now"; do
  w="$(sh -c "printf '%s\n' $(initial_prompt_word "$c")")"
  check "$w" "$c" "initial prompt survives the launch shell as one word: $c"
done
# An untrusted working_dir fails before launch, with the reason, instead of the
# command waiting behind claude's trust prompt.
mkdir -p "$TMP/trusthome" "$TMP/wd-trusted" "$TMP/wd-untrusted"
printf '{"projects":{"%s":{"hasTrustDialogAccepted":true}}}' "$(cd "$TMP/wd-trusted" && pwd -P)" > "$TMP/trusthome/.claude.json"
if HOME="$TMP/trusthome" backend_launch_check "$TMP/wd-trusted" >/dev/null; then t=1; else t=0; fi
check "$t" "1" "claude launch check passes a trusted working_dir"
if r="$(HOME="$TMP/trusthome" backend_launch_check "$TMP/wd-untrusted")"; then t=1; else t=0; fi
check "$t" "0" "claude launch check fails an untrusted working_dir"
case "$r" in *"not trusted by claude"*) t=1;; *) t=0;; esac
check "$t" "1" "claude launch check says why"

# The Stop hook marks done only for the daemon's own session, never for a child
# `claude -p` that a user hook spawns with the same env.
STOP_CMD="$(jq -r '.Stop[0].hooks[0].command' "$ROOT/config/hooks/claude-hooks.json")"
SENT="$TMP/sentinel"; rm -f "$SENT"
echo '{"session_id":"someone-else"}' | DAIMON_SENTINEL="$SENT" DAIMON_AGENT_SESSION="0f0e" sh -c "$STOP_CMD"
check "$([ -e "$SENT" ] && echo 1 || echo 0)" "0" "Stop hook ignores a child session's stop"
echo '{"session_id":"0f0e"}' | DAIMON_SENTINEL="$SENT" DAIMON_AGENT_SESSION="0f0e" sh -c "$STOP_CMD"
check "$([ -e "$SENT" ] && echo 1 || echo 0)" "1" "Stop hook marks done for the daemon's own session"

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

DAIMON_SLUG=lg bash "$ROOT/lib/result.sh" 'PR opened sc-1 "x"
second line'
check "$(tail -1 "$TMP/state/logs/lg.log" | sed 's/^[^ ]* //')" \
  "level=info daemon=lg event=result msg=\"PR opened sc-1 'x' second line\"" \
  "daimon log records one sanitized result line"
bash "$ROOT/lib/result.sh" --slug other2 'skipped sc-2'
check "$(grep -c 'event=result' "$TMP/state/logs/other2.log")" "1" "daimon log honors --slug"
env -u DAIMON_SLUG bash "$ROOT/lib/result.sh" 'x' 2>/dev/null
check "$?" "2" "daimon log without a slug fails"

# worktree sweep: removes clean+pushed prefix worktrees, keeps dirty/unpushed/foreign
source "$ROOT/lib/worktrees.sh"
W="$TMP/wt"; mkdir -p "$W"
git init -q --bare "$W/origin.git"
git clone -q "$W/origin.git" "$W/repo" 2>/dev/null
( cd "$W/repo" && git -c user.email=t@t -c user.name=t commit -q --allow-empty -m init && git push -q origin HEAD:main 2>/dev/null && git fetch -q )
g() { git -C "$W/repo" -c user.email=t@t -c user.name=t "$@"; }
g worktree add -q "$W/repo/.worktrees/pushed" -b daimon/pushed origin/main
( cd "$W/repo/.worktrees/pushed" && git -c user.email=t@t -c user.name=t commit -q --allow-empty -m a && git push -q -u origin daimon/pushed 2>/dev/null )
g worktree add -q "$W/repo/.worktrees/dirty" -b daimon/dirty origin/main
echo x > "$W/repo/.worktrees/dirty/new.txt"
g worktree add -q "$W/repo/.worktrees/ahead" -b daimon/ahead origin/main
( cd "$W/repo/.worktrees/ahead" && git -c user.email=t@t -c user.name=t commit -q --allow-empty -m b )
g worktree add -q "$W/repo/.worktrees/mine" -b feat/mine origin/main
out="$(sweep_worktrees "$W/repo" "daimon/" main)"
check "$(echo "$out" | grep -c '^removed worktree pushed')" "1" "sweep removes a clean, pushed daimon worktree"
check "$([ -d "$W/repo/.worktrees/pushed" ] && echo yes || echo no)" "no" "sweep deleted the pushed worktree dir"
check "$(echo "$out" | grep -c '^kept dirty.*uncommitted')" "1" "sweep keeps a worktree with uncommitted files"
check "$(echo "$out" | grep -c '^kept ahead.*unpushed')" "1" "sweep keeps a worktree with unpushed commits"
check "$([ -d "$W/repo/.worktrees/mine" ] && echo yes || echo no)" "yes" "sweep ignores branches outside the prefix"
check "$(sweep_worktrees "$W/repo" "" main | grep -c .)" "0" "empty prefix sweeps nothing"

# claude backend: a resumed run passes --resume, a fresh one --session-id
( source "$ROOT/backends/claude.sh"
  DAIMON_AGENT_SESSION=abc DAIMON_RESUME=1 backend_cli_args opus 1 s | grep -q -- "--resume abc" && echo yes || echo no ) > "$TMP/r1"
check "$(cat "$TMP/r1")" "yes" "claude backend resumes a session by id"
( source "$ROOT/backends/claude.sh"
  DAIMON_AGENT_SESSION=abc DAIMON_RESUME=0 backend_cli_args opus 1 s | grep -q -- "--session-id abc" && echo yes || echo no ) > "$TMP/r2"
check "$(cat "$TMP/r2")" "yes" "claude backend pins a fresh session id"

exit "$fails"
