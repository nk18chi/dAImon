# The catalog: choosing your daemons

dAImon is the shell: the framework, backends, source profiles, TUI and skills.
Daemons come from a **catalog**, and each machine picks the ones it runs.

## Where daemons come from

| Folder | What it holds | In git |
|--------|---------------|--------|
| `catalog/` in the dAImon install | dAImon's own generic daemons ([index](../catalog/README.md)) | yes, tested by dAImon's CI |
| `daemons/` in each [pack](packs.md) | a team's daemons | in the pack's repo |
| `daemons/` in the dAImon install | your own daemons, and private `<slug>.local` ones | no (only its README) |

dAImon's `catalog/` and every pack's `daemons/` are catalogs: they offer daemons
you can install. The install's own `daemons/` is different: a daemon there is
yours, active as soon as it exists, and takes precedence over a catalog daemon of
the same slug (an **ejected** copy).

Team-specific daemons (a team's systems, channels, IDs, workflow) belong in a
pack, never in `catalog/`.

## Installed, registered, active

- **Installed:** listed in `[daemons].installed` in `~/.daimon/daimon.toml`.
- **Active:** installed, plus your own daemons in `daemons/`, minus
  `[daemons].disabled`. Active daemons are what `daimon sync` renders, `daimon
  validate` checks, and `daimon daemons` / the TUI list.
- **Registered:** has a launchd plist, so launchd schedules it. Installing never
  registers: select the daemon in `daimon tui` and press `r`.

A daemon found in two catalogs (dAImon and a pack, or two packs) is a validation
error unless you have your own copy in `daemons/`, which settles it, or the
pack's copy was [ejected into the pack](#ejecting-into-a-pack) from dAImon's
catalog, which overrides dAImon's on purpose. An installed
slug that no catalog offers is a validation error too: `daimon remove` it.

## Commands

```bash
daimon catalog                 # every daemon you can install: source, state, description
daimon add <slug>…             # install: add to `installed`, scaffold personal settings, sync
daimon remove <slug>…          # unregister (asks first if loaded; --yes skips) and uninstall
daimon init [slug…]            # choose the whole set at once (multi-select without slugs)
daimon scaffold <slug>         # write a new daemon of your own into daemons/
daimon eject <slug>            # copy an installed daemon into daemons/ to edit it
daimon eject <slug> --pack     # copy a dAImon daemon into your pack, for the team
daimon add <slug> --pack       # the same, and install it here
daimon eject <slug> --as <new> # fork it as a new daemon <new> (add --pack for the pack)
daimon outdated                # ejected copies whose upstream (or the copy) changed
daimon diff <slug>             # diff -ru upstream against your copy
daimon uneject <slug>          # delete your copy (asks; --yes skips): linked again
```

`daimon add` copies the daemon's `daemon.local.toml.example` (and its source
profiles' `profile.local.toml.example`) to `~/.daimon/` when you have no
settings file yet; edit `working_dir` and any inputs there. It edits
`daimon.toml` in place, keeping your comments and other settings. `daimon remove`
keeps your personal settings, so adding the daemon back picks them up again.

## Linked or ejected

An installed daemon is **linked**: it runs from its catalog, so a dAImon update
or a pull of the pack brings its fixes. Settings never need a copy: change them
in `~/.daimon/daemons/<slug>.toml` (or the TUI), which overrides the
daemon's `daemon.toml` without touching it.

To change the daemon itself (its prompt, gate or default inputs), **eject** it:

```bash
daimon eject work-queue
```

This copies the folder it loads from (dAImon's `catalog/`, or a pack's
`daemons/`) to `daemons/work-queue/` in the install, which is gitignored and
takes precedence, so you can edit it freely. The slug stays in `installed`
(ejecting a daemon you hadn't installed installs it). Right after ejecting,
nothing it does changes: same settings, same rendered skill (paths written
with `{{daemon_dir}}` now point into the copy, which holds the same files). A gitignored
`daemon.local.toml` left beside the original is moved to your personal settings
first, so it isn't left behind. `daimon eject` refuses a daemon you already have
in `daemons/`.

The copy holds `.origin.json`, recording where it came from:

```json
{"source": "dAImon", "path": "catalog/work-queue", "hash": "sha256:…"}
```

`source` is `dAImon` or the pack's name, `path` the folder relative to that
dAImon install or pack, and `hash` a hash of the copied files (paths, contents
and executable bits, leaving out `.origin.json`, caches and `*.local.toml`).

### Seeing upstream changes

Because the hash records the files as they were copied, comparing it with each
side today tells which one changed:

```console
$ daimon outdated
DAEMON      COPY        UPSTREAM    YOUR COPY   FROM
work-queue  local       changed     edited      dAImon: catalog/work-queue
story-sync  tbl-agents  unchanged   unchanged   dAImon: catalog/story-sync
```

`UPSTREAM` is `changed` when the original changed since the copy (fixes you may
want), `gone` when its catalog no longer has it; `YOUR COPY` is `edited` when the
copy changed. It lists your copies in `daemons/` and every pack copy with an
`.origin.json`. `daimon doctor` notes each copy whose upstream changed.

`daimon diff <slug>` runs `diff -ru` from upstream's current files (`---`) to
your copy (`+++`), after a line saying which side changed since the eject. When
both did, the diff mixes the two: read it against `git log` for that folder.

### Going back to linked

`daimon uneject <slug>` deletes your copy in `daemons/`, after asking (it warns
when you edited it; `--yes` skips the question), so the daemon runs from its
catalog again. Your personal settings and the slug in `installed` stay. It
refuses a daemon with no `.origin.json` (one you wrote yourself) and a pack's
copy, which the team changes by a PR to the pack.

### Ejecting into a pack

A team that wants its own version of a dAImon daemon copies it into its pack:

```bash
daimon eject work-queue --pack            # the only pack in [packs].paths
daimon eject work-queue --pack ~/tbl/tbl-agents
daimon add work-queue --pack              # copy it, and install it here too
```

The copy goes to the pack's `daemons/work-queue/` with an `.origin.json` naming
`dAImon` and `catalog/work-queue`, and leaves out `*.local.toml`, so nothing
personal reaches the pack. `--pack` without a directory needs exactly one
configured pack. Commit the copy in the pack's repo; from then on it replaces
dAImon's daemon for everyone with the pack (`daimon validate` accepts it as an
intentional override rather than a duplicate), and `daimon outdated` /
`daimon diff` show the team dAImon's later fixes to fold in by PR.

### Forking under a new name

To run a variant *beside* the original rather than instead of it, give the copy
its own slug:

```bash
daimon eject work-queue --as bug-queue           # daemons/bug-queue/
daimon eject work-queue --as bug-queue --pack    # the pack's daemons/bug-queue/
```

The copy comes from the original's catalog, and the slug is rewritten wherever
the daemon's own files name it on its own: `command = "/bug-queue"`, the
skill's `name:`, `state_file bug-queue` and `daimon state get bug-queue` in the
gate and skill, and so on (`work-queue-x` would be left alone). So the fork gets
its own rendered skill (`/bug-queue`), launchd job (`com.<namespace>.bug-queue`),
state and logs, and both can be installed and registered at once. Nothing about
the original changes; `bug-queue` is added to `installed`. If you have personal
settings for the original (`daemons/work-queue.toml` in your personal settings
folder) and none for the fork, they are copied to `daemons/bug-queue.toml` as a
starting point.

A pack's team settings for the original (`overrides/work-queue.toml`) apply only
to `work-queue`, so the fork takes them into its own `daemon.toml` instead: every
`[daemon]` and `[inputs]` value they set, layered in pack order as they are for
the original, each under a comment naming the pack it came from. The command
lists the override files it folded in. With those and your settings copied, the
fork starts with exactly the original's effective config (working directory,
repos and so on), apart from its name. Later changes to the pack's override
don't reach the fork.

`.origin.json` still points at the original, plus the new name:

```json
{"source": "dAImon", "path": "catalog/work-queue", "as": "bug-queue", "hash": "sha256:…"}
```

`hash` covers the renamed copy, and `daimon outdated` / `daimon diff bug-queue`
compare it with upstream through the same rewrite, so the rename alone is not
an edit and the diff shows only real changes on either side. The folded-in team
overrides are not part of `hash`, so they show as edits to your copy (`YOUR COPY`
`edited`, and in the diff), which is what they now are.

A fork is a distinct daemon, never an override: `daimon validate` treats it like
any other daemon, even in a pack. `daimon eject --as` refuses a name that isn't
a valid slug, is the original's own, or already exists in any catalog, pack or
`daemons/`. `daimon uneject` refuses a fork, since nothing is linked under its
name: `daimon remove bug-queue`, then delete its folder.

## Installs from before the catalog

dAImon's daemons used to live in `daemons/`, and every one of them was active
unless listed in `disabled`. With no `installed` key, dAImon still behaves that
way: every catalog daemon not in `disabled` counts as installed. So a scheduled
job that fires between an update's `git merge` and its migration runs exactly as
before.

`daimon install` (which every self-update runs) and `daimon init` then run
`daimon migrate`, which:

- moves the personal dir from `~/.config/daimon` to `~/.daimon`
  ([details](configuration.md#local-overrides-keep-your-config-out-of-git));
- writes `installed` as that active set, once, leaving `disabled` as it is;
- moves the gitignored `daemon.local.toml` files the move left in
  `daemons/<slug>/` to `~/.daimon/daemons/<slug>.toml`, and your
  slack-commands runbooks from `daemons/slack-commands/commands.local/` to
  `~/.daimon/commands/`;
- removes a `daemons/<slug>/` folder left holding only migration stubs and caches.

Slugs, state, logs and launchd plists don't change, so registered jobs keep
running. Private `daemons/<slug>.local` daemons were already where your own
daemons live, and keep working unchanged.
