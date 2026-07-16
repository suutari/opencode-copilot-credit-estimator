"""Headless Textual tests for the responsive compact layout."""

from datetime import datetime, timezone

import pytest

import estimator
from estimator import CreditEstimatorApp, ModelTable, StatusBar, UsageSummary


def make_app(db="/nonexistent/opencode.db", budget=50_000, interval=3600):
    return CreditEstimatorApp(db=db, budget=budget, interval=interval)


def populated_rows():
    return [{
        "ts_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
        "model": "claude-sonnet-with-a-very-long-model-name",
        "input": 1_000,
        "output": 500,
        "reasoning": 0,
        "cache_read": 0,
        "cache_write": 0,
    }]


@pytest.mark.asyncio
async def test_normal_size_shows_summary_chart_and_full_table():
    app = make_app()
    async with app.run_test(size=(160, 50)) as pilot:
        assert app.compact is False

        summary = app.query_one("#summary", UsageSummary)
        assert summary.display

        chart = app.query_one("#chart")
        assert chart.display

        table = app.query_one("#table", ModelTable)
        assert table.display
        assert tuple(str(c.label) for c in table.columns.values()) == ModelTable.FULL_COLUMNS


@pytest.mark.asyncio
async def test_compact_size_hides_chart_and_narrows_table(monkeypatch):
    monkeypatch.setattr(estimator, "fetch_rows", lambda *_: populated_rows())
    app = make_app()
    async with app.run_test(size=(40, 45)) as pilot:
        assert app.compact is True

        summary = app.query_one("#summary", UsageSummary)
        assert summary.display

        main = app.query_one("#main")
        assert main.has_class("compact")

        chart = app.query_one("#chart")
        # Hidden via CSS `display: none` on `.compact CreditChart`.
        assert not chart.visible or chart.styles.display == "none"

        table = app.query_one("#table", ModelTable)
        assert tuple(str(c.label) for c in table.columns.values()) == ModelTable.COMPACT_COLUMNS
        assert table.row_count == 1
        assert table.max_scroll_x == 0


@pytest.mark.asyncio
async def test_resize_across_breakpoint_switches_layout_both_ways():
    app = make_app()
    async with app.run_test(size=(160, 50)) as pilot:
        assert app.compact is False

        await pilot.resize_terminal(40, 45)
        await pilot.pause()
        assert app.compact is True
        status = app.query_one("#status", StatusBar)
        assert "Last updated:" not in str(status.content)

        table = app.query_one("#table", ModelTable)
        assert tuple(str(c.label) for c in table.columns.values()) == ModelTable.COMPACT_COLUMNS

        await pilot.resize_terminal(160, 50)
        await pilot.pause()
        assert app.compact is False
        assert tuple(str(c.label) for c in table.columns.values()) == ModelTable.FULL_COLUMNS
        assert "Last updated:" in str(status.content)


@pytest.mark.asyncio
async def test_empty_data_state():
    app = make_app(db="/definitely/does/not/exist.db")
    async with app.run_test(size=(160, 50)) as pilot:
        summary = app.query_one("#summary", UsageSummary)
        assert "0.0 / 50,000 credits used" in str(summary.content)
        table = app.query_one("#table", ModelTable)
        assert table.row_count == 0


@pytest.mark.asyncio
async def test_zero_budget_state():
    app = make_app(budget=0)
    async with app.run_test(size=(160, 50)) as pilot:
        summary = app.query_one("#summary", UsageSummary)
        # Should not raise a ZeroDivisionError and should render something sane.
        assert "/ 0 credits used" in str(summary.content)
