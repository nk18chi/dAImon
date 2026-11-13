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

## Running it in the background

`slack run` stops when its terminal closes. To keep the bridge up without a
terminal, run it as a launchd service: it starts at login, restarts if it
exits, and logs to `~/.local/state/daimon/logs/bridge.log`. It still runs
only while your Mac is awake.

1. Add your app's two tokens to `.env` (from your app's page on
   api.slack.com). The service runs `node app.js` itself, so it needs what
   `slack run` normally supplies:
   - `SLACK_BOT_TOKEN=xoxb-…` — *OAuth & Permissions* → Bot User OAuth Token.
   - `SLACK_APP_TOKEN=xapp-…` — *Basic Information* → App-Level Tokens →
     Generate, with scope `connections:write`. Leave token rotation off: a
     rotated token expires and the service can't renew it.
2. `daimon bridge service install`. It refuses, saying what's missing, until
   both tokens and the setup above are in place.
3. Stop any `slack run` terminal, so only one bridge is connected.

`daimon bridge service status` shows whether it's running;
`daimon bridge service uninstall` removes it. The control panel
(`daimon tui`) shows the same under the daemon list — "slack bridge" running
or off — and `B` starts or stops it (stopping asks first). Re-run `install` after
upgrading Node: the service points at the `node` that was on your PATH.

## Configuration (env)

| Variable | Default | Purpose |
|----------|---------|---------|
| `BRIDGE_NAME` | `env-bridge` | App + bot display name (make it yours) |
| `BRIDGE_SLASH_COMMAND` | `/hub` | Slash command — must be workspace-unique |
| `BRIDGE_ASK_CHANNELS` | — | Comma-separated channel IDs where an @-mention is a free-form question for the `slack-ask` daemon instead of a command (see [docs/slack-commands.md](../../docs/slack-commands.md)) |
| `BRIDGE_ASK_DAILY_LIMIT` | `30` | Questions one person may ask in the ask channels per day (local midnight to midnight) |
| `BRIDGE_ASK_DAILY_TEAM_LIMIT` | `100` | Questions everyone together may ask per day |
| `BRIDGE_REPORT_CHANNELS` | — | Ask channels where every new post by the report form gets an automatic first look, with nobody tagging the bot |
| `BRIDGE_REPORT_APP_ID` | — | The report form's app id (a post's `app_id`); only its top-level posts start a run |
| `BRIDGE_REPORT_DAILY_LIMIT` | `20` | Automatic first looks per day, counted apart from the question limits |
| `DAIMON_STATE_DIR` | `~/.local/state/daimon` | Where the daimon inbox lives |
| `DAIMON_BIN` | `~/.local/bin/daimon` | The daimon CLI used to nudge the daemon |
| `DAIMON_NS` | `daimon` | dAImon's `core.namespace`; the bridge checks the `<namespace>-slack-ask` session to tell a new question how many are ahead of it (the service sets it for you) |
| `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` | — | Only for the background service (`slack run` supplies them otherwise) — see above |
| `BRIDGE_LOG_LEVEL` | `debug` | Bolt log level; the service uses `info` |

`manifest.json` is generated (`npm run manifest`) and untracked — the
committed source of truth is `manifest.template.json`.

## Notes

- `slack-commands` replies come from the daemon's Slack credentials; for
  those, the app only posts the "queued" acknowledgement.
- `slack-ask` has no Slack access. For a mention in an ask channel the app
  reads the thread, plus up to three same-channel threads the question links
  to, into the queued message, then posts the daemon's reply as
  this bot from `<state dir>/outbox/slack-ask/` — only into an ask channel.
- Images attached in those threads (PNG, JPG, GIF or WebP, at most 4 per
  question, 5 MB each) are downloaded to
  `<state dir>/runtime/slack-ask-images/` for the bot to look at, and deleted
  once its answer is posted; a sweep removes any left after a day. This needs
  the `files:read` scope: after adding it to an existing app, reinstall the
  app in the workspace. Without it, images are skipped and logged.
- With the `reactions:write` scope, the app marks each question 👀 when it's
  queued, ✅ once its answer is posted, and 🚫 when it's over the daily limit.
  Without the scope it posts ":mag: looking into it…" instead of 👀.
- `.scrap/` holds unused Slack starter-template parts; delete it freely.
