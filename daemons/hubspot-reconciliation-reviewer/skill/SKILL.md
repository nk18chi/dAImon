---
name: hubspot-reconciliation-reviewer
description: Review the daily HubSpot property reconciliation drift report, cluster it by mapper field, and file one Shortcut story per new cluster.
---

# hubspot-reconciliation-reviewer

Turn the daily HubSpot property reconciliation into tracked work. Each run: read
the drift clusters the gate already built, drop the ones that are already
tracked, investigate what is left against the mappers, and file **one story per
new cluster**.

This is **unattended** — never use AskUserQuestion and never stop waiting on
permission. Do the work within the bounds below.

## 1. Read the candidates

The gate wrote `$DAIMON_STATE_DIR/runtime/hubspot-reconciliation-reviewer-candidates.json`:

```json
{ "total_candidates": 4, "handed_over": 4, "clusters": [
  { "signature": "customObject:tour:tour_area_id", "kind": "customObject:tour",
    "field": "tour_area_id", "count": 8, "statuses": ["FIELD_MISMATCH"],
    "missing_reasons": [], "run_ids": ["hubspot-property-reconciliation-2026-08-05"],
    "co_fields": ["tour_area_id"], "sample_mongo_ids": ["664d23b1…"] } ] }
```

Clusters are keyed `<kind>:<field>` and already deduped against your state file.
Do not re-query Datadog for the window — query it only to answer a specific
question (is this cluster new or chronic? what did the count look like last
month?).

If `total_candidates` is 0, stop. Nothing to file.

## 2. Dedupe against the tracker — before writing anything

The gate's state check only knows what **this daemon** filed. A human has very
likely already filed the cluster you are holding. Check, every run, for every
candidate, **before** any investigation work.

**Tier 1 — state file.** `$DAIMON_STATE_FILE` is a JSON array of
`{signature, story_id, title, count, last_seen}`. The gate already applied it, but
re-read it so you can update `last_seen` and `count` on recurrence. (Prefer your
platform's file tools with the literal state path — env expansions like
`$DAIMON_STATE_FILE` require interactive approval in non-danger sessions.)

**Tier 2 — search Shortcut for the field name.** The HubSpot property name is a
distinctive token that appears verbatim in titles, descriptions, and acceptance
criteria of stories in this class. It is a far stronger match than free-text
keywords. For each candidate, run both:

1. `label:"{{inputs.story_labels}}"` — the whole class, ~10 stories, cheap to scan.
2. A workspace-wide search for the raw field token (`tour_area_id`,
   `booking_status`, `guide_email_address`) across name and description,
   non-archived, any author.

Both are needed: (1) catches stories that describe the cluster without naming the
field, (2) catches stories filed outside this label, including by other squads.

Verified examples of what this finds:

| Cluster | Existing story |
|---|---|
| `customObject:tour:tour_area_id` | sc-51197 — open in Backlog |
| `standardObject:deal:booking_status` | sc-48679, sc-48994 — both **Done** |

**Tier 3 — the Done rule.** A match is only an adopt-and-stay-silent if the story
is **open**. Do not treat a Done story as covering live drift:

- **Open match** → do **not** file. Record
  `{signature, story_id: <existing>, last_seen}` in state so the cluster is known
  from now on. Report it as `existing — adopted sc-<id>`.
- **Done match, and drift is still flowing** → **file a new story** that links the
  Done one as a suspected regression or incomplete fix. Say so in the title
  (`… recurring after sc-<id>`) and open the body with the evidence: the Done
  story's id, and the drift count in the current window. A shipped fix is not
  proof the drift stopped — verify against the data in front of you, not the
  workflow state.
- **Done match, drift not seen since the fix merged** → not a candidate at all;
  record it in state and move on.

Silently adopting a Done story is the one failure mode that makes this daemon
worse than nothing: it converts an active, growing discrepancy into permanent
silence. When the two readings are close, file — a duplicate is cheap to close,
a suppressed regression is invisible.

## 3. Investigate the root cause — with MCP, not guesswork

A story that only restates the drift count is not worth filing. Use **both** MCP
surfaces on every cluster before writing anything. Both are read-only.

**If an MCP server is not present in this session**, do not silently skip the
analysis it was for. `sources` does not provision MCP — these servers come from
the operator's Claude Code config and can be absent in an unattended run.
- **Datadog MCP missing** → fall back to the `pup` CLI (see *Source: Datadog*).
- **MongoDB MCP missing** → there is no fallback. This is the one case that
  legitimately triggers the investigation-only last resort described at the end
  of this section: name the specific unanswered question and the exact check that
  would answer it. Never infer a Mongo value you were unable to read.

### Datadog MCP — when did this start, and what else was happening?

- `search_datadog_logs` — the cluster's own events for the exact `runId`, then
  widen the window to classify it: **new**, **chronic**, or **growing**.

  **Quote any `kind` value.** Every kind contains a colon (`contact:agent`,
  `customObject:tour`), and an unquoted `@kind:contact:agent` fails the whole
  request with `Cannot parse query` — not an empty result, a 400. Always write
  `@kind:"contact:agent"`.
- `aggregate_events` with a daily interval — the shape of the curve is the
  strongest causal signal available. A step change points at a deploy or a script
  run; a slow ramp points at organic data drift; a lone spike points at a
  backfill. Drift is bursty here (830 records on 2026-07-30 against single digits
  either side), so never infer a trend from one day.
- **Companion events on the same `mongoId`s.** Query `@event:hubspot.outbound.*`
  for those ids. Whether an outbound sync was even *attempted* splits the causes
  in half — absence is itself the finding, and points at a missing `enqueue*Sync*`
  rather than a mapper bug.
- If an event carries a trace id, fetch the trace.

### MongoDB MCP — what does the data actually look like?

The configured connection is **TBL Production**
(`profiles/mongodb/profile.local.toml`), so this is the real drifted data, not a
sample.

- `find` the `sample_mongo_ids` in the kind's collection and read the drifting
  field. Is it `null`, an empty string, a shape the mapper does not handle, or a
  value with no matching HubSpot option?
- `collection-schema` — is the field required, does it default, is `null` legal?
  This is what decides whether clearing the HubSpot value is correct or
  destructive. Do not propose a clear without checking it.
- `aggregate` a value distribution over the field. For enum drift this
  immediately names the values that have no HubSpot option.
- `count` documents matching the drift-triggering shape → the collection-wide
  blast radius. The report samples, so this is the only way to state real scale.

**Read-only, always.** `find`, `aggregate`, `count`, `collection-schema`,
`explain` are free to use. Never `update-many`, `delete-many`, `drop-*`,
`create-index`, or any other write. Reference documents by `_id` only — never put
emails, names, phone numbers, or tokens in a story.

### Then read the mapper

`field` names the mapper property; `kind` names the mapper. Open
`packages/hubspot/src/mappers/<kind>.mapper.ts` and read the assignment for that
field. The recurring causes, in rough order of frequency:

- **Omit-vs-clear.** A guarded assignment (`if (doc.x) props.y = …`) omits the key
  when the Mongo value is absent. HubSpot property updates merge, so an omitted
  key leaves the stale value forever. Precedent: `cb2052643a` (sc-49429).
- **Enum drift.** A Mongo value has no matching HubSpot option → `INVALID_OPTION`,
  the write is rejected, the old value survives. Precedent: sc-50267 / sc-50271.
- **Missing enqueue.** A service mutates a tracked field without a following
  `enqueue*Sync*` call, so nothing ever pushes the new value.
- **Ownership.** The field is HubSpot-owned or inbound, and "drift" is expected.
  Check `developerOwnedProperties.ts` before proposing any Mongo-side change.

Cross-check `.claude/rules/integrations/hubspot-outbound-sync.md` and
`docs/runbooks/hubspot-historical-fields.md` in the working repo.

**You file an implementation ticket, not an investigation ticket.** Your job is
to finish the investigation so the next person doesn't have to start one. The
story must land with the root cause **proven** — not hypothesised — and a
specific fix proposed. The bar is sc-51499 / sc-51500 / sc-51501: those name the
exact index, the exact file:line, and the numeric before→after.

- **Prove it, don't guess it.** "The mapper probably omits the key" is not a root
  cause. Read the mapper, read the documents, check whether a sync fired, then
  state what *is* happening. If a hypothesis is cheap to test, test it — a
  disproven hypothesis costs one query and saves a wrong story.
- **Name the change.** Which file, which line, what it should say instead. Not
  "fix the mapper".
- **Do not write the code.** No branch, no edit, no PR — implementing is
  `work-queue`'s job. Propose precisely; let someone else apply it.

**Investigation-only is a last resort, not a fallback you reach for.** It is
allowed only when a required evidence source was genuinely unavailable — an MCP
server missing, a system you cannot read. When you use it, name the specific
unanswered question and the exact check that would answer it, so the story is
still actionable. "Investigate the drift" is never acceptable.

## 4. Size the work

Estimate the **implementation effort for the fix you are proposing**, not how bad
the drift is. 540 drifted records a week behind a one-line mapper guard is a 1.

| Points | Effort | Typical work | Anchor |
|---|---|---|---|
| 1 | ≤ half day | Mapper omit-vs-clear guard; add an enum option; exclude a field from reconciliation; add a terminal skip reason. Location known, precedent exists. | sc-51436 |
| 2 | ~1 day | Mapper/service change **plus** an enqueue path or schema option, plus verification against a following reconciliation run. | sc-48679 |
| 3 | 1–1.5 days | Retry/ordering semantics, partial-batch handling, or idempotency across several helpers. | sc-51424 |
| 5 | 2–3 days | Ownership change (inbound vs outbound), or a fix needing a backfill plus a sync plan. | — |
| 8 | — | **Avoid — split it.** | — |

This scale is coarser than it looks: sc-51436 is a **1** and it touches four
helper files with six test cases. Do not inflate.

Size the fix you named in §3. If you find yourself unable to size it, that means
the investigation is not finished — go back to §3 and finish it, rather than
downgrading the story to investigation-only. Never guess a number for work you
have not understood.

## 5. File a story per new cluster

At most `{{inputs.max_new_stories}}` per run, highest `count` first. Set:

- **state** — `{{inputs.triage_state}}`
- **type** — `{{inputs.story_type}}`
- **team** — `{{inputs.team}}`
- **epic** — `{{inputs.epic_id}}`
- **labels** — `{{inputs.story_labels}}`, spelled **exactly**. Add **no**
  assessment label (`ai-ready`, `ai-assist`, …) — that is not this daemon's call.
- **estimate** — from the table above

Body:

```markdown
{{inputs.bot_marker}} ## Problem

<one sentence: which HubSpot property drifts, on which object, and that the daily
property reconciliation surfaced it>

- **<count> drifted records** in the last {{inputs.lookback}} · run `<runId>`
- Status: <FIELD_MISMATCH / MISSING + missingReason>
- Co-occurring fields on the same records: <co_fields, or "none">
- Sample Mongo ids: `<up to 5>`

## Analysis

<The proven mechanism, in the order you established it:>

- **Mapper**: <file:line, the exact assignment, and which of the four causes it
  matches — quote the line>
- **Mongo says** (production, read-only): <the actual value on the sampled
  documents, plus the schema's default/required/nullable, which decides whether
  clearing HubSpot is correct or destructive>
- **Outbound sync**: <was one attempted for these ids? cite the
  `hubspot.outbound.*` events, or state that none exist and what that implies>
- **Trend** (Datadog, 30d): <new / chronic / growing, with the daily shape>
- **Blast radius** (Mongo `count`): <documents collection-wide matching the
  drift-triggering shape, vs the sampled count above>
- **Ruled out**: <hypotheses you tested and disproved, with the evidence. This is
  worth as much as the cause — it stops the next person re-testing them.>

## Proposed fix

<The specific change. Show the before/after where it is code:>

```ts
// before — <what it does wrong>
<the current line>

// after — <why this is correct>
<the corrected line>
```

<Any guard the fix requires and why; the repo rule it must follow (migration,
index registry, enqueue placement); and what to verify before relying on it.>

## Acceptance criteria

- [ ] <the mapper/service change, stated concretely>
- [ ] Unit test covering the drifting case, and one covering the case the guard
      protects
- [ ] A following daily property reconciliation reports **0** `<field>` drift
      (from <count> today)
```

Title: `<object>: <field> drift — <one-phrase cause>`. Add
`(recurring after sc-<id>)` when tier 3 flagged a Done match.

## 6. Finish

Append each filed cluster to `$DAIMON_STATE_FILE` as
`{signature, story_id, title, count, last_seen}`. Update `last_seen`/`count` for
clusters you skipped as known.

Summarize: each cluster, its count, and the story opened — or
`existing — adopted sc-<id>`, or `recurring after sc-<id> — filed sc-<new>`. If
`total_candidates` exceeded what you filed, say how many are waiting.
