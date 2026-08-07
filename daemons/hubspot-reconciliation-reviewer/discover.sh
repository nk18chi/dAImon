#!/usr/bin/env bash
# Gate for hubspot-reconciliation-reviewer: fire when the daily HubSpot property
# reconciliation reported drift on a (kind, field) pair we have not already filed.
#
# The seen-check belongs here, not only in the skill. Drift persists until someone
# ships a mapper fix, so the same cluster reappears in every daily report for days
# or weeks — without this the gate would wake the agent each run just to no-op.
#
# Clustering explodes fieldNames: one drifted record listing three mismatched
# fields contributes to three clusters, because the fix is per mapper field. The
# skill re-derives co-occurrence from the handed-over sample so a human can merge
# them if they share a root cause.
#
# Fails closed (no pup, no auth, bad query) to "skip".
set -uo pipefail

source "$(dirname "$0")/../../lib/common.sh"
source "$(dirname "$0")/../../profiles/datadog/lib.sh"

events="$(dd_log_json "$DAIMON_INPUT_LOG_QUERY" "${DAIMON_INPUT_LOOKBACK:-30h}")"
seen="$(load_seen_state "$(state_file hubspot-reconciliation-reviewer)")"

# Datadog nests custom attributes under .attributes.attributes; tolerate a flat
# shape too so an envelope change degrades to "no candidates", never a crash.
clusters="$(printf '%s' "$events" | jq -c --argjson seen "$seen" '
  [ .[] | (.attributes.attributes // .attributes // {}) ]
  | map(select(.kind != null and (.fieldNames | type) == "array"))
  | map(. as $r | $r.fieldNames[] | {
      signature: ($r.kind + ":" + .),
      kind: $r.kind,
      field: .,
      status: $r.status,
      missing_reason: $r.missingReason,
      run_id: $r.runId,
      mongo_id: $r.mongoId,
      co_fields: $r.fieldNames
    })
  | group_by(.signature)
  | map({
      signature: .[0].signature,
      kind: .[0].kind,
      field: .[0].field,
      count: length,
      statuses: (map(.status) | unique),
      missing_reasons: (map(.missing_reason) | map(select(. != null)) | unique),
      run_ids: (map(.run_id) | unique),
      co_fields: (map(.co_fields) | add | unique),
      sample_mongo_ids: (map(.mongo_id) | unique | .[0:5])
    })
  | map(select(. as $c | ($seen | any(.signature == $c.signature) | not)))
  | sort_by(-.count)
' 2>/dev/null)" || clusters=""
[ -z "$clusters" ] && clusters="[]"

total="$(printf '%s' "$clusters" | jq 'length' 2>/dev/null || echo 0)"

# Hand the clustered result to the agent rather than making it re-query Datadog:
# the raw window runs to ~1000 events of near-identical JSON, and the agent only
# files max_new_stories per run. Twice that leaves headroom for candidates it
# drops as already-tracked in the tracker. The remainder is not lost — it stays
# absent from the state file, so the next run resurfaces it.
hand_over=$(( ${DAIMON_INPUT_MAX_NEW_STORIES:-3} * 2 ))
[ "$hand_over" -lt 4 ] && hand_over=4

mkdir -p "$(runtime_dir)" 2>/dev/null
candidates_file="$(runtime_dir)/hubspot-reconciliation-reviewer-candidates.json"
printf '%s' "$clusters" | jq --argjson n "$hand_over" --argjson total "$total" \
  '{total_candidates: $total, handed_over: (. | length | if . > $n then $n else . end), clusters: .[0:$n]}' \
  > "$candidates_file" 2>/dev/null \
  || printf '{"total_candidates":0,"handed_over":0,"clusters":[]}' > "$candidates_file"

[ "$total" -gt 0 ]
