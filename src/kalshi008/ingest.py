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


def fetch_series(client: KalshiClient) -> dict[str, dict]:
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
    if series_index:
        parts = market_ticker.split("-")
        for k in range(len(parts), 0, -1):
            cand = "-".join(parts[:k])
            if cand in series_index:
                return cand
    return market_ticker.split("-", 1)[0]


CENSUS_FIELDS = (
    "ticker", "event_ticker", "series_ticker", "result", "status",
    "open_time", "close_time", "settlement_ts",
    "volume_fp", "mve_collection_ticker",
    "settlement_value_dollars", "notional_value_dollars",
)


def _slim(m: dict, series_index: dict | None = None) -> dict:
    d = {k: m.get(k) for k in CENSUS_FIELDS if k != "series_ticker"}
    d["series_ticker"] = series_ticker_of(m.get("ticker", ""), series_index)
    return d


def is_combo(m: dict) -> bool:
    return bool(m.get("mve_collection_ticker") or m.get("mve_selected_legs"))


def census_archive_tier(
    client: KalshiClient, max_pages: int | None = None, progress: Any = None
) -> Iterator[dict]:
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


def event_sample_score(event_ticker: str, seed: int = SAMPLE_SEED) -> float:
    h = hashlib.sha256(f"{seed}:{event_ticker}".encode("utf8")).digest()
    return int.from_bytes(h[:8], "big") / float(1 << 64)


def select_events(event_tickers: Iterable[str], n_target: int, seed: int = SAMPLE_SEED) -> set[str]:
    scored = sorted(((event_sample_score(e, seed), e) for e in set(event_tickers)))
    return {e for _, e in scored[:n_target]}


def select_events_stratified(
    events_by_category: dict[str, list[str]], per_category: int, seed: int = SAMPLE_SEED
) -> set[str]:
    out: set[str] = set()
    for cat, evs in events_by_category.items():
        out |= select_events(evs, per_category, seed)
    return out


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
