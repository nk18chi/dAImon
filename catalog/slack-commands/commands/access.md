---
name: access
match: access
mutating: false
admin: true
description: Manage who may run mutating commands (list / grant / revoke).
---

Arguments: `list`, `grant <@user>`, or `revoke <@user>`. Slack renders
mentions as `<@U012345>` — extract the bare user ID.

The grants live in this daemon's state (`daimon state get` /
`daimon state set`) as a `grants` array of Slack user IDs, merged over the
rest of the state record — never drop other keys.

- `list` — reply with the admins (from config, immutable from Slack) and
  the current grants, resolving IDs to display names via the Slack MCP
  user tools when available.
- `grant` — add the user ID to `grants` (idempotent); reply confirming
  what they can now run (the mutating command list).
- `revoke` — remove the ID from `grants`; reply confirming. Revoking an
  admin is a no-op — say that config admins can only be changed on the
  machine.
