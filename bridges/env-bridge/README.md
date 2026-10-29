# env-bridge

A deliberately thin Slack → local-agent bridge. It runs on your machine in
Socket Mode (no hosting, no public endpoint) and does exactly one thing: turn
a slash command or @-mention into a message in your
[dAImon](https://github.com/effekt/dAImon) inbox, then nudge the
`slack-commands` daemon to handle it. All command logic — parsing,
authorization, execution, replying — lives in that daemon's plugin-driven
skill, so adding a command never touches this app.

```
/hub standup            env-bridge (Socket Mode, local)
@env-bridge epic 123  ─────────────► daimon inbox ──► slack-commands daemon
                                                        (your local agent:
                                                         full MCP + repo access)
```

## Why this shape

- **The app is dumb on purpose.** No AI key, no business logic, ~60 lines.
  The brain is your existing local agent environment, which already has the
  credentials and context (repo, tracker CLI, MCP servers) that a hosted app
  can't have.
- **Commands are plugins.** Each command is a markdown runbook in the
  daemon's `commands/` directory (shared) or `commands.local/` (yours /
  your company's, gitignored). Drop in a file, get a command.
- **Authorization is central.** Mutating commands are gated on a Slack
  user-ID allowlist in the daemon's config, not in app code.

## Setup (white-labeled per engineer)

Each engineer registers their **own** Slack app from this shared code — the
app's name and slash command come from your `.env`, so instances don't
collide. Slash commands are workspace-global: pick one nobody else claimed
(e.g. `/hub-sam`), or skip slash entirely and rely on @-mentions of your
bot's unique name.

1. Prereqs: [Slack CLI](https://docs.slack.dev/tools/slack-cli) (authed to
   your workspace), Node 18+, a dAImon install with the `slack-commands`
   daemon configured.
2. `npm run setup` — checks the toolchain, asks for your app/bot name and
   slash command, writes `.env`, and renders `manifest.json`. (Manual
   equivalent: `cp .env.sample .env`, edit, `npm run manifest`.) The app
   refuses to start until this has run.
3. `slack run` — creates + installs *your* app to the workspace (admin
   approval may be required) and starts the local Socket Mode process.
4. Try `<your-slash> help` in Slack, or `@<your-bot> help`.

## Configuration (env)

| Variable | Default | Purpose |
|----------|---------|---------|
| `BRIDGE_NAME` | `env-bridge` | App + bot display name (make it yours) |
| `BRIDGE_SLASH_COMMAND` | `/hub` | Slash command — must be workspace-unique |
| `BRIDGE_ASK_CHANNELS` | — | Comma-separated channel IDs where an @-mention is a free-form question for the `slack-ask` daemon instead of a command (see [docs/slack-commands.md](../../docs/slack-commands.md)) |
| `DAIMON_STATE_DIR` | `~/.local/state/daimon` | Where the daimon inbox lives |
| `DAIMON_BIN` | `~/.local/bin/daimon` | The daimon CLI used to nudge the daemon |

`manifest.json` is generated (`npm run manifest`) and untracked — the
committed source of truth is `manifest.template.json`.

## Notes

- Replies come from the daemon's Slack credentials, not this bot — the app
  only posts the ephemeral "queued" acknowledgement.
- `.scrap/` holds unused Slack starter-template parts; delete it freely.
