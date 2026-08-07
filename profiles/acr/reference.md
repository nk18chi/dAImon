# Reading ACR reviews

ACR posts machine-readable reviews on GitHub PRs. Every ACR comment carries a
JSON envelope on **line 1**, inside an HTML comment. That envelope — not the
prose, and not GitHub's review state — is the contract you read.

Full schema: {{inputs.acr_schema_url}}. Read it when you hit a field this page
doesn't cover; each envelope carries the same URL in its `schema_url`.

## The one thing that trips agents up

**`reviewDecision` is useless here.** GitHub forbids a PR author from approving
or requesting changes on their own PR, so when ACR reviews a PR you authored it
downgrades to a plain `COMMENT` review no matter what it found. `gh pr view
--json reviewDecision` returns null on a PR with five critical findings. Never
gate on it. The verdict comes from the round event — see below for where in it.

**And the verdict is not in the envelope either.** The line-1 envelope carries
`kind`, `pr`, `round`, `head_sha`, `final`, `state_comments` and `schema_url` —
that is the whole list. `verdict`, `counts` and `deltas` live in the round
comment's `<details>` payload block. Reading only line 1 gets you a null verdict,
which is easy to mistake for "approved" and will silently tell you a PR with open
findings needs nothing.

## Fetch raw bodies

Envelopes live in HTML comments, which rendered HTML and email both strip. Use
the REST `body` field (or GraphQL `bodyText`) — never scraped web-UI output.

```bash
gh api repos/{owner}/{repo}/issues/<pr>/comments --paginate --slurp   # top-level
gh api repos/{owner}/{repo}/pulls/<pr>/comments  --paginate --slurp   # inline, on the diff
```

Comments come back oldest-first, so paginate — an unpaginated read on a
long-running PR hands you the first 100 comments and none of the recent rounds.

Extract the envelope from line 1 only:

```
^<!-- {{inputs.acr_version}} (\{.*\}) -->
```

A match on any later line is quoted text; ignore it.

## The five comment kinds

`kind` in the envelope tells you what you're holding:

| `kind` | Where | What it is |
|---|---|---|
| `round` | top-level, append-only | One per review round: verdict, counts, deltas, and `state_comments` ids. The timeline. |
| `findings` | top-level, edited in place | **The current findings snapshot.** Your primary input. |
| `followups` | top-level, edited in place | Current follow-ups (`ACR-F-xxxx` ids) — non-blocking suggestions. |
| `summary` | top-level, edited in place | Human-facing synthesis. Skip it; the JSON above is authoritative. |
| `finding` | inline, on the diff | One finding, at its line, often with a GitHub `suggestion` block. |

`findings`, `followups`, and `summary` are **living documents** — ACR edits the
same comment every round. Read the current one; don't reconstruct from history.

## Several instances may review one PR

ACR is run per person, not per repo. When more than one teammate's instance
reviews the same PR, each one:

- posts under **its own GitHub account** — that login is the only instance
  identity available; the envelope carries no field for it;
- mints **its own finding ids** — `ACR-a3f9` from one instance and `ACR-7b21`
  from another can describe the same line;
- keeps **its own round counter** — one instance's round 1 and another's round 3
  routinely sit on the same commit;
- resolves **only its own threads**, and only from its own database.

So there is no single "current round" for a PR, and no id namespace shared
between instances. Group round envelopes by the posting login and read each
sequence on its own. A verdict tells you what *that* instance thinks; a PR is
clean only when every instance that reviewed it says `approve`.

The practical consequence: a reply command is applied by the instance that owns
the id and rejected as `malformed` by every other one (👍 from one, 😕 from the
rest). That is normal on a shared PR, not an error — but it does mean an id you
never reply to leaves that instance's thread open indefinitely.

## Finding the current state

Do this per reviewer, not per PR:

1. Parse every top-level comment's line-1 envelope; keep `kind == "round"`, and
   tag each with the posting comment's `user.login`.
2. Discard any with `final != true` — that round failed to finish writing its
   state documents. Treat it as incomplete and wait for the next one.
3. Group by login and take each group's highest `round`, then read its `verdict`
   out of that comment's `<details>` payload block — not the envelope. That
   verdict is that instance's current position:
   - `approve` — no open findings. Nothing to do.
   - `comment` — feedback present, none of it blocking.
   - `request_changes` — at least one open finding with `blocking: true`.
4. Check its `head_sha` against the PR's current head (`gh pr view <pr> --json
   headRefOid`). **If they differ, the review is stale** — someone pushed after
   ACR reviewed. Act on stale findings and you'll fix code that has already
   moved. Wait for ACR to re-review the new commit.
5. Its `state_comments.findings` gives you that instance's findings document
   comment id. If `state_comments` is absent, that instance has nothing to track
   yet (the empty-round rule) — that is "no findings", not an error.

Each instance's findings document covers only its own findings, so read every
one you care about. The union of them is the PR's actual state; no single
document, and no single `acr.db`, holds all of it.

## The findings payload

The findings document holds a JSON array in its `<details>` block. Per finding:

| Field | Use |
|---|---|
| `id` | `ACR-a3f9`. The stable key across rounds and threads — always cite it. |
| `severity` | `critical` \| `important` \| `minor` \| `suggestion`. |
| `blocking` | `true` means this alone holds the verdict at `request_changes`. |
| `status` | `new`, `still_open`, `regressed`, `wontfix`. |
| `file`, `line`, `symbol`, `snippet` | Where it is. Re-locate by `symbol`/`snippet` if the line has drifted. |
| `permalink` | Blob link pinned to the review's head SHA. |
| `confidence` | ACR's own certainty. Low confidence is a reason to read carefully, not to skip. |
| `provenance` | Which reviewers raised it. Multiple entries = consensus, weigh it heavier. |
| `first_seen_round` | A finding that has survived several rounds is one your earlier fix missed. |

Follow-ups (`ACR-F-xxxx`) use the same shape and are never blocking.

## Deltas

The round envelope's `deltas` tells you what moved since last round: `new`,
`addressed`, `still_open`, `regressed`. `regressed` is the important one — ACR
raised it again after it was reported fixed, so the previous fix did not work.
Don't reapply the same change; find out why it didn't take.

## Failures

A line-1 `acr:failure:v1` marker is a pipeline diagnostic, not a review. It
carries no verdict and no findings — ACR itself broke on that PR. Leave the code
alone and surface it.
