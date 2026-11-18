# Log what you did

The operator reads a one-line-per-event log to see what each run did. Add to it
with `daimon log "<message>"` (your daemon is known from the session), once for
each item you acted on, as soon as that item is finished:

```bash
daimon log 'auto-ready sc-123 https://app.shortcut.com/acme/story/123 — Fix the thing'
```

- **Outcome** first, in a word or two: the label or status you set, `PR opened`,
  `merged`, `closed`, `replied`, `skipped`, `failed`, …
- Then the item's id and a link to it (a story's `app_url`, a PR's URL) and its
  title. Add the PR URL too when you opened one, or a few words of reason for a
  skip or failure.
- Wrap the message in single quotes, and write any `'` in a title as `’`, so
  the shell never expands a `$` or backtick in it.
- One line per item, no line breaks. Never put secrets or tokens in it.

If the run ends without acting on anything, log one line saying why
(`nothing to do: …`).
