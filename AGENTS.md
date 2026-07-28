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

This project has an associated Homebrew formula at
`springernature/homebrew-opensource` (`Formula/opencode-copilot-credit-estimator.rb`).
It tracks the latest tagged release via a pinned `url` + `sha256`, so every
release must bump the formula to the new tag (an unbumped formula leaves the
tap serving the previous version).

When cutting a new release (see `CONTRIBUTING.md` for the version-bump/tag
steps), you must also update the Homebrew formula in the same pass:

1. Clone `springernature/homebrew-opensource` and open
   `Formula/opencode-copilot-credit-estimator.rb`.
2. Point the formula at the new tagged release:
   - Update the `url` and `sha256` to the new release tarball, e.g.:
     ```ruby
     url "https://github.com/springernature/opencode-copilot-credit-estimator/archive/refs/tags/vX.Y.Z.tar.gz"
     sha256 "<sha256 of that tarball>"
     ```
     Compute the sha256 with `curl -L <tarball-url> | shasum -a 256`.
   - Homebrew infers the version from the `url` for GitHub tag tarballs, but
     double check with `brew style`/`brew audit` if available.
3. Confirm the `license` field is `license "MIT"` (matching the upstream
   `LICENSE` file). It should already be set; fix it if a prior edit regressed
   it.
4. Re-check the `resource` blocks (dependency name/version/sha256 for
   `textual`, `textual-plotext`, and their transitive deps) against the
   `uv.lock` in this repo at the tagged commit — regenerate any resources
   whose pinned versions have moved since the formula was last updated.
5. Sanity check the `install`/`test` blocks still match this repo's layout
   (currently: no `[project.scripts]` entry point, so the formula builds a
   venv, installs the runtime files it needs — `estimator.py`, `pricing.py`,
   and the `resources/` directory (the bundled pricing snapshot) — and
   hand-writes a wrapper script that runs `estimator.py` from the venv. See
   `Formula/opencode-copilot-credit-estimator.rb` for the exact approach).
   If packaging changes in this repo — a new runtime module/data file, or a
   console-script entry point — the formula's `install` block must be updated
   to match, or the installed binary will break at runtime.
6. Commit and push the formula change to `homebrew-opensource` (or open a PR,
   per that repo's contribution norms), referencing the release tag in the
   commit message.
7. Verify locally if possible:
   ```sh
   brew install --build-from-source springernature/opensource/opencode-copilot-credit-estimator
   brew test springernature/opensource/opencode-copilot-credit-estimator
   ```

Do not consider a release finished until the formula update has been made —
a tagged GitHub release with no corresponding formula update leaves the tap
silently stale (serving the previous pinned version).
