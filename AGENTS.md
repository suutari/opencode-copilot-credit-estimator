# AGENTS.md

Instructions for agents working in this repository.

## Making changes

When you make a user-facing change (behaviour, CLI flags, output, or anything
documented in `README.md`), add a bullet under the `## [Unreleased]` heading in
`CHANGELOG.md` describing it. This is required — CI blocks pull requests that
touch `*.py` or `README.md` without also updating `CHANGELOG.md`. See
`CONTRIBUTING.md` for the full contribution and release conventions.

## Preflight checks

`scripts/preflight.sh` is the single source of truth for the validation
gates (lockfile sync via `uv lock --check`, dependency install, tests, and a
compile check). Both `.github/workflows/ci.yml` and `release.yml` invoke it
rather than duplicating the steps, so run it locally before pushing or tagging:

```sh
scripts/preflight.sh          # base checks (CI-equivalent)
scripts/preflight.sh vX.Y.Z   # also assert the tag matches pyproject.toml and
                              # that CHANGELOG.md has a section for that version
```

If you add or change a validation gate, edit `preflight.sh` — do not re-add
the step inline in a workflow.

## Cutting a release

See `CONTRIBUTING.md` for the version-bump/tag steps. The Homebrew formula in
`springernature/homebrew-opensource` updates itself via a workflow in that
repo when a new release is tagged here — you do **not** need to touch the
formula as part of a release.

