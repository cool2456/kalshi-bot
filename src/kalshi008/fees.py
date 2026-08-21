"""Kalshi fee schedule, verified from Kalshi's own published documentation.

Primary source
--------------
https://kalshi.com/docs/kalshi-fee-schedule.pdf
Document title : "Fee Schedule for July 2026  - 7.7.26 Update"
Page footer    : "Last updated and effective: July 7, 2026"
Retrieved      : 2026-08-21 (UTC)

Verbatim, from page 2 of that document:

    fees = round up(M x 0.07 x C x P x (1-P))
    P = the price of a contract in dollars (50 cents is 0.5)
    C = the number of contracts being traded
    M = the multiplier for each contract (default is 1 unless otherwise indicated)
    round up = rounds up such that the fee + positionCost is rounded to a centicent

    Maker Fees
    fees = round up(M x 0.0175 x C x P x (1-P))
    ... M = the multiplier for each contract (default is 0 unless otherwise indicated)

From page 3 of that document:

    Settlement Fees
    There is no settlement fee.

The full verbatim capture, including the general fee table used as the arithmetic
check below, lives in docs/sources/kalshi_fee_schedule_2026-07-07.md.

Nothing in this module is tuned, inferred or substituted. Every constant is quoted
from the primary source above.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Constants quoted verbatim from the primary source. Do not change these without
# re-verifying against kalshi.com/docs/kalshi-fee-schedule.pdf and updating
# docs/sources/kalshi_fee_schedule_2026-07-07.md.
# ---------------------------------------------------------------------------

TAKER_COEFFICIENT = 0.07
"""The 0.07 in `fees = round up(M x 0.07 x C x P x (1-P))`."""

MAKER_COEFFICIENT = 0.0175
"""The 0.0175 in `fees = round up(M x 0.0175 x C x P x (1-P))`."""

DEFAULT_TAKER_MULTIPLIER = 1.0
"""`M = the multiplier for each contract (default is 1 unless otherwise indicated)`."""

DEFAULT_MAKER_MULTIPLIER = 0.0
"""`M = the multiplier for each contract (default is 0 unless otherwise indicated)`."""

SETTLEMENT_FEE_DOLLARS = 0.0
"""`Settlement Fees / There is no settlement fee.`"""

SCHEDULE_EFFECTIVE_DATE = "2026-07-07"
SCHEDULE_SOURCE_URL = "https://kalshi.com/docs/kalshi-fee-schedule.pdf"
SCHEDULE_RETRIEVED_DATE = "2026-08-21"


def taker_fee_dollars(price_dollars: float, contracts: int = 1, multiplier: float = DEFAULT_TAKER_MULTIPLIER) -> float:
    """Kalshi taker (trading) fee in dollars, rounded up to the cent.

    `fees = round up(M x 0.07 x C x P x (1-P))`

    The source defines `round up` as rounding so that `fee + positionCost` lands on a
    centicent. For whole-cent contract prices -- which is what this study measures --
    that is indistinguishable from rounding the fee up to the next whole cent, and the
    published General Trading Fees Table is reproduced exactly by doing so. See
    `verify_against_published_table()`.
    """
    raw = multiplier * TAKER_COEFFICIENT * contracts * price_dollars * (1.0 - price_dollars)
    return math.ceil(raw * 100.0 - 1e-9) / 100.0


def maker_fee_dollars(price_dollars: float, contracts: int = 1, multiplier: float = DEFAULT_MAKER_MULTIPLIER) -> float:
    """Kalshi maker fee in dollars, rounded up to the cent.

    `fees = round up(M x 0.0175 x C x P x (1-P))`, with M defaulting to 0.
    """
    raw = multiplier * MAKER_COEFFICIENT * contracts * price_dollars * (1.0 - price_dollars)
    return math.ceil(raw * 100.0 - 1e-9) / 100.0


# ---------------------------------------------------------------------------
# Fee-equivalent price error (PREREG_008 s6).
# ---------------------------------------------------------------------------

def fee_equivalent_price_error_cents(
    price_cents: float,
    multiplier: float = DEFAULT_TAKER_MULTIPLIER,
    legs: int = 1,
) -> float:
    """The miscalibration, in cents of price, that a fee exactly cancels.

    A contract priced `P` dollars pays $1 on YES. A taker who buys it pays
    `0.07 * M * P * (1-P)` dollars in fee per contract, and -- because there is no
    settlement fee -- pays nothing further if the position is held to resolution.
    So the fee per contract, expressed in cents, IS the price error it cancels:
    the realized frequency must differ from the implied price by at least this many
    cents before the mispricing covers its own transaction cost.

    This is computed WITHOUT the round-up, because the round-up is a per-order
    artifact of order size (a 1-contract order pays a whole cent; a 1000-contract
    order pays the exact continuous amount per contract). The continuous form is the
    per-contract economic floor and is the conservative -- i.e. smaller -- choice.

    `legs` selects how many taker crossings the floor is charged for:
      legs=1 -- enter as taker, hold to settlement (settlement fee is zero).
      legs=2 -- enter as taker and exit as taker before settlement.
    See FINDINGS_008.md for which the reported analysis uses.
    """
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
    """Fee-equivalent price error for each PREREG_008 s3 price bucket.

    `bucket_edges` is the 11 fixed edges (0, 10, ..., 100). Reported at the bucket
    midpoint and at both edges, since `P*(1-P)` is not linear across a bucket.
    """
    floors: list[BucketFeeFloor] = []
    for i in range(len(bucket_edges) - 1):
        lo, hi = bucket_edges[i], bucket_edges[i + 1]
        mid = (lo + hi) / 2.0
        f = lambda c: fee_equivalent_price_error_cents(c, multiplier=multiplier, legs=legs)
        # P*(1-P) peaks at 50c; the max within a bucket is at 50c if the bucket
        # straddles it, otherwise at whichever edge is nearer 50c.
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


# ---------------------------------------------------------------------------
# Arithmetic check against Kalshi's own published General Trading Fees Table
# (pages 4-5 of the primary source). If this fails, the formula above is wrong.
# ---------------------------------------------------------------------------

PUBLISHED_GENERAL_FEE_TABLE: tuple[tuple[float, float, float], ...] = (
    # (price of 1 contract $, fee for 1 contract $, fee for 100 contracts $)
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
    """Recompute Kalshi's published table from the formula. Returns a list of failures."""
    failures: list[str] = []
    for price, fee1, fee100 in PUBLISHED_GENERAL_FEE_TABLE:
        got1 = taker_fee_dollars(price, contracts=1)
        got100 = taker_fee_dollars(price, contracts=100)
        if abs(got1 - fee1) > 1e-9:
            failures.append(f"1 contract @ ${price:.2f}: published ${fee1:.2f}, formula ${got1:.2f}")
        if abs(got100 - fee100) > 1e-9:
            failures.append(f"100 contracts @ ${price:.2f}: published ${fee100:.2f}, formula ${got100:.2f}")
    return failures
