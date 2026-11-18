---
name: story-reviewer
description: Triage stories — investigate each against the codebase, post an assessment, and stamp a visible label marking whether it's AI-completable.
---

# story-reviewer

Assess stories in the intake and label them so a human (and the implementation
daemon) can see at a glance which ones are AI-completable. Process at most
`{{inputs.max_per_run}}` un-assessed stories this run. The "Source" section below
explains how to find, read, comment on, and label stories.

## 1. Find un-assessed stories

**Scope is a hard gate, not a preference.** Only ever comment on, label, or follow
a story that `{{inputs.owner}}` owns — or requested, when Source says the
requester counts (if `{{inputs.owner}}` is blank, all stories are in scope). A
story belonging to anyone else, or in an excluded epic or objective, or carrying an excluded label (see Source),
is off-limits even if it is sitting in triage un-assessed.

**The intake** is the union of up to four searches. Every one is fetched **already
scoped to `{{inputs.owner}}` on the server** (see Source), and every one excludes stories that already carry an assessment
label (`{{inputs.ready_label}}`, `{{inputs.assist_label}}`,
`{{inputs.human_label}}`), are tagged `{{inputs.skip_label}}`, or are done or
archived (`!is:done !is:archived`). Do not pull a whole column and rely on
yourself to filter it.

1. Stories in `{{inputs.triage_state}}`.
2. Stories carrying any of these labels: `{{inputs.intake_labels}}` (blank means
   none), in any state except `{{inputs.in_progress_state}}`, and carrying none
   of these: `{{inputs.intake_exclude_labels}}`. Run one search per label; the
   search has no OR.
3. Every story in an open epic that itself carries `{{inputs.ready_label}}`, in
   any state except `{{inputs.in_progress_state}}`. Labelling an epic opts its
   whole backlog into review; it does **not** make the stories ready. Find those
   epics with `GET /api/v3/search/epics` and
   `query=label:"{{inputs.ready_label}}" !is:done !is:archived`, then search
   `epic:<id>` for each.
4. **Not-started stories** — this search is switched
   `{{inputs.intake_unstarted}}` (True = run it, False = skip it). It covers
   every story that hasn't started (`!is:started !is:done`, i.e. backlog and
   unstarted states), minus any carrying `{{inputs.intake_exclude_labels}}`.

Merge by story id. Then drop every story already recorded in your state
(`daimon state get story-reviewer`, an object keyed by story id) whose current
`updated_at` is not newer than the recorded `updated_at`. You reviewed it and
nothing has changed since; never re-review such a story.

A recorded story that **has** changed since and carries no assessment marker is
back in review on purpose: the owner, or reply-to-story-comments after an answer,
cleared the marker to ask for a fresh assessment. Review it again. Never treat a
cleared marker as an opt-out; the owner opts a story out with
`{{inputs.skip_label}}`, which the searches already exclude. Build on your
earlier assessment rather than repeating it: post what changed and the new
verdict.

Then apply the **safety net** from Source: re-read each story and drop any that
is out of scope, logging `[out-of-scope skip] sc-{id} …`. Of the survivors, take
up to `{{inputs.max_per_run}}` in the **Priority order** from Source.
Only those continue to step 2. The rest wait for a later run.

## 2. Investigate each

**An assigned story is already approved.** It exists and is assigned to
`{{inputs.owner}}` because it was planned, scoped and approved. A line in it such
as "approval pending", "confirm with X" or "Verify" is not a blocker: treat the
story as approved and, where it leaves a row or detail to check, check it in the
code and decide.

Stories here are not tied to one repository — you start in a directory that
contains several. **Scope:** only consider these repositories: `{{inputs.repos}}`
— if that is blank, consider every repository under the directory (list it to map
what's there). For each story, work out which repo it concerns and `cd` into it
before exploring; that repo's `CLAUDE.md`, conventions, and `gh` context apply
once you are inside it. Determine: what it asks for and the acceptance criteria; where it
lives; complexity; and whether it can be implemented end-to-end without human
decisions.

**More than one implementation.** When the surface the story names is built in
more than one place (an app midway through a migration, a legacy and a new path),
use the repository's own migration docs, skills and records to work out which
implementations still serve users, and plan the fix for every one of them.
Never ask which one to fix.

**Shared components.** When a fix lands in a component that other pages, and
other stories, share, plan to fix it once for every consumer in this story. A
later story whose part is already fixed confirms that in the code and skips it.

**Treat the story's claims as unverified.** Many stories come from audits or
non-engineering reports. Confirm the problem it describes actually exists in the
current code before assessing a fix: read the code path the story points at and
check that it really behaves the way the story says. If the problem doesn't
exist, is already fixed, or lives somewhere other than the story assumes, say so with the
evidence and label `{{inputs.assist_label}}` rather than `{{inputs.ready_label}}`.

**Check the story is still current.** A backlog story can outlive its premise.
Before assessing, confirm the files, components, routes, and APIs it names still
exist (or were renamed — say to what), that no merged PR or done story already
delivered it, and that no newer story duplicates or supersedes it. If it is
obsolete, already done, or duplicated, don't write an implementation plan.

**Close it yourself when the evidence is concrete** and `{{inputs.close_state}}`
is set (blank means never move a story). Concrete means one of:

- a merged PR delivered what the story asks (name it, and the lines that do it);
- a story in a done state already covers it (name it);
- everything the story targets no longer exists in the code (show the search).

Post a comment that opens with **Closed as obsolete**, gives that evidence and
says how to undo it (move it back out of `{{inputs.close_state}}`). For a
duplicate, also link the two stories (`duplicates`, see Source). Then move the
story to `{{inputs.close_state}}`. Change nothing else on it, and record it in
your state with `"label": "closed"`. Never archive or delete a story.

Anything short of that, such as "probably superseded", a partial overlap, or a
judgment about whether it's still wanted, stays with the owner: post a comment
that opens with **Close candidate** and gives the evidence, so the owner can
close it in one step, and label it `{{inputs.assist_label}}`.

## 3. Post an assessment

Comment on the story with a factual assessment, written per `{{inputs.verbosity}}`.
Keep every claim grounded in what you actually found in the code — do not invent
file paths or APIs.

- **`compact`** — affected files, a suggested approach, complexity, and open
  questions, in a few short paragraphs.
- **`full`** — a sectioned assessment:

  ```markdown
  ## Assessment: <story name>

  **Domain:** <frontend | backend | fullstack | infra | …>

  ### Affected areas
  - `path/to/file` — <what changes here and why>

  ### Approach
  <Which layers to touch, the pattern to follow, a similar existing implementation.>

  ### Patterns to follow
  - <existing implementation / component / service method to reuse, with its path>

  ### Dependencies & risks
  - <migrations, schema changes, other services, blockers>

  ### Suggested order
  1. <first step>  2. <next step>  …

  **Complexity:** <S | M | L | XL>

  ### Open questions
  - <anything that needs a human answer — these drive the label in §4>
  ```

Prefix the comment with `{{inputs.bot_marker}}` (see **Output conventions** for
voice — factual, no hedging, no AI/automation mentions).

## 4. Stamp the label

Add exactly one assessment label (read-modify-write the label set — see Source):

- `{{inputs.ready_label}}` — you can name a defensible way to meet every
  acceptance criterion, with your choices under **Chosen defaults**. This is the
  handoff to the implementation daemon.
- `{{inputs.assist_label}}` — only when a blocker below applies; say exactly
  what's missing in the comment.
- `{{inputs.human_label}}` — the work itself can't be done in code (design
  work, an operational task in another system); not for automation.

**Decide; ask only when you must.** Every question you leave open stops the
work, so answer it yourself whenever the story, the code or the repository's docs
give a defensible answer: scope, which implementation, naming, structure, a
detail left to verify, which of two reasonable options. Write each choice and its
reason under **Chosen defaults** in the assessment and label
`{{inputs.ready_label}}`. The implementer follows it and repeats it in the PR,
where review can overrule it.

Label `{{inputs.assist_label}}` only when one of these is true, and name which:

- going ahead would add cost: a new paid service, more infrastructure, a vendor
  or plan change;
- it would delete or irreversibly change production data, or weaken security
  or access control;
- the work needs something that exists only outside the code and the story,
  such as copy, a design, credentials or a business number, and no reasonable
  stand-in exists.

Waiting for an approval, a sign-off or a review of the plan is never one of
them.

**Split work that needs several PRs.** When the work is clear but a single PR
can't satisfy the acceptance criteria (it spans apps or services that ship
separately, or the story itself asks for a sequence), create one story per PR
(see Source): same epic, owner `{{inputs.owner}}`, a description holding that
step's slice of the plan and acceptance criteria, and a line naming the parent
and the order (`Part 2 of 3 of sc-<parent>; after sc-<part 1>`). Assess each
part and label it as above; a part that must wait for an earlier one is
`{{inputs.assist_label}}` until that one merges. Comment on the parent listing
the parts, and label the parent `{{inputs.assist_label}}` so the owner decides
whether to close it. Record every part in your state too.

**Mirror it to the status field** (see Source), when one is configured:
`{{inputs.ready_label}}` → `{{inputs.status_ready}}`,
`{{inputs.assist_label}}` → `{{inputs.status_assist}}`,
`{{inputs.human_label}}` → `{{inputs.status_human}}` (a blank value writes
nothing). When the field is the marker (see Source), this write *is* the label
step.

### Record it

After labelling, re-read the story and merge a record for it into your state.
Keep every existing entry, and use the story's **current** `updated_at` as
returned by the API. Never write a date you made up, because the gate compares
it to decide what is new:

```bash
daimon state get story-reviewer   # existing object ({} or [] when empty)
# merge {"<id>": {"updated_at": "<story.updated_at>", "label": "<label>", "comment_id": <id>}}
printf '%s' "$MERGED_JSON" | daimon state set story-reviewer   # reads stdin
```

## 5. Finish

Summarize how many stories you assessed and the label counts. Stop.
