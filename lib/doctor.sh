#!/usr/bin/env bash
# Preflight: check that everything a real run needs is present and configured.
set -uo pipefail
DAIMON_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DAIMON_LIB_DIR/common.sh"

WARN=0; FAIL=0
ok()   { echo "  ok    $1"; }
warn() { echo "  warn  $1"; WARN=1; }
bad()  { echo "  FAIL  $1"; FAIL=1; }
note() { echo "  note  $1"; }
have() { command -v "$1" >/dev/null 2>&1; }
claude_trusts() { python3 "$DAIMON_LIB_DIR/claude_trust.py" "$1" 2>/dev/null; }

echo "platform"
[ "$(uname)" = "Darwin" ] && ok "macOS — launchd scheduling available" \
  || warn "non-macOS — 'daimon run' works, but launchd scheduling ('install --load') does not"

echo "tools"
have python3 && ok "python3 $(python3 --version 2>&1 | awk '{print $2}')" || bad "python3 missing"
have tmux && ok "tmux" || bad "tmux missing"
have jq && ok "jq" || bad "jq missing (discovery gates and hooks need it)"
have gh && ok "gh" || warn "gh missing (PR/issue daemons need it)"
have claude && ok "claude" || warn "claude not on PATH (set DAIMON_CLAUDE_BIN)"
have gh && { gh auth status >/dev/null 2>&1 && ok "gh authenticated" || warn "gh not authenticated (gh auth login)"; }

echo "paths"
mkdir -p "$DAIMON_STATE_DIR" 2>/dev/null
[ -w "$DAIMON_STATE_DIR" ] && ok "state_dir writable: $DAIMON_STATE_DIR" || bad "state_dir not writable"
[ -d "$DAIMON_INSTALL_ROOT" ] && ok "install_root: $DAIMON_INSTALL_ROOT" || bad "install_root missing"

echo "claude integration"
grep -q "DAIMON_" "$HOME/.claude/settings.json" 2>/dev/null \
  && ok "completion/heartbeat hooks installed" || warn "hooks NOT installed — run: daimon install"

echo "config"
if cfg_out="$(cfg validate 2>&1)"; then
  ok "config valid"
else
  bad "config invalid:"
  while IFS= read -r line; do echo "        $line"; done <<<"$cfg_out"
fi

echo "daemons"
needs_shortcut=0; needs_codex=0; needs_codex_slack=0; needs_datadog=0; needs_mongodb=0
needs_acr=0; acr_dirs=""
for slug in $(cfg daemons); do
  wd="$(cfg daemon "$slug" working_dir)"
  wd_configured="$(cfg daemon "$slug" working_dir_configured)"
  cmd="$(cfg daemon "$slug" command | sed 's#^/##')"
  be="$(cfg daemon "$slug" backend)"
  backends="$(cfg backends "$slug")"
  # Check the whole sources list, not just the primary: a daemon that reads one
  # source and writes another (e.g. datadog-log-reviewer) depends on both tools.
  srcs=" $(cfg daemon "$slug" sources 2>/dev/null) "
  case "$srcs" in *" shortcut "*) needs_shortcut=1 ;; esac
  case "$srcs" in *" datadog "*) needs_datadog=1 ;; esac
  case "$srcs" in *" mongodb "*) needs_mongodb=1 ;; esac
  # ACR has to be watching this daemon's repo or no verdict ever appears there;
  # keep the dirs so the acr block below can check each one by name.
  case "$srcs" in *" acr "*) needs_acr=1; acr_dirs="$acr_dirs$wd
" ;; esac
  case " $backends $(cfg daemon "$slug" mcp 2>/dev/null) " in *" codex "*) needs_codex=1 ;; esac
  case "$slug:$backends" in
    slack-channel-watch:*codex*|slack-commands:*codex*|slack-standup:*codex*) needs_codex_slack=1 ;;
  esac
  msg="$slug"
  if [ "$wd_configured" != "1" ]; then
    msg="$msg [working_dir not set — point it at your repo]"
  elif [ ! -d "$wd" ]; then msg="$msg [working_dir missing: $wd]"
  elif [ "$be" = "claude" ] && ! claude_trusts "$wd"; then
    msg="$msg [working_dir not trusted by claude — first run hangs on the trust prompt; open claude there once]"
  fi
  [ -f "$HOME/.claude/skills/$cmd/SKILL.md" ] || msg="$msg [skill not synced — run: daimon sync]"
  ( set -u; eval "$(cfg env "$slug")" ) >/dev/null 2>&1 \
    || msg="$msg [inputs do not eval cleanly — run: daimon validate]"
  [ "$msg" = "$slug" ] && ok "$slug" || warn "$msg"
done

# A daemon can ship doctor.sh for what only it knows it needs (a keychain item,
# a personal setting): exit 0 ok, 1 warn, 2 fail, first line of output as the
# message. Run for registered daemons only, with the daemon's inputs in env.
daemon_check() {  # slug dir
  local out rc
  out="$(set -a; eval "$(cfg env "$1")"; set +a
         DAIMON_DAEMON_DIR="$2" bash "$2/doctor.sh" 2>&1)"; rc=$?
  out="$(printf '%s' "$out" | head -1)"
  case "$rc" in
    0) ok "$1: ${out:-ok}" ;;
    1) warn "$1: ${out:-needs attention}" ;;
    *) bad "$1: ${out:-check failed (exit $rc)}" ;;
  esac
}
checks_header=0
for slug in $(cfg daemons); do
  [ -f "$HOME/Library/LaunchAgents/com.${DAIMON_NS}.${slug}.plist" ] || continue
  dir="$(cfg daemon-dir "$slug")"
  [ -f "$dir/doctor.sh" ] || continue
  [ "$checks_header" = 1 ] || { echo "daemon checks"; checks_header=1; }
  daemon_check "$slug" "$dir"
done

if [ "$needs_codex" = 1 ]; then
  echo "codex"
  codex_bin="${DAIMON_CODEX_BIN:-codex}"
  if have "$codex_bin"; then
    ok "codex $("$codex_bin" --version 2>/dev/null | awk '{print $NF}')"
    "$codex_bin" login status >/dev/null 2>&1 && ok "codex authenticated" \
      || warn "codex not authenticated (codex login) — codex-backed daemons fail; mcp second-opinion falls back"
  else
    warn "codex not on PATH (set DAIMON_CODEX_BIN) — codex-backed daemons fail; mcp second-opinion falls back"
  fi
fi

if [ "$needs_shortcut" = 1 ]; then
  echo "shortcut"
  source "$DAIMON_INSTALL_ROOT/profiles/shortcut/lib.sh"
  [ -n "$(shortcut_token)" ] && ok "API token resolves" \
    || warn "no token (~/.config/short/config.json or \$SHORTCUT_API_TOKEN)"
fi

check_slack_mcp() {
  # Slack daemons reach Slack only through MCP. Claude gets it from the plugin;
  # Codex fallback uses the same hosted server through Codex's MCP config.
  if grep -q '"slack@' "$HOME/.claude/settings.json" 2>/dev/null; then
    ok "slack MCP plugin enabled"
    echo "        (authorize once in an interactive claude session: /mcp)"
  else
    warn "slack MCP plugin not enabled — install it in claude (plugin install slack@claude-plugins-official) and authorize with /mcp"
  fi
  if [ "$needs_codex_slack" = 1 ]; then
    codex_bin="${DAIMON_CODEX_BIN:-codex}"
    if python3 "$DAIMON_LIB_DIR/mcp_setup.py" status slack >/dev/null 2>&1; then
      ok "codex Slack MCP configured and authenticated"
    else
      warn "codex Slack MCP not authenticated — run: daimon mcp setup slack"
    fi
  fi
}

check_watch_token() {
  local tok_cmd
  tok_cmd="$(python3 "$DAIMON_LIB_DIR/config.py" env slack-channel-watch 2>/dev/null \
    | grep '^DAIMON_INPUT_TOKEN_COMMAND=' | cut -d= -f2- | tr -d "'")"
  if [ -z "$tok_cmd" ]; then
    warn "channel-watch token_command empty — polling runs via agent sessions (costlier); set it once a bot token exists"
  elif bash -c "$tok_cmd" >/dev/null 2>&1; then
    ok "channel-watch token_command resolves"
  else
    warn "channel-watch token_command fails — scripted gate errors loudly every tick"
  fi
}

if cfg daemons | grep -qx slack-commands; then
  echo "slack commands"
  check_slack_mcp
  check_watch_token
fi

if [ "$needs_datadog" = 1 ]; then
  echo "datadog"
  if have pup; then
    ok "pup"
    if pup auth status --output json 2>/dev/null | grep -qE '"authenticated"[[:space:]]*:[[:space:]]*true'; then
      ok "pup authenticated"
    else
      warn "pup not authenticated (pup auth login) — datadog gate fails closed, so the daemon never fires"
    fi
  else
    warn "pup not installed (make tooling, or brew install datadog-labs/pack/pup) — datadog daemons never fire"
  fi
fi

if [ "$needs_mongodb" = 1 ]; then
  echo "mongodb"
  source "$DAIMON_INSTALL_ROOT/profiles/mongodb/lib.sh"
  if [ -z "$(atlas_creds)" ]; then
    warn "no Atlas service account (\$ATLAS_CLIENT_ID/\$ATLAS_CLIENT_SECRET, $DAIMON_PERSONAL_DIR/atlas.env, or the MongoDB MCP server) — mongodb gate fails closed, so the daemon never fires"
  elif [ -n "$(atlas_token)" ]; then
    ok "Atlas service account authenticates"
  else
    warn "Atlas service account found but the token exchange failed (expired or revoked key?) — mongodb gate fails closed"
  fi
fi

if [ "$needs_acr" = 1 ]; then
  echo "acr"
  source "$DAIMON_INSTALL_ROOT/profiles/acr/lib.sh"
  if [ "$(acr_config)" = "{}" ]; then
    warn "no ACR config (~/.acr/config.json) — nothing posts review verdicts, so the acr gate never fires"
  else
    while IFS= read -r d; do
      [ -n "$d" ] || continue
      nwo="$(acr_repo_nwo "$d")"
      if [ -z "$nwo" ]; then
        warn "$d: no git origin — cannot confirm ACR reviews it"
      elif acr_watches "$nwo"; then
        ok "ACR reviews $nwo"
      else
        warn "ACR does not list $nwo in ~/.acr/config.json — no verdict is ever posted there, so the acr gate never fires"
      fi
    done <<EOF
$acr_dirs
EOF
  fi
fi

# Ejected copies (yours, and packs') whose upstream changed since the copy:
# not a problem, just fixes you may want to fold in.
outdated="$(PYTHONPATH="$DAIMON_LIB_DIR/.." python3 -m daimon.eject outdated --brief 2>/dev/null)"
if [ -n "$outdated" ]; then
  echo "ejected daemons"
  while IFS= read -r line; do note "$line — see: daimon diff ${line%% *}"; done <<<"$outdated"
fi

echo "updates"
if [ "$(cfg get update.auto)" = 1 ]; then
  launchctl print "gui/$(id -u)/com.${DAIMON_NS}.update" >/dev/null 2>&1 \
    && ok "auto-update on (com.${DAIMON_NS}.update loaded)" \
    || warn "auto-update on but com.${DAIMON_NS}.update isn't loaded: run daimon sync"
  [ -e "$DAIMON_PERSONAL_DIR/no-auto-update" ] && warn "opted out on this machine ($DAIMON_PERSONAL_DIR/no-auto-update)"
  last="$(tail -1 "$(logs_dir)/update.log" 2>/dev/null | sed 's/.*msg="//; s/"$//')"
  [ -n "$last" ] && ok "last check: $last"
else
  ok "auto-update off ([update].auto)"
fi

echo ""
[ "$FAIL" = 1 ] && { echo "FAIL — fix the above before running."; exit 1; }
[ "$WARN" = 1 ] && { echo "ready, with warnings above."; exit 0; }
echo "all checks passed."
