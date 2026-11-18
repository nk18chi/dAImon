# Migrating to the catalog layout

dAImon changed shape in five steps (#117–#121). Daemons moved into a **catalog**
you install from, and everything personal moved out of the repo into
**`~/.daimon/`**. Most installs need **no manual steps**: the migration runs on the
next `daimon install`, which the self-updater runs after every update. This page
says what changed, what moves automatically, and the few cases that need you.

## What changed

| Before | After |
| --- | --- |
| Every daemon in `daemons/` ran unless listed in `[daemons].disabled` | Only the daemons in `[daemons].installed` run (`daimon catalog`, `daimon add`, `daimon remove`) |
| dAImon's daemons lived in `daemons/<slug>/` | They live in `catalog/<slug>/`; `daemons/` is gitignored and holds **your** daemons and ejected copies |
| Global config at `~/.config/daimon/daimon.toml` | `~/.daimon/daimon.toml` |
| Your settings in `daemons/<slug>/daemon.local.toml` (in the repo) | `~/.daimon/daemons/<slug>.toml` |
| `profiles/<name>/profile.local.toml` | `~/.daimon/profiles/<name>.toml` |
| slack-commands' `commands.local/` | `~/.daimon/commands/` |
| Self-update opt-out `~/.config/daimon/no-auto-update` | `~/.daimon/no-auto-update` |
| Changing a shipped daemon meant editing it in place | `daimon eject <slug>` copies it into `daemons/` to edit; `daimon outdated` / `daimon diff` show upstream changes; `daimon uneject` goes back |
| — | `daimon eject <slug> --as <new>` forks a daemon under a new name; `--pack` puts a copy in a team pack |

Settings layering is unchanged in order: `daemon.toml` < a pack's
`overrides/<slug>.toml` < your personal file.

## What happens automatically

On the first `daimon install` (or `daimon migrate`) after updating:

1. **`~/.config/daimon/` moves to `~/.daimon/`**, files copied verbatim with
   their permissions. A `MOVED` pointer is left behind; delete it whenever you like.
   Anything already in `~/.daimon/` from a much older dAImon is set aside in
   `~/.daimon/legacy-<date>/`, not deleted.
2. **Every `daemon.local.toml` / `profile.local.toml`** (in dAImon and in your
   packs) moves to `~/.daimon/daemons/` / `~/.daimon/profiles/`, comments kept. If
   both exist, the new file's values win and the old ones are kept as comments.
3. **`[daemons].installed` is written once** as exactly the daemons that were
   active: everything found, minus `disabled`. `disabled` is left as it was.
4. **Leftover `daemons/<slug>/` folders** that held only moved settings and
   caches are removed. Anything else in them is left alone.

Nothing about scheduling changes: slugs, launchd labels, plists, state and logs
stay the same, so registered jobs keep running. Until the migration has run, the
new code still reads the old locations, so a job that fires mid-update behaves
as before.

Check it worked:

```bash
daimon validate      # config OK (N daemon(s))
daimon catalog       # your daemons show as installed
daimon status        # the same jobs registered as before
ls ~/.daimon         # daimon.toml, daemons/, profiles/
```

## When you need to do something

**You edited a shipped daemon in place.** The self-updater refuses to update a
clone with local changes (it logs `local changes`). Move your edits into an
ejected copy:

```bash
cd <your dAImon clone>
git stash                          # set your edits aside
git pull --ff-only && make install # update and migrate
daimon eject <slug>                # copy into daemons/<slug>/ (the path your edits had)
git stash show -p | patch -p1      # re-apply them to the copy
git stash drop
daimon diff <slug>                 # upstream vs your copy
```

**You have scripts, aliases or dotfiles** that read or write
`~/.config/daimon/...`, `daemons/<slug>/daemon.local.toml` or
`profiles/<name>/profile.local.toml`: point them at `~/.daimon/...`. `python3 <dAImon>/lib/config.py paths` prints the
resolved ones (`DAIMON_PERSONAL_DIR`, …).

**You wrote your own daemon** in `daemons/<slug>/` or `daemons/<slug>.local/`: it
keeps working, and now counts as yours (no `.origin.json`). If its gate finds
dAImon's `lib/` with `$(dirname "$0")/../../lib`, switch it to
`$DAIMON_INSTALL_ROOT`, as `daimon scaffold` does, so it works wherever it lives.

**You maintain a pack.**
- New daemons you add to the pack no longer start everywhere: each person runs
  `daimon add <slug>` (or your setup script does).
- Gates should resolve dAImon through `$DAIMON_INSTALL_ROOT`, not relative paths.
- Docs or setup scripts that write `*.local.toml` or `~/.config/daimon` should
  use `~/.daimon`, or better, ask dAImon: `python3 "$DAIMON_INSTALL_ROOT/lib/config.py" paths`.
- To customise one of dAImon's daemons for the whole team, use
  `daimon eject <slug> --pack` rather than copying it by hand: the copy records
  where it came from, overrides dAImon's, and shows up in `daimon outdated`.

**You set `$DAIMON_CONFIG`.** Nothing moves; your personal files live beside
that `daimon.toml` (`daemons/`, `profiles/`, `commands/`, `no-auto-update`).

**New installs** start with `installed = []`. Pick daemons with `daimon init` or
`daimon catalog` then `daimon add <slug>`; installing never schedules anything,
register in `daimon tui` (`r`).

## Rolling back

Older dAImon only reads `~/.config/daimon/` and `*.local.toml` beside the
daemons, so going back to a commit before #117 needs the files moved back by
hand: `~/.daimon/daimon.toml` to `~/.config/daimon/`, each
`~/.daimon/daemons/<slug>.toml` to `daemons/<slug>/daemon.local.toml`, and each
`~/.daimon/profiles/<name>.toml` to `profiles/<name>/profile.local.toml`. Pause
the old self-updater too (`touch ~/.config/daimon/no-auto-update`) or it will move
you forward again.
