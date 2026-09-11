from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Sequence

from .buckets import bucket_index
from .config import HORIZONS
from .ingest import Candle


class ExclusionReason:
    DID_NOT_EXIST = "did_not_exist_at_horizon"
    NO_CANDLE = "no_candle_at_or_before_horizon"
    NO_TRADE = "no_trade_at_or_before_horizon"
    EMPTY_BOOK = "both_book_sides_empty"
    NO_BOOK = "no_book_quote"
    GATE_FAILED = "timestamp_gate_failed"
    OUT_OF_RANGE = "mid_out_of_price_range"


@dataclass(frozen=True)
class Snapshot:
    ticker: str
    event_ticker: str
    series_ticker: str
    category: str
    horizon: str
    target_ts: int
    source_candle_ts: int
    staleness_s: int
    mid_cents: float
    bucket: int
    outcome: int
    one_sided_book: bool
    yes_bid_cents: float
    yes_ask_cents: float
    spread_cents: float
    close_ts: int
    settlement_ts: int
    fee_multiplier: float

    def to_dict(self) -> dict:
        return asdict(self)


def gate_strictly_before(source_candle_ts: int, settlement_ts: int, horizon_seconds: int) -> bool:
    return source_candle_ts < settlement_ts - horizon_seconds


def latest_candle_at_or_before(candles: Sequence[Candle], target_ts: int, not_before: int) -> Candle | None:
    best: Candle | None = None
    for c in candles:
        if c.end_ts <= target_ts and c.end_ts >= not_before:
            if best is None or c.end_ts > best.end_ts:
                best = c
    return best


def cumulative_volume_at_or_before(
    candles: Sequence[Candle],
    target_ts: int,
    fine: Sequence[Candle] | None = None,
) -> float:
    coarse_cut = -1
    total = 0.0
    for c in candles:
        if c.end_ts <= target_ts:
            total += c.volume
            if c.end_ts > coarse_cut:
                coarse_cut = c.end_ts
    if fine:
        for c in fine:
            if coarse_cut < c.end_ts <= target_ts:
                total += c.volume
    return total


def snapshots_for_market(
    market: dict,
    candles: Sequence[Candle],
    category: str,
    fee_multiplier: float,
    counters: dict[str, int] | None = None,
    fine_candles: Sequence[Candle] | None = None,
    fine_horizons: Sequence[str] = ("T-1h",),
) -> tuple[list[Snapshot], dict[str, int]]:
    reasons: dict[str, int] = counters if counters is not None else {}

    def bump(key: str) -> None:
        reasons[key] = reasons.get(key, 0) + 1

    open_ts = market["open_ts"]
    close_ts = market["close_ts"]
    settle_ts = market["settlement_ts_epoch"]
    outcome = 1 if market["result"] == "yes" else 0

    out: list[Snapshot] = []
    for hname, hsec in HORIZONS.items():
        target = close_ts - hsec

        if not (open_ts <= target < close_ts):
            bump(f"{hname}:{ExclusionReason.DID_NOT_EXIST}")
            continue

        source = candles
        if hname in fine_horizons and fine_candles:
            source = fine_candles
        c = latest_candle_at_or_before(source, target, open_ts)
        if c is None and source is not candles:
            c = latest_candle_at_or_before(candles, target, open_ts)
        if c is None:
            bump(f"{hname}:{ExclusionReason.NO_CANDLE}")
            continue

        if not gate_strictly_before(c.end_ts, settle_ts, hsec):
            bump(f"{hname}:{ExclusionReason.GATE_FAILED}")
            continue

        fine_for_vol = fine_candles if (hname in fine_horizons and fine_candles) else None
        if cumulative_volume_at_or_before(candles, target, fine_for_vol) <= 0.0:
            bump(f"{hname}:{ExclusionReason.NO_TRADE}")
            continue

        if not c.has_book:
            bump(f"{hname}:{ExclusionReason.NO_BOOK}")
            continue
        if c.both_sides_empty:
            bump(f"{hname}:{ExclusionReason.EMPTY_BOOK}")
            continue

        mid_cents = c.mid * 100.0
        b = bucket_index(mid_cents)
        if b < 0:
            bump(f"{hname}:{ExclusionReason.OUT_OF_RANGE}")
            continue

        out.append(
            Snapshot(
                ticker=market["ticker"],
                event_ticker=market["event_ticker"],
                series_ticker=market["series_ticker"],
                category=category,
                horizon=hname,
                target_ts=target,
                source_candle_ts=c.end_ts,
                staleness_s=target - c.end_ts,
                mid_cents=mid_cents,
                bucket=b,
                outcome=outcome,
                one_sided_book=(c.yes_bid <= 0.0 or c.yes_ask >= 1.0),
                yes_bid_cents=c.yes_bid * 100.0,
                yes_ask_cents=c.yes_ask * 100.0,
                spread_cents=(c.yes_ask - c.yes_bid) * 100.0,
                close_ts=close_ts,
                settlement_ts=settle_ts,
                fee_multiplier=fee_multiplier,
            )
        )
    return out, reasons


def audit_gate(snapshots: Sequence[Snapshot]) -> dict:
    violations = []
    max_margin = None
    for s in snapshots:
        hsec = HORIZONS[s.horizon]
        margin = (s.settlement_ts - hsec) - s.source_candle_ts
        if margin <= 0:
            violations.append(s.ticker)
        if max_margin is None or margin < max_margin:
            max_margin = margin
    return {
        "n_snapshots": len(snapshots),
        "n_violations": len(violations),
        "violating_tickers": violations[:20],
        "min_margin_seconds": max_margin,
        "passed": len(violations) == 0,
    }


def audit_close_before_settlement(markets: Sequence[dict]) -> dict:
    bad = [m["ticker"] for m in markets if m["close_ts"] > m["settlement_ts_epoch"]]
    return {
        "n_markets": len(markets),
        "n_close_after_settlement": len(bad),
        "examples": bad[:20],
        "passed": not bad,
    }
