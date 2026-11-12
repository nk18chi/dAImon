# Learning across runs

You start each run with a fresh context. The only things that carry knowledge
from one run to the next are this project's Claude memory and your durable state
file — use both deliberately.

## At the start of the run

1. Read this project's memory index (`MEMORY.md`) and load any memory whose
   description is relevant to what you're about to do. These capture lessons from
   earlier runs — recurring feedback, non-obvious codebase facts, known false
   positives.
2. Before you act on a finding or a decision, check it against what memory already
   tells you. If a `feedback` memory says a given finding is a known false positive
   or a settled style preference, do not raise it again.

## At the end of the run

Write a memory when you learned something that will still be true next run and
isn't already recorded:

- **feedback** — a correction or preference that recurred (e.g. the same review
  comment got pushed back on more than once). Record the rule, why it holds, and
  how to apply it, so a future run doesn't repeat the mistake.
- **project** — a non-obvious fact about the codebase (a canonical helper, a
  convention, a dependency between areas) that wasn't apparent from a single file.
- **reference** — a pointer to a canonical example (a merged PR, a file) that shows
  how something should be done.

Memory file format (one fact per file, in the project's memory directory):

```markdown
---
name: {short-kebab-slug}
description: {one line — used to judge relevance on later runs}
type: {feedback | project | reference}
---

{the fact; for feedback/project add **Why:** and **How to apply:** lines}
```

After writing the file, add a one-line pointer to `MEMORY.md`.

## What does NOT belong in memory

- Per-item processing state (which PR/story/comment you already handled this run)
  — that goes in your durable state (`daimon state get`/`set`), not memory.
- Anything already in the repo's `CLAUDE.md` or rules files.
- A duplicate of an existing memory — update that file instead, and delete a
  memory that turns out to be wrong.
