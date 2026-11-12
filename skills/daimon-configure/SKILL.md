---
name: daimon-configure
description: Edit an existing dAImon daemon's settings or inputs, then re-validate and re-sync.
---

# daimon-configure

Modify a daemon the user names (or list `daimon daemons` and ask which).

1. Read its `daemons/<slug>/daemon.toml` and `skill/SKILL.md`.
2. Ask what to change — schedule, backend/model (offer `daimon models <backend>`),
   capacity-only fallback backend, danger, `stuck_after`, an `[inputs]` value, or
   the prompt itself.
3. Apply the edit. If an `[inputs]` key changes, update any `{{inputs.<key>}}` use
   in `skill/SKILL.md` to stay consistent.
4. Run `daimon config validate`; if clean, remind the user to `daimon sync` so the
   plist and rendered skill pick up the change.

Never enable/disable launchd scheduling without confirming.
