# Packs: share a team's setup

dAImon's own repo holds generic daemons in its `catalog/`. A team's real setup (its private
daemons, the settings everyone shares, its Slack runbooks) belongs in a repo the
team owns, not in one person's settings on one machine. A **pack** is
that repo: a folder dAImon loads alongside its own.

```toml
# ~/.daimon/daimon.toml
[packs]
paths = ["~/work/daimon-team"]
```

## Layout

Every folder is optional.

```
daimon-team/
  daemons/<slug>/       whole daemons, exactly like dAImon's catalog/<slug>
  overrides/<slug>.toml team settings for any daemon: [daemon] and [inputs]
  profiles/<name>.toml  team [defaults] for a source profile
  commands/*.md         slack-commands runbooks
  .gitignore            *.local.toml
```

## How settings layer

Last wins:

- **Daemon:** `daemon.toml` → `overrides/<slug>.toml` (each pack, in `paths`
  order) → legacy `daemon.local.toml` → `~/.daimon/daemons/<slug>.toml`.
- **Profile:** `profile.toml` → `profiles/<name>.toml` → legacy
  `profile.local.toml` → `~/.daimon/profiles/<name>.toml`.

Put what everyone on the team shares in the pack: the log query, the epic,
labels, the `role`. Keep what is yours (your member ID, your schedule) in
`~/.daimon/daemons/<slug>.toml` — the same place for a pack daemon as for
one of dAImon's own. A pack daemon's older gitignored `daemon.local.toml`, beside
its `daemon.toml`, is still read and is moved there by `daimon migrate`
([configuration](configuration.md#local-overrides-keep-your-config-out-of-git)).

## Daemons in a pack

- A pack's `daemons/` is a [catalog](catalog.md): `daimon catalog` lists its
  daemons beside dAImon's, and each person installs the ones they want with
  `daimon add <slug>`. A pack daemon nobody installed does not run.
- A slug defined in two catalogs (dAImon and a pack, or two packs) is a validation
  error, unless you have your own copy in `daemons/`, which wins.
- `disabled` works the same.
- State and logs are keyed by slug, so moving a daemon into a pack keeps its
  history.
- A pack daemon's gate can't reach dAImon's libraries with a relative path.
  `run.sh` exports `DAIMON_INSTALL_ROOT` and `DAIMON_DAEMON_DIR`:

  ```bash
  source "$DAIMON_INSTALL_ROOT/lib/common.sh"
  source "$DAIMON_INSTALL_ROOT/profiles/shortcut/lib.sh"
  source "$DAIMON_DAEMON_DIR/lib.sh"
  ```

- In a skill, `{{daemon_dir}}` renders as the daemon's absolute folder, for
  scripts it ships. An `[inputs]` value can use it too (slack-commands'
  `commands_dir = "{{daemon_dir}}/commands"`), so the path follows the daemon
  into a pack or an ejected copy.

## Adding a daemon to a pack

`daimon new --pack` (Claude interviews you) or `daimon scaffold <slug> --pack`
(a skeleton) creates it in the first pack's `daemons/`; give `--pack <dir>` to
pick another. The skeleton's gate already sources dAImon's libraries through
`$DAIMON_INSTALL_ROOT`, and skips every run until you write it. Commit it in the
pack's repo, and teammates see it in `daimon catalog` after their next
`daimon sync`. It runs on a machine only once someone installs it there
(`daimon add <slug>`) and registers it (`r` in `daimon tui`).

Team-specific daemons always go in a pack, never in dAImon's `catalog/`.

To adapt one of dAImon's daemons for the team instead, copy it into the pack
with `daimon eject <slug> --pack` (or `daimon add <slug> --pack` to install it
too). The pack's copy replaces dAImon's, and `daimon outdated` shows when
dAImon's changes: see [ejecting into a pack](catalog.md#ejecting-into-a-pack).

A pack daemon can ship `doctor.sh` for its own needs
([writing a daemon](writing-a-daemon.md#4-doctorsh-optional)). A pack is kept
current by `daimon sync`, which runs hourly through `daimon update` when
`[update] auto` is on.

## Runbooks

slack-commands reads `commands/` in every pack, after its shared runbooks and
before your own in `~/.daimon/commands/`. Scaffold one into a pack with
`daimon command new <name> --pack <dir>`.

## Commands

- `daimon packs` lists each pack and what it adds.
- `daimon sync` fast-forwards each pack that is a clean git checkout, then
  re-renders as usual. A pack adding daemons doesn't start anything: each person
  installs the ones they want (`daimon add`, or `daimon init`) and registers them
  (`r` in the TUI).
