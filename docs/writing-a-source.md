# Adding a source

A **source** is a profile under `profiles/<name>/` that teaches daemons how to
talk to one external system — GitHub, Shortcut, Datadog, Jira, Linear, Sentry.
Daemons opt in with `sources = [...]` in their `daemon.toml`; the framework merges
the profile's default inputs and composes its reference docs into the rendered
skill. A source can be **read** (a gate queries it) or **write** (the agent acts
on it), and a single daemon can read one and write another — `datadog-log-reviewer`
reads Datadog and writes Shortcut.

## Files

Only `profile.toml` is required. Everything else is optional and added as needed.

### 1. `profile.toml` (required)

```toml
[profile]
tool = "jira"
description = "Jira issues via the REST API"

[defaults]                     # input defaults every daemon on this source inherits
base_url = "https://you.atlassian.net"
triage_state = "Backlog"       # see "Conventions" — needed to feed the triage loop
```

`[defaults]` become `{{inputs.<key>}}` values in skills and reference docs. A
daemon overrides any of them in its own `[inputs]`; the merge and provenance live
in `lib/config.py` (the only TOML parser). The directory name is the source name
used in `sources`.

### 2. `lib.sh` (optional — for a read gate)

Gate helpers a daemon's `discover.sh` sources explicitly (it is **not**
auto-loaded). Pure bash + the system's CLI/`curl` + `jq`, stdlib only. **Every
helper must fail closed** — no CLI, no auth, or bad output resolves to the "no
work" answer, so a broken source never launches the agent. See
`profiles/github/lib.sh` (gh) and `profiles/datadog/lib.sh` (pup) for the shape.

### 3. `reference.md` (optional — read guidance)

Appended to the rendered skill for **every** daemon using this source. Document
how the agent reads the system: the API/CLI, auth, key endpoints, and any
domain-specific method (e.g. Datadog's log clustering). Reference inputs as
`{{inputs.<key>}}`.

### 4. `reference.write.md` (optional — write guidance)

Appended **only** when a daemon lists the source with `write = true`. Document the
mutating operations — create, comment, label, transition — with the exact calls.
A read-only daemon never sees this, so keep read vs write cleanly split. See
`profiles/shortcut/reference.write.md`.

### 5. `profile.local.toml.example` (optional)

Each person's overrides of `[defaults]`, shared across every daemon on the source
(e.g. your Shortcut `owner`), live outside the repo in
`~/.daimon/profiles/<name>.toml`. Commit a `profile.local.toml.example` to
show the shape; `daimon init` copies it there.

## How a daemon uses it

```toml
# in <slug>/daemon.toml
sources = ["datadog", { name = "shortcut", write = true }]
```

- **Defaults → inputs.** Each source's `[defaults]` merge into the daemon's inputs
  (daemon `[inputs]` win), then export as `DAIMON_INPUT_*` for the gate and render
  into the skill.
- **Reference composition.** `render-skill` appends each source's `reference.md`,
  plus `reference.write.md` for write sources — so the skill inherits the
  how-to instead of restating it.
- **The gate** sources `lib.sh` itself: `source "$(dirname "$0")/../../profiles/<name>/lib.sh"`.

## Credentials

Resolve them from the environment **or a file under `$HOME`** (as `gh`,
`shortcut_token`, and `pup` do) — never from the plist. launchd forwards only
`PATH`, `HOME`, and `SSH_AUTH_SOCK` to a daemon and does **not** read your shell
profile, so a token exported in `.zshrc` won't reach an unattended run. Credentials
cached under `$HOME` (a CLI's `auth login`, `~/.config/...`) are what survive. Add
a check to `lib/doctor.sh` gated on the source being in use (mirror the `shortcut`
/ `datadog` blocks) so a missing tool or lapsed auth surfaces loudly.

## Conventions for a write source that feeds the triage loop

A daemon that files work items (like `datadog-log-reviewer`) is source-agnostic:
its skill defers to *"your write source's writing reference."* For a new tracker to
drop into that slot, its profile must:

- expose a **`triage_state`** input (the skill puts new items there so
  `story-reviewer` picks them up), and
- give `reference.write.md` a **"Create …"** section with the exact create call.

Honor those two and swapping Shortcut for Jira is profile-only — no skill edits.

## Activate

```bash
daimon config validate   # errors if a referenced source has no profiles/<name>/profile.toml
daimon run <slug>        # one gated run
make docs                # regenerate the daemon README (shows the sources)
```

Validation (`lib/config.py`) fails when a daemon references an unknown source, and
`make check` runs `check_links` so any relative link you add here must resolve.
