---
name: scheduled-command
description: Placeholder — this daemon enqueues its command from the gate and never launches an agent.
---

# scheduled-command

Nothing to do here. This daemon's work happens entirely in `discover.sh`:
it enqueues `{{inputs.command_text}}` for the `{{inputs.target}}` engine
and reports "no work", so no agent session is ever launched on its behalf.

If you are reading this, the daemon was launched manually (`daimon launch
scheduled-command`). Report that the gate is the whole daemon and stop —
to run the command by hand, type it in a watched Slack channel instead.
