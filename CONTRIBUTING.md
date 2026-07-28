# Contributing

Thanks for considering a contribution to opencode Copilot Credit Estimator.

## Development setup

```sh
uv sync --all-extras --dev
uv run pytest
uv run python -m py_compile estimator.py
```

## Pull requests

- Keep changes focused; unrelated fixes should be a separate PR.
- Add or update tests for behavioural changes.
- Update `README.md` and `CHANGELOG.md` (under `[Unreleased]`) when user-facing behaviour changes.
- CI (`.github/workflows/ci.yml`) must pass before merge.

## Releasing (maintainers)

This project uses [Semantic Versioning](https://semver.org/) with `vX.Y.Z` git tags.

1. Move the `[Unreleased]` entries in `CHANGELOG.md` under a new `## [X.Y.Z] - YYYY-MM-DD` heading.
2. Bump `version` in `pyproject.toml` to match.
3. Refresh the bundled pricing snapshot: `uv run pricing.py --update-snapshot`
   (commit it if it changed).
4. Commit as `chore: release vX.Y.Z`.
5. Tag and push:

   ```sh
   git tag -a vX.Y.Z -m "Release vX.Y.Z"
   git push origin main --tags
   ```

   Pushing the tag triggers `.github/workflows/release.yml`, which runs the
   tests, verifies the tag matches `pyproject.toml`, and creates the GitHub
   Release using the matching `CHANGELOG.md` section as the release notes.
   You do **not** need to create the release by hand.

6. The Homebrew formula in `springernature/homebrew-opensource` updates itself
   via a workflow in that repo when the release is tagged — no manual formula
   change is needed here.
