import math

from kalshi008 import fees
from kalshi008.config import BUCKET_EDGES


def test_formula_reproduces_every_published_row():
    assert fees.verify_against_published_table() == []


def test_constants_match_the_primary_source():
    assert fees.TAKER_COEFFICIENT == 0.07
    assert fees.MAKER_COEFFICIENT == 0.0175
    assert fees.DEFAULT_TAKER_MULTIPLIER == 1.0
    assert fees.DEFAULT_MAKER_MULTIPLIER == 0.0
    assert fees.SETTLEMENT_FEE_DOLLARS == 0.0


def test_peak_fee_is_1_75_percent_not_7_percent():
    peak = max(
        fees.TAKER_COEFFICIENT * (p / 100) * (1 - p / 100) for p in range(0, 101)
    )
    assert math.isclose(peak, 0.0175, rel_tol=1e-12)


def test_fee_is_symmetric_in_yes_and_no():
    for p in (0.01, 0.13, 0.37, 0.5, 0.62, 0.88, 0.99):
        assert math.isclose(
            fees.fee_equivalent_price_error_cents(p * 100),
            fees.fee_equivalent_price_error_cents((1 - p) * 100),
            rel_tol=1e-12,
        )


def test_bucket_floors_peak_in_the_middle_and_vanish_at_the_extremes():
    floors = fees.bucket_fee_floors(BUCKET_EDGES)
    assert len(floors) == 10
    mids = [f.floor_at_midpoint_cents for f in floors]
    assert math.isclose(max(mids), 1.7325, abs_tol=1e-9)
    assert math.isclose(mids[0], 0.3325, abs_tol=1e-9)
    assert math.isclose(mids[-1], 0.3325, abs_tol=1e-9)
    assert mids[0] < mids[4] and mids[-1] < mids[5]


def test_zero_multiplier_series_have_no_fee_floor():
    assert fees.fee_equivalent_price_error_cents(50.0, multiplier=0.0) == 0.0


def test_two_leg_floor_is_exactly_double():
    for p in (5.0, 25.0, 50.0, 75.0, 95.0):
        one = fees.fee_equivalent_price_error_cents(p, legs=1)
        two = fees.fee_equivalent_price_error_cents(p, legs=2)
        assert math.isclose(two, 2 * one, rel_tol=1e-12)
