# Slack commands

Run commands against your local agent environment from Slack, and let
daemons post updates back. Three pieces:

| Piece | What it does |
|---|---|
| `slack-commands` daemon | The engine. Reads commands from its inbox, runs the matching plugin runbook, replies in Slack. |
| A front door | Either `bridges/env-bridge` (a Socket Mode Slack app: slash command + @-mention) or the `slack-channel-watch` daemon (polls channels for `?`-prefixed messages — no Slack app needed). |
| `slack-standup` daemon | Scheduled outbound: posts a standup on a weekday cadence. |
| `slack-ask` daemon | Q&A bot: answers free-form @-mention questions from the codebase (see [below](#qa-bot-slack-ask)). |

## Prerequisites

- **Slack MCP** — the daemons reach Slack only through Slack's hosted MCP server.
  For Claude, run `plugin install slack@claude-plugins-official`, then authorize
  once in an interactive session with `/mcp`. For Codex fallback, run
  `daimon mcp setup slack` once and complete Slack OAuth in the browser. The
  first setup in a workspace uses Slack CLI authentication to create a
  dedicated internal `dAImon Codex` app with MCP + PKCE enabled and a fixed
  local callback. It stores only the public app and client IDs under dAImon's
  state directory. Run `daimon mcp share slack` to print the setup command for
  teammates; each developer reuses the same app but completes OAuth into their
  own Codex credential store. If your workspace already provides an
  MCP-enabled app, pass its public ID as `daimon mcp setup slack <client-id>`
  instead. `daimon doctor` checks both paths, including whether Codex completed
  OAuth.
- **jq**, **gh**, **node 18+** (front door only), and the
  [Slack CLI](https://docs.slack.dev/tools/slack-cli) (app front door
  only). `make tooling` reports what's missing.

## Pick a front door

**Channel watcher (no app, no admin approval).** Configure
`daemons/slack-channel-watch/daemon.local.toml` with the channel IDs to
watch; anyone types `?help` in one of them. Two polling modes:

- *Scripted* (preferred): set `token_command` to a command printing a
  Slack token with `channels:history` / `groups:history` scope. The gate
  polls in pure script — no agent launches, so ticks are free and the
  interval can go to 30s.
- *Agent fallback* (`token_command` empty): each tick is a short agent
  session using the Slack MCP. Works with no extra token; costs a model
  call per tick, so keep the interval at 120s or higher.

**Slack app.** `make bridge-setup` (toolchain check + names + manifest),
then `daimon bridge` to create and run it. Gives `/<your-command>` and
@-mentions. Each engineer registers their own app — `BRIDGE_NAME` and
`BRIDGE_SLASH_COMMAND` come from `.env`, and slash commands are
workspace-global so they must be unique.

## Writing a command

Commands are markdown runbooks, one file per command:

- `daemons/slack-commands/commands/` — committed, shared by everyone.
- `daemons/slack-commands/commands.local/` — gitignored, yours or your
  company's; a local file overrides a shared one of the same `name`.

Drop a file in, and it's live on the next run — no sync, no restart.

```markdown
---
name: prod-status
match: prod-status
mutating: false
description: What shipped to production recently.
---

1. `gh pr list --state merged --limit 50` filtered to the window.
2. Reply with ticket-led bullets grouped by scope.
```

Conventions:

- **Name**: one hyphenated token, `{domain}-{action/topic}`
  (`staging-push`, `epic-status`); a bare domain only when unambiguous
  (`standup`). Everything after the first space is arguments.
- **`mutating: true`** — restricted to the `mutate_allowlist` (config) plus
  anyone granted from Slack via `access grant @user`. Use it for anything
  that writes, deploys, or spends real work.
- **`admin: true`** — allowlist only, and hidden from listings for
  everyone else.
- Runbooks run from the daemon's `working_dir`, so repo tooling is just
  there. Write them as instructions, not scripts: state the goal, the
  commands to run, and the reply shape.
- Long work (an implementation, a deploy) must be **launched detached**
  and reported asynchronously — never block the engine, or other queued
  commands stall behind it.

## Access control

`mutate_allowlist` in `daemon.local.toml` is the root of trust (Slack user
IDs, machine-only). Those admins manage everyone else from Slack:
`access list` / `access grant @user` / `access revoke @user`, persisted in
daemon state. Grants never confer admin.

## Q&A bot (slack-ask)

Tag the bot with a question in a configured channel — "@bot why didn't this
deal sync to HubSpot?" — and the `slack-ask` daemon answers in the thread from
the code (and read-only data tools you grant it). Each channel gets a
playbook: `crm` explains behavior for non-engineers; `bug-triage` names likely
causes and asks up to three follow-up questions. It only runs when tagged; to
continue, tag it again in the thread — it re-reads the whole thread each time.

**Setup** (start with a throwaway test channel):

1. Create the channel, invite the bot (`/invite @<your-bot>`) **and yourself**
   — replies post through your Slack MCP, so you must be a member.
2. Put the channel ID in env-bridge's `.env` as `BRIDGE_ASK_CHANNELS`, and
   restart `daimon bridge`.
3. Copy `daemons/slack-ask/daemon.local.toml.example` to `daemon.local.toml`:
   a dedicated clone as `working_dir`, the channel in `channel_playbooks`, and
   the read-only MCP tools you want in `tools`.
4. `daimon config validate && daimon sync`.

**Security model.** Anyone in the channel can trigger it, so the message text
is untrusted. The daemon sets `[daemon].tools`, which runs Claude in
`dontAsk` mode: tools not on the allowlist are denied, never prompted, and the
target repo's own settings can't widen the list. The default list is read-only
(file reads, a few `git` reads, draining its own inbox, and two Slack tools).
Data tools are opt-in and named one by one. The allowlist is not the only
guard for a database: connect it as a **read-only user** too, since some
"read" tools (an aggregate with `$out`/`$merge`) can write. The skill also
treats Slack text as a question, never as instructions, refuses to post
secrets, and answers data questions with aggregates and IDs, never raw
documents. A mention in a channel not in `channel_playbooks` gets no answer.
