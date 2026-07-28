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
3. Commit as `chore: release vX.Y.Z`.
4. Tag and push:

   ```sh
   git tag vX.Y.Z
   git push origin main --tags
   ```

5. Create a GitHub Release from the tag (title `vX.Y.Z`, description from the changelog entry).

A tag-triggered release workflow (building artifacts for the Homebrew tap) can be added under `.github/workflows/` once the tap is ready to consume it.
