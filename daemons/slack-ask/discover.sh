#!/usr/bin/env bash
# Discovery gate for slack-ask. This daemon has no autonomous work — it only
# runs when the inbox gate (checked before discovery in run.sh) finds a
# mention queued for it. Always report "nothing to do" here.
exit 1
