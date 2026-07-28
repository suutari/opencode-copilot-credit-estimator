# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Usage summary now shows a "Budget resets in <n> days" line, counting down to the first day of the next month (shows "Budget resets tomorrow" when only one day remains).

### Fixed

- `uv.lock` project version was out of sync with `pyproject.toml` (stuck at `0.1.0`); resynced to `0.2.0`. CI and release workflows now run `uv lock --check` to fail fast if the lockfile drifts again.

## [0.2.0] - 2026-07-28

### Added

- Automated GitHub Copilot pricing: rates are now fetched and parsed from GitHub's published pricing page (`pricing.py`) instead of a hardcoded dict, expanding coverage from 14 to 29 models.
- Offline-first pricing cache (`~/.cache/opencode-copilot-credit-estimator/`) with a bundled fallback snapshot; live refresh only when stale (>24h).
- `--offline` flag to skip all network pricing refreshes.
- `pricing_source`/`pricing_retrieved_at` reported in JSON output and a "Pricing last refreshed" line in table output.
- Maintainer command `uv run pricing.py --update-snapshot` to regenerate the bundled snapshot.

### Changed

- Pricing is refreshed synchronously before `--output` runs and in a non-blocking background worker in the TUI.

## [0.1.0] - 2026-07-28

### Added

- Initial public release: Textual-based TUI for tracking GitHub Copilot AI credit usage from opencode session logs.
- Hour/Today/Week/Month tabs with cumulative credit chart and per-model breakdown table.
- Responsive compact layout for narrow/short terminals.
- `--output table`/`--output json` for non-interactive use.
