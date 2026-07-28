#!/usr/bin/env python3
"""
Estimate GitHub Copilot AI credit usage generated via opencode — TUI edition.

opencode logs per-message token counts (input/output/reasoning/cache) locally
in ~/.local/share/opencode/opencode.db for every request, tagged with the
providerID and modelID actually used. This script reads those logs and shows a
real-time cumulative chart of AI credit consumption across three time ranges:
today, this week, and this month.

This is a *local estimate* based only on requests made through opencode on
this machine. It does not include Copilot usage from other IDEs/clients, and
it will not exactly match GitHub's own billing (rounding, promo pricing
windows, price changes, etc).

Usage:
    uv run estimator.py
    uv run estimator.py --budget 30000
    uv run estimator.py --db /path/to/opencode.db
    uv run estimator.py --interval 15
"""

import argparse
import calendar
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from itertools import accumulate

from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Label, Tab, Tabs
from textual_plotext import PlotextPlot

import pricing as pricing_source

# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------

DEFAULT_DB = os.path.expanduser("~/.local/share/opencode/opencode.db")
DEFAULT_BUDGET = 50_000
DEFAULT_INTERVAL = 30  # seconds

# Per 1,000,000 tokens in USD: (input, cached_input, cache_write, output).
# Sourced from GitHub's published Copilot pricing docs (see pricing.py),
# cached on disk and refreshed automatically when stale. Populated here from
# the on-disk cache / bundled snapshot only (no network call at import time);
# `main()` and the TUI's background refresh may update it with live data.
PRICING: dict[str, tuple[float, float, float | None, float]]
PRICING_META: pricing_source.PricingMeta
PRICING, PRICING_META = pricing_source.load_pricing(refresh=False)

# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------

def range_bounds(range_key: str) -> tuple[int, int]:
    """Return (start_ms, end_ms) UTC for the given range key."""
    now = datetime.now(timezone.utc)
    if range_key == "hour":
        start = now - timedelta(hours=1)
    elif range_key == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif range_key == "week":
        start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif range_key == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        raise ValueError(f"Unknown range: {range_key}")
    end = now
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def fetch_rows(db_path: str, start_ms: int, end_ms: int) -> list[dict]:
    """
    Return one dict per assistant message within [start_ms, end_ms).
    Each dict has: ts_ms, model, input, output, reasoning, cache_read, cache_write.
    """
    if not os.path.exists(db_path):
        return []
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(
        """
        SELECT
            time_created AS ts_ms,
            json_extract(data, '$.modelID')            AS model,
            COALESCE(json_extract(data, '$.tokens.input'),       0) AS input,
            COALESCE(json_extract(data, '$.tokens.output'),      0) AS output,
            COALESCE(json_extract(data, '$.tokens.reasoning'),   0) AS reasoning,
            COALESCE(json_extract(data, '$.tokens.cache.read'),  0) AS cache_read,
            COALESCE(json_extract(data, '$.tokens.cache.write'), 0) AS cache_write
        FROM message
        WHERE json_extract(data, '$.role')       = 'assistant'
          AND json_extract(data, '$.providerID') = 'github-copilot'
          AND time_created >= ? AND time_created < ?
        ORDER BY time_created
        """,
        (start_ms, end_ms),
    )
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


def cost_usd(model: str, inp: int, out: int, reasoning: int, cr: int, cw: int) -> float:
    if model not in PRICING:
        return 0.0
    p_in, p_cr, p_cw, p_out = PRICING[model]
    total = (inp / 1_000_000) * p_in
    total += (cr / 1_000_000) * p_cr
    total += (cw / 1_000_000) * (p_cw if p_cw is not None else p_in)
    total += ((out + reasoning) / 1_000_000) * p_out
    return total


def credits(usd: float) -> float:
    return usd * 100  # 1 AI credit = $0.01 USD


def days_until_budget_reset(now: datetime | None = None) -> int:
    """Whole days until the budget resets on the first of next month (local time)."""
    if now is None:
        now = datetime.now().astimezone()
    today = now.date()
    if today.month == 12:
        reset = today.replace(year=today.year + 1, month=1, day=1)
    else:
        reset = today.replace(month=today.month + 1, day=1)
    return (reset - today).days


def build_series(
    rows: list[dict], range_key: str
) -> tuple[list[str], list[float]]:
    """
    Bucket rows into time slots and return (x_labels, cumulative_credits).
    Buckets: per-minute for hour, hourly for today/week, daily for month.
    """
    if not rows:
        return [], []

    local_tz = datetime.now().astimezone().tzinfo
    now = datetime.now(timezone.utc)
    now_local = now.astimezone(local_tz)

    if range_key == "hour":
        # Per-minute buckets over the last 60 minutes
        start = now - timedelta(hours=1)
        start_local = start.astimezone(local_tz)
        n_buckets = 60
        def bucket_fn(ts_ms):
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            return int((dt - start).total_seconds() / 60)
        def label_fn(i):
            dt = start_local + timedelta(minutes=i)
            return dt.strftime("%H:%M") if i % 10 == 0 else ""
    elif range_key == "today":
        # Hourly buckets from midnight to now
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        n_buckets = now.hour + 1
        def bucket_fn(ts_ms):
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            return dt.hour
        utc_offset_hours = int(now_local.utcoffset().total_seconds() // 3600)  # type: ignore[union-attr]
        def label_fn(i):
            # Offset bucket index by local UTC offset so labels show local hours
            local_hour = (i + utc_offset_hours) % 24
            return f"{local_hour:02d}:00"
    elif range_key == "week":
        # Hourly buckets from Monday 00:00 to now
        start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        total_hours = int((now - start).total_seconds() / 3600) + 1
        n_buckets = total_hours
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        def bucket_fn(ts_ms):
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            return int((dt - start).total_seconds() / 3600)
        def label_fn(i):
            # Use local time to determine day boundaries for labels
            dt = (start + timedelta(hours=i)).astimezone(local_tz)
            if dt.hour == 0:
                return day_names[dt.weekday()]
            return ""
    else:  # month
        # Daily buckets from 1st to today
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        n_buckets = now.day
        def bucket_fn(ts_ms):
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            return dt.day - 1
        def label_fn(i):
            return str(i + 1)

    buckets: list[float] = [0.0] * n_buckets
    for r in rows:
        idx = bucket_fn(r["ts_ms"])
        if 0 <= idx < n_buckets:
            buckets[idx] += credits(
                cost_usd(r["model"] or "", r["input"], r["output"],
                         r["reasoning"], r["cache_read"], r["cache_write"])
            )

    cumulative = list(accumulate(buckets))
    labels = [label_fn(i) for i in range(n_buckets)]
    return labels, cumulative


def summarize_by_model(rows: list[dict]) -> list[tuple[str, dict]]:
    """Aggregate rows by model, compute cost, return sorted list."""
    by_model: dict[str, dict] = {}
    for r in rows:
        model = r["model"] or "unknown"
        m = by_model.setdefault(
            model,
            {"requests": 0, "input": 0, "output": 0,
             "cache_read": 0, "cache_write": 0, "usd": 0.0, "priced": True}
        )
        m["requests"] += 1
        m["input"] += r["input"]
        m["output"] += r["output"] + r["reasoning"]
        m["cache_read"] += r["cache_read"]
        m["cache_write"] += r["cache_write"]
        usd = cost_usd(model, r["input"], r["output"], r["reasoning"],
                       r["cache_read"], r["cache_write"])
        m["usd"] += usd
        if model not in PRICING:
            m["priced"] = False

    return sorted(by_model.items(), key=lambda kv: -kv[1]["usd"])


# ---------------------------------------------------------------------------
# TUI
# ---------------------------------------------------------------------------

RANGES = [
    ("hour",  "Last hour",  "Hour"),
    ("today", "Today",      "Today"),
    ("week",  "This week",  "Week"),
    ("month", "This month", "Month"),
]

# Terminal size thresholds below which the app switches to compact mode.
COMPACT_WIDTH = 80
COMPACT_HEIGHT = 30

# Below this width, the status bar drops the last-updated timestamp.
STATUS_TIME_MIN_WIDTH = 70


class CreditChart(PlotextPlot):
    """Cumulative credit chart for a given time range."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._labels: list[str] = []
        self._values: list[float] = []
        self._range_label: str = ""
        self._total: float = 0.0
        self._budget: float = DEFAULT_BUDGET

    def update_data(
        self,
        labels: list[str],
        values: list[float],
        range_label: str,
        budget: float,
    ) -> None:
        self._labels = labels
        self._values = values
        self._range_label = range_label
        self._budget = budget
        self._total = values[-1] if values else 0.0
        self._draw()
        self.refresh()

    def on_mount(self) -> None:
        self._draw()

    def _draw(self) -> None:
        plt = self.plt
        plt.clear_figure()
        if not self._values:
            plt.title("No data")
            return

        xs = list(range(len(self._values)))
        plt.plot(xs, self._values, color="cyan", label="Credits used")

        pct = (self._total / self._budget * 100) if self._budget else 0
        plt.title(
            f"{self._range_label}  —  {self._total:,.1f} of {self._budget:,.0f} AI credits used ({pct:.1f}%)"
        )

        # Show only a sparse set of x-tick labels to avoid overlap
        tick_step = max(1, len(self._labels) // 12)
        tick_xs = list(range(0, len(self._labels), tick_step))
        tick_labels = [self._labels[i] for i in tick_xs]
        plt.xticks(tick_xs, tick_labels)


class ModelTable(DataTable):
    """Per-model breakdown table.

    Supports two column schemas: the full nine-column schema used in regular
    mode, and a compact three-column schema (model, requests, % of budget)
    used when the terminal is small.
    """

    FULL_COLUMNS = (
        "Model", "Reqs", "Input tok", "Output tok", "Cache R", "Cache W",
        "Credits", "% of used credits", "% of budget",
    )
    COMPACT_COLUMNS = ("Model", "Reqs", "% budget")
    COMPACT_COLUMN_WIDTHS = (15, 7, 8)

    MAX_MODEL_NAME_LEN = 24

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._compact = False
        self._model_rows: list[tuple[str, dict]] = []
        self._total_credits: float = 0.0
        self._budget: float = DEFAULT_BUDGET

    def on_mount(self) -> None:
        self._rebuild_columns()

    def _rebuild_columns(self) -> None:
        self.clear(columns=True)
        columns = self.COMPACT_COLUMNS if self._compact else self.FULL_COLUMNS
        widths = self.COMPACT_COLUMN_WIDTHS if self._compact else (None,) * len(columns)
        for col, width in zip(columns, widths):
            self.add_column(col, key=col, width=width)

    def set_compact(self, compact: bool) -> None:
        """Switch column schema. No-op if already in the requested mode."""
        if compact == self._compact:
            return
        self._compact = compact
        self._rebuild_columns()
        self._render_rows()

    def update_data(
        self,
        model_rows: list[tuple[str, dict]],
        total_credits: float,
        budget: float,
    ) -> None:
        self._model_rows = model_rows
        self._total_credits = total_credits
        self._budget = budget
        self._render_rows()

    @classmethod
    def _truncate(cls, name: str) -> str:
        if len(name) <= cls.MAX_MODEL_NAME_LEN:
            return name
        return name[: cls.MAX_MODEL_NAME_LEN - 1] + "…"

    def _render_rows(self) -> None:
        self.clear()
        for model, m in self._model_rows:
            cred_val = credits(m["usd"])
            cred = f"{cred_val:,.1f}" if m["priced"] else "?"
            pct_used = (
                f"{cred_val / self._total_credits * 100:.1f}%"
                if (m["priced"] and self._total_credits) else "?"
            )
            pct_budget = (
                f"{cred_val / self._budget * 100:.2f}%"
                if (m["priced"] and self._budget) else "?"
            )
            name = self._truncate(model)
            if self._compact:
                self.add_row(name, f"{m['requests']:,}", pct_budget)
            else:
                self.add_row(
                    name,
                    f"{m['requests']:,}",
                    f"{m['input']:,}",
                    f"{m['output']:,}",
                    f"{m['cache_read']:,}",
                    f"{m['cache_write']:,}",
                    cred,
                    pct_used,
                    pct_budget,
                )


class UsageSummary(Label):
    """Always-visible summary of credits used, total budget, and percentage.

    This is the highest-priority metric and must stay visible regardless of
    terminal size or compact/regular mode.
    """

    def update_summary(self, total: float, budget: float) -> None:
        pct = (total / budget * 100) if budget else 0.0
        days = days_until_budget_reset()
        reset_line = (
            "Budget resets tomorrow"
            if days == 1
            else f"Budget resets in {days} days"
        )
        self.update(
            f"{total:,.1f} / {budget:,.0f} credits used  ({pct:.1f}% of budget)\n"
            f"{reset_line}"
        )


class StatusBar(Label):
    pass


class CreditEstimatorApp(App):
    """opencode Copilot credit estimator TUI."""

    CSS = """
    Tabs { dock: top; }
    UsageSummary { width: 100%; height: auto; padding: 0 1; text-style: bold; }
    #main { height: 1fr; }
    CreditChart { height: 65%; border: round $primary; }
    ModelTable { height: 1fr; border: round $surface-lighten-2; }
    StatusBar { dock: bottom; height: 1; color: $text-muted; padding: 0 1; }
    #main.compact CreditChart { display: none; }
    #main.compact ModelTable { height: 1fr; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
        Binding("r", "refresh", "Refresh now"),
        Binding("1", "switch_tab('hour')", "Last hour"),
        Binding("2", "switch_tab('today')", "Today"),
        Binding("3", "switch_tab('week')", "Week"),
        Binding("4", "switch_tab('month')", "Month"),
    ]

    active_range: reactive[str] = reactive("month")
    compact: reactive[bool] = reactive(False)

    def __init__(self, db: str, budget: float, interval: int,
                 compact_width: int = COMPACT_WIDTH, compact_height: int = COMPACT_HEIGHT,
                 offline: bool = False):
        super().__init__()
        self.db = db
        self.budget = budget
        self.interval = interval
        self.compact_width = compact_width
        self.compact_height = compact_height
        self.offline = offline

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Tabs(
            *[Tab(label, id=key) for key, label, _ in RANGES],
            active="month",
            id="range-tabs",
        )
        yield UsageSummary("", id="summary")
        with Vertical(id="main"):
            yield CreditChart(id="chart")
            yield ModelTable(id="table", zebra_stripes=True, cursor_type="none")
        yield StatusBar("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self._update_compact(self.size.width, self.size.height)
        self.refresh_data()
        self.set_interval(self.interval, self.refresh_data)
        if not self.offline:
            self.run_worker(self._refresh_pricing, thread=True, exclusive=True)

    def _refresh_pricing(self) -> None:
        """Refresh the GitHub Copilot pricing table in a background thread.

        Only does anything if the cached/bundled snapshot is stale; on any
        failure (offline, parsing error) the existing table is left as-is.
        """
        global PRICING, PRICING_META
        table, meta = pricing_source.load_pricing(refresh=True)
        if table:
            PRICING, PRICING_META = table, meta
            self.call_from_thread(self.refresh_data)

    def on_resize(self, event: events.Resize) -> None:
        self._update_compact(event.size.width, event.size.height)
        self._update_status(event.size.width)

    def _update_compact(self, width: int, height: int) -> None:
        self.compact = width < self.compact_width or height < self.compact_height

    def watch_compact(self, compact: bool) -> None:
        main = self.query_one("#main", Vertical)
        main.set_class(compact, "compact")

        table = self.query_one("#table", ModelTable)
        table.set_compact(compact)

        self._update_tab_labels(compact)

    def _update_tab_labels(self, compact: bool) -> None:
        try:
            tabs = self.query_one("#range-tabs", Tabs)
        except Exception:
            return
        for key, full_label, short_label in RANGES:
            try:
                tab = tabs.query_one(f"#{key}", Tab)
            except Exception:
                continue
            tab.label = short_label if compact else full_label

    @on(Tabs.TabActivated, "#range-tabs")
    def tab_activated(self, event: Tabs.TabActivated) -> None:
        if event.tab:
            self.active_range = event.tab.id  # type: ignore[assignment]
            self.refresh_data()

    def action_switch_tab(self, key: str) -> None:
        self.query_one("#range-tabs", Tabs).active = key

    def action_refresh(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        range_key = self.active_range
        range_label = {key: label for key, label, _ in RANGES}[range_key]

        start_ms, end_ms = range_bounds(range_key)
        rows = fetch_rows(self.db, start_ms, end_ms)

        labels, cumulative = build_series(rows, range_key)
        model_rows = summarize_by_model(rows)
        total = cumulative[-1] if cumulative else 0.0

        chart = self.query_one("#chart", CreditChart)
        chart.update_data(labels, cumulative, range_label, self.budget)

        table = self.query_one("#table", ModelTable)
        table.update_data(model_rows, total, self.budget)

        summary = self.query_one("#summary", UsageSummary)
        summary.update_summary(total, self.budget)

        self._update_status()

    def _update_status(self, width: int | None = None) -> None:
        now_str = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        status = self.query_one("#status", StatusBar)
        parts = []
        if (self.size.width if width is None else width) >= STATUS_TIME_MIN_WIDTH:
            parts.append(f"Last updated: {now_str}")
        parts.append(f"refreshes every {self.interval}s")
        parts.append("q to quit")
        status.update("  |  ".join(parts))


# ---------------------------------------------------------------------------
# Non-interactive output modes
# ---------------------------------------------------------------------------

def output_json(model_rows: list[tuple[str, dict]], total_credits: float, budget: float) -> None:
    import json as _json
    rows = []
    for model, m in model_rows:
        cred_val = credits(m["usd"])
        rows.append({
            "model": model,
            "requests": m["requests"],
            "input_tokens": m["input"],
            "output_tokens": m["output"],
            "cache_read_tokens": m["cache_read"],
            "cache_write_tokens": m["cache_write"],
            "credits": round(cred_val, 4) if m["priced"] else None,
            "pct_of_used": round(cred_val / total_credits * 100, 2) if (m["priced"] and total_credits) else None,
            "pct_of_budget": round(cred_val / budget * 100, 4) if (m["priced"] and budget) else None,
        })
    print(_json.dumps({
        "period": "month",
        "budget": budget,
        "total_credits": round(total_credits, 4),
        "pct_of_budget": round(total_credits / budget * 100, 2) if budget else None,
        "models": rows,
        "pricing_source": PRICING_META.get("source"),
        "pricing_retrieved_at": PRICING_META.get("retrieved_at"),
    }, indent=2))


def output_table(model_rows: list[tuple[str, dict]], total_credits: float, budget: float) -> None:
    pct_budget_total = total_credits / budget * 100 if budget else 0
    header = (
        f"{'Model':<26} {'Reqs':>6} {'Input':>12} {'Output':>10} "
        f"{'Cache R':>10} {'Cache W':>10} {'Credits':>10} {'% used':>8} {'% budget':>10}"
    )
    print(f"\nOpencode -> GitHub Copilot AI credit estimate (this month)")
    print("=" * len(header))
    print(header)
    print("-" * len(header))
    for model, m in model_rows:
        cred_val = credits(m["usd"])
        cred = f"{cred_val:,.1f}" if m["priced"] else "?"
        pct_used = f"{cred_val / total_credits * 100:.1f}%" if (m["priced"] and total_credits) else "?"
        pct_bud = f"{cred_val / budget * 100:.2f}%" if (m["priced"] and budget) else "?"
        print(
            f"{model:<26} {m['requests']:>6,} {m['input']:>12,} {m['output']:>10,} "
            f"{m['cache_read']:>10,} {m['cache_write']:>10,} {cred:>10} {pct_used:>8} {pct_bud:>10}"
        )
    print("-" * len(header))
    print(f"{'TOTAL':<26} {'':>6} {'':>12} {'':>10} {'':>10} {'':>10} "
          f"{total_credits:>10,.1f} {'100.0%':>8} {pct_budget_total:>9.2f}%")
    print(f"\nBudget: {budget:,.0f} AI credits")
    retrieved_at = PRICING_META.get("retrieved_at")
    if retrieved_at:
        print(f"Pricing last refreshed: {retrieved_at}")
    print("Local estimate from opencode logs only — https://github.com/settings/copilot/features for actuals.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--budget", type=float, default=DEFAULT_BUDGET,
                    help=f"Monthly AI credit budget (default {DEFAULT_BUDGET:,})")
    ap.add_argument("--db", default=DEFAULT_DB,
                    help="Path to opencode's SQLite database")
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                    help=f"Auto-refresh interval in seconds (default {DEFAULT_INTERVAL})")
    ap.add_argument("--compact-width", type=int, default=COMPACT_WIDTH,
                    help=f"Terminal width threshold below which compact mode activates (default {COMPACT_WIDTH})")
    ap.add_argument("--compact-height", type=int, default=COMPACT_HEIGHT,
                    help=f"Terminal height threshold below which compact mode activates (default {COMPACT_HEIGHT})")
    ap.add_argument("--output", choices=["json", "table"], default=None,
                    help="Print monthly data in the given format and exit (no TUI)")
    ap.add_argument("--offline", action="store_true",
                    help="Never fetch pricing over the network; use cached/bundled pricing only")
    args = ap.parse_args()

    global PRICING, PRICING_META
    if not args.offline:
        PRICING, PRICING_META = pricing_source.load_pricing(refresh=True)

    if args.output:
        start_ms, end_ms = range_bounds("month")
        rows = fetch_rows(args.db, start_ms, end_ms)
        model_rows = summarize_by_model(rows)
        total = sum(credits(m["usd"]) for _, m in model_rows if m["priced"])
        if args.output == "json":
            output_json(model_rows, total, args.budget)
        else:
            output_table(model_rows, total, args.budget)
        return

    app = CreditEstimatorApp(db=args.db, budget=args.budget, interval=args.interval,
                             compact_width=args.compact_width, compact_height=args.compact_height,
                             offline=args.offline)
    app.run()


if __name__ == "__main__":
    main()
