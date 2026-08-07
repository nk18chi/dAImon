# Replying to ACR

ACR reads structured commands back off the PR. This is how you tell it what you
did, and it is what makes the review loop converge instead of repeating itself.

## The commands

One per line, at the **start of the line**, case-sensitive. Anything else on the
line's own is ignored silently — no error, no effect.

```
/acr ack ACR-a3f9                      # acknowledged, fixing it
/acr fixed ACR-a3f9                    # claimed fixed — ACR verifies next round
/acr wontfix ACR-a3f9 <reason>         # declining, with the reason
/acr done ACR-F-77c2                   # follow-up completed
/acr declined ACR-F-77c2 <reason>      # follow-up declined, with the reason
```

`ACR-xxxx` ids are findings; `ACR-F-xxxx` are follow-ups. Using the wrong verb
for the wrong id type is rejected as malformed. `<reason>` is free text, never
interpreted, and re-rendered escaped — write it for the human reading the PR.

## Where to put them

Either works, and both are scanned:

- **On the finding's inline thread** — reply to the inline comment for that
  finding (`gh api repos/{owner}/{repo}/pulls/<pr>/comments -f
  in_reply_to=<comment_id> -f body=...`). Preferred: the command sits next to
  the code it's about, and the thread reads as a conversation.
- **As a top-level PR comment** — `gh pr comment <pr> --body ...`. Use this to
  batch several commands, or when a finding has no inline comment.

## What ACR does with them

At the start of the next round ACR scans all comments, checks that the commenter
is the PR author or has write permission, and applies accepted commands —
reacting 👍 to each, or 😕 to one it rejects. It replays by comment id, so a
command is applied exactly once and a command it missed is picked up later.

Two consequences worth planning around:

- **`fixed` is a claim, not a fact.** ACR re-reviews the code. If the finding
  is still there it comes back with status `regressed`, which is a worse
  position than not having claimed it. Only send `fixed` after the change is
  committed and pushed.
- **`wontfix` is the only thing that permanently retires a finding.** It
  suppresses that id in later reviews. Without it, a finding you disagree with
  is re-raised every single round and the loop never converges. Use it — with a
  real reason — rather than ignoring the finding.

ACR resolves the GitHub thread itself once a later round confirms the fix. Don't
resolve threads by hand; your reply plus the next round is the whole protocol.
