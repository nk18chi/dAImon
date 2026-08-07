#!/usr/bin/env bash
# Gate for mongo-slow-query-reviewer: fire when Atlas Query Shape Insights holds a
# query shape over any threshold that we have not already filed a story for.
#
# The seen-check belongs in the gate here, not only in the skill. The window is a
# rolling lookback_hours (24h by default), so a shape that trips a threshold keeps
# tripping it for a full day — without this the daemon would relaunch the agent
# every 30 minutes to rediscover the same shapes and no-op, ~48 empty runs a day.
# queryShapeHash is Atlas's own canonical shape id, so the match is exact and needs
# no signature normalization.
#
# Fails closed (no creds, no auth, bad response) to "skip".
set -uo pipefail

source "$(dirname "$0")/../../lib/common.sh"
source "$(dirname "$0")/../../profiles/mongodb/lib.sh"

shapes="$(mdb_query_shapes \
  "$DAIMON_INPUT_ATLAS_PROJECT_ID" "$DAIMON_INPUT_CLUSTER_NAME" "$DAIMON_INPUT_LOOKBACK_HOURS")"
slow="$(mdb_slow_shapes "$shapes" \
  "$DAIMON_INPUT_AVG_MS_THRESHOLD" "$DAIMON_INPUT_TOTAL_MS_THRESHOLD" \
  "$DAIMON_INPUT_EXAMINED_RATIO_THRESHOLD" "$DAIMON_INPUT_DOCS_PER_EXEC_THRESHOLD")"
seen="$(load_seen_state "$(state_file mongo-slow-query-reviewer)")"

# Namespace exclusions are applied here too, so an ignored-but-slow collection
# never wakes the agent just to be filtered out again.
candidates="$(printf '%s' "$slow" | jq -c \
  --argjson seen "$seen" \
  --arg ignore "${DAIMON_INPUT_IGNORE_NAMESPACES:-}" '
  ($ignore | split(",") | map(gsub("^\\s+|\\s+$";"")) | map(select(length > 0))) as $skip
  | [ .[] | select(. as $s
      | ($seen | any(.query_shape_hash == $s.queryShapeHash) | not)
      and ($skip | any(. as $n | ($s.namespace // "") | contains($n)) | not))
    ] | sort_by(-.totalWorkingMillis)
' 2>/dev/null)" || candidates=""
[ -z "$candidates" ] && candidates="[]"

total="$(printf '%s' "$candidates" | jq 'length' 2>/dev/null || echo 0)"

# Hand the result to the agent rather than making it re-query Atlas. See
# mdb_candidates_file for why. Written on every fire, so it can never go stale
# behind a launch that did run the gate.
#
# Only the top slice goes over, pretty-printed. The full candidate set runs to
# ~50k tokens of normalized pipelines on a busy cluster — more than the agent can
# read in one call, and it only files max_new_stories per run anyway. Twice that
# leaves headroom for candidates it drops as already-tracked. The remainder is not
# lost: it stays unfiled in the state file, so the next run's dedupe surfaces it.
hand_over=$(( ${DAIMON_INPUT_MAX_NEW_STORIES:-3} * 2 ))
[ "$hand_over" -lt 4 ] && hand_over=4

mkdir -p "$(runtime_dir)" 2>/dev/null
printf '%s' "$candidates" | jq --argjson n "$hand_over" --argjson total "$total" \
  '{total_candidates: $total, handed_over: (. | length | if . > $n then $n else . end), shapes: .[0:$n]}' \
  > "$(mdb_candidates_file mongo-slow-query-reviewer)" 2>/dev/null \
  || printf '{"total_candidates":0,"handed_over":0,"shapes":[]}' > "$(mdb_candidates_file mongo-slow-query-reviewer)"

[ "$total" -gt 0 ]
