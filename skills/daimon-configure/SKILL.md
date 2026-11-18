---
name: daimon-configure
description: Edit an existing dAImon daemon's settings or inputs, then re-validate and re-sync.
---

# daimon-configure

Modify a daemon the user names (or list `daimon daemons` and ask which).

1. Find its folder with `daimon config daemon-dir <slug>` and read its
   `daemon.toml` and `skill/SKILL.md`. Note where it lives (`docs/catalog.md`):
   - dAImon's `catalog/` or a pack's `daemons/`: **linked**, shared code in git.
     Never edit files there.
   - the install's own `daemons/`: an ejected copy or the user's own daemon,
     theirs to edit (gitignored).
2. Ask what to change — schedule, backend/model (offer `daimon models <backend>`),
   capacity-only fallback backend, danger, `stuck_after`, an `[inputs]` value, or
   the prompt itself.
3. **Settings** (any `[daemon]` field or an `[inputs]` value): write only the
   changed keys to the personal file `~/.daimon/daemons/<slug>.toml`, under
   `[daemon]` / `[inputs]`, keeping what is already there. It overrides the
   daemon's `daemon.toml` wherever that lives, and is outside every repo.
4. **Structural changes** (the prompt, the gate, new or renamed inputs, shipped
   files): only in a folder the user owns.
   - Linked from dAImon's catalog: offer `daimon eject <slug>`, then edit the copy
     in `daemons/<slug>/`. (A change useful to everyone can go to dAImon instead,
     by PR.)
   - Linked from a pack: the team owns it, so change it by a PR to the pack, or
     `daimon eject <slug>` for a change just for this machine.
   - Already in `daemons/`: edit it in place. If an `[inputs]` key changes, update
     any `{{inputs.<key>}}` use in `skill/SKILL.md` to stay consistent.
5. Run `daimon config validate`; if clean, remind the user to `daimon sync` so the
   plist and rendered skill pick up the change.

Never enable/disable launchd scheduling without confirming.
