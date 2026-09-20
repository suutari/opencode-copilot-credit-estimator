# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Added the `occe` console script so the installed CLI is available when the project virtual environment is active.
- Added `--sessions` to report estimated AI credit consumption grouped by OpenCode session. Use it with `--output table` or `--output json`.
- Added `--month YYYY-MM` to estimate a specific calendar month in the TUI and all non-interactive output modes.
- Added `--session SESSION_ID` to filter the TUI and non-interactive output to one OpenCode session.
- Added `--prompts[=short|long|full]` to print user prompts and their usage data for a selected session.
- Long and full prompt output now places credits on a separate indented line for easier scanning.
- Added `--week`, `--day`, and `--hour` selectors for ISO and recent bare-number time ranges in the TUI, table, JSON, session, and prompt output modes.
- Selected week, day, and hour ranges now replace the corresponding TUI tab label with the exact selected period.
- TUI tabs now derive their selected hour, day, week, and month from any supplied time selector.

## [0.4.0] - 2026-09-17

### Added

- `--output json` now also reports `remaining_credits`, `pct_remaining` and `days_until_reset` for the current month, and `--output table` prints a matching `Remaining:` line under the totals.
- New `--remaining` flag prints the number of AI credits left this month as a bare value (no labels or units) and exits. It cannot be combined with `--output`.
- The TUI can now be quit with `Ctrl+C` in addition to `q`.

### Changed

- Release process no longer requires a manual Homebrew formula bump; the tap in `springernature/homebrew-opensource` self-updates via its own workflow when a release is tagged. Removed the manual formula steps from `AGENTS.md`/`CONTRIBUTING.md` and the "Homebrew tap reminder" step from the release workflow.
- Refreshed the bundled pricing snapshot from GitHub's published model pricing.

## [0.3.0] - 2026-07-28

### Added

- Usage summary now shows a "Budget resets in <n> days" line, counting down to the first day of the next month (shows "Budget resets tomorrow" when only one day remains).

### Fixed

- `uv.lock` project version was out of sync with `pyproject.toml` (stuck at `0.1.0`); resynced to `0.2.0`. CI and release workflows now run `uv lock --check` to fail fast if the lockfile drifts again.

### Changed

- Added `scripts/preflight.sh` as the single source of truth for the validation gates (lock check, dependency install, tests, compile check, and — with a version argument — the tag/version and changelog checks). CI and the release workflow now call it instead of duplicating the individual steps.

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
