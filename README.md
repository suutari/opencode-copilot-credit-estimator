# opencode Copilot Credit Estimator

A local CLI tool for estimating your monthly [GitHub Copilot](https://github.com/features/copilot) AI credit consumption from [opencode](https://opencode.ai) sessions.

## How it works

opencode logs every LLM request to a local SQLite database at `~/.local/share/opencode/opencode.db`, including token counts (input, output, reasoning, cache read/write) and the model used. This script reads those logs, applies GitHub's published per-model token pricing, and reports your estimated AI credit usage for the month.

> **Note:** This is a local estimate based only on requests made through opencode on this machine. It does not include Copilot usage from other IDEs or clients, and it may not exactly match GitHub's actual billing (rounding, promo pricing windows, price changes, etc). See your [GitHub Copilot usage dashboard](https://github.com/settings/copilot/features) for the authoritative figure.

## Requirements

- Python 3 (no third-party dependencies)
- opencode with the `github-copilot` provider

## Usage

```sh
# Current month, default budget of 50,000 AI credits
python3 estimator.py

# Set a custom monthly budget
python3 estimator.py --budget 30000

# Query a specific month
python3 estimator.py --year 2026 --month 6

# Point to a non-default database location
python3 estimator.py --db /path/to/opencode.db

# Watch mode: refresh every 30 seconds
python3 estimator.py --watch

# Watch mode with a custom interval
python3 estimator.py --watch --interval 60
```

## Options

| Flag | Default | Description |
|---|---|---|
| `--budget` | `50000` | Monthly AI credit budget to compare against |
| `--year` | current year | Year to report on |
| `--month` | current month | Month to report on |
| `--db` | `~/.local/share/opencode/opencode.db` | Path to the opencode SQLite database |
| `--watch` | off | Continuously refresh the output |
| `--interval` | `30` | Refresh interval in seconds (requires `--watch`) |

## Output

The script prints a table of per-model usage broken down by requests, token counts (input, output, cache read/write), and estimated AI credits. Totals and percentage of budget consumed are shown at the bottom.

Models with no published pricing are flagged with `?` and excluded from the cost total.

## Pricing

Prices are sourced from [GitHub Copilot model documentation](https://docs.github.com/en/copilot/using-github-copilot/ai-models/choosing-an-ai-model-for-copilot) and hardcoded in `estimator.py`. Update the `PRICING` dict in the script if prices change or new models are added.

1 AI credit = $0.01 USD.
