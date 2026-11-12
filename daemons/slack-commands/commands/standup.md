---
name: standup
match: standup
mutating: false
description: Generate the standup on demand and reply with it here.
---

Invoke the standup skill configured on this machine (default `/standup`; if a
`slack-standup` daemon is configured, use its `standup_command` input). Claude
may invoke it normally. Codex reads `~/.claude/commands/<name>.md` and follows
that command body inline, substituting the provided arguments; it never types a
Claude slash command into a shell.
Reply with the generated standup verbatim in the requesting channel/thread —
do NOT also post to the regular standup channel and do NOT record any
standup state; this is a read-only, on-demand copy.
