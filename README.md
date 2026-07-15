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
- A **cumulative line chart** of AI credits consumed over time. The Y axis scales automatically as usage grows.
- A **per-model breakdown table** with requests, token counts (input, output, cache read/write), estimated credits, percentage of credits used, and percentage of monthly budget consumed.
- A **status bar** showing last-updated time, total credits used, and percentage of budget.

### Key bindings

| Key | Action |
|---|---|
| `1` / `2` / `3` / `4` | Switch tab |
| `r` | Refresh now |
| `q` | Quit |

## Pricing

Prices are sourced from [GitHub Copilot model documentation](https://docs.github.com/en/copilot/using-github-copilot/ai-models/choosing-an-ai-model-for-copilot) and hardcoded in `estimator.py`. Update the `PRICING` dict in the script if prices change or new models are added.

1 AI credit = $0.01 USD.
