#!/usr/bin/env bash
# Discovery gate for slack-commands. This daemon has no autonomous work —
# it only runs when the inbox gate (checked before discovery in run.sh)
# finds a message addressed to it. Always report "nothing to do" here.
exit 1
