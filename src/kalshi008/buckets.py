"""Fixed price buckets, frozen by PREREG_008 s3.

    "Bucketing: prices sorted into 10 fixed buckets -- [0,10), [10,20), ... [90,100]
     -- in cents. Fixed edges, not quantiles, so the buckets are the same across
     every category and horizon."

Note the last bucket is CLOSED at 100: [90,100]. Every other bucket is half-open.
"""

from __future__ import annotations

BUCKET_EDGES: tuple[int, ...] = (0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
N_BUCKETS = len(BUCKET_EDGES) - 1

BUCKET_LABELS: tuple[str, ...] = tuple(
    f"[{BUCKET_EDGES[i]},{BUCKET_EDGES[i + 1]}{']' if i == N_BUCKETS - 1 else ')'}"
    for i in range(N_BUCKETS)
)


def bucket_index(price_cents: float) -> int:
    """Return the 0-based bucket for a price in cents, or -1 if out of [0,100].

    Half-open [lo, hi) for buckets 0..8; closed [90, 100] for bucket 9.
    """
    if price_cents < 0 or price_cents > 100:
        return -1
    if price_cents == 100:
        return N_BUCKETS - 1
    return min(int(price_cents // 10), N_BUCKETS - 1)
