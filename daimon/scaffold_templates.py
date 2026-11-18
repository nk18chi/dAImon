"""The files `daimon scaffold` writes; `{slug}` is filled in, so literal braces are doubled."""

DAEMON_TOML = """\
[daemon]
backend = "claude"
schedule = {{ interval = 1800 }}
command = "/{slug}"
# Override [defaults] only where this daemon differs: model, danger, stuck_after.
# role = "{slug}"   # run on one machine at a time ([roles].command)

[inputs]
# What the skill and gate need, as {{{{inputs.<key>}}}} / $DAIMON_INPUT_<KEY>.
# Shared values go here; each person's own go in ~/.daimon/daemons/<slug>.toml.
"""

LOCAL_EXAMPLE = """\
# Copy to ~/.daimon/daemons/<slug>.toml (daimon init does it) for values
# that are yours alone.
[daemon]
# working_dir = "~/code/your-repo"

[inputs]
"""

SKILL = """\
---
name: {slug}
description: TODO one sentence on what {slug} does.
---

# {slug}

## 1. Discover
Find the work items this run should handle. Skip anything already handled
(read `daimon state get`).

## 2. Act
For each item: TODO the per-item work.

## 3. Finish
Record what was handled with `daimon state set`; summarize briefly.
"""

DISCOVER = """\
#!/usr/bin/env bash
# Gate for {slug}: exit 0 to launch the agent, 1 to skip (nothing to do), any
# stderr or exit >= 2 to report an error. Inputs arrive as $DAIMON_INPUT_<KEY>.
set -uo pipefail

# dAImon exports this when it runs the gate; fall back to the `daimon` on PATH.
DAIMON_INSTALL_ROOT="${{DAIMON_INSTALL_ROOT:-$(cd "$(dirname "$(readlink -f "$(command -v daimon)")")/.." && pwd)}}"
# shellcheck source=/dev/null
source "$DAIMON_INSTALL_ROOT/lib/common.sh"
# Source profiles' helpers the same way, e.g.:
# source "$DAIMON_INSTALL_ROOT/profiles/github/lib.sh"

# TODO: look for work and exit 0 when there is some. Until then this daemon
# never launches.
exit 1
"""
