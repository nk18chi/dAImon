---
name: help
match: help
mutating: false
description: List the available commands.
---

Reply with one line per installed command plugin — `name` — description —
with mutating ones marked "(restricted)". **Omit `admin: true` plugins
entirely unless the requester is an admin** — non-admins have no use for
them and the surface shouldn't advertise its own controls. Mention both
invocation forms (the slash command and @-mention).
