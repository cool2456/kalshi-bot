"""BUILD step 3's gate -- the one most likely to fabricate a result.

    "assert that every price used at horizon H is timestamped strictly before
     settlement minus H. A snapshot taken even slightly late captures information the
     market had already absorbed and manufactures apparent miscalibration.
     Test with a fixture containing a market that settled early."
"""
import pytest

from kalshi008.config import HORIZONS
from kalshi008.horizons import (
    ExclusionReason, audit_close_before_settlement, audit_gate, gate_strictly_before,
    latest_candle_at_or_before, snapshots_for_market,
)
from kalshi008.ingest import Candle

HOUR = 3600
DAY = 86400


def mk_market(ticker="M", open_ts=0, close_ts=10 * DAY, settle_ts=None, result="yes"):
    return dict(
        ticker=ticker, event_ticker="E1", series_ticker="S1",
        open_ts=open_ts, close_ts=close_ts,
        settlement_ts_epoch=close_ts + 1800 if settle_ts is None else settle_ts,
        result=result,
    )


def hourly(open_ts, close_ts, bid=0.40, ask=0.42, vol=5.0):
    return [
        Candle(end_ts=t, yes_bid=bid, yes_ask=ask, trade_close=(bid + ask) / 2, volume=vol)
        for t in range(open_ts, close_ts + 1, HOUR)
    ]


# --------------------------------------------------------------------------
# the gate itself
# --------------------------------------------------------------------------

def test_gate_is_strict_not_inclusive():
    settle, h = 1_000_000, HOUR
    assert gate_strictly_before(settle - h - 1, settle, h) is True
    assert gate_strictly_before(settle - h, settle, h) is False       # exactly at: rejected
    assert gate_strictly_before(settle - h + 1, settle, h) is False   # after: rejected


def test_snapshot_never_uses_a_candle_after_the_horizon():
    m = mk_market()
    cs = hourly(m["open_ts"], m["close_ts"])
    snaps, _ = snapshots_for_market(m, cs, "Sports", 1.0)
    assert len(snaps) == 3
    for s in snaps:
        assert s.source_candle_ts <= s.target_ts
        assert s.staleness_s >= 0
        assert s.source_candle_ts < s.settlement_ts - HORIZONS[s.horizon]
    assert audit_gate(snaps)["passed"]


def test_a_candle_after_the_horizon_is_never_selected():
    """Explicitly plant a much better-looking candle AFTER the horizon."""
    m = mk_market()
    target = m["close_ts"] - DAY
    cs = [
        Candle(end_ts=target - HOUR, yes_bid=0.30, yes_ask=0.32, trade_close=0.31, volume=1.0),
        Candle(end_ts=target + HOUR, yes_bid=0.95, yes_ask=0.97, trade_close=0.96, volume=1.0),
    ]
    c = latest_candle_at_or_before(cs, target, m["open_ts"])
    assert c.end_ts == target - HOUR
    assert c.yes_bid == 0.30


# --------------------------------------------------------------------------
# the required early-settlement fixture
# --------------------------------------------------------------------------

def test_market_that_settled_early_does_not_leak_information():
    """A market whose outcome became known -- and which closed -- long before its
    scheduled expiration.

    Trading stops at close_ts. T = close_ts, so all three horizons sit inside the live
    trading window and none of them can pick up a post-resolution quote. The candles
    after close (a frozen book at 0.99/1.00) must never be selected.
    """
    close = 30 * DAY
    m = mk_market(open_ts=0, close_ts=close, settle_ts=close + 45 * 60)
    live = hourly(0, close)
    dead = [                       # post-close frozen book: the outcome is known here
        Candle(end_ts=close + i * HOUR, yes_bid=0.99, yes_ask=1.00, trade_close=1.00, volume=0.0)
        for i in range(1, 6)
    ]
    snaps, _ = snapshots_for_market(m, live + dead, "Politics", 1.0)
    assert len(snaps) == 3
    for s in snaps:
        assert s.source_candle_ts <= close - HORIZONS[s.horizon]
        assert s.mid_cents == pytest.approx(41.0)     # never the 99.5 dead quote
    assert audit_gate(snaps)["passed"]


def test_settlement_lag_longer_than_the_horizon_still_passes_the_gate():
    """If settlement lags close by days, T = close_ts keeps every horizon safe.

    This is the case that would break a settlement-anchored T: T_settle - 1h would fall
    AFTER the book closed.
    """
    close = 20 * DAY
    m = mk_market(open_ts=0, close_ts=close, settle_ts=close + 3 * DAY)
    snaps, _ = snapshots_for_market(m, hourly(0, close), "Economics", 1.0)
    assert len(snaps) == 3
    audit = audit_gate(snaps)
    assert audit["passed"]
    assert audit["min_margin_seconds"] >= 3 * DAY


def test_close_after_settlement_would_be_caught():
    good = [dict(ticker="A", close_ts=100, settlement_ts_epoch=200)]
    bad = [dict(ticker="B", close_ts=300, settlement_ts_epoch=200)]
    assert audit_close_before_settlement(good)["passed"]
    assert not audit_close_before_settlement(bad)["passed"]


# --------------------------------------------------------------------------
# per-horizon exclusions (s3, decisions 5/7/13)
# --------------------------------------------------------------------------

def test_short_lived_market_is_excluded_from_the_long_horizon_only():
    """s3: excluded "from that horizon only"."""
    close = 3 * DAY
    m = mk_market(open_ts=0, close_ts=close)
    snaps, reasons = snapshots_for_market(m, hourly(0, close), "Crypto", 1.0)
    got = {s.horizon for s in snaps}
    assert got == {"T-24h", "T-1h"}
    assert reasons[f"T-7d:{ExclusionReason.DID_NOT_EXIST}"] == 1


def test_both_sides_empty_book_is_excluded_one_sided_is_kept():
    """Decision 5. bid 0.0000 AND ask 1.0000 is no price at all; one-sided is a price."""
    close = 10 * DAY
    m = mk_market(open_ts=0, close_ts=close)

    empty = [Candle(end_ts=t, yes_bid=0.0, yes_ask=1.0, trade_close=None, volume=3.0)
             for t in range(0, close + 1, HOUR)]
    snaps, reasons = snapshots_for_market(m, empty, "Other", 1.0)
    assert snaps == []
    assert reasons[f"T-1h:{ExclusionReason.EMPTY_BOOK}"] == 1

    one_sided = [Candle(end_ts=t, yes_bid=0.0, yes_ask=0.01, trade_close=0.01, volume=3.0)
                 for t in range(0, close + 1, HOUR)]
    snaps2, _ = snapshots_for_market(m, one_sided, "Other", 1.0)
    assert len(snaps2) == 3
    assert all(s.one_sided_book for s in snaps2)
    assert all(s.bucket == 0 for s in snaps2)          # 0.5c -> [0,10)
    assert snaps2[0].mid_cents == pytest.approx(0.5)


def test_market_with_no_trade_before_the_horizon_is_excluded_there():
    """Decision 7: cumulative volume must be > 0 at or before H."""
    close = 10 * DAY
    m = mk_market(open_ts=0, close_ts=close)
    cs = []
    for t in range(0, close + 1, HOUR):
        # zero volume until 12 hours before close, then it starts trading
        v = 0.0 if t < close - 12 * HOUR else 4.0
        cs.append(Candle(end_ts=t, yes_bid=0.40, yes_ask=0.42, trade_close=0.41, volume=v))
    snaps, reasons = snapshots_for_market(m, cs, "Weather", 1.0)
    assert {s.horizon for s in snaps} == {"T-1h"}
    assert reasons[f"T-7d:{ExclusionReason.NO_TRADE}"] == 1
    assert reasons[f"T-24h:{ExclusionReason.NO_TRADE}"] == 1


def test_staleness_is_recorded_and_carried_forward_within_the_market_life():
    """Candles are sparse. The snapshot carries forward, and the age is recorded."""
    close = 10 * DAY
    m = mk_market(open_ts=0, close_ts=close)
    target = close - DAY
    cs = [Candle(end_ts=0, yes_bid=0.40, yes_ask=0.42, trade_close=0.41, volume=9.0),
          Candle(end_ts=target - 5 * HOUR, yes_bid=0.55, yes_ask=0.57, trade_close=0.56, volume=2.0)]
    snaps, _ = snapshots_for_market(m, cs, "Sports", 1.0)
    by_h = {s.horizon: s for s in snaps}
    assert by_h["T-24h"].staleness_s == 5 * HOUR
    assert by_h["T-24h"].mid_cents == pytest.approx(56.0)


def test_quote_from_before_the_market_opened_is_never_used():
    close = 10 * DAY
    m = mk_market(open_ts=5 * DAY, close_ts=close)
    stale = [Candle(end_ts=DAY, yes_bid=0.90, yes_ask=0.92, trade_close=0.91, volume=1.0)]
    assert latest_candle_at_or_before(stale, close - DAY, m["open_ts"]) is None
    snaps, reasons = snapshots_for_market(m, stale, "Sports", 1.0)
    assert snaps == []
    assert reasons[f"T-24h:{ExclusionReason.NO_CANDLE}"] == 1


def test_step4_gate_reports_not_passed_when_it_checked_nothing():
    """BUILD_PROMPT: "Do not report a gate as passed without running it.\""""
    from kalshi008.gates import gate_mutually_exclusive_events
    g = gate_mutually_exclusive_events({}, [dict(ticker="a", event_ticker="E1", result="yes")])
    assert g.detail["exclusive_events_checked"] == 0
    assert g.detail["vacuous_no_events_checked"] is True
    assert not g.passed
    assert g.detail["events_skipped_no_metadata_fetched"] == 1


def test_step4_gate_passes_only_on_real_exclusive_events():
    from kalshi008.gates import gate_mutually_exclusive_events
    evs = {"E1": {"mutually_exclusive": True}, "E2": {"mutually_exclusive": False}}
    mk = [dict(ticker="a", event_ticker="E1", result="yes"),
          dict(ticker="b", event_ticker="E1", result="no"),
          dict(ticker="c", event_ticker="E2", result="yes"),
          dict(ticker="d", event_ticker="E2", result="yes")]
    g = gate_mutually_exclusive_events(evs, mk)
    assert g.passed
    assert g.detail["exclusive_events_checked"] == 1
    assert g.detail["events_skipped_not_mutually_exclusive"] == 1


def test_all_no_exclusive_event_is_not_a_violation():
    """Kalshi's flag means AT MOST one YES, not exactly one.

    A strike ladder whose settlement falls outside every listed band resolves all-NO
    legitimately -- verified on KXWTI-25MAY15 (15 bands, all NO, market list complete).
    """
    from kalshi008.gates import gate_mutually_exclusive_events
    evs = {"E1": {"mutually_exclusive": True}}
    mk = [dict(ticker=f"m{i}", event_ticker="E1", result="no") for i in range(15)]
    g = gate_mutually_exclusive_events(evs, mk)
    assert g.passed
    assert g.detail["violations"] == 0
    assert g.detail["exclusive_events_with_zero_yes"] == 1


def test_two_yes_in_one_exclusive_event_IS_a_violation():
    """Two YES in one exclusive event is what a wrong grouping looks like."""
    from kalshi008.gates import gate_mutually_exclusive_events
    evs = {"E1": {"mutually_exclusive": True}}
    mk = [dict(ticker="a", event_ticker="E1", result="yes"),
          dict(ticker="b", event_ticker="E1", result="yes"),
          dict(ticker="c", event_ticker="E1", result="no")]
    g = gate_mutually_exclusive_events(evs, mk)
    assert not g.passed
    assert g.detail["violations"] == 1
