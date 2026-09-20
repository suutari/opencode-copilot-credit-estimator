"""Headless Textual tests for the responsive compact layout."""

from datetime import date, datetime, timezone

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


def test_parse_month_accepts_year_month():
    assert estimator.parse_month("2024-02") == date(2024, 2, 1)


def test_parse_month_rejects_invalid_values():
    with pytest.raises(estimator.argparse.ArgumentTypeError):
        estimator.parse_month("2024-2")
    with pytest.raises(estimator.argparse.ArgumentTypeError):
        estimator.parse_month("2024-13")


def test_parse_week_accepts_iso_and_bare_week():
    now = datetime(2026, 9, 20, 22, tzinfo=timezone.utc)
    assert estimator.parse_week("2026-W38", now) == date(2026, 9, 14)
    assert estimator.parse_week("2026W38", now) == date(2026, 9, 14)
    assert estimator.parse_week("38", now) == date(2026, 9, 14)


def test_parse_day_bare_number_uses_latest_past_date():
    now = datetime(2026, 9, 20, 22, tzinfo=timezone.utc)
    assert estimator.parse_day("20", now) == date(2026, 9, 20)
    assert estimator.parse_day("21", now) == date(2026, 8, 21)


def test_parse_hour_accepts_local_iso_and_bare_hour():
    now = datetime(2026, 9, 20, 22, 15, tzinfo=timezone.utc)
    assert estimator.parse_hour("2026-08-20T22", now).replace(tzinfo=None) == datetime(2026, 8, 20, 22)
    assert estimator.parse_hour("2026-08-20 22", now).replace(tzinfo=None) == datetime(2026, 8, 20, 22)
    assert estimator.parse_hour("22", now).replace(tzinfo=None) == datetime(2026, 9, 20, 22)
    assert estimator.parse_hour("23", now).replace(tzinfo=None) == datetime(2026, 9, 19, 23)


def test_selected_time_range_has_timestamp_bounds():
    now = datetime(2026, 9, 20, 22, 15, tzinfo=timezone.utc)
    period = estimator.selected_time_range("day", date(2026, 9, 20), now)
    assert period.start.replace(tzinfo=None) == datetime(2026, 9, 20)
    assert period.end == now
    assert period.label == "2026-09-20"


def test_derived_ranges_follow_hour_anchor():
    now = datetime(2026, 9, 20, 22, 15, tzinfo=timezone.utc)
    ranges = estimator.derived_time_ranges(
        "hour", datetime(2026, 9, 10, 19, tzinfo=timezone.utc), now
    )
    assert ranges["hour"].label == "2026-09-10T19"
    assert ranges["today"].label == "2026-09-10"
    assert ranges["week"].label == "2026-W37"
    assert ranges["month"].label == "2026-09"


def test_derived_ranges_use_noon_wednesday_and_fifteenth_fallbacks():
    now = datetime(2026, 9, 20, 22, 15, tzinfo=timezone.utc)
    day_ranges = estimator.derived_time_ranges("day", date(2026, 9, 10), now)
    assert day_ranges["hour"].label == "2026-09-10T12"

    week_ranges = estimator.derived_time_ranges("week", date(2026, 9, 7), now)
    assert week_ranges["today"].label == "2026-09-09"
    assert week_ranges["hour"].label == "2026-09-09T12"

    month_ranges = estimator.derived_time_ranges("month", date(2026, 9, 1), now)
    assert month_ranges["today"].label == "2026-09-15"
    assert month_ranges["hour"].label == "2026-09-15T12"


def test_month_bounds_handles_leap_year():
    start, end = estimator.month_bounds(date(2024, 2, 1))
    assert start == datetime(2024, 2, 1, tzinfo=timezone.utc)
    assert end == datetime(2024, 3, 1, tzinfo=timezone.utc)


def test_range_bounds_for_historical_month():
    start_ms, end_ms = estimator.range_bounds("month", date(2024, 2, 1))
    assert start_ms == int(datetime(2024, 2, 1, tzinfo=timezone.utc).timestamp() * 1000)
    assert end_ms == int(datetime(2024, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)


def test_output_json_reports_selected_month(capsys):
    import json

    estimator.output_json([], 0.0, 50_000.0, date(2024, 2, 1))
    data = json.loads(capsys.readouterr().out)
    assert data["period"] == "2024-02"
    assert data["days_until_reset"] is None


# --- Selected month ---------------------------------------------------------

@pytest.mark.asyncio
async def test_selected_month_is_shown_on_month_tab():
    app = CreditEstimatorApp(
        db="/nonexistent/opencode.db",
        budget=50_000,
        interval=3600,
        month=date(2024, 2, 1),
    )
    async with app.run_test(size=(160, 50)):
        tab = app.query_one("#month")
        assert str(tab.label) == "2024-02"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("selected_range", "initial_tab", "expected"),
    [
        (estimator.TimeRange(
            datetime(2026, 9, 14, tzinfo=timezone.utc),
            datetime(2026, 9, 21, tzinfo=timezone.utc),
            "2026-W38",
        ), "week", "2026-W38"),
        (estimator.TimeRange(
            datetime(2026, 9, 20, tzinfo=timezone.utc),
            datetime(2026, 9, 21, tzinfo=timezone.utc),
            "2026-09-20",
        ), "today", "2026-09-20"),
        (estimator.TimeRange(
            datetime(2026, 9, 20, 22, tzinfo=timezone.utc),
            datetime(2026, 9, 20, 23, tzinfo=timezone.utc),
            "2026-09-20T22",
        ), "hour", "2026-09-20T22"),
    ],
)
async def test_selected_period_is_shown_on_corresponding_tab(
    selected_range, initial_tab, expected
):
    app = CreditEstimatorApp(
        db="/nonexistent/opencode.db",
        budget=50_000,
        interval=3600,
        selected_range=selected_range,
        initial_tab=initial_tab,
    )
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        tab = app.query_one(f"#{initial_tab}")
        assert str(tab.label) == expected


def test_time_selector_uses_generic_help_labels():
    app = CreditEstimatorApp(
        db="/nonexistent/opencode.db",
        budget=50_000,
        interval=3600,
        selected_ranges={"hour": estimator.TimeRange(
            datetime(2026, 9, 20, 22, tzinfo=timezone.utc),
            datetime(2026, 9, 20, 23, tzinfo=timezone.utc),
            "2026-09-20T22",
        )},
    )
    labels = {binding.key: binding.description for binding in app.BINDINGS}
    assert labels["1"] == "Hour"
    assert labels["2"] == "Day"
    assert labels["3"] == "Week"
    assert labels["4"] == "Month"


def test_current_time_uses_current_help_labels():
    app = make_app()
    labels = {binding.key: binding.description for binding in app.BINDINGS}
    assert labels["1"] == "Hour"
    assert labels["2"] == "Day"


def test_navigation_help_bindings_are_available():
    app = make_app()
    bindings = {binding.action: binding for binding in app.BINDINGS}
    assert bindings["next_period"].description == "Next"
    assert bindings["next_period"].key == "up,n"
    assert bindings["next_period"].key_display == "↑/n"
    assert bindings["previous_period"].description == "Previous"
    assert bindings["previous_period"].key == "down,p"
    assert bindings["previous_period"].key_display == "↓/p"


def test_navigation_moves_all_ranges_from_active_day():
    app = CreditEstimatorApp(
        db="/nonexistent/opencode.db",
        budget=50_000,
        interval=3600,
        selected_ranges=estimator.derived_time_ranges(
            "day", date(2026, 9, 10), datetime(2026, 9, 20, 22, tzinfo=timezone.utc)
        ),
        initial_tab="today",
    )
    app.active_range = "today"
    app._move_period(1)
    assert app.selected_ranges["today"].label == "2026-09-11"
    assert app.selected_ranges["hour"].label == "2026-09-11T12"
    assert app.selected_ranges["week"].label == "2026-W37"
    assert app.selected_ranges["month"].label == "2026-09"


def test_refresh_returns_to_live_mode():
    app = CreditEstimatorApp(
        db="/nonexistent/opencode.db",
        budget=50_000,
        interval=15,
        month=date(2024, 2, 1),
        selected_range=estimator.TimeRange(
            datetime(2024, 2, 15, tzinfo=timezone.utc),
            datetime(2024, 2, 16, tzinfo=timezone.utc),
            "2024-02-15",
        ),
        selected_ranges=estimator.derived_time_ranges(
            "day", date(2024, 2, 15), datetime(2024, 2, 20, 12, tzinfo=timezone.utc)
        ),
        initial_tab="today",
    )
    app.action_refresh()
    assert app.selected_range is None
    assert app.selected_ranges == {}
    assert app.month is None


def test_filter_session_rows():
    rows = [
        {"session_id": "session-a", "value": 1},
        {"session_id": "session-b", "value": 2},
    ]

    assert estimator.filter_session_rows(rows, "session-a") == [rows[0]]
    assert estimator.filter_session_rows(rows, None) == rows


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
            "project_name": "Project A",
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
            "project_name": "Project A",
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
            "project_name": "Project B",
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
    assert session["project"] == "Project A"
    assert session["requests"] == 2
    assert session["input"] == 1_500_000
    assert session["output"] == 200_000
    assert session["first_ts_ms"] == 100
    assert session["last_ts_ms"] == 200
    assert session["usd"] == pytest.approx(1.9)


def test_output_sessions_shows_session_breakdown(monkeypatch, capsys):
    monkeypatch.setattr(estimator, "PRICING_META", {})
    rows = [
        (
            "session-a",
            {
                "title": "A task",
                "project": "Project A",
                "requests": 2,
                "input": 1_000,
                "output": 500,
                "cache_read": 0,
                "cache_write": 0,
                "first_ts_ms": 100,
                "last_ts_ms": 200,
                "usd": 1.25,
                "priced": True,
            },
        )
    ]

    estimator.output_sessions_table(rows, 125.0, 50_000.0)
    out = capsys.readouterr().out

    assert "estimate by session" in out
    assert "A task" in out
    assert "Project A" in out
    assert "session-a" in out
    assert "125.0" in out


def test_output_sessions_json_includes_sessions(monkeypatch, capsys):
    import json

    monkeypatch.setattr(estimator, "PRICING_META", {})
    rows = [
        (
            "session-a",
            {
                "title": "A task",
                "project": "Project A",
                "requests": 1,
                "input": 10,
                "output": 5,
                "cache_read": 0,
                "cache_write": 0,
                "first_ts_ms": 100,
                "last_ts_ms": 100,
                "usd": 0.01,
                "priced": True,
            },
        )
    ]

    estimator.output_sessions_json(rows, 1.0, 50_000.0)
    data = json.loads(capsys.readouterr().out)

    assert data["sessions"][0]["session_id"] == "session-a"
    assert data["sessions"][0]["title"] == "A task"
    assert data["sessions"][0]["project"] == "Project A"
    assert data["sessions"][0]["credits"] == 1.0


def test_output_json_does_not_include_sessions(capsys):
    import json

    estimator.output_json([], 0.0, 50_000.0)
    assert "sessions" not in json.loads(capsys.readouterr().out)


def test_prompt_preview_modes():
    text = "First line " + "x" * 400 + "\nsecond line"

    assert len(estimator.prompt_preview(text, "short")) == 80
    assert len(estimator.prompt_preview(text, "long")) == 300
    assert estimator.prompt_preview(text, "full") == text


def test_attach_prompt_usage_assigns_requests_to_prompts(monkeypatch):
    monkeypatch.setattr(estimator, "PRICING", {
        "test-model": (1.0, 0.5, None, 2.0),
    })
    prompts = [
        {"ts_ms": 100, "prompt": "first"},
        {"ts_ms": 300, "prompt": "second"},
    ]
    rows = [{
        "ts_ms": 200, "model": "test-model", "input": 1_000,
        "output": 200, "reasoning": 0, "cache_read": 0, "cache_write": 0,
    }, {
        "ts_ms": 400, "model": "test-model", "input": 2_000,
        "output": 300, "reasoning": 0, "cache_read": 0, "cache_write": 0,
    }]

    estimator.attach_prompt_usage(prompts, rows)

    assert prompts[0]["requests"] == 1
    assert prompts[1]["requests"] == 1
    assert prompts[0]["input"] == 1_000
    assert prompts[1]["input"] == 2_000


def test_output_prompts_short_has_header_and_inline_data(capsys):
    prompt = {
        "session_id": "session-a", "session_title": "Full session name",
        "project_name": "Project A", "prompt": "Do the thing",
        "ts_ms": 100, "requests": 1, "input": 10, "output": 5,
        "cache_read": 0, "cache_write": 0, "credits": 1.0,
    }

    estimator.output_prompts_table([prompt], "short")
    out = capsys.readouterr().out

    assert "Session: session-a" in out
    assert "Name: Full session name" in out
    assert "Project: Project A" in out
    assert "Timestamp        Prompt" in out
    assert "Reqs      Input     Output    Cache R    Cache W    Credits" in out
    assert "Data" not in out
    assert estimator.prompt_timestamp(prompt) in out
    assert "Do the thing" in out
    assert "        1.0" in out


def test_output_prompts_full_puts_data_on_next_line(capsys):
    prompt = {
        "session_id": "session-a", "session_title": "A task",
        "project_name": "Project A", "prompt": "line one\nline two",
        "ts_ms": 100, "requests": 1, "input": 10, "output": 5,
        "cache_read": 0, "cache_write": 0, "credits": 1.0,
    }

    estimator.output_prompts_table([prompt], "full")
    lines = capsys.readouterr().out.splitlines()
    prompt_index = next(i for i, line in enumerate(lines) if line.endswith("line one"))

    assert lines[prompt_index + 1] == "line two"
    assert lines[prompt_index + 2] == ""
    assert "1 requests" in lines[prompt_index + 3]
    assert lines[prompt_index + 4] == "    CREDITS: 1.0"
