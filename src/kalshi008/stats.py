"""Calibration point estimates and standard errors.

PREREG_008 s5 requires BOTH a naive standard error and one clustered at the event
level, and states plainly that "the clustered figures govern s6". s6 fixes the
thresholds: t > 3.5 for any of the 180 individual bucket-category-horizon cells,
t > 2.0 for the 3 pooled per-horizon tests. Those thresholds are compared against
the raw t-statistic, so no degrees-of-freedom lookup is involved.

Estimand
--------
For a set of markets indexed i, each with implied YES price p_i (in dollars) and
binary settled outcome y_i, the calibration residual is

    r_i = y_i - p_i

and the reported difference is d = mean(r_i) = realized frequency - mean implied
price. d > 0 means the market UNDERPRICED YES; d < 0 means it OVERPRICED YES.
Favorite-longshot bias, as PREREG_008 s1 describes it, is d < 0 in low-price
buckets.

Standard errors
---------------
naive     sd(r) / sqrt(n), treating every market as independent. This is what s5 calls
          the naive standard error and it is reported for contrast only.

binomial  the MODEL-BASED standard error under the calibration null, ASSUMING
          INDEPENDENCE. If the market is calibrated then y_i ~ Bernoulli(p_i) with
          Var(y_i) = p_i(1-p_i) exactly, so

              SE_binomial = sqrt( sum_i p_i (1 - p_i) ) / n

          This is reported, but it is NOT what the guard uses -- see below.

binomial  the model-based standard error under the calibration null assuming PERFECT
clustered POSITIVE dependence within each event and independence across events. The
          variance of a sum of perfectly correlated variables is the square of the sum of
          their standard deviations, so

              SE_bin_clustered = sqrt( sum_g ( sum_{i in g} sqrt(p_i (1-p_i)) )^2 ) / n

          When every market is its own event this collapses exactly to SE_binomial. When
          markets share an event it is strictly larger, and it is an upper bound on the
          clustered variance under any positive dependence structure.

clustered cluster-robust (CR) at the event level, which is what s5 mandates. For
          the sample mean the CR0 variance is

              V_CR0 = (1 / n^2) * sum_g ( sum_{i in g} (r_i - d) )^2

          summing over clusters g. CR1 applies the standard finite-sample correction
          G/(G-1), which inflates the standard error and shrinks |t|.

WHY THE GOVERNING SE IS max(CR1, binomial-clustered)
----------------------------------------------------
Both sd(r) and the cluster-robust "meat" estimate the spread of the residuals FROM THE
SAMPLE. Both are unbiased, and both are catastrophically unstable in exactly the extreme
buckets s9 warned about. Concretely, in a validation run this estimator reported:

    18 markets in [0,10), mean implied 0.0711, ALL 18 resolved NO
    residuals all equal to -p_i, spanning only -0.05 to -0.09
    sd(r) = 0.0149  ->  SE = 0.0035  ->  t = -20.2

An all-NO outcome for 18 contracts priced near 7c has probability about 0.27. It is
utterly unremarkable, yet the sample-variance standard error called it a 20-sigma event,
because with every outcome identical the residual spread measures the spread of the
PRICES rather than the sampling variability of the OUTCOMES.

The model-based standard error does not have that failure mode. So the governing standard
error is

    SE_governing = max( SE_clustered_CR1, SE_bin_clustered )

IT MUST BE THE CLUSTERED MODEL SE, NOT THE INDEPENDENCE ONE. An earlier version of this
module used SE_binomial here, and that was a bug serious enough to manufacture findings.
The failing case, found by adversarial review and reproduced exactly:

    30 markets in 6 events, markets INSIDE each event perfectly co-moving (a nested
    threshold ladder in one event_ticker -- "temp above 68 / above 69 / above 70 ...",
    which is a real and common Kalshi structure in Weather and Sports). All priced 50c,
    market perfectly calibrated. All 6 events resolve NO -- probability 1/32.

      every residual identical  ->  CR meat exactly 0  ->  se_clustered_cr1 = 0.0
      SE_binomial = sqrt(30 * 0.25) / 30 = 0.0913   <- the INDEPENDENCE SE for 30 draws,
                                                        when there are only 6 independent draws
      t = -0.5 / 0.0913 = -5.48   -> clears t > 3.5, clears the fee floor, and survives
                                     the coarse re-cluster, because SE_binomial does not
                                     depend on the cluster key at all.
      correct event-level SE = 0.5 / sqrt(6) = 0.2041  ->  t = -2.45, not significant.

    Exact enumeration over the 2^6 event outcomes: P(|t| > 3.5) = 1/32 = 0.031 against a
    nominal 0.0005. A 66x inflation, on data that is calibrated by construction.

    Worse, the unguarded statistic in that cell is NaN, which can never pass any threshold.
    So the guard converted a cell that was safe into one that manufactured a finding --
    the exact opposite of what a guard is for.

SE_bin_clustered fixes it: for that cell, sum_{i in g} sqrt(p(1-p)) = 5 * 0.5 = 2.5 per
event, so SE = sqrt(6 * 2.5^2) / 30 = 0.2041, giving t = -2.45. Correct.

Note what this guard is and is not. SE_bin_clustered is NOT a lower bound on the true
standard error in general. Within a MUTUALLY EXCLUSIVE event exactly one market resolves
YES, which is NEGATIVE dependence, and negative dependence reduces the variance of the
cluster sum below even the independent value. So for exclusive events this deliberately
OVERSTATES the uncertainty. That overstatement is intended: the guard exists to stop a
degenerate cell manufacturing significance, and erring toward a larger standard error is
the direction a study whose purpose is to avoid false findings should err in.

The one case where the guard makes a finding POSSIBLE that was not possible before is the
zero-meat case above, where the unguarded statistic is NaN. There it substitutes a
principled conservative bound for an estimate that carries no information at all. That is
stated plainly rather than papered over with a claim that the guard "can only make findings
harder".

Every one of the four standard errors is carried in the result, and the unguarded
clustered t-statistic is reported alongside the governing one, so the effect of this
guard is visible rather than buried.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Iterable, Sequence

import numpy as np


@dataclass(frozen=True)
class CalibrationCell:
    n_markets: int
    n_events: int
    mean_implied_price: float      # dollars, 0..1
    realized_frequency: float      # 0..1
    difference: float              # realized - implied, in probability units
    se_naive: float                # sd(r)/sqrt(n)  -- reported for contrast only
    se_binomial: float             # sqrt(sum p(1-p))/n -- model-based, INDEPENDENCE
    se_binomial_clustered: float   # model-based with perfect within-event dependence
    se_clustered_cr0: float
    se_clustered_cr1: float
    se_governing: float            # max(se_clustered_cr1, se_binomial_clustered)
    t_naive: float
    t_clustered: float             # difference / se_governing  -- GOVERNS s6
    t_clustered_unguarded: float   # difference / se_clustered_cr1 -- shows the guard's effect

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
    """Compute one calibration cell with naive and event-clustered standard errors.

    implied_prices : YES price in DOLLARS (0..1)
    outcomes       : 1 if the market settled YES, 0 if NO
    event_ids      : parent event identifier per market, for clustering
    """
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

    # naive: sample dispersion of the residuals
    if n > 1:
        se_naive = float(r.std(ddof=1) / math.sqrt(n))
    else:
        se_naive = float("nan")

    # model-based under the calibration null: Var(y_i) = p_i (1 - p_i) exactly
    sd_i = np.sqrt(p * (1.0 - p))
    se_binomial = float(math.sqrt(float(np.sum(sd_i ** 2))) / n)

    # cluster-robust at the event level
    resid = r - d
    order = np.argsort(ev.astype(str), kind="stable")
    ev_sorted = ev[order].astype(str)
    resid_sorted = resid[order]
    # sum of residuals within each cluster
    boundaries = np.flatnonzero(np.r_[True, ev_sorted[1:] != ev_sorted[:-1], True])
    cluster_sums = np.add.reduceat(resid_sorted, boundaries[:-1])
    meat = float(np.sum(cluster_sums ** 2))

    # model-based SE assuming PERFECT positive dependence within each event. Variance of
    # a sum of perfectly correlated variables is the square of the sum of their sds.
    sd_sorted = sd_i[order]
    sd_cluster_sums = np.add.reduceat(sd_sorted, boundaries[:-1])
    se_bin_clustered = float(math.sqrt(float(np.sum(sd_cluster_sums ** 2))) / n)
    v_cr0 = meat / (n ** 2)
    se_cr0 = math.sqrt(v_cr0) if v_cr0 > 0 else 0.0
    if g > 1:
        se_cr1 = se_cr0 * math.sqrt(g / (g - 1.0))
    else:
        se_cr1 = float("nan")

    # The governing standard error. A single cluster still cannot support a clustered
    # estimate, so it stays NaN and the cell can never produce a finding.
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
    """Shuffle outcomes WITHIN each group, exactly preserving each group's YES rate.

    PREREG_008 / BUILD step 8: "Permute settlement outcomes within each category,
    preserving the marginal YES rate". Shuffling within a group is an exact
    permutation, so the group's YES count -- and hence its marginal YES rate -- is
    identical in every replication, not merely equal in expectation.
    """
    y = np.asarray(outcomes)
    grp = np.asarray(group_ids, dtype=object).astype(str)
    out = y.copy()
    for gval in np.unique(grp):
        idx = np.flatnonzero(grp == gval)
        out[idx] = y[idx][rng.permutation(idx.size)]
    return out
