# Release Process

Releases are automated via [release-please](https://github.com/googleapis/release-please). Do not cut tags manually.

## How it works

1. Every push to `main` triggers the release-please workflow, which uses [`.release-please/config.json`](../.release-please/config.json) and [`.release-please/manifest.json`](../.release-please/manifest.json).
2. When there are user-facing conventional commits since the last release, release-please opens or updates a release PR with the computed version bump, `CHANGELOG.md` update, `.release-please/manifest.json` update, and `pyproject.toml` version update.
3. Merging the release PR causes the next `main` run to create the semver tag (e.g. `v1.2.0`) and GitHub release.
4. When a release is created, the workflow force-moves the floating major tag (e.g. `v1`) to the new release tag so callers pinned to `@v1` pick up backward-compatible updates.

## PR title conventions

All PRs must use [Conventional Commits](https://www.conventionalcommits.org/) format in the title. The `pr-title-check` workflow validates PR titles when a PR is opened, edited, synchronized, or reopened.

Release-please computes releases from conventional commit messages on `main`. In the normal squash-merge flow, the PR title should become the squash commit title, so the PR title is the release signal. The version bump is determined by the highest-impact merged commit since the last release:

| PR title prefix | Bump | Notes |
| --- | --- | --- |
| `<type>!:` or `BREAKING CHANGE:` in the commit body | Major | Removing a workflow, renaming an input, changing required secrets |
| `feat:` | Minor | New workflow, new optional input |
| `fix:`, `perf:` | Patch | Bug fixes, performance improvements |
| `docs:` | None | README, TOOLS.md, AGENTS.md changes |
| `chore:`, `ci:`, `test:`, `refactor:` | None | Internal changes with no caller impact |

A scope is optional but encouraged for clarity, e.g. `feat(docker): add multi-platform build support`.

## Semver rules for this repo

| Change | Bump |
| --- | --- |
| Removing a workflow, removing or renaming an input, changing required secret names, breaking script interface (args, exit codes, GHA outputs) | Major |
| New optional input, new workflow, new composite action | Minor |
| Bug fix, internal refactor, dependency update with no behavior change | Patch |

## Release-please config

- Config: [`.release-please/config.json`](../.release-please/config.json)
- Manifest: [`.release-please/manifest.json`](../.release-please/manifest.json) - owned by release-please, do not edit by hand
- Release type: `python` - release-please updates `version` in `pyproject.toml` on each release
- Changelog sections: `feat`, `fix`, and `perf` are shown in release notes as `Features`, `Bug Fixes`, and `Performance Improvements`; `chore` is configured as hidden. Other conventional types are intentionally omitted from the generated changelog unless the config is expanded.
- `extra-files` in the `.` package config keeps `uv.lock`'s embedded `github-action-pipeline-blueprints` package version in sync with the `pyproject.toml` bump. Without it, release-please's version PR fails CI: `uv sync --locked` rejects a lockfile whose recorded version no longer matches `pyproject.toml`.
- The jsonpath filter for the `uv.lock` entry must compare against `@.name.value`, not `@.name`. Release-please's TOML updater wraps every scalar as `{start, end, value}`, so a bare `@.name` never matches a string filter — it silently logs "No entries modified" and leaves the file untouched instead of failing the workflow.
