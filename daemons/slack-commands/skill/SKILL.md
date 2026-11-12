---
name: slack-commands
description: Handle bridged Slack commands from the daimon inbox via plugin runbooks, with an allowlist gate on mutating commands.
---

# slack-commands

You are launched because a Slack bridge app queued command messages in the
daimon inbox. Handle every queued message, reply in Slack, and finish. You
run inside `working_dir`.

**First action, unconditionally**: make the Slack tools available:

- **Claude:** use ToolSearch with query
  `select:mcp__plugin_slack_slack__slack_send_message,mcp__plugin_slack_slack__slack_search_users`.
  The plugin tools are deferred and invisible until loaded.
- **Codex:** do not look for ToolSearch. Use `slack_send_message` and
  `slack_search_users` directly from the authenticated `slack` MCP server.

Never substitute curl, the Slack CLI, or raw API calls for these tools; if
backend-specific discovery or a call fails with an auth problem, report it and
stop.

## 1. Drain the inbox

Resolve the state dir (`daimon config paths` → `DAIMON_STATE_DIR`); the inbox
is `$DAIMON_STATE_DIR/runtime/inbox.json` with shape
`{"messages": [{"to": "<slug>", ...}]}`. In one small python/jq step, take
every message with `to == "slack-commands"` and rewrite the file with exactly
those removed (other daemons' messages stay). If none were queued, report
"inbox empty" and stop.

Each taken message has: `command` (text), `channel`, `ts` (the command
message's own timestamp), optional `thread_ts`, `user` (Slack user ID of
the requester), `via`.

**Dedupe before handling**: drop any message whose `(channel, ts)` pair
already appears in the `handled` list in this daemon's state — watchers
can re-forward on watermark bugs, and running a command twice (a second
staging push, a duplicate standup post) is worse than dropping a
duplicate. Note dropped duplicates in the summary; do not reply to them
in Slack.

## 2. Load command plugins

Read every `*.md` in `{{inputs.commands_dir}}` then
`{{inputs.local_commands_dir}}` (paths relative to the dAImon install root;
a local plugin with the same `name` replaces the shared one). Each plugin has
frontmatter — `name`, `match` (the command word), `mutating` (bool),
optional `admin` (bool), `description` — and a body that is the runbook to
follow. Command words are always a **single token**, named
`{domain}-{action/topic}` (`staging-push`, `epic-status`, `bazaar-update`);
a bare domain is acceptable only when it's unambiguous (`standup`, `help`).
Everything after the first space is arguments.

## 3. Handle each message

Authorization has two tiers:

- **Admins** — the Slack user IDs in `{{inputs.mutate_allowlist}}` (config
  is the root of trust; only a machine edit changes it).
- **Granted users** — the `grants` array in this daemon's state
  (`daimon state get`), managed from Slack by admins via the `access`
  plugin. The effective mutate allowlist is admins ∪ grants.

Per message:

1. Match the command's **first word** against the plugins' `match` tokens,
   case-insensitive; the rest of the text is the arguments.
2. **No match** → reply with the command list (`name` — description per
   plugin, mutating ones marked "restricted"). Omit `admin: true` plugins
   from any listing shown to a non-admin.
3. **`admin: true`** and `user` is not an admin → reply "admins only"; do
   NOT execute. Grants do not confer admin.
4. **`mutating: true`** and `user` is not in the effective allowlist →
   reply that the command is restricted and that an admin can grant access
   with `access grant @them`; do NOT execute any part of the runbook.
5. Otherwise follow the plugin's runbook with the arguments. Runbooks run
   from `working_dir`.

**Parallelism**: with ONE authorized message queued, just run its runbook
inline. With SEVERAL and an agent/subagent tool available, dispatch each
non-mutating runbook to its own subagent in one parallel batch (prompt = the
runbook body + the arguments + "return the Slack reply text as your final
message"), then post each reply as results come back. If this backend has no
subagent tool, run non-mutating runbooks inline. Keep mutating and admin runbooks
in the main session, run sequentially — authorization and side effects stay
single-threaded.

If a runbook says to invoke a slash command such as `/standup`, Claude may invoke
it normally. Codex must instead read `~/.claude/commands/<name>.md`, treat its
body as the nested runbook, substitute any arguments locally, and follow it
inline. Never type a Claude slash command into a shell.

## 4. Reply

Reply with the Slack MCP tool `slack_send_message` to the message's
`channel`, threading on `thread_ts` when present. One concise reply per
message: labeled links only (never
bare URLs), no timestamps, no closing offers. On a runbook failure, reply
with the actual error rather than staying silent — a missing reply reads as
a lost command.

## 5. Finish

Append the handled commands to `daimon state set` as
`{"handled": [{"command", "user", "channel", "ts", "ok"}]}` merged over the
previous record — `channel` + `ts` are the dedupe key, so they are
mandatory. Keep only the newest ~100 handled entries. Summarize what was
handled and how each reply went.
