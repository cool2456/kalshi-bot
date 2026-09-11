from __future__ import annotations

import math
from dataclasses import dataclass

TAKER_COEFFICIENT = 0.07
MAKER_COEFFICIENT = 0.0175
DEFAULT_TAKER_MULTIPLIER = 1.0
DEFAULT_MAKER_MULTIPLIER = 0.0
SETTLEMENT_FEE_DOLLARS = 0.0

SCHEDULE_EFFECTIVE_DATE = "2026-07-07"
SCHEDULE_SOURCE_URL = "https://kalshi.com/docs/kalshi-fee-schedule.pdf"
SCHEDULE_RETRIEVED_DATE = "2026-08-21"


def taker_fee_dollars(price_dollars: float, contracts: int = 1, multiplier: float = DEFAULT_TAKER_MULTIPLIER) -> float:
    raw = multiplier * TAKER_COEFFICIENT * contracts * price_dollars * (1.0 - price_dollars)
    return math.ceil(raw * 100.0 - 1e-9) / 100.0


def maker_fee_dollars(price_dollars: float, contracts: int = 1, multiplier: float = DEFAULT_MAKER_MULTIPLIER) -> float:
    raw = multiplier * MAKER_COEFFICIENT * contracts * price_dollars * (1.0 - price_dollars)
    return math.ceil(raw * 100.0 - 1e-9) / 100.0


def fee_equivalent_price_error_cents(
    price_cents: float,
    multiplier: float = DEFAULT_TAKER_MULTIPLIER,
    legs: int = 1,
) -> float:
    if legs < 1:
        raise ValueError("legs must be >= 1")
    p = price_cents / 100.0
    return legs * multiplier * TAKER_COEFFICIENT * p * (1.0 - p) * 100.0


@dataclass(frozen=True)
class BucketFeeFloor:
    bucket_index: int
    low_cents: int
    high_cents: int
    midpoint_cents: float
    floor_at_midpoint_cents: float
    floor_at_low_edge_cents: float
    floor_at_high_edge_cents: float
    max_floor_in_bucket_cents: float


def bucket_fee_floors(
    bucket_edges: tuple[int, ...],
    multiplier: float = DEFAULT_TAKER_MULTIPLIER,
    legs: int = 1,
) -> list[BucketFeeFloor]:
    floors: list[BucketFeeFloor] = []
    for i in range(len(bucket_edges) - 1):
        lo, hi = bucket_edges[i], bucket_edges[i + 1]
        mid = (lo + hi) / 2.0
        f = lambda c: fee_equivalent_price_error_cents(c, multiplier=multiplier, legs=legs)
        if lo <= 50 <= hi:
            worst = f(50.0)
        else:
            worst = max(f(lo), f(hi))
        floors.append(
            BucketFeeFloor(
                bucket_index=i,
                low_cents=lo,
                high_cents=hi,
                midpoint_cents=mid,
                floor_at_midpoint_cents=f(mid),
                floor_at_low_edge_cents=f(lo),
                floor_at_high_edge_cents=f(hi),
                max_floor_in_bucket_cents=worst,
            )
        )
    return floors


PUBLISHED_GENERAL_FEE_TABLE: tuple[tuple[float, float, float], ...] = (
    (0.01, 0.01, 0.07),
    (0.05, 0.01, 0.34),
    (0.10, 0.01, 0.63),
    (0.15, 0.01, 0.90),
    (0.20, 0.02, 1.12),
    (0.25, 0.02, 1.32),
    (0.30, 0.02, 1.47),
    (0.35, 0.02, 1.60),
    (0.40, 0.02, 1.68),
    (0.45, 0.02, 1.74),
    (0.50, 0.02, 1.75),
    (0.55, 0.02, 1.74),
    (0.60, 0.02, 1.68),
    (0.65, 0.02, 1.60),
    (0.70, 0.02, 1.47),
    (0.75, 0.02, 1.32),
    (0.80, 0.02, 1.12),
    (0.85, 0.01, 0.90),
    (0.90, 0.01, 0.63),
    (0.95, 0.01, 0.34),
    (0.99, 0.01, 0.07),
)


def verify_against_published_table() -> list[str]:
    failures: list[str] = []
    for price, fee1, fee100 in PUBLISHED_GENERAL_FEE_TABLE:
        got1 = taker_fee_dollars(price, contracts=1)
        got100 = taker_fee_dollars(price, contracts=100)
        if abs(got1 - fee1) > 1e-9:
            failures.append(f"1 contract @ ${price:.2f}: published ${fee1:.2f}, formula ${got1:.2f}")
        if abs(got100 - fee100) > 1e-9:
            failures.append(f"100 contracts @ ${price:.2f}: published ${fee100:.2f}, formula ${got100:.2f}")
    return failures
