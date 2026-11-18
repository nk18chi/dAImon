# Running unattended

Nobody is watching this run. A permission prompt never gets an answer: the run
sits on it until it is marked stuck, and any half-finished work is stranded.

- The operator's permission settings can make some commands ask first even in
  this mode, commonly `rm`, `git clean`, `git reset`, `git restore`, `git rebase`
  and `git merge`. Don't run them. Leave scratch files where they are (the
  scratchpad is cleaned for you) or overwrite them, and bring a branch up to
  date by committing on top of it rather than rebasing or resetting.
- Never put a variable or command substitution in a destructive command: the
  harness can't check it in advance and will prompt.
- If a step can only be done with a command that will prompt, skip that step,
  finish the rest, and say what you skipped in your summary.
