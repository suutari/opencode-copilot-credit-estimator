"""Tests for pricing.py's markdown parsing, caching, and fallback behavior."""

import json
import os

import pytest

import pricing


SAMPLE_MD = """
### OpenAI

| Model         | Release status | Category    | Tier         | Threshold (input tokens) |  Input | Cached input | Output |
| ------------- | -------------- | ----------- | ------------ | ------------------------ | -----: | -----------: | -----: |
|               |                |             |              |                          |        |              |        |
| GPT-5 mini    | GA             | Lightweight | Default      | Not applicable           |  $0.25 |       $0.025 |  $2.00 |
|               |                |             |              |                          |        |              |        |
| GPT-5.4       | GA             | Versatile   | Default      | \u2264 272K               |  $2.50 |        $0.25 | $15.00 |
|               |                |             |              |                          |        |              |        |
| GPT-5.4       | GA             | Versatile   | Long context | > 272K                   |  $5.00 |        $0.50 | $22.50 |
|               |                |             |              |                          |        |              |        |

### Anthropic

Anthropic models include a cache write cost in addition to cached input.

| Model                                 | Release status | Category  |  Input | Cached input | Cache write | Output |
| -------------------------------------- | -------------- | --------- | -----: | -----------: | ----------: | -----: |
|                                       |                |           |        |              |             |        |
| Claude Sonnet 5[^sonnet-5-promo]      | GA             | Versatile |  $2.00 |        $0.20 |       $2.50 | $10.00 |
|                                       |                |           |        |              |             |        |
| Claude Opus 4.8 (fast mode) (preview) | GA             | Powerful  | $10.00 |        $1.00 |      $12.50 | $50.00 |
|                                       |                |           |        |              |             |        |
"""


def test_parse_markdown_tables_finds_both_tables():
    tables = pricing.parse_markdown_tables(SAMPLE_MD)
    assert len(tables) == 2
    assert len(tables[0]) == 3  # GPT-5 mini, GPT-5.4 Default, GPT-5.4 Long context
    assert len(tables[1]) == 2  # Claude Sonnet 5, Claude Opus 4.8 fast


def test_build_pricing_table_filters_long_context_and_parses_dollars():
    tables = pricing.parse_markdown_tables(SAMPLE_MD)
    table = pricing.build_pricing_table(tables)

    assert "gpt-5-mini" in table
    assert table["gpt-5-mini"] == (0.25, 0.025, None, 2.00)

    # Long context tier row must be dropped, only Default kept.
    assert table["gpt-5.4"] == (2.50, 0.25, None, 15.00)


def test_build_pricing_table_strips_footnotes():
    tables = pricing.parse_markdown_tables(SAMPLE_MD)
    table = pricing.build_pricing_table(tables)
    assert "claude-sonnet-5" in table
    assert table["claude-sonnet-5"] == (2.00, 0.20, 2.50, 10.00)


def test_build_pricing_table_applies_alias_overrides():
    tables = pricing.parse_markdown_tables(SAMPLE_MD)
    table = pricing.build_pricing_table(tables)
    # "Claude Opus 4.8 (fast mode) (preview)" naively slugifies to
    # "claude-opus-4.8-fast-preview"; ALIAS_OVERRIDES maps it to the real
    # opencode modelID "claude-opus-4.8-fast".
    assert "claude-opus-4.8-fast" in table
    assert "claude-opus-4.8-fast-preview" not in table


def test_build_pricing_table_drops_colliding_slugs():
    md = """
| Model   | Input | Cached input | Output |
| ------- | ----: | ------------: | -----: |
| Foo Bar | $1.00 |         $0.10 |  $2.00 |

| Model   | Input | Cached input | Output |
| ------- | ----: | ------------: | -----: |
| foo bar | $9.00 |         $0.90 |  $9.00 |
"""
    tables = pricing.parse_markdown_tables(md)
    table = pricing.build_pricing_table(tables)
    assert "foo-bar" not in table


def test_parse_dollar_handles_not_applicable_and_footnotes():
    assert pricing.parse_dollar("$1.25") == 1.25
    assert pricing.parse_dollar("Not applicable") is None
    assert pricing.parse_dollar("") is None
    assert pricing.parse_dollar("$1,234.50") == 1234.50


def test_slugify_basic_and_qualifiers():
    assert pricing.slugify("GPT-5.4 mini") == "gpt-5.4-mini"
    assert pricing.slugify("Claude Sonnet 4.5") == "claude-sonnet-4.5"
    assert pricing.slugify("Claude Sonnet 5[^sonnet-5-promo]") == "claude-sonnet-5"


def test_save_and_load_snapshot_roundtrip(tmp_path):
    path = str(tmp_path / "snapshot.json")
    table = {"gpt-5-mini": (0.25, 0.025, None, 2.00)}
    pricing.save_snapshot(path, table, "https://example.com/pricing.md")

    loaded = pricing.load_snapshot(path)
    assert loaded is not None
    loaded_table, retrieved_at, source = loaded
    assert loaded_table == table
    assert source == "https://example.com/pricing.md"
    assert retrieved_at is not None

    with open(path) as f:
        payload = json.load(f)
    assert payload["pricing"]["gpt-5-mini"] == [0.25, 0.025, None, 2.00]


def test_load_snapshot_missing_file_returns_none(tmp_path):
    assert pricing.load_snapshot(str(tmp_path / "nope.json")) is None


def test_snapshot_age_seconds_missing_or_invalid_is_infinite():
    assert pricing.snapshot_age_seconds(None) == float("inf")
    assert pricing.snapshot_age_seconds("not-a-date") == float("inf")


def test_load_pricing_without_refresh_uses_bundled_snapshot_when_no_cache(tmp_path, monkeypatch):
    missing_cache = str(tmp_path / "no-cache-here.json")
    table, meta = pricing.load_pricing(
        refresh=False,
        cache_path=missing_cache,
        bundled_path=pricing.BUNDLED_SNAPSHOT_PATH,
    )
    # Deliberately model-agnostic: the bundled snapshot tracks GitHub's live
    # model list, so individual model names come and go between refreshes.
    assert table
    assert all(len(prices) == 4 for prices in table.values())
    assert meta["source"] == pricing.GITHUB_PRICING_URL


def test_load_pricing_refresh_false_never_touches_network(tmp_path, monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("network should not be called when refresh=False")

    monkeypatch.setattr(pricing, "fetch_pricing_table", _boom)
    table, meta = pricing.load_pricing(
        refresh=False,
        cache_path=str(tmp_path / "missing.json"),
        bundled_path=pricing.BUNDLED_SNAPSHOT_PATH,
    )
    assert table  # bundled snapshot still loaded


def test_load_pricing_keeps_existing_table_on_fetch_failure(tmp_path, monkeypatch):
    cache_path = str(tmp_path / "cache.json")
    stale_table = {"gpt-5-mini": (0.25, 0.025, None, 2.00)}
    # Write a snapshot with an old timestamp so it's considered stale.
    pricing.save_snapshot(cache_path, stale_table, "https://example.com")
    with open(cache_path) as f:
        payload = json.load(f)
    payload["retrievedAt"] = "2000-01-01T00:00:00Z"
    with open(cache_path, "w") as f:
        json.dump(payload, f)

    def _boom(*args, **kwargs):
        raise OSError("network unavailable")

    monkeypatch.setattr(pricing, "fetch_pricing_table", _boom)
    table, meta = pricing.load_pricing(
        refresh=True,
        cache_path=cache_path,
        bundled_path=pricing.BUNDLED_SNAPSHOT_PATH,
    )
    assert table == stale_table


def test_load_pricing_refreshes_and_saves_on_success(tmp_path, monkeypatch):
    cache_path = str(tmp_path / "cache.json")
    fresh_table = {"gpt-5-mini": (0.30, 0.03, None, 3.00)}

    monkeypatch.setattr(pricing, "fetch_pricing_table", lambda *a, **k: fresh_table)
    table, meta = pricing.load_pricing(
        refresh=True,
        cache_path=cache_path,
        bundled_path=str(tmp_path / "missing-bundled.json"),
    )
    assert table == fresh_table
    assert os.path.exists(cache_path)
