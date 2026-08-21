"""PREREG s3 fixes the bucket edges; DECISIONS decision 10a fixes the mechanics."""
import pytest

from kalshi008.buckets import BUCKET_EDGES, BUCKET_LABELS, N_BUCKETS, bucket_index


def test_ten_fixed_buckets_with_the_frozen_edges():
    assert BUCKET_EDGES == (0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
    assert N_BUCKETS == 10
    assert BUCKET_LABELS[0] == "[0,10)"
    assert BUCKET_LABELS[-1] == "[90,100]"


@pytest.mark.parametrize(
    "price,expected",
    [
        (0.0, 0), (0.5, 0), (9.99, 0),
        (10.0, 1), (19.999, 1),
        (50.0, 5), (59.5, 5),
        (89.999, 8),
        (90.0, 9), (99.5, 9), (100.0, 9),   # last bucket is CLOSED at 100
    ],
)
def test_half_open_buckets_and_closed_last_bucket(price, expected):
    assert bucket_index(price) == expected


def test_half_cent_mids_are_not_rounded_up():
    """Decision 10a: a 9c/10c book gives a 9.5c mid, which belongs to [0,10).

    Rounding to whole cents first would move it to [10,20) and would shift mass upward
    at all nine interior boundaries.
    """
    assert bucket_index(9.5) == 0
    assert bucket_index(19.5) == 1
    assert bucket_index(89.5) == 8
    assert bucket_index(99.5) == 9


def test_out_of_range_prices_are_rejected_not_clamped():
    assert bucket_index(-0.01) == -1
    assert bucket_index(100.01) == -1
