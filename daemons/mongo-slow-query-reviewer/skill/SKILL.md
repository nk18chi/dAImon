---
name: mongo-slow-query-reviewer
description: Review MongoDB Atlas query shapes, find the ones costing the most execution time, and file one Shortcut story per new offender with a proposed index or rewrite.
---

# mongo-slow-query-reviewer

Turn expensive MongoDB query shapes into tracked, actionable work. Each run: pull
the query shape aggregates from Atlas, pick the ones tripping a threshold, and file
**one Shortcut story per new shape** — which `story-reviewer` then assesses and
`work-queue` can implement. You run inside the service's repo, so you can find the
code that issues the query.

This is **unattended and runs with permissions enforced**, not skipped. Nobody is
watching: any tool call that raises a permission prompt stalls the run until the
idle reaper kills it, and the work is simply lost. So never use AskUserQuestion,
and prefer pre-approved tools — your platform's file tools and the MCP tools listed
below — over shell commands. Avoid shell `curl`, and avoid commands that expand
environment variables; those are never auto-approved.

## 1. Read the candidate shapes

**The gate has already fetched them for you.** Read
`~/.local/state/daimon/runtime/mongo-slow-query-reviewer-candidates.json` with your
file tools:

```json
{ "total_candidates": 43, "handed_over": 6, "shapes": [ … ] }
```

`shapes` holds the ones that tripped a threshold — already filtered by
`ignore_namespaces`, already deduped against your state file, and already sorted by
`totalWorkingMillis` descending. Each element is a raw Query Shape Insights record;
see **Source: MongoDB Atlas** below for what every field means.

`handed_over` is deliberately a slice of `total_candidates`: the full set is far
more than you can read at once, and you only file `{{inputs.max_new_stories}}` per
run. The remainder is not lost — anything you don't file stays absent from your
state file, so the next run's gate surfaces it again. Mention both numbers in your
closing summary so the backlog is visible.

Work from that file. Do not re-query the Atlas API: the gate holds the credentials,
the agent side has no permission to reach `cloud.mongodb.com`, and attempting it
will stall the run.

If the file is missing or empty, stop — the gate found nothing to do. (It is
rewritten on every gated fire. Only a `daimon launch`, which bypasses the gate, can
leave it stale; in that case still stop rather than reaching for the API.)

## 2. Understand what you were given

The gate selected these using four thresholds, **OR'd deliberately**:

| Signal | Threshold | What it catches |
|---|---|---|
| `avgWorkingMillis` | > `{{inputs.avg_ms_threshold}}` | Individually heavy queries |
| `totalWorkingMillis` | > `{{inputs.total_ms_threshold}}` | Frequent queries dominating cluster load |
| `docsExaminedRatio` | > `{{inputs.examined_ratio_threshold}}` | Waste — missing indexes, before they get slow. Applied only where the ratio is a genuine per-row figure (see below). |
| `docsExamined / execCount` | > `{{inputs.docs_per_exec_threshold}}` | Absolute scan cost per run. Catches shapes the ratio hides — 124k docs read per execution at a healthy-looking 3:1. |

They select near-disjoint sets, which is the point. A query averaging 380ms is
nowhere near the avg threshold, but run 1,350 times it burns 8.6 minutes of cluster
time and outranks everything. So when you describe *why* a shape was flagged, work
out which rule it tripped — a shape caught only by the ratio rule is a
missing-index-in-waiting, not a slow query, and the story should say so.

The list is already ranked by `totalWorkingMillis` descending. **Keep that order** —
it is what the shape actually costs the cluster, and it is the priority order.

### Before you quote `docsExaminedRatio`, check it means something

Always compute **docs examined per execution** = `docsExamined / execCount`. It is
well defined for every shape. Then decide whether the ratio is also quotable:

- `docsReturned == 0` — the query returns nothing. The ratio is not a ratio. Report
  docs-per-execution and say it returns no rows.
- `docsReturned == execCount` — one envelope document per run (`$facet`, or `$group`
  on `_id: null`), so the ratio has already collapsed into docs-per-execution.
  Report it as per-execution; do not call it "per returned document".
- Otherwise — a genuine per-row figure. Quote it.

This is not pedantry. On a real cluster about one shape in five falls into the first
two cases, and the gate's ratio threshold fires on the raw number regardless. Writing
"reads 3,613,864 documents to return one" into a story a human will act on — when the
shape actually reads 4 documents per execution and returns nothing — sends someone
hunting for an index that was never the problem.

## 3. Dedupe against what you've already filed

`$DAIMON_STATE_FILE` is your durable JSON memory: an array of
`{query_shape_hash, namespace, story_id, title, total_ms, last_seen}`. Read it
first. (Prefer your platform's file tools with the literal state path over shell
commands that expand `$DAIMON_STATE_FILE` — env expansions require interactive
approval in non-danger sessions.)

- A shape whose `queryShapeHash` you've already filed is **known** — do not file a
  second story. Update `last_seen` and `total_ms`; never open a duplicate.
- A shape with a new hash is a **candidate**.

`queryShapeHash` is Atlas's canonical shape id, so this match is exact — do not
attempt fuzzy signature matching on the pipeline text.

**Then dedupe candidates against the tracker itself.** Your state only records
stories *you* filed — a human may already have filed this. For each candidate,
search the write source for existing non-archived stories (any author, recent or
still open) matching the namespace, the collection, or the operation. If one
plausibly covers the same query, do **not** file; record
`{query_shape_hash, story_id: <existing>, …}` in state so the shape is known from
now on, and note it in your summary as "existing — adopted sc-<id>".

## 4. File a story per new shape

Process at most `{{inputs.max_new_stories}}` new shapes this run (highest
`totalWorkingMillis` first); leave the rest for the next run. For each:

1. **Investigate.** Do not file "this query is slow" — find out why.
   - **Check the existing indexes first** (`collection-indexes` on the namespace).
     If an index that should serve this query already exists, the bug is that the
     query isn't using it — wrong field order for the sort, a leading `$regex`, a
     collation mismatch, or a `$lookup` on an unindexed foreign field. Say so.
     Do not recommend creating an index that is already there.
   - **Check Atlas's own recommendation** (`atlas-get-performance-advisor`,
     `suggestedIndexes` for the namespace). If it suggests an index for this shape,
     quote it verbatim rather than inventing your own.
   - **Find the code.** The normalized `queryShape` gives you the pipeline stages
     and field names — grep the repo for those field combinations, the collection
     name, and distinctive stages (`$lookup` targets, `$facet`, unusual `$match`
     keys). Name the file and function if you find it. Say "not located in this
     repo" if you don't; do not guess.
   - **Do not attempt the fix.** That is `work-queue`'s job downstream.

   **Read-only, always.** Use `explain`, `collection-schema`,
   `collection-storage-size`, `count`, `find`, `aggregate` freely. Never
   `create-index`, `update-many`, `delete-many`, `drop-*`, or any collection change.

2. **Size the work.** Estimate the *implementation effort for the fix you are
   proposing* — not how bad the query is. A catastrophic query with a one-line
   index fix is a 1.

   | Points | Effort | Typical slow-query work |
   |---|---|---|
   | 1 | 1–2 hours | The exact index is already known (Atlas named it); one migration, no app code. |
   | 2 | Half a day | One index plus a small contained change in a single resolver — or dropping/replacing an index. |
   | 3 | 1–1.5 days | Pipeline rewrite in one service, plus an index, plus before/after verification. |
   | 5 | 2–3 days | Fix spans several call sites, needs a caching layer, or changes how a field is resolved. |
   | 8 | ~5 days | **Avoid — split it instead.** |

   **Do not file an 8 if the work can be split, and it almost always can.** "Add
   the index", "rewrite the pipeline", and "add the cache" are three stories with
   independent value, each shippable on its own. File them separately, estimate
   each on its own, and cross-reference them. Use 8 only when the work genuinely
   cannot be divided — and then state in the story *why* it cannot.

   If you cannot identify the fix confidently enough to size it, estimate the
   **investigation** (1 or 2) and scope the story to investigation only. Never
   guess a number for work you have not understood.

3. **File a work item** in your write source — see **Source: … — writing** below
   for the exact create call (this daemon is source-agnostic: whichever tracker is
   configured as the write source provides it). Set:

   - **state** — the triage state (`{{inputs.triage_state}}`)
   - **type** — `{{inputs.story_type}}`
   - **labels** — `{{inputs.story_labels}}`, spelled **exactly**. The workspace
     contains near-identical decoys (`performance`, `database`, `Performance`);
     picking one of those fragments the reporting these labels exist to enable.
     Add **no** assessment label (`{{inputs.ready_label}}`,
     `{{inputs.assist_label}}`, …) — that is `story-reviewer`'s call, and setting
     one here bypasses triage.
   - **estimate** — from the table above
   - **epic/parent** — the configured one, if the write source defines one

   Body:

   ```markdown
   {{inputs.bot_marker}} ## Problem

   <one sentence: what is expensive, and that Atlas Query Insights surfaced it>

   ### `<namespace>` — <command>
   - **Avg <avg>** · Total <total> over {{inputs.lookback_hours}}h · <count> runs
   - Scan: <docsExamined> examined, <docs-per-execution> per execution<, and the ratio only if it is meaningful — see below>
   - Tripped: <which threshold, and why that one matters here>
   - Shape hash: `<queryShapeHash>`

   **Query shape**
   ```
   <the normalized queryShape, pretty-printed>
   ```

   ## Analysis

   - Existing indexes on `<namespace>`: <what is there now>
   - <why it is slow: selectivity, lookup fan-out, an index that cannot be used, …>
   - <source: file:line, or "not located in this repo">

   ## Proposed fix (read-only investigation only — apply/test changes yourself)

   - <the index with exact field order and direction, or the rewrite>

   ## Acceptance criteria

   - [ ] <measurable outcome — e.g. docs examined per run below N>
   - [ ] Avg execution time drops below <target> (verify in Atlas Query Insights)

   ## Evidence
   Atlas → Query Insights → Query Shapes, shape hash `<queryShapeHash>`.
   ```

   Title format: `<collection>: <operation> scanning <n> docs per result` or
   `<collection>: <n>s aggregate — <the expensive stage>`. Short and specific;
   never just "slow query".

## 5. Finish

Append each filed shape to `$DAIMON_STATE_FILE` as
`{query_shape_hash, namespace, story_id, title, total_ms, last_seen}`. Summarize
briefly: each shape, its total execution time, and the story you opened (or
"known — skipped").
