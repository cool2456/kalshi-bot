import pytest

from kalshi008.categories import KALSHI_TO_PREREG, check_mapping_covers, to_prereg_category
from kalshi008.config import CATEGORIES
from kalshi008.ingest import (
    Candle, event_sample_score, is_combo, normalise_candle, parse_ts, select_events,
    series_ticker_of,
)

LIVE = {
    "end_period_ts": 1787061660, "open_interest_fp": "7.00",
    "price": {"close_dollars": "0.4300", "open_dollars": "0.3200"},
    "volume_fp": "12.00",
    "yes_bid": {"close_dollars": "0.3300"}, "yes_ask": {"close_dollars": "0.4200"},
}
ARCHIVE = {
    "end_period_ts": 1628179200, "open_interest": "0.00",
    "price": {"close": None, "open": None},
    "volume": "0.00",
    "yes_bid": {"close": "0.2000"}, "yes_ask": {"close": "0.7900"},
}


def test_live_and_archive_candles_fold_to_the_same_shape():
    a, b = normalise_candle(LIVE), normalise_candle(ARCHIVE)
    assert (a.yes_bid, a.yes_ask, a.trade_close, a.volume) == (0.33, 0.42, 0.43, 12.0)
    assert (b.yes_bid, b.yes_ask, b.trade_close, b.volume) == (0.20, 0.79, None, 0.0)
    assert a.mid == pytest.approx(0.375)
    assert b.mid == pytest.approx(0.495)


def test_no_trade_candle_still_yields_a_mid():
    live_no_trade = {"end_period_ts": 1, "price": {"previous_dollars": "0.43"},
                     "volume_fp": "0.00",
                     "yes_bid": {"close_dollars": "0.33"}, "yes_ask": {"close_dollars": "0.42"}}
    c = normalise_candle(live_no_trade)
    assert c.volume == 0.0
    assert c.trade_close is None
    assert c.mid == pytest.approx(0.375)


def test_empty_book_sentinels():
    both = normalise_candle({"end_period_ts": 1, "price": {}, "volume_fp": "0",
                             "yes_bid": {"close_dollars": "0.0000"},
                             "yes_ask": {"close_dollars": "1.0000"}})
    assert both.both_sides_empty
    one = normalise_candle({"end_period_ts": 1, "price": {}, "volume_fp": "0",
                            "yes_bid": {"close_dollars": "0.0000"},
                            "yes_ask": {"close_dollars": "0.0100"}})
    assert not one.both_sides_empty
    assert one.mid == pytest.approx(0.005)


def test_missing_book_side_gives_no_mid():
    c = normalise_candle({"end_period_ts": 1, "price": {}, "volume_fp": "0",
                          "yes_bid": {}, "yes_ask": {}})
    assert not c.has_book
    assert c.mid is None


def test_combo_detection_uses_mve_fields_not_exchange_index():
    archived_combo = {"exchange_index": 0, "mve_collection_ticker": "KXMVESPORTS-R"}
    ordinary = {"exchange_index": 1}
    assert is_combo(archived_combo)
    assert not is_combo(ordinary)
    assert is_combo({"mve_selected_legs": [{"market_ticker": "X"}]})


def test_sample_score_depends_on_nothing_but_ticker_and_seed():
    a = event_sample_score("KXHIGHNY-26AUG19")
    assert a == event_sample_score("KXHIGHNY-26AUG19")
    assert a != event_sample_score("KXHIGHNY-26AUG20")
    assert a != event_sample_score("KXHIGHNY-26AUG19", seed=1)
    assert 0.0 <= a < 1.0


def test_sample_is_stable_and_roughly_uniform():
    evs = [f"E-{i}" for i in range(5000)]
    s1 = select_events(evs, 500)
    assert len(s1) == 500
    assert s1 == select_events(evs, 500)
    deciles = {int(e.split("-")[1]) // 500 for e in s1}
    assert len(deciles) >= 8


def test_series_ticker_is_the_head_of_the_market_ticker():
    assert series_ticker_of("KXHIGHNY-26JUN14-T92") == "KXHIGHNY"
    assert series_ticker_of("HIGHNY-21AUG06-T86") == "HIGHNY"


def test_timestamp_parsing_handles_both_kalshi_formats():
    assert parse_ts("2026-06-15T04:59:00Z") == 1781499540
    assert parse_ts("2026-06-15T12:01:23.401074Z") is not None
    assert parse_ts(None) is None
    assert parse_ts("") is None


def test_every_mapping_target_is_one_of_the_six_frozen_categories():
    assert set(KALSHI_TO_PREREG.values()) <= set(CATEGORIES)


def test_the_contested_mappings_are_what_decisions_008_says():
    assert to_prereg_category("Elections") == "Politics"
    assert to_prereg_category("Mentions") == "Politics"
    assert to_prereg_category("Crypto") == "Financial"
    assert to_prereg_category("Financials") == "Financial"
    assert to_prereg_category("Commodities") == "Other"
    assert to_prereg_category("Companies") == "Other"
    assert to_prereg_category("Climate and Weather") == "Weather"


def test_an_unknown_category_falls_to_other_but_is_reported_not_silent():
    assert to_prereg_category("Brand New Kalshi Category") == "Other"
    assert check_mapping_covers({"Sports", "Brand New Kalshi Category"}) == [
        "Brand New Kalshi Category"
    ]
    assert check_mapping_covers({"Sports", "Politics"}) == []
