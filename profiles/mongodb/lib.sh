#!/usr/bin/env bash
# Shared helpers for the MongoDB source profile: Atlas Query Shape Insights via the
# Atlas Admin API, for discovery gates. Sourced by a daemon's discover.sh. Every
# helper fails closed (no creds, no auth, bad response) to the "no work" answer, so
# a gate never launches on a broken query.
#
# Why the raw API rather than the MongoDB MCP server: MCP exposes no Query Shape
# Insights tool. Its atlas-get-performance-advisor returns suggested indexes and a
# 50-row slow-query-log sample — not the per-shape avg/total/count aggregates a
# slow-query daemon ranks on. The skill still uses MCP for enrichment; only the
# gate needs this, because gates are plain bash and run before any agent exists.

ATLAS_API_BASE="https://cloud.mongodb.com"
# Query Shape Insights is a preview resource and 404s without an explicit version.
ATLAS_API_VERSION="application/vnd.atlas.2025-03-12+json"

# atlas_creds -> "<client-id> <client-secret>" on stdout, empty on failure. Every
# source is under $HOME by necessity: launchd forwards only PATH, HOME and
# SSH_AUTH_SOCK to a scheduled run, so a key exported in .zshrc never arrives.
#   1. $ATLAS_CLIENT_ID / $ATLAS_CLIENT_SECRET
#   2. ~/.config/daimon/atlas.env — KEY=value lines (preferred; cheapest to read)
#   3. the service account the MongoDB MCP server is already configured with, so
#      a working MCP setup needs no second copy of the credentials
atlas_creds() {
  python3 - <<'PY' 2>/dev/null
import json, os, re, sys

def emit(cid, sec):
    if cid and sec:
        print(f"{cid} {sec}")
        sys.exit(0)

emit(os.environ.get("ATLAS_CLIENT_ID"), os.environ.get("ATLAS_CLIENT_SECRET"))

path = os.path.expanduser("~/.config/daimon/atlas.env")
if os.path.exists(path):
    kv = {}
    with open(path) as fh:
        for line in fh:
            m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)", line)
            if m:
                kv[m.group(1)] = m.group(2).strip().strip("\"'")
    emit(kv.get("ATLAS_CLIENT_ID"), kv.get("ATLAS_CLIENT_SECRET"))

path = os.path.expanduser("~/.claude.json")
if os.path.exists(path):
    try:
        with open(path) as fh:
            env = json.load(fh)["mcpServers"]["mongodb-mcp-server"]["env"]
        emit(env.get("MDB_MCP_API_CLIENT_ID"), env.get("MDB_MCP_API_CLIENT_SECRET"))
    except Exception:
        pass
PY
}

# atlas_token -> a bearer token for the Atlas Admin API ("" on any failure).
# Service accounts use OAuth2 client credentials, not the older digest auth.
atlas_token() {
  local creds id sec
  creds="$(atlas_creds)"
  [ -z "$creds" ] && return
  id="${creds%% *}"; sec="${creds#* }"
  curl -s --max-time 20 --request POST --url "$ATLAS_API_BASE/api/oauth/token" \
    --user "$id:$sec" \
    --header 'Content-Type: application/x-www-form-urlencoded' \
    --header 'Accept: application/json' \
    --data 'grant_type=client_credentials' 2>/dev/null \
    | python3 -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null
}

# mdb_query_shapes "<project-id>" "<cluster>" "<lookback-hours>" -> JSON array of
# user query shapes over the window ([] on any failure). Each element carries
# queryShapeHash, queryShape, namespace, command, execCount, avgWorkingMillis,
# totalWorkingMillis, docsExamined/Returned/Ratio, keysExaminedRatio and p50/p90/p99.
mdb_query_shapes() {
  local token since hours out
  token="$(atlas_token)"
  [ -z "$token" ] && { printf '[]'; return; }
  hours="${3:-24}"
  # Guard the arithmetic: a non-numeric input would write to stderr, which run.sh
  # reads as a broken gate rather than an honest "no work".
  case "$hours" in ''|*[!0-9]*) hours=24 ;; esac
  since=$(( ( $(date +%s) - hours * 3600 ) * 1000 ))
  out="$(curl -s --max-time 45 \
    --url "$ATLAS_API_BASE/api/atlas/v2/groups/$1/clusters/$2/queryShapeInsights/summaries?since=$since" \
    --header "Accept: $ATLAS_API_VERSION" \
    --header "Authorization: Bearer $token" 2>/dev/null)" || { printf '[]'; return; }
  # Drop systemQuery shapes — Atlas's own internal traffic, which the UI hides
  # behind "Show system queries". They are never actionable and one of them
  # outranks every user query by total execution time.
  printf '%s' "$out" \
    | jq -c '[ (.summaries // [])[] | select(.systemQuery != true) ]' 2>/dev/null \
    || printf '[]'
}

# mdb_candidates_file "<slug>" -> path the gate hands its candidate list to the
# agent through. The gate has already authenticated and fetched; writing the result
# here means the skill reads a local file instead of calling the Atlas API itself.
# That matters in non-danger sessions: an agent-side curl to cloud.mongodb.com
# would sit on a permission prompt with nobody there to answer it until
# stuck_after reaps the run. It also spares the agent any credential handling.
mdb_candidates_file() { echo "$(runtime_dir)/$1-candidates.json"; }

# mdb_slow_shapes "<shapes-json>" <avg-ms> <total-ms> <ratio> <per-exec> -> the subset
# tripping any threshold ([] on any failure). See profile.toml for why these are OR'd.
#
# The ratio rule is guarded. docsExaminedRatio is docsExamined/docsReturned, and
# docsReturned counts result DOCUMENTS, not underlying rows — so it means what it
# looks like only sometimes. About one shape in five on a real cluster is one of:
#   docsReturned == 0          -> returned nothing; the ratio is not a ratio, and
#                                 Atlas still reports a huge number for it.
#   docsReturned == execCount  -> one envelope doc per run ($facet, or $group on
#                                 _id:null), so the "ratio" is already docs/execution.
# Firing rule 3 on those produces stories asserting "reads 3.6M documents to return
# one" about a query that reads 4 per run and returns nothing. The per-exec rule
# covers both cases honestly, so the guard loses no coverage.
mdb_slow_shapes() {
  printf '%s' "$1" | jq -c \
    --argjson avg "$2" --argjson total "$3" --argjson ratio "$4" --argjson perexec "${5:-1000}" '
    def per_exec: (.docsExamined // 0) / ([(.execCount // 0), 1] | max);
    def ratio_is_per_row:
      ((.docsReturned // 0) > 0)
      and ((((.docsReturned // 0) - (.execCount // 0)) | length) > 0.5);
    [ .[] | select(
         ((.avgWorkingMillis   // 0) > $avg)
      or ((.totalWorkingMillis // 0) > $total)
      or (ratio_is_per_row and ((.docsExaminedRatio // 0) > $ratio))
      or (per_exec > $perexec)
    ) ]' 2>/dev/null || printf '[]'
}
