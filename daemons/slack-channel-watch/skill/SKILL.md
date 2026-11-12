---
name: slack-channel-watch
description: Poll Slack channels for trigger-prefixed command messages and forward them to the command daemon's inbox.
---

# slack-channel-watch

Front door for the `{{inputs.target}}` plugin engine when no Slack app can
be installed: watch the channels in `{{inputs.watch_channels}}` and forward
new command messages. Be fast and cheap — read, forward, exit. Never
execute commands yourself.

## 0. The exact tool-call sequence — follow it literally

MCP tools are invoked EXACTLY like Bash: as direct tool calls in your
response. **Bash can NEVER call an MCP tool** — no bash script, loop,
pipe, or helper can reach them, so never attempt it and never "collect
results" via shell. There is also no need for parallelism cleverness:
just make these calls, in order:

1. `daimon state get slack-channel-watch` (Bash) → the `last_ts` map.
2. Make the Slack tools available for this backend:
   - **Claude:** use ToolSearch with query
     `select:mcp__plugin_slack_slack__slack_read_channel,mcp__plugin_slack_slack__slack_read_thread`.
     The plugin tools are deferred and invisible until this runs.
   - **Codex:** do not look for ToolSearch. The authenticated `slack` MCP server
     exposes `slack_read_channel` and `slack_read_thread` directly; call those
     tools from the available Slack MCP namespace.
3. One `slack_read_channel` call per watched channel (a plain tool call
   each, `limit: 15`, no `oldest`).
4. `slack_read_thread` only for threads whose reply activity is newer
   than the channel's `last_ts`.
5. If anything qualified: edit the inbox file, then the double-forked
   nudge (Bash). Update state (Bash). Done.

If the backend-specific discovery above fails or a Slack call errors with an
auth problem, report that and stop — never substitute curl, the Slack CLI, raw
API calls, or subagents.

## 1. Read new messages

`daimon state get` → `last_ts`, a map of channel id → newest activity
timestamp already seen. For each watched channel, read the **most recent
messages WITHOUT an `oldest` filter** — `slack_read_channel` with
`limit: 15` and `response_format: "detailed"` (detailed carries the
thread/reply metadata you need; 15 recent messages is ample at this poll
cadence — never fetch the default 100). Never pass `oldest = last_ts`:
thread replies don't appear in channel history, so a thread is
only discoverable through its parent's reply metadata — and parents are
usually older than the watermark. Filtering happens by timestamp
comparison, not by the API window:

- **Top-level command**: message `ts` > the channel's `last_ts`, from a
  human, text starts with `{{inputs.trigger_prefix}}`.
- **Thread command**: for any fetched message whose thread shows reply
  activity newer than `last_ts` (latest reply timestamp / new reply
  count), read the thread with `slack_read_thread` and apply the same
  human + prefix test to replies with `ts` > `last_ts` (skip the parent
  row — it was handled as top-level when it was new).

Everything else is ignored, so mixed-purpose channels are safe. A channel
with no recorded `last_ts` yet gets a baseline-only pass — record the
newest activity timestamp, forward nothing old.

If nothing qualifies anywhere, finish with a one-line "no new commands"
(still advance `last_ts` per channel so old chatter isn't rescanned).

## 2. Forward

Strip the trigger prefix from each command's text. Resolve the state dir
(`daimon config paths` → `DAIMON_STATE_DIR`) and append one entry per
command to `$DAIMON_STATE_DIR/runtime/inbox.json` (`{"messages": [...]}`,
preserving existing messages):

```json
{"to": "{{inputs.target}}", "command": "<text without prefix>", "channel": "<message's channel id>",
 "ts": "<the command message's OWN ts>", "thread_ts": "<parent ts for replies, own ts for top-level>",
 "user": "<author user id>", "via": "channel"}
```

`ts` is the engine's dedupe key — always the command message's own
timestamp, never the parent's.

`thread_ts` is the command message's own `ts`, so the reply threads under
it. Then nudge the engine — the inbox gate launches it immediately — with
EXACTLY this double-forked form:

```bash
( nohup daimon run {{inputs.target}} >/dev/null 2>&1 & )
```

Never wait on it and never use a plain background job: `daimon run`
blocks until the launched agent finishes AND it is the process that reaps
the engine's session afterward. Your own session gets reaped the moment
you finish, killing your children — the double fork reparents the nudge
to init so it survives you and the engine gets cleaned up.

## 3. Finish

`daimon state set` with the updated per-channel map, EXACTLY this shape —
timestamps nested under a `last_ts` key, never at the top level (the
scripted gate reads this same record):

```json
{"last_ts": {"<channel id>": "<newest ts>", "...": "..."}}
```

The new watermark per channel is the MAX across everything you saw this
tick: top-level message timestamps AND every thread's newest reply
timestamp — even for channels/threads where nothing was forwarded. A
watermark that lags a thread reply re-forwards that command on every
tick.

Summarize: how many forwarded, from which channels.
