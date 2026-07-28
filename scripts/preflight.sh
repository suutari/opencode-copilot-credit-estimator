#!/usr/bin/env bash
#
# Preflight checks shared by local development, CI, and the release workflow.
#
# This is the single source of truth for the validation gates. The GitHub
# workflows (.github/workflows/ci.yml and release.yml) invoke this script
# rather than duplicating the individual steps.
#
# Usage:
#   scripts/preflight.sh            # run the base checks (lock, deps, tests, compile)
#   scripts/preflight.sh vX.Y.Z     # also verify a release tag matches pyproject
#                                   # and that CHANGELOG.md has a section for it
#
# Exits non-zero on the first failing check.

set -euo pipefail

cd "$(dirname "$0")/.."

step() { printf '\n==> %s\n' "$1"; }

step "Verify uv.lock is in sync with pyproject.toml"
uv lock --check

step "Install dependencies"
uv sync --all-extras --dev

step "Run tests"
uv run pytest

step "Compile check"
uv run python -m py_compile estimator.py pricing.py

# Release-only checks: only run when a version/tag argument is supplied.
if [ "$#" -ge 1 ]; then
  version="${1#v}"

  step "Verify tag matches pyproject version"
  proj="$(uv run python -c 'import tomllib,pathlib; print(tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["version"])')"
  if [ "$version" != "$proj" ]; then
    echo "error: version $version does not match pyproject.toml version $proj" >&2
    exit 1
  fi
  echo "Tag and pyproject version agree: $proj"

  step "Verify CHANGELOG.md has a section for $version"
  if [ -z "$(uv run python scripts/extract_changelog.py "$version")" ]; then
    echo "error: no CHANGELOG.md section for $version (add one under a '## [$version]' heading)" >&2
    exit 1
  fi
  echo "CHANGELOG.md section for $version found."
fi

step "All preflight checks passed."
