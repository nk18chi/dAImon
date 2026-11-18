---
name: daemon-status
match: daemon-status
mutating: false
description: Report the daimon fleet — what ran, what's scheduled, anything stuck.
---

Run `daimon status`. Reply with a short per-daemon list: enabled/disabled,
last run outcome, and anything currently running or stuck. Lead with a
one-line health verdict (all quiet / N running / something stuck).
