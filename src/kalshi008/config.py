from __future__ import annotations

HORIZONS = {
    "T-7d": 7 * 24 * 3600,
    "T-24h": 24 * 3600,
    "T-1h": 3600,
}
BUCKET_EDGES = (0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
CATEGORIES = ("Weather", "Economics", "Politics", "Sports", "Financial", "Other")
N_CELLS = (len(BUCKET_EDGES) - 1) * len(CATEGORIES) * len(HORIZONS)

T_INDIVIDUAL = 3.5
T_POOLED = 2.0
T_UNCORRECTED = 2.0

DEFINITIVE_RESULTS = frozenset({"yes", "no"})

HORIZON_ANCHOR = "close_time"
EXCLUDE_MVE_COMBOS = True
ROUND_MID_TO_CENTS = False
INCLUDE_NO_SIDE_OBSERVATION = False
CLUSTER_KEY = "event_ticker"
COARSE_CLUSTER_KEY = "series_and_close_date"
MAX_STALENESS_SECONDS = None
FRESH_LIMITS = dict(HORIZONS)
FEE_FLOOR_LEGS = 1
FEE_FLOOR_LEGS_ALTERNATE = 2

PERMUTATIONS = 8
PERMUTATION_SEED = 20260821
SAMPLE_SEED = 20260821

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
USER_AGENT = (
    "kalshi-research/0.1 (experiment-008 calibration measurement; "
    "contact tamilselvan.p.r@gmail.com)"
)
REQUESTS_PER_SECOND = 4.0
CANDLE_PERIOD_MINUTES = 60

CACHE_DIR = "data/cache"
DERIVED_DIR = "data/derived"
