"""Horizon snapshots and the Step 3 timestamp gate.

PREREG_008 s3 measures the mid price at T-7d, T-24h and T-1h. T is `close_time`
(DECISIONS_008 decision 4), the instant trading stops.

BUILD_PROMPT step 3 states the gate that matters most:

    "assert that every price used at horizon H is timestamped strictly before
     settlement minus H. A snapshot taken even slightly late captures information the
     market had already absorbed and manufactures apparent miscalibration."

That assertion is implemented in `gate_strictly_before()` and is checked for EVERY
snapshot the pipeline produces, not on a sample. A snapshot that fails is dropped and
counted; it never reaches a calibration cell.

Two independent conservatisms make the gate hard to fail by accident:
  1. T is `close_time`, and `close_time <= settlement_ts` on every market, so a price
     before `close_time - H` is necessarily before `settlement_ts - H`.
  2. The snapshot is the latest candle whose `end_period_ts <= T - H`, and
     `end_period_ts` is the INCLUSIVE END of that candle's interval (proven by matching
     trades to candles: a trade 32 ms before a minute boundary lands in the candle whose
     end_period_ts is the ceiling). So the quote is the book state at or before T - H.
"""

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
    target_ts: int          # T - H
    source_candle_ts: int   # the REAL end_period_ts used; never a synthetic stamp
    staleness_s: int        # target_ts - source_candle_ts, >= 0
    mid_cents: float
    bucket: int
    outcome: int            # 1 if settled yes, 0 if no
    one_sided_book: bool
    yes_bid_cents: float    # the book at the snapshot, kept for diagnosis
    yes_ask_cents: float
    spread_cents: float
    close_ts: int
    settlement_ts: int
    fee_multiplier: float

    def to_dict(self) -> dict:
        return asdict(self)


def gate_strictly_before(source_candle_ts: int, settlement_ts: int, horizon_seconds: int) -> bool:
    """BUILD step 3's gate: the price must be timestamped STRICTLY before T_settle - H.

    Strict, not `<=`. A candle stamped exactly at `settlement_ts - H` closes at that
    instant and therefore includes the instant itself.
    """
    return source_candle_ts < settlement_ts - horizon_seconds


def latest_candle_at_or_before(candles: Sequence[Candle], target_ts: int, not_before: int) -> Candle | None:
    """The latest candle with `not_before <= end_ts <= target_ts`.

    Candles are emitted only when something changes, so an exact hit at `target_ts` is
    the exception. `not_before` is the market's open_time: a quote from before the market
    existed is not a quote for this market.
    """
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
    """Traded volume recorded at or before the horizon (DECISIONS_008 decision 7).

    A candle's `end_period_ts` is the INCLUSIVE END of its interval, so counting only
    candles with `end_ts <= target_ts` can never include volume that occurred after the
    horizon -- there is no straddling candle to leak.

    But that also means the hourly series stops at the last whole-hour boundary at or
    before the horizon, leaving a ragged sub-hour window uncounted. At T-1h that window
    is up to 59 minutes wide, so a market whose FIRST trade lands in it would be wrongly
    excluded for "no trade". When a finer series is supplied its volume in that remaining
    window is added.
    """
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
    """Produce up to three snapshots for one market, one per horizon.

    s3: "Markets that did not exist or had no trades at a given horizon are excluded
    from THAT HORIZON ONLY". Each horizon is evaluated independently.

    `candles` are 60-minute candles spanning the market's life. They serve T-7d and
    T-24h, where an at-most-59-minute carry-forward is negligible against horizons of
    7 days and 24 hours, and they are the source for the cumulative-volume test at every
    horizon (they cover the whole life; the fine series does not).

    `fine_candles` are 1-MINUTE candles covering a short window ending at T-1h. They are
    required for the T-1h snapshot: with hourly candles a market closing at 15:30 would
    take its "T-1h" price from 14:00 -- effectively T-1h30m -- and a market that lived
    less than two hours would have no hourly candle at or before T-1h at all. Both would
    corrupt precisely the horizon s8 already flags as artifact-prone.
    """
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

        # (a) the market must have existed at the horizon
        if not (open_ts <= target < close_ts):
            bump(f"{hname}:{ExclusionReason.DID_NOT_EXIST}")
            continue

        # (b) a real candle at or before the horizon, inside the market's life.
        # Short horizons use the 1-minute series where it is available.
        source = candles
        if hname in fine_horizons and fine_candles:
            source = fine_candles
        c = latest_candle_at_or_before(source, target, open_ts)
        if c is None and source is not candles:
            c = latest_candle_at_or_before(candles, target, open_ts)
        if c is None:
            bump(f"{hname}:{ExclusionReason.NO_CANDLE}")
            continue

        # (c) the Step 3 gate, on the SOURCE candle's real timestamp
        if not gate_strictly_before(c.end_ts, settle_ts, hsec):
            bump(f"{hname}:{ExclusionReason.GATE_FAILED}")
            continue

        # (d) a trade recorded at or before the horizon
        fine_for_vol = fine_candles if (hname in fine_horizons and fine_candles) else None
        if cumulative_volume_at_or_before(candles, target, fine_for_vol) <= 0.0:
            bump(f"{hname}:{ExclusionReason.NO_TRADE}")
            continue

        # (e) a usable book. One-sided is KEPT; both-sides-empty is not a price.
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
    """Re-assert the Step 3 gate over produced snapshots. Reported, not assumed."""
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
    """Assert close_time <= settlement_ts, which is what makes T = close_time safe."""
    bad = [m["ticker"] for m in markets if m["close_ts"] > m["settlement_ts_epoch"]]
    return {
        "n_markets": len(markets),
        "n_close_after_settlement": len(bad),
        "examples": bad[:20],
        "passed": not bad,
    }
