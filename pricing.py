"""
Fetch, parse, and cache GitHub Copilot per-model token pricing.

Pricing is sourced from GitHub's own published Markdown page (the same page
rendered at https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing),
rather than being hand-copied into a hardcoded dict. This module:

1. Fetches the raw Markdown, parses every GitHub-Flavored-Markdown pricing
   table in it, and reduces it to a flat `{model_slug: PricingEntry}` table.
2. Caches the parsed result to disk (`~/.cache/opencode-copilot-credit-estimator/`)
   with a retrieval timestamp, so we don't hit the network on every run.
3. Falls back to a bundled snapshot (`resources/github-copilot-pricing-snapshot.json`,
   committed to the repo) if there's no cache yet and/or the network is
   unavailable, so the tool always works offline.

A `PricingEntry` is a 4-tuple `(input, cached_input, cache_write, output)`,
each in USD per 1,000,000 tokens — the same unit GitHub's docs use, and the
same shape the estimator's cost calculation expects. `cache_write` may be
`None`, meaning "no separate cache-write rate published; fall back to the
input rate" (see `estimator.cost_usd`).

Model names in the doc don't always map 1:1 to opencode's `modelID` values
(e.g. "Claude Opus 4.8 (fast mode) (preview)" vs. opencode's
`claude-opus-4.8-fast`). `ALIAS_OVERRIDES` patches known mismatches; if a
model shows up as unpriced ("?") in the TUI after a refresh, check whether
its parsed slug needs an entry there.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

GITHUB_PRICING_URL = (
    "https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing.md"
)

CACHE_DIR = os.path.expanduser("~/.cache/opencode-copilot-credit-estimator")
CACHE_PATH = os.path.join(CACHE_DIR, "github-copilot-pricing.json")

_HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLED_SNAPSHOT_PATH = os.path.join(_HERE, "resources", "github-copilot-pricing-snapshot.json")

STALE_AFTER_SECONDS = 24 * 60 * 60  # 1 day
DEFAULT_TIMEOUT = 10  # seconds

PricingEntry = tuple[float, float, float | None, float]

# Maps a naively-slugified model display name (from the doc) to the actual
# opencode modelID, for cases where the two diverge. Seed values below were
# confirmed against real opencode usage.
ALIAS_OVERRIDES: dict[str, str] = {
    # Doc lists the "Default" (<=200K) tier row simply as "Gemini 3.1 Pro",
    # but the model is still labelled "preview" in opencode while it's in
    # public preview.
    "gemini-3.1-pro": "gemini-3.1-pro-preview",
    # Doc's parenthetical qualifiers slugify to a trailing "-preview" this
    # entry doesn't carry in opencode.
    "claude-opus-4.8-fast-preview": "claude-opus-4.8-fast",
}

_FOOTNOTE_RE = re.compile(r"\[\^[^\]]*\]")
_WHITESPACE_RE = re.compile(r"\s+")
_DASH_RE = re.compile(r"-+")
_NON_SLUG_RE = re.compile(r"[^a-z0-9.\-]+")

_NOT_APPLICABLE = {"", "not applicable", "n/a", "—", "-", "–"}


# ---------------------------------------------------------------------------
# Markdown table parsing
# ---------------------------------------------------------------------------

def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def _is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-+:?", c) for c in cells)


def parse_markdown_tables(md: str) -> list[list[dict[str, str]]]:
    """Parse every GFM pipe-table in `md` into a list of row dicts (per table)."""
    lines = md.splitlines()
    tables: list[list[dict[str, str]]] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        if line.startswith("|") and i + 1 < n:
            next_cells = _split_row(lines[i + 1]) if lines[i + 1].strip().startswith("|") else []
            if _is_separator_row(next_cells):
                headers = _split_row(lines[i])
                i += 2
                rows: list[dict[str, str]] = []
                while i < n and lines[i].strip().startswith("|"):
                    cells = _split_row(lines[i])
                    if any(c for c in cells):
                        row = {h: (cells[j] if j < len(cells) else "") for j, h in enumerate(headers)}
                        rows.append(row)
                    i += 1
                tables.append(rows)
                continue
        i += 1
    return tables


def _norm_header(h: str) -> str:
    return h.strip().lower()


def parse_dollar(raw: str) -> float | None:
    s = (raw or "").strip()
    s = _FOOTNOTE_RE.sub("", s).strip()
    if s.lower() in _NOT_APPLICABLE:
        return None
    s = s.replace("$", "").replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def slugify(name: str) -> str:
    s = _FOOTNOTE_RE.sub("", name).strip()
    s = s.replace("(fast mode)", "fast").replace("(preview)", "preview")
    s = s.replace("(", " ").replace(")", " ")
    s = _WHITESPACE_RE.sub(" ", s).strip().lower()
    s = s.replace(" ", "-")
    s = _NON_SLUG_RE.sub("", s)
    s = _DASH_RE.sub("-", s).strip("-")
    return s


def build_pricing_table(
    tables: list[list[dict[str, str]]],
) -> dict[str, PricingEntry]:
    """Reduce parsed tables into `{model_slug: (input, cached_input, cache_write, output)}`.

    Only "Default" tier rows are kept (tables without a Tier column have no
    such distinction and are used as-is). If two rows produce the same slug
    with conflicting prices, that slug is dropped rather than guessed at.
    """
    result: dict[str, PricingEntry] = {}
    collisions: set[str] = set()

    for rows in tables:
        for row in rows:
            norm = {_norm_header(k): v for k, v in row.items()}
            model_name = norm.get("model", "").strip()
            if not model_name:
                continue

            tier = norm.get("tier", "").strip()
            if tier and tier.lower() != "default":
                continue

            inp = parse_dollar(norm.get("input", ""))
            out = parse_dollar(norm.get("output", ""))
            if inp is None or out is None:
                continue
            cached = parse_dollar(norm.get("cached input", ""))
            cache_write = parse_dollar(norm.get("cache write", ""))

            slug = slugify(model_name)
            slug = ALIAS_OVERRIDES.get(slug, slug)
            if not slug:
                continue

            entry: PricingEntry = (inp, cached if cached is not None else inp, cache_write, out)
            if slug in result and result[slug] != entry:
                collisions.add(slug)
                continue
            result[slug] = entry

    for slug in collisions:
        result.pop(slug, None)

    return result


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_pricing_markdown(url: str = GITHUB_PRICING_URL, timeout: float = DEFAULT_TIMEOUT) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": "opencode-copilot-credit-estimator"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read().decode("utf-8")


def fetch_pricing_table(
    url: str = GITHUB_PRICING_URL, timeout: float = DEFAULT_TIMEOUT
) -> dict[str, PricingEntry]:
    md = fetch_pricing_markdown(url, timeout=timeout)
    return build_pricing_table(parse_markdown_tables(md))


# ---------------------------------------------------------------------------
# Snapshot cache (disk)
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def save_snapshot(path: str, table: dict[str, PricingEntry], source: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "source": source,
        "retrievedAt": _now_iso(),
        "pricing": {k: list(v) for k, v in table.items()},
    }
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp_path, path)


def load_snapshot(path: str) -> tuple[dict[str, PricingEntry], str | None, str | None] | None:
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return None
    raw_pricing = payload.get("pricing", {})
    table: dict[str, PricingEntry] = {}
    for k, v in raw_pricing.items():
        if isinstance(v, list) and len(v) == 4:
            table[k] = (v[0], v[1], v[2], v[3])
    return table, payload.get("retrievedAt"), payload.get("source")


def snapshot_age_seconds(retrieved_at: str | None) -> float:
    if not retrieved_at:
        return float("inf")
    try:
        dt = datetime.strptime(retrieved_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return float("inf")
    return (datetime.now(timezone.utc) - dt).total_seconds()


class PricingMeta(dict):
    """Small dict subclass just for a clearer type at call sites."""


def load_pricing(
    refresh: bool = True,
    timeout: float = DEFAULT_TIMEOUT,
    cache_path: str = CACHE_PATH,
    bundled_path: str = BUNDLED_SNAPSHOT_PATH,
    url: str = GITHUB_PRICING_URL,
) -> tuple[dict[str, PricingEntry], PricingMeta]:
    """
    Load the current GitHub Copilot pricing table.

    Resolution order:
    1. On-disk cache (`cache_path`), if present.
    2. Bundled snapshot committed to the repo (`bundled_path`), if no cache.
    3. If `refresh` is True and the resolved snapshot is missing or older
       than `STALE_AFTER_SECONDS`, attempt a live fetch + parse. On success,
       the result is cached to `cache_path` and returned. On any failure
       (network, parsing), the previously-resolved table is kept as-is —
       pricing never disappears just because the network is unavailable.

    Returns `(table, meta)` where `meta` has `source` and `retrieved_at`.
    """
    table: dict[str, PricingEntry] = {}
    retrieved_at: str | None = None
    source: str | None = None

    cached = load_snapshot(cache_path)
    if cached:
        table, retrieved_at, source = cached
    else:
        bundled = load_snapshot(bundled_path)
        if bundled:
            table, retrieved_at, source = bundled

    is_stale = not table or snapshot_age_seconds(retrieved_at) > STALE_AFTER_SECONDS
    if refresh and is_stale:
        try:
            fresh_table = fetch_pricing_table(url=url, timeout=timeout)
            if fresh_table:
                save_snapshot(cache_path, fresh_table, url)
                table, retrieved_at, source = fresh_table, _now_iso(), url
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            pass  # keep whatever we already resolved

    return table, PricingMeta(source=source, retrieved_at=retrieved_at)


# ---------------------------------------------------------------------------
# Maintainer CLI: regenerate the bundled snapshot committed to the repo
# ---------------------------------------------------------------------------

def _update_bundled_snapshot() -> None:
    table = fetch_pricing_table()
    save_snapshot(BUNDLED_SNAPSHOT_PATH, table, GITHUB_PRICING_URL)
    print(f"Wrote {len(table)} models to {BUNDLED_SNAPSHOT_PATH}")


if __name__ == "__main__":
    import sys

    if "--update-snapshot" in sys.argv:
        _update_bundled_snapshot()
    else:
        print(__doc__)
        print("Run with --update-snapshot to refresh the bundled pricing snapshot.")
