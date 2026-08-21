"""Frozen parameters (PREREG_008 s7) and the resolved specification gaps.

Everything in the FROZEN block is quoted from PREREG_008.md and may not be changed
without creating experiment 009. Everything in the RESOLVED block was underdetermined
by the pre-registration and was decided, with reasons, in DECISIONS_008.md before any
analysis ran.
"""

from __future__ import annotations

from typing import Final

# ===========================================================================
# FROZEN by PREREG_008 s7 — universe rule, exclusions, horizons, bucket edges,
# the six categories, event-level clustering, the Bonferroni threshold, and the
# requirement to report all 180 cells.
# ===========================================================================

HORIZONS: Final[dict[str, int]] = {
    "T-7d": 7 * 24 * 3600,
    "T-24h": 24 * 3600,
    "T-1h": 3600,
}
"""s3: 'T-7 days, T-24 hours, T-1 hour'. Seconds before T."""

BUCKET_EDGES: Final[tuple[int, ...]] = (0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
"""s3: '10 fixed buckets -- [0,10), [10,20), ... [90,100] -- in cents'."""

CATEGORIES: Final[tuple[str, ...]] = (
    "Weather", "Economics", "Politics", "Sports", "Financial", "Other",
)
"""s4: the six pre-specified categories. All reported, none selected post hoc."""

N_CELLS: Final[int] = (len(BUCKET_EDGES) - 1) * len(CATEGORIES) * len(HORIZONS)  # 180

T_INDIVIDUAL: Final[float] = 3.5
"""s6: 'Bonferroni-corrected threshold: t > 3.5' for any individual cell."""

T_POOLED: Final[float] = 2.0
"""s6: the 3 pooled per-horizon tests use t > 2.0."""

T_UNCORRECTED: Final[float] = 2.0
"""BUILD step 6: report how many cells would have passed at an uncorrected t > 2.0."""

DEFINITIVE_RESULTS: Final[frozenset[str]] = frozenset({"yes", "no"})
"""s2: 'Resolved with a definitive YES or NO outcome.'"""

# ===========================================================================
# RESOLVED — underdetermined by the pre-registration, decided in DECISIONS_008.md
# on 2026-08-21 before any analysis was run. Each carries its decision number.
# ===========================================================================

HORIZON_ANCHOR: Final[str] = "close_time"
"""Decision 4. T = close_time; close_time <= settlement_ts is asserted per market."""

EXCLUDE_MVE_COMBOS: Final[bool] = True
"""Decision 2. Multivariate combo parlays are excluded and counted separately."""

ROUND_MID_TO_CENTS: Final[bool] = False
"""Decision 10a. Bucket the exact half-cent mid; never round to whole cents first."""

INCLUDE_NO_SIDE_OBSERVATION: Final[bool] = False
"""Decision 10b. One YES observation per market, not a mirrored NO row."""

CLUSTER_KEY: Final[str] = "event_ticker"
"""Decision 11. Primary clustering key (s5, frozen)."""

COARSE_CLUSTER_KEY: Final[str] = "series_and_close_date"
"""Decision 11. Strictly coarser key; any t > 3.5 cell must survive it too."""

MAX_STALENESS_SECONDS: Final[dict[str, int] | None] = None
"""Decision 12. No staleness cap on the primary result -- a cap would be a liquidity
filter, which s2 forbids. The freshness robustness check uses FRESH_LIMITS below."""

FRESH_LIMITS: Final[dict[str, int]] = dict(HORIZONS)
"""Decision 12. Robustness check: snapshot age <= one horizon-period."""

FEE_FLOOR_LEGS: Final[int] = 1
"""Decision 8. One taker leg (no settlement fee); the two-leg floor is also printed."""

FEE_FLOOR_LEGS_ALTERNATE: Final[int] = 2

PERMUTATIONS: Final[int] = 8
"""BUILD step 8: '>= 8 permutations'."""

PERMUTATION_SEED: Final[int] = 20260821
SAMPLE_SEED: Final[int] = 20260821

# ---------------------------------------------------------------------------
# Ingestion / API
# ---------------------------------------------------------------------------

BASE_URL: Final[str] = "https://api.elections.kalshi.com/trade-api/v2"
USER_AGENT: Final[str] = (
    "kalshi-research/0.1 (experiment-008 calibration measurement; "
    "contact tamilselvan.p.r@gmail.com)"
)

REQUESTS_PER_SECOND: Final[float] = 4.0
"""Measured 2026-08-21: 60/60 HTTP 200 at 4 req/s; 19/60 HTTP 429 at 8 req/s.
This is a free, unauthenticated public endpoint. Do not raise this."""

CANDLE_PERIOD_MINUTES: Final[int] = 60
"""One 60-minute request covers up to 208 days, so a single call per market serves all
three horizons. Accepted values are 1, 60 and 1440 only."""

CACHE_DIR: Final[str] = "data/cache"
DERIVED_DIR: Final[str] = "data/derived"
