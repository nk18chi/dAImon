# Conventions for comment-posting daemons

You post to a shared repository and run repeatedly. Two conventions keep that safe
and idempotent — they apply to every comment-posting daemon, so follow them even
where the steps above don't restate them.

## Mark every comment you post

Prefix every comment, review, or reply you post with `{{inputs.bot_marker}}`. This
is how other daemons — and you, on a later run — tell your automated comments from
a human's. The reply daemons (`reply-to-pr-comments`, `reply-to-story-comments`)
only act on replies to comments carrying this marker, and no daemon should ever
act on its own comments.

## Track what you've handled with `daimon state`

Your durable JSON memory across runs is stored outside the repo, under the
configured state dir. **Access it only through the `daimon state` command** — pass
JSON, never a path — so your record always lands in the right place no matter what
directory you're running in:

```bash
daimon state get                    # read your record (empty output if none yet)
printf '%s' "$new_json" | daimon state set   # write it (validated + atomic)
```

`get`/`set` default to your own daemon; pass a slug to read another's, e.g.
`daimon state get review-prs`. Read your record at the start and skip any item
already handled at its current commit/state; write the updated record at the end.
Key each record by the item **and** the commit or state it was at, so an unchanged
item is never reprocessed and a changed one always is.

You run inside a git repository. **Never write state into it** — do not `cat` or
redirect a state-file path yourself, do not invent a `.daimon/` or `state/`
directory in the working tree, and do not name a file by date. `daimon state` is
the only thing that touches the state file.
