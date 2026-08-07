---
name: datadog-log-reviewer
description: Review recent Datadog error logs, cluster them by root cause, and file one Shortcut story per new cluster for triage.
---

# datadog-log-reviewer

Turn recent Datadog errors into tracked, actionable work. Each run: pull the
error logs, group them into root-cause clusters, and file **one Shortcut story
per new cluster** — which `story-reviewer` then assesses and `work-queue` can
implement. You run inside the service's repo, so you can look up the code a stack
trace points at.

This is **unattended** — never use AskUserQuestion and never stop waiting on
permission; you run with permissions skipped. Do the work within the bounds
below.

## 1. Pull the errors

Search Datadog for the window — prefer the Datadog MCP tools
(`mcp__datadog-mcp__search_datadog_logs` with `{{inputs.log_query}}` over the
last `{{inputs.lookback}}`) when the session has them; otherwise the `pup` CLI
(see **Source: Datadog** below for details and clustering guidance):

```bash
pup logs search --query="{{inputs.log_query}}" --from="{{inputs.lookback}}" --output json
```

If the search returns nothing (auth lapsed, transient failure), stop — there is
nothing to file.

## 2. Cluster by root cause

Group the raw events into **clusters** by a stable signature (normalized message
+ `service` + error `type`/top stack frame — see the Source section). Record for
each cluster: a short title, the signature, occurrence count in the window, one
representative sample (message + stack + a couple of key attributes), the
service, and the environment.

## 3. Dedupe against what you've already filed

`$DAIMON_STATE_FILE` is your durable JSON memory: an array of
`{signature, story_id, title, last_seen}`. Read it first. (Prefer your
platform's file tools with the literal state path over shell commands that
expand `$DAIMON_STATE_FILE` — env expansions require interactive approval in
non-danger sessions.)

- A cluster whose signature you've already filed is **known** — do not file a
  second story. (Optionally note it recurred by updating `last_seen`; never open
  a duplicate.)
- A cluster with a new signature is a **candidate**.

**Then dedupe candidates against the tracker itself.** Your state only records
stories *you* filed — a human may have already filed this error. For each
candidate, search the write source for existing non-archived stories (any
author, created recently or still open) matching the cluster's key terms:
the service name, the error message, the status code, the failing
function/file. If one plausibly covers the same root error, do **not** file;
record `{signature, story_id: <existing>, title, last_seen}` in state so the
cluster is known from now on, and mention it in your summary as
"existing — adopted sc-<id>".

## 4. File a story per new cluster

Process at most `{{inputs.max_new_stories}}` new clusters this run (highest
occurrence count first); leave the rest for the next run. For each:

1. **Investigate briefly.** The stack/source location usually names a file — open
   it in the repo and read enough to describe the likely cause. Do not attempt a
   fix here; that's `work-queue`'s job downstream.

   Enrich when the tools are available, so the story is specific, not generic:
   - **Datadog MCP** — aggregate the cluster over a longer window (is it new or
     chronic? trending up?), pull companion WARN/INFO events around a sample
     occurrence, and fetch the related trace/span when the log carries a trace id.
   - **MongoDB MCP, read-only** — when the error implicates a specific document
     (an `_id`/`documentId` in the log attributes), you may inspect it with
     read-only tools (`find`, `aggregate`, `count`, `collection-schema`) to say
     *why* it fails (missing field, unexpected shape, stale reference). Never
     write to the database — no updates, deletes, index or collection changes.
   - **PII:** reference documents by `_id` only. Never paste emails, names,
     phone numbers, addresses, or tokens into the story — describe the field
     shape ("phone lacks country code"), not the value.
2. **File a work item** in your write source — see **Source: … — writing** below
   for the exact create call (this daemon is source-agnostic: whichever tracker is
   configured as the write source provides it). Put it in that source's triage
   state (`{{inputs.triage_state}}`) with **no** assessment label, so the triage
   daemon picks it up, and group it under the configured epic/parent if the write
   source defines one. Body:

   ```markdown
   {{inputs.bot_marker}} **Datadog error — <service> (<env>)**

   **Signature:** <normalized signature>
   **Occurrences:** <n> in the last {{inputs.lookback}}

   **Sample**
   ```
   <representative message + stack>
   ```

   **Likely cause:** <what you found in the code — file:line if identified>
   **Datadog:** <a link/query to view these logs>
   ```

   Keep the title short and specific: `<service>: <error type> in <area>`.

## 5. Finish

Append each filed cluster as `{signature, story_id, title, last_seen}` to
`$DAIMON_STATE_FILE`. Summarize briefly: each cluster, its occurrence count, and
the story you opened (or "known — skipped").
