# OpenCode Copilot Credit Estimator (Occe)

Occe is a terminal UI for monitoring your [GitHub Copilot](https://github.com/features/copilot) AI credit consumption in real time, sourced from [opencode](https://opencode.ai) session logs.

## Installation

### Homebrew (macOS/Linux)

```sh
brew tap springernature/opensource
brew install springernature/opensource/occe
```

### From source

<details>
<summary>Clone this repository and run it directly with <code>uv</code></summary>

Requirements:

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)

Dependencies (`textual`, `textual-plotext`) are managed by uv and installed automatically on first run.

Clone this repository and run it directly with `uv` (see [Usage](#usage) below) — no separate install step is required.

</details>

## How it works

opencode logs every LLM request to a local SQLite database at `~/.local/share/opencode/opencode.db`, including token counts (input, output, reasoning, cache read/write) and the model used. This tool reads those logs, applies GitHub's published per-model token pricing, and displays a cumulative line chart of AI credit usage — updated automatically on a configurable interval.

> **Note:** This is a local estimate based only on requests made through opencode on this machine. It does not include Copilot usage from other IDEs or clients, and it may not exactly match GitHub's actual billing (rounding, promo pricing windows, price changes, etc). See your [GitHub Copilot usage dashboard](https://github.com/settings/copilot/features) for the authoritative figure.

## Supported platforms

- macOS and Linux (anywhere `opencode` writes its SQLite log to `~/.local/share/opencode/opencode.db`).
- Windows is not currently tested.
- Requires a terminal emulator supported by [Textual](https://textual.textualize.io/), e.g. iTerm2 or Alacritty.

## Usage

### TUI (default)

```sh
# Launch the interactive TUI (defaults: budget 50,000 credits, refresh every 30s)
occe

# Set a custom monthly budget
occe --budget 30000

# Point to a non-default database location
occe --db /path/to/opencode.db

# Change the auto-refresh interval
occe --interval 15

# Override the compact mode breakpoints
occe --compact-width 100 --compact-height 40
```

### Non-interactive output

Use `--output` to print this month's data and exit without launching the TUI:

```sh
# Human-readable table
occe --output table

# JSON (useful for scripting/piping)
occe --output json
```

## Options

| Flag | Default | Description |
|---|---|---|
| `--budget` | `50000` | Monthly AI credit budget to compare against |
| `--db` | `~/.local/share/opencode/opencode.db` | Path to the opencode SQLite database |
| `--interval` | `30` | Auto-refresh interval in seconds (TUI only) |
| `--compact-width` | `80` | Terminal width (columns) below which compact mode activates |
| `--compact-height` | `30` | Terminal height (rows) below which compact mode activates |
| `--output` | — | Print monthly data as `table` or `json` and exit |
| `--offline` | off | Skip network pricing refresh; use cached/bundled pricing only |

## TUI interface

The app opens on the **This month** tab by default. Tabs are selectable with `1`–`4` or by clicking:

| Key | Tab | Time range | X-axis granularity |
|---|---|---|---|
| `1` | Last hour | Rolling 60 minutes | Per minute |
| `2` | Today | Midnight → now | Hourly |
| `3` | This week | Monday → now | Hourly (day labels at midnight) |
| `4` | This month | 1st → today | Daily |

Each tab shows:
- A **usage summary** — credits used, total budget, and percentage used — docked below the tabs. This is the highest-priority metric and stays visible at every terminal size.
- A **cumulative line chart** of AI credits consumed over time. The Y axis scales automatically as usage grows.
- A **per-model breakdown table** with requests, token counts (input, output, cache read/write), estimated credits, percentage of credits used, and percentage of monthly budget consumed.
- A **status bar** showing last-updated time, refresh interval, and quit hint.

### Compact mode

When the terminal is small — narrower than about 80 columns or shorter than about 30 rows — the layout switches to a compact mode optimized for narrow panes (e.g. a sidebar terminal like Herdr). The thresholds can be adjusted with `--compact-width` and `--compact-height`:

- The credit chart is hidden so it doesn't consume space.
- The model table moves directly below the usage summary and expands to fill the remaining height.
- The model table is limited to three columns: `Model`, `Reqs`, and `% budget`.
- Tab labels shorten to `Hour`, `Today`, `Week`, and `Month`.
- Long model names are truncated (never horizontally scrolled).
- The last-updated timestamp is dropped from the status bar if the terminal is very narrow; refresh and quit hints always remain.

The usage summary (credits used, budget, percentage) is always shown, in both compact and regular mode. Resizing the terminal across the breakpoint switches the layout automatically in both directions — no restart required.

In regular mode, the full chart and complete nine-column model table (token counts, cache read/write, credits, `% used`, `% budget`) are shown, with the usage summary visible above the chart.

### Key bindings

| Key | Action |
|---|---|
| `1` / `2` / `3` / `4` | Switch tab |
| `r` | Refresh now |
| `q` | Quit |

## Pricing

Prices are parsed automatically from GitHub's own published pricing page (`https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing.md`) by `pricing.py`, rather than hardcoded.

- On startup, pricing is loaded from a local cache (`~/.cache/opencode-copilot-credit-estimator/github-copilot-pricing.json`), falling back to a bundled snapshot (`resources/github-copilot-pricing-snapshot.json`) committed to the repo if there's no cache yet.
- If the resolved pricing is missing or more than 24 hours old, a refresh is attempted automatically: synchronously before `--output` runs, or in the background (without blocking the UI) for the TUI. If the network is unavailable, the existing pricing is kept as-is — the tool always works offline.
- Pass `--offline` to skip network refreshes entirely and only use cached/bundled pricing.
- Maintainers can regenerate the bundled snapshot with `uv run pricing.py --update-snapshot`.

Model names in GitHub's docs don't always match opencode's `modelID` exactly (e.g. promo/preview qualifiers). Known mismatches are patched in `pricing.py`'s `ALIAS_OVERRIDES`; if a model you use shows up as unpriced (`?`), it may need an entry there.

1 AI credit = $0.01 USD.

## License

Released under the [MIT License](LICENSE).

## Maintenance & support

This project is maintained by Springer Nature on a best-effort basis. Bug reports and pull requests are welcome via [GitHub Issues](https://github.com/springernature/opencode-copilot-credit-estimator/issues). There is no guaranteed response time or SLA.

