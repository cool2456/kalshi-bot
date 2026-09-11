from __future__ import annotations

BUCKET_EDGES: tuple[int, ...] = (0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
N_BUCKETS = len(BUCKET_EDGES) - 1

BUCKET_LABELS: tuple[str, ...] = tuple(
    f"[{BUCKET_EDGES[i]},{BUCKET_EDGES[i + 1]}{']' if i == N_BUCKETS - 1 else ')'}"
    for i in range(N_BUCKETS)
)


def bucket_index(price_cents: float) -> int:
    if price_cents < 0 or price_cents > 100:
        return -1
    if price_cents == 100:
        return N_BUCKETS - 1
    return min(int(price_cents // 10), N_BUCKETS - 1)
