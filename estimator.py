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
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
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

def parse_month(value: str) -> date:
    """Parse a YYYY-MM month selector into its first day."""
    if not re.fullmatch(r"\d{4}-\d{2}", value):
        raise argparse.ArgumentTypeError("month must use YYYY-MM format")
    try:
        parsed = datetime.strptime(value, "%Y-%m").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("month must use YYYY-MM format") from exc
    return parsed.replace(day=1)


def month_bounds(month: date | None = None) -> tuple[datetime, datetime]:
    """Return UTC start and exclusive end datetimes for a calendar month."""
    if month is None:
        now = datetime.now(timezone.utc)
        month = now.date().replace(day=1)
    start = datetime(month.year, month.month, 1, tzinfo=timezone.utc)
    if month.month == 12:
        end = datetime(month.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(month.year, month.month + 1, 1, tzinfo=timezone.utc)
    return start, end


def month_label(month: date | None = None) -> str:
    """Return the selected month as YYYY-MM for output labels."""
    if month is None:
        month = datetime.now(timezone.utc).date()
    return month.strftime("%Y-%m")


def is_current_month(month: date | None) -> bool:
    now = datetime.now(timezone.utc).date()
    return month is None or (month.year == now.year and month.month == now.month)


def range_bounds(range_key: str, month: date | None = None) -> tuple[int, int]:
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
        start, end = month_bounds(month)
        if end > now:
            end = now
        return int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    else:
        raise ValueError(f"Unknown range: {range_key}")
    end = now
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def fetch_rows(db_path: str, start_ms: int, end_ms: int) -> list[dict]:
    """
    Return one dict per assistant message within [start_ms, end_ms).
    Each dict has: ts_ms, session_id, session_title, project_name, model, input,
    output, reasoning, cache_read, cache_write.
    """
    if not os.path.exists(db_path):
        return []
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(
        """
        SELECT
            m.time_created AS ts_ms,
            m.session_id AS session_id,
            COALESCE(s.title, '') AS session_title,
            COALESCE(p.name, p.worktree, '') AS project_name,
            json_extract(m.data, '$.modelID')            AS model,
            COALESCE(json_extract(m.data, '$.tokens.input'),       0) AS input,
            COALESCE(json_extract(m.data, '$.tokens.output'),      0) AS output,
            COALESCE(json_extract(m.data, '$.tokens.reasoning'),   0) AS reasoning,
            COALESCE(json_extract(m.data, '$.tokens.cache.read'),  0) AS cache_read,
            COALESCE(json_extract(m.data, '$.tokens.cache.write'), 0) AS cache_write
        FROM message AS m
        LEFT JOIN session AS s ON s.id = m.session_id
        LEFT JOIN project AS p ON p.id = s.project_id
        WHERE json_extract(m.data, '$.role')       = 'assistant'
          AND json_extract(m.data, '$.providerID') = 'github-copilot'
          AND m.time_created >= ? AND m.time_created < ?
        ORDER BY m.time_created
        """,
        (start_ms, end_ms),
    )
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


def filter_session_rows(rows: list[dict], session_id: str | None) -> list[dict]:
    """Limit rows to one OpenCode session when a session was selected."""
    if session_id is None:
        return rows
    return [row for row in rows if row.get("session_id") == session_id]


def fetch_prompts(db_path: str, session_id: str, start_ms: int, end_ms: int) -> list[dict]:
    """Return user prompts and their metadata for one session and time range."""
    if not os.path.exists(db_path):
        return []
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(
        """
        SELECT
            m.id AS message_id,
            m.time_created AS ts_ms,
            m.session_id AS session_id,
            COALESCE(s.title, '') AS session_title,
            COALESCE(p.name, p.worktree, '') AS project_name,
            COALESCE(
                NULLIF(GROUP_CONCAT(json_extract(pt.data, '$.text'), char(10)), ''),
                json_extract(m.data, '$.content'),
                ''
            ) AS prompt
        FROM message AS m
        LEFT JOIN session AS s ON s.id = m.session_id
        LEFT JOIN project AS p ON p.id = s.project_id
        LEFT JOIN part AS pt ON pt.message_id = m.id
            AND json_extract(pt.data, '$.type') = 'text'
        WHERE m.session_id = ?
          AND json_extract(m.data, '$.role') = 'user'
          AND m.time_created >= ? AND m.time_created < ?
        GROUP BY m.id, m.time_created, m.session_id, s.title, p.name, p.worktree
        ORDER BY m.time_created, m.id
        """,
        (session_id, start_ms, end_ms),
    )
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


def attach_prompt_usage(prompts: list[dict], rows: list[dict]) -> list[dict]:
    """Attach assistant request, token, and credit totals to each prompt."""
    for prompt in prompts:
        prompt.update({
            "requests": 0,
            "input": 0,
            "output": 0,
            "cache_read": 0,
            "cache_write": 0,
            "credits": 0.0,
        })
    for row in rows:
        target = next(
            (prompt for prompt in reversed(prompts) if prompt["ts_ms"] <= row["ts_ms"]),
            None,
        )
        if target is None:
            continue
        target["requests"] += 1
        target["input"] += row["input"]
        target["output"] += row["output"] + row["reasoning"]
        target["cache_read"] += row["cache_read"]
        target["cache_write"] += row["cache_write"]
        target["credits"] += credits(cost_usd(
            row["model"] or "", row["input"], row["output"], row["reasoning"],
            row["cache_read"], row["cache_write"],
        ))
    return prompts


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
    rows: list[dict], range_key: str, month: date | None = None
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
        # Daily buckets from the first through the last selected month day.
        start, month_end = month_bounds(month)
        end = min(month_end, now)
        n_buckets = (
            now.date().day
            if end < month_end
            else (month_end.date() - start.date()).days
        )
        n_buckets = max(n_buckets, 1)
        def bucket_fn(ts_ms):
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            return (dt.date() - start.date()).days
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


def summarize_by_session(rows: list[dict]) -> list[tuple[str, dict]]:
    """Aggregate rows by OpenCode session, compute cost, and sort by cost."""
    by_session: dict[str, dict] = {}
    for r in rows:
        session_id = r.get("session_id") or "unknown"
        session = by_session.setdefault(
            session_id,
            {
                "title": r.get("session_title") or "Untitled session",
                "project": r.get("project_name") or "Unknown project",
                "requests": 0,
                "input": 0,
                "output": 0,
                "cache_read": 0,
                "cache_write": 0,
                "first_ts_ms": r["ts_ms"],
                "last_ts_ms": r["ts_ms"],
                "usd": 0.0,
                "priced": True,
            },
        )
        session["requests"] += 1
        session["input"] += r["input"]
        session["output"] += r["output"] + r["reasoning"]
        session["cache_read"] += r["cache_read"]
        session["cache_write"] += r["cache_write"]
        session["first_ts_ms"] = min(session["first_ts_ms"], r["ts_ms"])
        session["last_ts_ms"] = max(session["last_ts_ms"], r["ts_ms"])
        session["usd"] += cost_usd(
            r["model"] or "",
            r["input"],
            r["output"],
            r["reasoning"],
            r["cache_read"],
            r["cache_write"],
        )
        if (r["model"] or "") not in PRICING:
            session["priced"] = False

    return sorted(by_session.items(), key=lambda kv: -kv[1]["usd"])


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

    def update_summary(self, total: float, budget: float, month: date | None = None) -> None:
        pct = (total / budget * 100) if budget else 0.0
        if is_current_month(month):
            days = days_until_budget_reset()
            reset_line = (
                "Budget resets tomorrow"
                if days == 1
                else f"Budget resets in {days} days"
            )
        else:
            reset_line = "Historical month"
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
                 offline: bool = False, month: date | None = None,
                 session_id: str | None = None):
        super().__init__()
        self.db = db
        self.budget = budget
        self.interval = interval
        self.compact_width = compact_width
        self.compact_height = compact_height
        self.offline = offline
        self.month = month
        self.session_id = session_id

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
            if key == "month" and self.month is not None:
                full_label = month_label(self.month)
                short_label = full_label
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
        if range_key == "month" and self.month is not None:
            range_label = f"{range_label} ({month_label(self.month)})"

        start_ms, end_ms = range_bounds(range_key, self.month)
        rows = filter_session_rows(fetch_rows(self.db, start_ms, end_ms), self.session_id)

        labels, cumulative = build_series(rows, range_key, self.month)
        model_rows = summarize_by_model(rows)
        total = cumulative[-1] if cumulative else 0.0

        chart = self.query_one("#chart", CreditChart)
        chart.update_data(labels, cumulative, range_label, self.budget)

        table = self.query_one("#table", ModelTable)
        table.update_data(model_rows, total, self.budget)

        summary = self.query_one("#summary", UsageSummary)
        summary.update_summary(total, self.budget, self.month)

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

def session_output_rows(
    session_rows: list[tuple[str, dict]], total_credits: float, budget: float
) -> list[dict]:
    rows = []
    for session_id, session in session_rows:
        cred_val = credits(session["usd"])
        rows.append({
            "session_id": session_id,
            "project": session["project"],
            "title": session["title"],
            "requests": session["requests"],
            "input_tokens": session["input"],
            "output_tokens": session["output"],
            "cache_read_tokens": session["cache_read"],
            "cache_write_tokens": session["cache_write"],
            "first_timestamp_ms": session["first_ts_ms"],
            "last_timestamp_ms": session["last_ts_ms"],
            "credits": round(cred_val, 4) if session["priced"] else None,
            "pct_of_used": round(cred_val / total_credits * 100, 2)
            if (session["priced"] and total_credits) else None,
            "pct_of_budget": round(cred_val / budget * 100, 4)
            if (session["priced"] and budget) else None,
        })
    return rows


def output_json(model_rows: list[tuple[str, dict]], total_credits: float, budget: float,
                month: date | None = None) -> None:
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
        "period": month_label(month),
        "budget": budget,
        "total_credits": round(total_credits, 4),
        "pct_of_budget": round(total_credits / budget * 100, 2) if budget else None,
        "remaining_credits": round(budget - total_credits, 4),
        "pct_remaining": round((budget - total_credits) / budget * 100, 2) if budget else None,
        "days_until_reset": days_until_budget_reset() if is_current_month(month) else None,
        "models": rows,
        "pricing_source": PRICING_META.get("source"),
        "pricing_retrieved_at": PRICING_META.get("retrieved_at"),
    }, indent=2))


def output_remaining(total_credits: float, budget: float) -> None:
    """Print the AI credits left this month as a bare number."""
    print(f"{budget - total_credits:.1f}")


def output_table(model_rows: list[tuple[str, dict]], total_credits: float, budget: float,
                 month: date | None = None) -> None:
    pct_budget_total = total_credits / budget * 100 if budget else 0
    header = (
        f"{'Model':<26} {'Reqs':>6} {'Input':>12} {'Output':>10} "
        f"{'Cache R':>10} {'Cache W':>10} {'Credits':>10} {'% used':>8} {'% budget':>10}"
    )
    print(f"\nOpencode -> GitHub Copilot AI credit estimate ({month_label(month)})")
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
    remaining = budget - total_credits
    pct_remaining = f" ({remaining / budget * 100:.1f}%)" if budget else ""
    if is_current_month(month):
        days = days_until_budget_reset()
        reset = "resets tomorrow" if days == 1 else f"resets in {days} days"
        reset_suffix = f" — budget {reset}"
    else:
        reset_suffix = " — historical month"
    print(f"Remaining: {remaining:,.1f} AI credits{pct_remaining}{reset_suffix}")
    retrieved_at = PRICING_META.get("retrieved_at")
    if retrieved_at:
        print(f"Pricing last refreshed: {retrieved_at}")
    print("Local estimate from opencode logs only — https://github.com/settings/copilot/features for actuals.")


def output_sessions_table(
    session_rows: list[tuple[str, dict]], total_credits: float, budget: float,
    month: date | None = None,
) -> None:
    """Print the current month's estimated credits grouped by OpenCode session."""
    header = (
        f"{'Project':<36} {'Session':<60} {'Reqs':>6} {'Input':>12} {'Output':>10} "
        f"{'Cache R':>10} {'Cache W':>10} {'Credits':>10} {'% used':>8} {'% budget':>10}"
    )
    print(f"\nOpencode -> GitHub Copilot AI credit estimate by session ({month_label(month)})")
    print("=" * len(header))
    print(header)
    print("-" * len(header))
    for session_id, session in session_rows:
        cred_val = credits(session["usd"])
        cred = f"{cred_val:,.1f}" if session["priced"] else "?"
        pct_used = (
            f"{cred_val / total_credits * 100:.1f}%"
            if (session["priced"] and total_credits) else "?"
        )
        pct_budget = (
            f"{cred_val / budget * 100:.2f}%"
            if (session["priced"] and budget) else "?"
        )
        project = session.get("project") or "Unknown project"
        if len(project) > 34:
            project = project[:33] + "..."
        label = session["title"] or "Untitled session"
        if len(label) > 58:
            label = label[:57] + "..."
        print(
            f"{project:<36} {label:<60} {session['requests']:>6,} {session['input']:>12,} "
            f"{session['output']:>10,} {session['cache_read']:>10,} "
            f"{session['cache_write']:>10,} {cred:>10} {pct_used:>8} {pct_budget:>10}"
        )
        print(f"{'':36}   {session_id}")
    print("-" * len(header))
    pct_budget_total = total_credits / budget * 100 if budget else 0
    print(
        f"{'TOTAL':<36} {'':<60} {'':>6} {'':>12} {'':>10} {'':>10} {'':>10} "
        f"{total_credits:>10,.1f} {'100.0%':>8} {pct_budget_total:>9.2f}%"
    )
    print(f"\nBudget: {budget:,.0f} AI credits")
    remaining = budget - total_credits
    pct_remaining = f" ({remaining / budget * 100:.1f}%)" if budget else ""
    days = days_until_budget_reset()
    reset = "resets tomorrow" if days == 1 else f"resets in {days} days"
    print(f"Remaining: {remaining:,.1f} AI credits{pct_remaining} — budget {reset}")
    retrieved_at = PRICING_META.get("retrieved_at")
    if retrieved_at:
        print(f"Pricing last refreshed: {retrieved_at}")
    print("Local estimate from opencode logs only — https://github.com/settings/copilot/features for actuals.")


def output_sessions_json(
    session_rows: list[tuple[str, dict]], total_credits: float, budget: float,
    month: date | None = None,
) -> None:
    import json as _json
    print(_json.dumps({
        "period": month_label(month),
        "budget": budget,
        "total_credits": round(total_credits, 4),
        "pct_of_budget": round(total_credits / budget * 100, 2) if budget else None,
        "remaining_credits": round(budget - total_credits, 4),
        "pct_remaining": round((budget - total_credits) / budget * 100, 2)
        if budget else None,
        "days_until_reset": days_until_budget_reset() if is_current_month(month) else None,
        "sessions": session_output_rows(session_rows, total_credits, budget),
        "pricing_source": PRICING_META.get("source"),
        "pricing_retrieved_at": PRICING_META.get("retrieved_at"),
    }, indent=2))


def prompt_preview(text: str, mode: str) -> str:
    """Format a prompt according to the requested display mode."""
    first_line = text.splitlines()[0] if text.splitlines() else ""
    if mode == "short":
        return first_line[:80]
    if mode == "long":
        return first_line[:300]
    return text


def prompt_data_line(prompt: dict) -> str:
    return (
        f"{prompt['requests']:,} requests  "
        f"{prompt['input']:,} input  {prompt['output']:,} output  "
        f"{prompt['cache_read']:,} cache read  {prompt['cache_write']:,} cache write"
    )


def prompt_timestamp(prompt: dict) -> str:
    """Format a prompt timestamp in local time at minute precision."""
    return datetime.fromtimestamp(prompt["ts_ms"] / 1000).astimezone().strftime(
        "%Y-%m-%dT%H:%M"
    )


def output_prompts_table(prompts: list[dict], mode: str) -> None:
    """Print prompts and their usage data for one session."""
    if not prompts:
        print("No prompts found for the selected session and period.")
        return
    first = prompts[0]
    print(f"Session: {first['session_id']}")
    print(f"Name: {first['session_title'] or 'Untitled session'}")
    print(f"Project: {first['project_name'] or 'Unknown project'}")
    print()
    if mode == "short":
        print(
            f"{'Timestamp':<16} {'Prompt':<80} {'Reqs':>6} {'Input':>10} "
            f"{'Output':>10} {'Cache R':>10} {'Cache W':>10} {'Credits':>10}"
        )
        print("-" * 156)
    for prompt in prompts:
        text = prompt_preview(prompt["prompt"], mode)
        if mode == "short":
            print(
                f"{prompt_timestamp(prompt):<16} {text:<80} "
                f"{prompt['requests']:>6,} {prompt['input']:>10,} "
                f"{prompt['output']:>10,} {prompt['cache_read']:>10,} "
                f"{prompt['cache_write']:>10,} {prompt['credits']:>10,.1f}"
            )
        else:
            lines = text.splitlines() or [""]
            print(f"{prompt_timestamp(prompt)} {lines[0]}")
            if len(lines) > 1:
                print("\n".join(lines[1:]))
            if mode == "full":
                print()
            print(f"    {prompt_data_line(prompt)}")
            print(f"    CREDITS: {prompt['credits']:,.1f}")
            print()


def output_prompts_json(prompts: list[dict], mode: str, month: date | None) -> None:
    import json as _json
    print(_json.dumps({
        "period": month_label(month),
        "session_id": prompts[0]["session_id"] if prompts else None,
        "session_title": prompts[0]["session_title"] if prompts else None,
        "project": prompts[0]["project_name"] if prompts else None,
        "prompt_mode": mode,
        "prompts": [
            {
                "timestamp_ms": prompt["ts_ms"],
                "prompt": prompt_preview(prompt["prompt"], mode),
                "requests": prompt["requests"],
                "input_tokens": prompt["input"],
                "output_tokens": prompt["output"],
                "cache_read_tokens": prompt["cache_read"],
                "cache_write_tokens": prompt["cache_write"],
                "credits": round(prompt["credits"], 4),
            }
            for prompt in prompts
        ],
    }, indent=2))


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
    ap.add_argument("--month", type=parse_month,
                    help="Calendar month to estimate in YYYY-MM format (default: current month)")
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
    ap.add_argument("--sessions", action="store_true",
                     help="Report monthly data grouped by OpenCode session (no TUI)")
    ap.add_argument("--session", dest="session_id",
                    help="Limit data to one OpenCode session ID")
    ap.add_argument("--prompts", nargs="?", const="short",
                    choices=["short", "long", "full"],
                    help="Print prompts for --session (short, long, or full)")
    ap.add_argument("--remaining", action="store_true",
                    help="Print the number of AI credits left this month and exit "
                         "(cannot be combined with --output)")
    ap.add_argument("--offline", action="store_true",
                    help="Never fetch pricing over the network; use cached/bundled pricing only")
    args = ap.parse_args()

    if args.prompts and not args.session_id:
        ap.error("--prompts requires --session SESSION_ID")
    if args.prompts and args.sessions:
        ap.error("--prompts cannot be combined with --sessions")
    if args.remaining and (args.output or args.sessions or args.session_id or args.prompts):
        ap.error("--remaining cannot be combined with --output, --sessions, --session, or --prompts; "
                 "use --output json, which already reports remaining_credits")

    global PRICING, PRICING_META
    if not args.offline:
        PRICING, PRICING_META = pricing_source.load_pricing(refresh=True)

    if args.output or args.remaining or args.sessions or args.prompts:
        start_ms, end_ms = range_bounds("month", args.month)
        rows = filter_session_rows(
            fetch_rows(args.db, start_ms, end_ms), args.session_id
        )
        if args.prompts:
            prompts = attach_prompt_usage(
                fetch_prompts(args.db, args.session_id, start_ms, end_ms), rows
            )
            if args.output == "json":
                output_prompts_json(prompts, args.prompts, args.month)
            else:
                output_prompts_table(prompts, args.prompts)
            return
        model_rows = summarize_by_model(rows)
        session_rows = summarize_by_session(rows)
        total = sum(credits(m["usd"]) for _, m in model_rows if m["priced"])
        if args.remaining:
            output_remaining(total, args.budget)
        elif args.sessions and args.output == "json":
            output_sessions_json(session_rows, total, args.budget, args.month)
        elif args.sessions:
            output_sessions_table(session_rows, total, args.budget, args.month)
        elif args.output == "json":
            output_json(model_rows, total, args.budget, args.month)
        else:
            output_table(model_rows, total, args.budget, args.month)
        return

    app = CreditEstimatorApp(db=args.db, budget=args.budget, interval=args.interval,
                             compact_width=args.compact_width, compact_height=args.compact_height,
                             offline=args.offline, month=args.month,
                             session_id=args.session_id)
    app.run()


if __name__ == "__main__":
    main()
