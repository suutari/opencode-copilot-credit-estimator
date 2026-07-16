# opencode Copilot Credit Estimator

A terminal UI for monitoring your [GitHub Copilot](https://github.com/features/copilot) AI credit consumption in real time, sourced from [opencode](https://opencode.ai) session logs.

## How it works

opencode logs every LLM request to a local SQLite database at `~/.local/share/opencode/opencode.db`, including token counts (input, output, reasoning, cache read/write) and the model used. This tool reads those logs, applies GitHub's published per-model token pricing, and displays a cumulative line chart of AI credit usage — updated automatically on a configurable interval.

> **Note:** This is a local estimate based only on requests made through opencode on this machine. It does not include Copilot usage from other IDEs or clients, and it may not exactly match GitHub's actual billing (rounding, promo pricing windows, price changes, etc). See your [GitHub Copilot usage dashboard](https://github.com/settings/copilot/features) for the authoritative figure.

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)

Dependencies (`textual`, `textual-plotext`) are managed by uv and installed automatically on first run.

## Usage

### TUI (default)

```sh
# Launch the interactive TUI (defaults: budget 50,000 credits, refresh every 30s)
uv run estimator.py

# Set a custom monthly budget
uv run estimator.py --budget 30000

# Point to a non-default database location
uv run estimator.py --db /path/to/opencode.db

# Change the auto-refresh interval
uv run estimator.py --interval 15

# Override the compact mode breakpoints
uv run estimator.py --compact-width 100 --compact-height 40
```

### Non-interactive output

Use `--output` to print this month's data and exit without launching the TUI:

```sh
# Human-readable table
uv run estimator.py --output table

# JSON (useful for scripting/piping)
uv run estimator.py --output json
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

Prices are sourced from [GitHub Copilot model documentation](https://docs.github.com/en/copilot/using-github-copilot/ai-models/choosing-an-ai-model-for-copilot) and hardcoded in `estimator.py`. Update the `PRICING` dict in the script if prices change or new models are added.

1 AI credit = $0.01 USD.
