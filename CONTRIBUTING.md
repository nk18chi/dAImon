# Contributing to dAImon

Thanks for your interest! This guide covers the local setup and the workflow for
changes. For the internals and conventions, see [AGENTS.md](AGENTS.md); to build a
daemon, see [docs/writing-a-daemon.md](docs/writing-a-daemon.md).

## Dev setup

```bash
git clone <your-fork> && cd dAImon
uv sync                 # dev tools: ruff, pyright (the runtime itself is stdlib-only)
uv run pre-commit install  # run lint / typecheck / doc-regen on every commit
make doctor             # confirm your toolchain (python 3.12+, tmux, gh, jq, claude)
```

## Before you push

```bash
make test               # bash syntax, python unittests, shellcheck, bats
make lint               # ruff check + ruff format --check + shellcheck
make typecheck          # pyright
make docs               # regenerate per-daemon READMEs (if you touched a daemon)
```

CI runs the same checks on every pull request (`.github/workflows/ci.yml`); a green
`make test && make lint && make typecheck` locally means CI should pass.

## Conventions

- **Shell must stay Bash 3.2-compatible** — macOS ships `/bin/bash` 3.2, and
  shellcheck won't catch 4.x-only syntax. No associative arrays, `${x,,}`, `mapfile`, etc.
- **Never commit machine-local config or secrets.** `*.local.toml`, `config/daimon.toml`,
  and `.env` are gitignored. Add new machine-specific settings as a tracked
  `*.local.toml.example`, not a real value.
- **Keep daemons self-contained** — a dAImon daemon is a folder under
  `catalog/<slug>/` (`daimon scaffold <slug> --catalog`); team-specific ones go in
  a pack instead. Run `daimon sync` after editing a `daemon.toml` or skill.
- **Daemon READMEs are generated** — `catalog/*/README.md` and `catalog/README.md`
  are built from each `daemon.toml` + `SKILL.md`. Don't hand-edit them; change the
  metadata and run `make docs`. CI (`tests/test_docs.py`) fails if they're stale.
- Match the style of the surrounding code; keep functions small and comments scarce.

## Pull requests

- Branch off `main`; use a descriptive `feat/…` or `fix/…` branch name.
- Keep PRs focused and write a body explaining the why.
- **PR titles must be [Conventional Commits](https://www.conventionalcommits.org/)**
  (`type(scope): summary`, e.g. `feat(tui): …`, `fix: …`, `docs: …`). Merges are
  **squash-only** and the squash commit uses the PR title, so the title becomes the
  entry in `main`'s history. The `pr-title` CI check enforces this.
- Make sure the checks pass (`test`, `lint`, `pr-title`) and update docs when
  behavior changes.

## Maintainers: repository settings

Merges are squash-only with auto-delete of merged branches. `main` is protected:
CI (`test`, `lint`, `conventional`) must pass, linear history, no force-push or
deletion, admins can override. **No review is required** — outsiders can't merge
because they lack write access, not because of a review gate; add a review
requirement only once there are other collaborators. To reproduce the protection
(nested JSON must go via `--input`; the `-f 'a[b]=c'` form does not build it):

```bash
gh api -X PUT repos/effekt/dAImon/branches/main/protection --input - <<'JSON'
{
  "required_status_checks": { "strict": true, "contexts": ["test", "lint", "conventional"] },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

Use classic branch protection (above), not a repository ruleset, for the required
checks: a ruleset with an empty bypass list blocks even admins, so release PRs
(which can't receive CI — see below) become unmergeable.

**Release PRs:** release-please opens its `chore(main): release …` PR using the
built-in `GITHUB_TOKEN`, and GitHub does not trigger CI on bot-token PRs — so the
required checks never appear on it. Merge it with an admin override (GitHub's
"merge without waiting for requirements", available because `enforce_admins` is
off), or give release-please a PAT secret (`RELEASE_PLEASE_TOKEN`) so its PRs run
CI and merge normally.
