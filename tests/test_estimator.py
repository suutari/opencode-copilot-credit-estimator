"""Headless Textual tests for the responsive compact layout."""

from datetime import datetime, timezone

import pytest

import estimator
from estimator import CreditEstimatorApp, ModelTable, StatusBar, UsageSummary


def make_app(db="/nonexistent/opencode.db", budget=50_000, interval=3600):
    return CreditEstimatorApp(db=db, budget=budget, interval=interval)


def populated_rows(requests=1):
    row = {
        "ts_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
        "model": "claude-sonnet-with-a-very-long-model-name",
        "input": 1_000,
        "output": 500,
        "reasoning": 0,
        "cache_read": 0,
        "cache_write": 0,
    }
    return [row] * requests


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
    monkeypatch.setattr(estimator, "fetch_rows", lambda *_: populated_rows(1_064))
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
        assert table.get_cell_at((0, 1)) == "1,064"
        assert tuple(table.columns.values())[1].width >= len("1,064")
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


# --- --remaining / JSON output ---------------------------------------------

def test_output_remaining_is_bare_number(capsys):
    estimator.output_remaining(12_500.0, 50_000.0)
    assert capsys.readouterr().out == "37500.0\n"


def test_output_remaining_can_exceed_budget(capsys):
    estimator.output_remaining(60_000.0, 50_000.0)
    assert capsys.readouterr().out == "-10000.0\n"


def test_output_table_shows_remaining(capsys):
    estimator.output_table([], 12_500.0, 50_000.0)
    out = capsys.readouterr().out
    assert "Remaining: 37,500.0 AI credits (75.0%)" in out
    assert "budget resets" in out


def test_output_table_zero_budget_omits_remaining_percentage(capsys):
    estimator.output_table([], 10.0, 0)
    assert "Remaining: -10.0 AI credits \u2014 budget resets" in capsys.readouterr().out


def test_output_json_includes_remaining(capsys):
    import json

    estimator.output_json([], 12_500.0, 50_000.0)
    data = json.loads(capsys.readouterr().out)
    assert data["total_credits"] == 12_500.0
    assert data["remaining_credits"] == 37_500.0
    assert data["pct_remaining"] == 75.0
    assert data["days_until_reset"] >= 1


def test_output_json_remaining_with_zero_budget(capsys):
    import json

    estimator.output_json([], 10.0, 0)
    data = json.loads(capsys.readouterr().out)
    assert data["remaining_credits"] == -10.0
    assert data["pct_remaining"] is None


def test_summarize_by_session_groups_requests(monkeypatch):
    monkeypatch.setattr(estimator, "PRICING", {
        "test-model": (1.0, 0.5, None, 2.0),
    })
    rows = [
        {
            "ts_ms": 200,
            "session_id": "session-a",
            "session_title": "First task",
            "model": "test-model",
            "input": 1_000_000,
            "output": 100_000,
            "reasoning": 0,
            "cache_read": 0,
            "cache_write": 0,
        },
        {
            "ts_ms": 100,
            "session_id": "session-a",
            "session_title": "First task",
            "model": "test-model",
            "input": 500_000,
            "output": 0,
            "reasoning": 100_000,
            "cache_read": 0,
            "cache_write": 0,
        },
        {
            "ts_ms": 300,
            "session_id": "session-b",
            "session_title": "Second task",
            "model": "test-model",
            "input": 1_000_000,
            "output": 0,
            "reasoning": 0,
            "cache_read": 0,
            "cache_write": 0,
        },
    ]

    sessions = estimator.summarize_by_session(rows)

    assert [session_id for session_id, _ in sessions] == ["session-a", "session-b"]
    session = sessions[0][1]
    assert session["title"] == "First task"
    assert session["requests"] == 2
    assert session["input"] == 1_500_000
    assert session["output"] == 200_000
    assert session["first_ts_ms"] == 100
    assert session["last_ts_ms"] == 200
    assert session["usd"] == pytest.approx(1.9)


def test_output_sessions_shows_session_breakdown(monkeypatch, capsys):
    monkeypatch.setattr(estimator, "PRICING_META", {})
    rows = [("session-a", {
        "title": "A task", "requests": 2, "input": 1_000, "output": 500,
        "cache_read": 0, "cache_write": 0, "first_ts_ms": 100,
        "last_ts_ms": 200, "usd": 1.25, "priced": True,
    })]

    estimator.output_sessions_table(rows, 125.0, 50_000.0)
    out = capsys.readouterr().out

    assert "estimate by session" in out
    assert "A task" in out
    assert "session-a" in out
    assert "125.0" in out


def test_output_sessions_json_includes_sessions(monkeypatch, capsys):
    import json

    monkeypatch.setattr(estimator, "PRICING_META", {})
    rows = [("session-a", {
        "title": "A task", "requests": 1, "input": 10, "output": 5,
        "cache_read": 0, "cache_write": 0, "first_ts_ms": 100,
        "last_ts_ms": 100, "usd": 0.01, "priced": True,
    })]

    estimator.output_sessions_json(rows, 1.0, 50_000.0)
    data = json.loads(capsys.readouterr().out)

    assert data["sessions"][0]["session_id"] == "session-a"
    assert data["sessions"][0]["title"] == "A task"
    assert data["sessions"][0]["credits"] == 1.0


def test_output_json_does_not_include_sessions(capsys):
    import json

    estimator.output_json([], 0.0, 50_000.0)
    assert "sessions" not in json.loads(capsys.readouterr().out)
