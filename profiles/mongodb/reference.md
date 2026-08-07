## Source: MongoDB Atlas

Query performance data comes from **Atlas Query Shape Insights** — the per-shape
aggregates behind the Atlas UI's *Query Insights → Query Shapes* tab.

**The MongoDB MCP server has no tool for this data.** Use the Admin API below for
the shape metrics; use MCP for everything else (schema, indexes, explain,
Performance Advisor). Both matter — the API tells you *which* query is expensive,
MCP tells you *why*.

### How the data is fetched — for reference, not for you to run

A daemon's **gate** performs this call and hands the result to you as a local file;
`profiles/mongodb/lib.sh` wraps it as `mdb_query_shapes` / `mdb_slow_shapes`, and
the credential resolution order is documented there. Runs are unattended with
permissions enforced, so an agent-side `curl` to `cloud.mongodb.com` stalls on a
permission prompt. This is here so you can interpret the fields, not re-fetch them.

```bash
# Service accounts use OAuth2 client credentials, not digest auth.
TOKEN=$(curl -s -X POST https://cloud.mongodb.com/api/oauth/token \
  --user "$ATLAS_CLIENT_ID:$ATLAS_CLIENT_SECRET" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'grant_type=client_credentials' | jq -r .access_token)

SINCE=$(( ($(date +%s) - {{inputs.lookback_hours}} * 3600) * 1000 ))   # epoch ms
curl -s -H "Accept: application/vnd.atlas.2025-03-12+json" -H "Authorization: Bearer $TOKEN" \
  "https://cloud.mongodb.com/api/atlas/v2/groups/{{inputs.atlas_project_id}}/clusters/{{inputs.cluster_name}}/queryShapeInsights/summaries?since=$SINCE" \
  | jq '[.summaries[] | select(.systemQuery != true)]'
```

`profiles/mongodb/lib.sh` wraps this as `mdb_query_shapes` / `mdb_slow_shapes` for
gates; the credential resolution order is documented there. The API version header
is required — the resource 404s without it. There is **no** `details` endpoint;
`summaries` carries everything.

### Fields on each shape

| Field | Meaning |
|---|---|
| `queryShapeHash` | Canonical, stable id for the shape — **use this as the dedupe key** |
| `queryShape` | The normalized pipeline/filter, with literals replaced by `?string`, `?number`, … |
| `namespace` | `db.collection` |
| `command` | `aggregate`, `find`, `update`, … |
| `execCount` | Executions in the window |
| `avgWorkingMillis` | Mean execution time |
| `totalWorkingMillis` | `avg × count` — aggregate cost to the cluster |
| `docsExamined` / `docsReturned` / `docsExaminedRatio` | Scan efficiency; the ratio is docs read per doc returned |
| `keysExamined` / `keysExaminedRatio` | Index-scan efficiency |
| `p50ExecMicros` / `p90ExecMicros` / `p99ExecMicros` | Latency percentiles, **microseconds** |
| `bytesRead`, `lastExecMicros`, `totalTimeToResponseMicros` | Supporting detail |
| `systemQuery` | `true` for Atlas's internal traffic — always exclude |

**Do not rank on the percentiles.** On real data `p99ExecMicros` sometimes reads
*below* `avgWorkingMillis`, which is impossible if it were a true percentile of the
same population — the semantics are unverified. Rank on `avgWorkingMillis` and
`totalWorkingMillis`; quote a percentile only as supporting colour.

### Reading the numbers

`totalWorkingMillis` is the honest measure of what a shape costs the cluster, and
it is **not** correlated with `avgWorkingMillis`. A 380ms query executed 1,350
times costs far more than a 26-second query executed three times. Rank by total;
use avg to describe severity per execution.

`docsExaminedRatio` is the strongest missing-index signal when it is meaningful,
and it is independent of both timers — a ratio of 126,988:1 means the query reads
~127k documents to return one, and it will get worse as the collection grows even
if it looks acceptable now.

**But check it is meaningful before quoting it.** It is `docsExamined / docsReturned`,
and `docsReturned` counts result *documents*, not underlying rows. Two cases break it,
and together they cover about a fifth of shapes on a real cluster:

| Condition | What the ratio actually is | What to report |
|---|---|---|
| `docsReturned == 0` | Not a ratio of anything — the query returned nothing | `docsExamined / execCount`, and note it returns no rows |
| `docsReturned == execCount` | One envelope doc per run (`$facet`, or `$group` on `_id: null`) — so it collapses to docs per *execution* | `docsExamined / execCount`, described as per-execution |
| otherwise | Genuine documents read per document returned | The ratio |

`docsExamined / execCount` — **docs examined per execution** — is always well defined.
Compute it every time. Quote `docsExaminedRatio` only in the third case, because in
the other two, writing "reads 3.6M documents to return one" states something false
in a story a human will act on.

The two measure different things and both matter: the ratio is *waste* (a missing
index), docs-per-execution is *absolute scan cost* (a query examining 124k docs per
run is expensive even at a healthy 3:1 ratio).

### Linking to Atlas

Deep-link a shape in the UI with its hash:

```
https://cloud.mongodb.com/v2/{{inputs.atlas_project_id}}#/metrics/replicaSet/<replicaSetId>/queryInsights/shape?checkedHash=<queryShapeHash>
```

If the `replicaSetId` isn't known, link the cluster's Query Insights tab and quote
the `queryShapeHash` in the body so a human can search for it.

### Enriching with MCP (read-only)

Once a shape is identified, the MongoDB MCP tools explain it:

- `collection-indexes` — what indexes exist on the namespace today. Essential: a
  suggested index that already exists means the query isn't using it, which is a
  different bug (wrong field order, collation, or a `$regex` that can't be indexed).
- `explain` — run the shape's pipeline to confirm `COLLSCAN` vs `IXSCAN`.
- `collection-schema`, `collection-storage-size`, `count` — shape and scale.
- `atlas-get-performance-advisor` — Atlas's own `suggestedIndexes` for the
  namespace. When it already recommends an index for this shape, quote it verbatim
  rather than inventing one.

**Never write.** No `create-index`, `update-many`, `delete-many`, `drop-*`, or
collection changes — proposing the index is the job, applying it is not.

**PII:** the `queryShape` is pre-normalized (literals stripped), so it is safe to
quote. Sample *documents* are not — reference them by `_id` only and describe field
shapes, never values.
