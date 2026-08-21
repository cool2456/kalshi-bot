"""Ingestion: universe census, event sampling, and price snapshots.

Endpoint provenance (all verified live 2026-08-21, all unauthenticated):

  GET /series
        Every series in ONE unpaginated response (13,339 objects). Supplies
        `category` (s4's "Kalshi's own series categorisation"), `fee_type` and
        `fee_multiplier` (s6's per-series fee).

  GET /historical/markets?mve_filter=exclude
        The ARCHIVE tier: markets settled before /historical/cutoff
        (market_settled_ts = 2026-06-22T00:00:00Z). Cursor paging only --
        min_close_ts / max_close_ts / status are ACCEPTED BUT SILENTLY IGNORED here.
        `series_ticker` and `mve_filter` are mutually exclusive.

  GET /markets?status=settled&mve_filter=exclude&min_close_ts=..&max_close_ts=..
        The LIVE tier: markets settled after the cutoff. Time filters DO work here.

  GET /series/{series}/markets/{ticker}/candlesticks     (live tier)
  GET /historical/markets/{ticker}/candlesticks          (archive tier)
        Prices. NOTE the two tiers use DIFFERENT FIELD NAMES for identical data:
        live `price.close_dollars` / `volume_fp` / `open_interest_fp`
        archive `price.close`      / `volume`    / `open_interest`
        and the archive tier writes explicit JSON nulls where the live tier omits keys.
        normalise_candle() below folds both into one shape.

The two tiers overlap for markets settled 2026-06-15..2026-06-22, so markets are
deduplicated on `ticker`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from dataclasses import dataclass, asdict
from typing import Any, Iterable, Iterator

from .api import KalshiClient, KalshiAPIUnreachable
from .categories import to_prereg_category
from .config import CACHE_DIR, DERIVED_DIR, EXCLUDE_MVE_COMBOS, SAMPLE_SEED

UTC = dt.timezone.utc


def parse_ts(s: str | None) -> int | None:
    """Parse a Kalshi RFC3339 timestamp to unix seconds."""
    if not s:
        return None
    try:
        return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def iso(ts: int | None) -> str | None:
    if ts is None:
        return None
    return dt.datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------

def fetch_series(client: KalshiClient) -> dict[str, dict]:
    """All series keyed by ticker. One request; the endpoint is not paginated."""
    payload = client.get("/series")
    out: dict[str, dict] = {}
    for s in payload.get("series", []):
        out[s["ticker"]] = {
            "ticker": s["ticker"],
            "kalshi_category": s.get("category"),
            "category": to_prereg_category(s.get("category")),
            "title": s.get("title"),
            "fee_type": s.get("fee_type"),
            "fee_multiplier": s.get("fee_multiplier"),
            "frequency": s.get("frequency"),
        }
    return out


def series_ticker_of(market_ticker: str, series_index: dict | None = None) -> str:
    """Resolve a market ticker to its series.

    Market tickers are SERIES-EVENTSUFFIX-STRIKE, so the head before the first hyphen is
    usually the series. But 151 of Kalshi's 13,339 series tickers CONTAIN a hyphen
    themselves, and for 63 of them the first-hyphen head is not a series at all -- those
    markets would silently get category "Other" and the default fee multiplier.

    When the series index is supplied, the longest hyphen-delimited prefix that is a real
    series wins. The index is already resident during ingestion, so this costs nothing.
    """
    if series_index:
        parts = market_ticker.split("-")
        for k in range(len(parts), 0, -1):
            cand = "-".join(parts[:k])
            if cand in series_index:
                return cand
    return market_ticker.split("-", 1)[0]


# ---------------------------------------------------------------------------
# Market census
# ---------------------------------------------------------------------------

CENSUS_FIELDS = (
    "ticker", "event_ticker", "series_ticker", "result", "status",
    "open_time", "close_time", "settlement_ts",
    "volume_fp", "mve_collection_ticker",
    "settlement_value_dollars", "notional_value_dollars",
)
"""Deliberately minimal. The census holds ~1.7M rows, so every field costs ~200 MB of
process memory if held in RAM and tens of megabytes on disk. `title`, `rules_primary`
and the strike fields are omitted: nothing downstream needs them, and the Step 2
hand-check re-fetches each sampled market individually anyway."""


def _slim(m: dict, series_index: dict | None = None) -> dict:
    d = {k: m.get(k) for k in CENSUS_FIELDS if k != "series_ticker"}
    d["series_ticker"] = series_ticker_of(m.get("ticker", ""), series_index)
    return d


def is_combo(m: dict) -> bool:
    """MVE combo parlay. `mve_collection_ticker` is the reliable marker --
    `exchange_index` is NOT: archived combos were observed with exchange_index == 0."""
    return bool(m.get("mve_collection_ticker") or m.get("mve_selected_legs"))


def census_archive_tier(
    client: KalshiClient, max_pages: int | None = None, progress: Any = None
) -> Iterator[dict]:
    """Every non-combo market settled before the historical cutoff."""
    path = "/historical/markets?mve_filter=exclude" if EXCLUDE_MVE_COMBOS else "/historical/markets"
    n = 0
    for page in client.paginate(path, "markets", limit=1000, max_pages=max_pages):
        for m in page:
            n += 1
            yield _slim(m)
        if progress:
            progress(n, "archive")


def census_live_tier(
    client: KalshiClient,
    min_close_ts: int,
    max_close_ts: int,
    max_pages: int | None = None,
    progress: Any = None,
) -> Iterator[dict]:
    """Every non-combo settled market whose close_time falls in the window.

    The live tier honours min_close_ts / max_close_ts, unlike the archive tier. The
    window is walked in day-sized slices because a single cursor walk over the live
    tier is dominated by minute-scale ladder markets.
    """
    mve = "&mve_filter=exclude" if EXCLUDE_MVE_COMBOS else ""
    n = 0
    day = 86400
    lo = min_close_ts
    while lo < max_close_ts:
        hi = min(lo + day, max_close_ts)
        path = f"/markets?status=settled{mve}&min_close_ts={lo}&max_close_ts={hi}"
        for page in client.paginate(path, "markets", limit=1000, max_pages=max_pages):
            for m in page:
                n += 1
                yield _slim(m)
        if progress:
            progress(n, f"live {iso(lo)}")
        lo = hi


# ---------------------------------------------------------------------------
# Outcome-blind event sampling (DECISIONS_008 decision 1)
# ---------------------------------------------------------------------------

def event_sample_score(event_ticker: str, seed: int = SAMPLE_SEED) -> float:
    """Deterministic uniform score in [0,1) from the event ticker alone.

    Depends on NOTHING but the event ticker and a fixed seed -- not on outcome, price,
    liquidity, volume, category or date. Sampling on this cannot select on outcome.
    """
    h = hashlib.sha256(f"{seed}:{event_ticker}".encode("utf8")).digest()
    return int.from_bytes(h[:8], "big") / float(1 << 64)


def select_events(event_tickers: Iterable[str], n_target: int, seed: int = SAMPLE_SEED) -> set[str]:
    """Take the n_target events with the smallest hash score. Stable and reproducible."""
    scored = sorted(((event_sample_score(e, seed), e) for e in set(event_tickers)))
    return {e for _, e in scored[:n_target]}


def select_events_stratified(
    events_by_category: dict[str, list[str]], per_category: int, seed: int = SAMPLE_SEED
) -> set[str]:
    """Take up to per_category events from each of the six categories.

    Stratification is on category, which is a property of the series and is known before
    any outcome is joined. It equalises statistical power across the six categories that
    s4 requires reported, instead of letting Sports (3,472 series) swamp Weather (354).
    """
    out: set[str] = set()
    for cat, evs in events_by_category.items():
        out |= select_events(evs, per_category, seed)
    return out


# ---------------------------------------------------------------------------
# Candlesticks
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Candle:
    end_ts: int
    yes_bid: float | None
    yes_ask: float | None
    trade_close: float | None
    volume: float

    @property
    def has_book(self) -> bool:
        return self.yes_bid is not None and self.yes_ask is not None

    @property
    def both_sides_empty(self) -> bool:
        """bid == 0.0000 AND ask == 1.0000: no quotes on either side of the book.

        DECISIONS_008 decision 5: this is the only case excluded. A one-sided book is
        kept, because dropping it would be filtering on liquidity, which s2 forbids.
        """
        return (
            self.yes_bid is not None and self.yes_ask is not None
            and self.yes_bid <= 0.0 and self.yes_ask >= 1.0
        )

    @property
    def mid(self) -> float | None:
        if not self.has_book:
            return None
        return (self.yes_bid + self.yes_ask) / 2.0


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def normalise_candle(raw: dict) -> Candle:
    """Fold the live and archive candlestick schemas into one shape.

    live    : price.close_dollars, volume_fp, yes_bid.close_dollars
    archive : price.close,         volume,    yes_bid.close        (explicit nulls)
    """
    price = raw.get("price") or {}
    bid = raw.get("yes_bid") or {}
    ask = raw.get("yes_ask") or {}
    return Candle(
        end_ts=int(raw["end_period_ts"]),
        yes_bid=_f(bid.get("close_dollars", bid.get("close"))),
        yes_ask=_f(ask.get("close_dollars", ask.get("close"))),
        trade_close=_f(price.get("close_dollars", price.get("close"))),
        volume=_f(raw.get("volume_fp", raw.get("volume"))) or 0.0,
    )


def fetch_candles(
    client: KalshiClient,
    market: dict,
    start_ts: int,
    end_ts: int,
    period_minutes: int,
    cutoff_ts: int,
) -> list[Candle]:
    """Fetch candles for one market, routing to the correct tier and falling back.

    `include_latest_before_start` is deliberately NOT used. It returns a candle stamped
    at the requested instant rather than at the real source candle's timestamp, which
    would defeat the Step 3 gate; and it is unavailable on the archive tier. The same
    widen-the-window rule is used on both tiers so the eras are treated identically.
    """
    settled = parse_ts(market.get("settlement_ts")) or parse_ts(market.get("close_time")) or 0
    ticker = market["ticker"]
    series = market.get("series_ticker") or series_ticker_of(ticker)
    q = f"start_ts={start_ts}&end_ts={end_ts}&period_interval={period_minutes}"

    live_path = f"/series/{series}/markets/{ticker}/candlesticks?{q}"
    arch_path = f"/historical/markets/{ticker}/candlesticks?{q}"
    order = [live_path, arch_path] if settled >= cutoff_ts else [arch_path, live_path]

    for path in order:
        try:
            payload = client.get(path, allow_404=True)
        except KalshiAPIUnreachable:
            payload = None
        if payload and payload.get("candlesticks"):
            return [normalise_candle(c) for c in payload["candlesticks"]]
    return []


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def write_jsonl(path: str, rows: Iterable[dict]) -> int:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    n = 0
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
            n += 1
    return n


def read_jsonl(path: str) -> Iterator[dict]:
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)
