---
name: reply-to-story-comments
description: Respond to human replies on your bot comments on Shortcut stories, and re-trigger triage when an awaiting-input question is answered.
---

# reply-to-story-comments

Respond to anyone who replied to a comment you previously posted on a Shortcut
story (e.g. a story-reviewer assessment or a work-queue note). Once a story has
been triaged or implemented, the other daemons stop watching it — this catches
replies that land afterward and, when a reply unblocks the story, hands it back to
story-reviewer for re-triage. The "Source" section below explains how to find,
read, comment on, and label stories.

**Scope is a hard gate, not a preference.** Only ever read, comment on, or label a
story that `{{inputs.owner}}` requested or owns (if `{{inputs.owner}}` is blank,
all stories are in scope). Apply the **safety net** from Source before every
write. A story belonging to anyone else is off-limits.

## 1. Discover new replies

Shortcut comments are **flat** — there is no native reply threading, so a "thread"
is the ordered list of comments on a story after one of your bot comments.
Reconstruct it by timestamp.

Fetch the owner-scoped stories that carry `{{inputs.assist_label}}` (the
awaiting-input stories this run is gated on). For each story, list its comments and:

- Identify your **bot** comments — those carrying the bot marker
  `{{inputs.bot_marker}}`. Each is a thread root.
- A comment counts as a **new human reply** when it is authored by someone other
  than you, posted *after* your most recent bot comment on that story, and its id
  is not already recorded in your state (`daimon state get`).

"You" is the automation. A comment carrying `{{inputs.bot_marker}}` is yours (or a
sibling daemon's) — never treat it as a human reply, and never reply to it.

**Recency window:** ignore replies older than 3 business days (walk back from
today counting Mon–Fri only). Record their ids as processed with a note so a
restart after downtime doesn't flood the pipeline with stale replies.

## 2. Respond to each story

For every story with a new human reply:

1. Read the full comment trail for context.
2. If the reply asks a question or requests something in scope, address it
   directly — make the change if it's within scope, or explain clearly why not.
3. Post your response as a story comment, prefixed with `{{inputs.bot_marker}}`,
   opening with the intent prefix from the reply taxonomy in **Output conventions**
   below — `Acknowledged — …` or `Respectfully disagree — …` (use `Fixed — …` only
   when you actually landed a change). Detail follows `{{inputs.verbosity}}`: `full`
   — when you made a change, name the files/changes touched and give a brief
   rationale; `compact` — a terse one-line outcome.

## 3. Re-trigger triage when an awaiting-input question is answered

If the story carries `{{inputs.assist_label}}` (story-reviewer parked it as
needing human input) and the reply supplies that input, **remove the
`{{inputs.assist_label}}` label** (read-modify-write the label set — see Source).
With no assessment label, the story falls back into story-reviewer's triage gate
and gets re-assessed next run — usually flipping to `{{inputs.ready_label}}`.

Do not re-trigger for purely conversational replies (thanks, acknowledgements) —
only when the answer actually unblocks the story. For a reply on a story that is
already in `{{inputs.in_progress_state}}` (work-queue is implementing it), leave
the labels alone and just post your reply; work-queue re-evaluates on its own.

## 4. Finish

Write the latest processed comment id per story back with `daimon state set`.
Summarize how many stories you replied to and any you handed back to story-reviewer.
