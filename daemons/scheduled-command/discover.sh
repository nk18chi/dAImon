#!/usr/bin/env bash
# Gate for scheduled-command: enqueue the configured command for the engine
# and always report "no work", so this daemon never launches an agent of its
# own. Everything here is script — a scheduled command costs nothing until
# the engine actually runs it.
set -uo pipefail

source "$(dirname "$0")/../../lib/common.sh"

tz="${DAIMON_INPUT_TZ:-America/New_York}"
days="${DAIMON_INPUT_DAYS:-}"
if [ -n "$days" ]; then
  today="$(TZ="$tz" date +%u)"
  case " $days " in *" $today "*) ;; *) exit 1 ;; esac
fi

python3 - "$(runtime_dir)/inbox.json" "$(state_file scheduled-command)" <<'PY' || exit 2
import json, os, sys, datetime

inbox_path, state_path = sys.argv[1], sys.argv[2]
tz = os.environ.get("DAIMON_INPUT_TZ", "UTC")
today = datetime.datetime.now().strftime("%Y-%m-%d")


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


# Once per day: launchd re-fires missed jobs on wake, and a duplicate
# scheduled post is worse than a late one.
state = load(state_path, {})
if state.get("last_enqueued") == today:
    raise SystemExit(0)

inbox = load(inbox_path, {"messages": []})
inbox.setdefault("messages", []).append(
    {
        "to": os.environ.get("DAIMON_INPUT_TARGET", "slack-commands"),
        "command": os.environ["DAIMON_INPUT_COMMAND_TEXT"],
        "channel": os.environ["DAIMON_INPUT_CHANNEL"],
        "user": os.environ.get("DAIMON_INPUT_AS_USER", ""),
        "ts": f"scheduled-{today}",
        "via": "schedule",
    }
)
os.makedirs(os.path.dirname(inbox_path), exist_ok=True)
with open(inbox_path, "w") as f:
    json.dump(inbox, f, indent=2)
    f.write("\n")

state["last_enqueued"] = today
os.makedirs(os.path.dirname(state_path), exist_ok=True)
with open(state_path, "w") as f:
    json.dump(state, f)
PY

target="${DAIMON_INPUT_TARGET:-slack-commands}"
# Double-forked: the nudge's launch.sh reaps the engine, so it must outlive us.
( nohup "$DAIMON_INSTALL_ROOT/bin/daimon" run "$target" >/dev/null 2>&1 & )
exit 1
