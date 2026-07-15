#!/usr/bin/env python3
"""
Estimate monthly GitHub Copilot AI credit usage generated via opencode.

opencode logs per-message token counts (input/output/reasoning/cache) locally
in ~/.local/share/opencode/opencode.db for every request, tagged with the
providerID and modelID actually used. This script sums those tokens for the
current calendar month (or a month you specify), converts them to USD using
GitHub's published per-model AI credit pricing, and reports the result as a
percentage of a monthly AI credit budget (1 AI credit = $0.01 USD).

This is a *local estimate* based only on requests made through opencode on
this machine. It does not include Copilot usage from other IDEs/clients, and
it will not exactly match GitHub's own billing (rounding, promo pricing
windows, price changes, etc). 

Usage:
    python3 opencode_copilot_ai_credits_estimation.py                  # this calendar month, default budget 50000
    python3 opencode_copilot_ai_credits_estimation.py --budget 30000
    python3 opencode_copilot_ai_credits_estimation.py --year 2026 --month 6
    python3 opencode_copilot_ai_credits_estimation.py --db /path/to/opencode.db
    python3 opencode_copilot_ai_credits_estimation.py --watch           # refresh every N seconds
"""

import argparse
import calendar
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

DEFAULT_DB = os.path.expanduser("~/.local/share/opencode/opencode.db")

# Pricing per 1,000,000 tokens, in USD. Source: GitHub Copilot docs,
# "Models and pricing for GitHub Copilot" (checked 2026-07-15).
# Keys must match the modelID strings opencode records for the
# github-copilot provider.
PRICING = {
    # model:            (input,  cached_input, cache_write, output)
    "claude-haiku-4.5":   (1.00, 0.10, 1.25,  5.00),
    "claude-sonnet-4":    (3.00, 0.30, 3.75, 15.00),
    "claude-sonnet-4.5":  (3.00, 0.30, 3.75, 15.00),
    "claude-sonnet-4.6":  (3.00, 0.30, 3.75, 15.00),
    "claude-opus-4.5":    (5.00, 0.50, 6.25, 25.00),
    "claude-opus-4.6":    (5.00, 0.50, 6.25, 25.00),
    "claude-opus-4.7":    (5.00, 0.50, 6.25, 25.00),
    "claude-opus-4.8":    (5.00, 0.50, 6.25, 25.00),
    "claude-opus-4.8-fast": (10.00, 1.00, 12.50, 50.00),
    "claude-sonnet-5":    (2.00, 0.20, 2.50, 10.00),  # promo pricing thru 2026-08-31
    "kimi-k2.7-code":     (0.95, 0.19, None, 4.00),   # no cache-write rate published
    "gemini-2.5-pro":     (1.25, 0.125, None, 10.00),
    "gemini-3.1-pro-preview": (2.00, 0.20, None, 12.00),  # <=200K tier
    "gpt-5.3-codex":      (1.75, 0.175, None, 14.00),
}

# Models seen locally that aren't in the current published pricing table
# (older/retired SKUs). Cost for these is left as "unknown".
UNPRICED_FALLBACK = {"gpt-5.2", "gpt-5.2-codex", "gpt-4.1"}


def month_bounds(year, month):
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    last_day = calendar.monthrange(year, month)[1]
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def fetch_usage(db_path, start_ms, end_ms):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(
        """
        SELECT
            json_extract(data, '$.modelID') AS model,
            json_extract(data, '$.providerID') AS provider,
            json_extract(data, '$.tokens.input') AS input,
            json_extract(data, '$.tokens.output') AS output,
            json_extract(data, '$.tokens.reasoning') AS reasoning,
            json_extract(data, '$.tokens.cache.read') AS cache_read,
            json_extract(data, '$.tokens.cache.write') AS cache_write
        FROM message
        WHERE json_extract(data, '$.role') = 'assistant'
          AND json_extract(data, '$.providerID') = 'github-copilot'
          AND time_created >= ? AND time_created < ?
        """,
        (start_ms, end_ms),
    )
    rows = cur.fetchall()
    con.close()
    return rows


def summarize(rows):
    by_model = {}
    for r in rows:
        model = r["model"] or "unknown"
        m = by_model.setdefault(
            model, {"requests": 0, "input": 0, "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0}
        )
        m["requests"] += 1
        m["input"] += r["input"] or 0
        m["output"] += (r["output"] or 0)
        m["reasoning"] += r["reasoning"] or 0
        m["cache_read"] += r["cache_read"] or 0
        m["cache_write"] += r["cache_write"] or 0
    return by_model


def cost_for_model(model, m):
    """Returns (usd_cost, priced: bool)."""
    if model not in PRICING:
        return 0.0, False
    inp, cached_in, cache_write, outp = PRICING[model]
    total = 0.0
    total += (m["input"] / 1_000_000) * inp
    total += (m["cache_read"] / 1_000_000) * cached_in
    if cache_write is not None:
        total += (m["cache_write"] / 1_000_000) * cache_write
    else:
        # fall back to treating cache writes like fresh input if no
        # published cache-write rate exists for this model
        total += (m["cache_write"] / 1_000_000) * inp
    # reasoning tokens billed at output rate
    total += ((m["output"] + m["reasoning"]) / 1_000_000) * outp
    return total, True


def format_credits(usd):
    return usd * 100  # 1 AI credit = $0.01


def render(by_model, budget, year, month):
    print(f"\nOpencode -> GitHub Copilot AI credit estimate ({year}-{month:02d})")
    print("=" * 72)
    total_usd = 0.0
    unpriced_models = []
    header = f"{'model':<26}{'reqs':>6}{'in':>12}{'out':>10}{'cache_r':>13}{'cache_w':>11}{'credits':>10}"
    print(header)
    print("-" * len(header))
    for model in sorted(by_model, key=lambda k: -sum(by_model[k][f] for f in ('input', 'output'))):
        m = by_model[model]
        usd, priced = cost_for_model(model, m)
        if not priced:
            unpriced_models.append(model)
        credits = format_credits(usd)
        total_usd += usd
        credit_str = f"{credits:,.1f}" if priced else "?"
        print(
            f"{model:<26}{m['requests']:>6}{m['input']:>12,}{m['output']:>10,}"
            f"{m['cache_read']:>13,}{m['cache_write']:>11,}{credit_str:>10}"
        )

    total_credits = format_credits(total_usd)
    pct = (total_credits / budget * 100) if budget else 0

    print("-" * len(header))
    print(f"Estimated AI credits used : {total_credits:,.1f}  (${total_usd:,.2f})")
    print(f"Budget                    : {budget:,}")
    print(f"Percent of budget used    : {pct:.1f}%")
    if unpriced_models:
        print(f"\nNote: no published pricing for: {', '.join(unpriced_models)} "
              f"(usage from these models is NOT included in the estimate above)")
    print("\nThis is a local estimate from opencode's own request logs only.")
    print("It won't include Copilot usage from other clients/IDEs, and pricing")
    print("may drift from GitHub's actual invoiced amount.")
    print("https://github.com/settings/copilot/features is always the source")
    print("of truth")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=float, default=50000, help="Monthly AI credit budget (default 50000)")
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--month", type=int, default=None)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--watch", action="store_true", help="Refresh continuously")
    ap.add_argument("--interval", type=int, default=30)
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    year = args.year or now.year
    month = args.month or now.month

    def run_once():
        start_ms, end_ms = month_bounds(year, month)
        rows = fetch_usage(args.db, start_ms, end_ms)
        by_model = summarize(rows)
        render(by_model, args.budget, year, month)

    if args.watch:
        try:
            while True:
                sys.stdout.write("\033[H\033[J")
                run_once()
                print(f"\n(updated {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}, refreshing every {args.interval}s, Ctrl+C to stop)")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        run_once()


if __name__ == "__main__":
    main()
