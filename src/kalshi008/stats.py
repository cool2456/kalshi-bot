from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Iterable, Sequence

import numpy as np


@dataclass(frozen=True)
class CalibrationCell:
    n_markets: int
    n_events: int
    mean_implied_price: float
    realized_frequency: float
    difference: float
    se_naive: float
    se_binomial: float
    se_binomial_clustered: float
    se_clustered_cr0: float
    se_clustered_cr1: float
    se_governing: float
    t_naive: float
    t_clustered: float
    t_clustered_unguarded: float

    @property
    def difference_cents(self) -> float:
        return self.difference * 100.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["difference_cents"] = self.difference_cents
        return d


def _safe_t(diff: float, se: float) -> float:
    if se <= 0 or not math.isfinite(se):
        return float("nan")
    return diff / se


def calibration_cell(
    implied_prices: Sequence[float],
    outcomes: Sequence[int],
    event_ids: Sequence[str],
) -> CalibrationCell:
    p = np.asarray(implied_prices, dtype=float)
    y = np.asarray(outcomes, dtype=float)
    ev = np.asarray(event_ids, dtype=object)
    n = p.size
    if n != y.size or n != ev.size:
        raise ValueError("implied_prices, outcomes and event_ids must be the same length")
    if n == 0:
        nan = float("nan")
        return CalibrationCell(0, 0, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan)

    r = y - p
    d = float(r.mean())
    uniq_events = np.unique(ev)
    g = int(uniq_events.size)

    if n > 1:
        se_naive = float(r.std(ddof=1) / math.sqrt(n))
    else:
        se_naive = float("nan")

    sd_i = np.sqrt(p * (1.0 - p))
    se_binomial = float(math.sqrt(float(np.sum(sd_i ** 2))) / n)

    resid = r - d
    order = np.argsort(ev.astype(str), kind="stable")
    ev_sorted = ev[order].astype(str)
    resid_sorted = resid[order]
    boundaries = np.flatnonzero(np.r_[True, ev_sorted[1:] != ev_sorted[:-1], True])
    cluster_sums = np.add.reduceat(resid_sorted, boundaries[:-1])
    meat = float(np.sum(cluster_sums ** 2))

    sd_sorted = sd_i[order]
    sd_cluster_sums = np.add.reduceat(sd_sorted, boundaries[:-1])
    se_bin_clustered = float(math.sqrt(float(np.sum(sd_cluster_sums ** 2))) / n)
    v_cr0 = meat / (n ** 2)
    se_cr0 = math.sqrt(v_cr0) if v_cr0 > 0 else 0.0
    if g > 1:
        se_cr1 = se_cr0 * math.sqrt(g / (g - 1.0))
    else:
        se_cr1 = float("nan")

    if g <= 1 or not math.isfinite(se_cr1):
        se_gov = float("nan")
    else:
        se_gov = max(se_cr1, se_bin_clustered)

    return CalibrationCell(
        n_markets=n,
        n_events=g,
        mean_implied_price=float(p.mean()),
        realized_frequency=float(y.mean()),
        difference=d,
        se_naive=se_naive,
        se_binomial=se_binomial,
        se_binomial_clustered=se_bin_clustered,
        se_clustered_cr0=se_cr0,
        se_clustered_cr1=se_cr1,
        se_governing=se_gov,
        t_naive=_safe_t(d, se_naive),
        t_clustered=_safe_t(d, se_gov),
        t_clustered_unguarded=_safe_t(d, se_cr1),
    )


def permute_outcomes_within_group(
    outcomes: Sequence[int],
    group_ids: Sequence[str],
    rng: np.random.Generator,
) -> np.ndarray:
    y = np.asarray(outcomes)
    grp = np.asarray(group_ids, dtype=object).astype(str)
    out = y.copy()
    for gval in np.unique(grp):
        idx = np.flatnonzero(grp == gval)
        out[idx] = y[idx][rng.permutation(idx.size)]
    return out
