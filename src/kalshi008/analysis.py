"""Calibration tables, significance, the fee overlay and the permutation null.

PREREG_008 s6 fixes the thresholds and s5 fixes what governs them:
  * 10 buckets x 6 categories x 3 horizons = 180 individual tests, Bonferroni t > 3.5
  * 3 pooled per-horizon tests, t > 2.0
  * the CLUSTERED figures govern; naive figures are reported alongside for contrast
  * the effective sample size is the number of distinct EVENTS, not markets

All 180 cells are reported, including empty ones. BUILD step 5: "Report all 180 cells.
Do not summarise to the interesting ones."
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from .buckets import BUCKET_LABELS, N_BUCKETS
from .config import (
    BUCKET_EDGES, CATEGORIES, FEE_FLOOR_LEGS, FEE_FLOOR_LEGS_ALTERNATE, FRESH_LIMITS,
    HORIZONS, PERMUTATIONS, PERMUTATION_SEED, T_INDIVIDUAL, T_POOLED, T_UNCORRECTED,
)
from .fees import fee_equivalent_price_error_cents
from .stats import calibration_cell, permute_outcomes_within_group

UTC = dt.timezone.utc


def snapshots_to_frame(snapshots: Iterable) -> pd.DataFrame:
    rows = [s.to_dict() if hasattr(s, "to_dict") else dict(s) for s in snapshots]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["implied"] = df["mid_cents"] / 100.0
    df["close_date"] = pd.to_datetime(df["close_ts"], unit="s", utc=True).dt.strftime("%Y-%m-%d")
    df["coarse_cluster"] = df["series_ticker"].astype(str) + "|" + df["close_date"]
    return df


# ---------------------------------------------------------------------------
# The 180 cells
# ---------------------------------------------------------------------------

def build_cells(df: pd.DataFrame, cluster_col: str = "event_ticker") -> pd.DataFrame:
    """Every bucket x category x horizon cell, populated or not."""
    records = []
    for horizon in HORIZONS:
        for category in CATEGORIES:
            for b in range(N_BUCKETS):
                sub = df[
                    (df["horizon"] == horizon)
                    & (df["category"] == category)
                    & (df["bucket"] == b)
                ] if not df.empty else df
                if sub is None or len(sub) == 0:
                    cell = calibration_cell([], [], [])
                else:
                    cell = calibration_cell(
                        sub["implied"].to_numpy(),
                        sub["outcome"].to_numpy(),
                        sub[cluster_col].to_numpy(),
                    )
                rec = cell.to_dict()
                rec.update(
                    horizon=horizon, category=category, bucket=b,
                    bucket_label=BUCKET_LABELS[b],
                )
                records.append(rec)
    cols = [
        "horizon", "category", "bucket", "bucket_label", "n_markets", "n_events",
        "mean_implied_price", "realized_frequency", "difference", "difference_cents",
        "se_naive", "se_binomial", "se_binomial_clustered", "se_clustered_cr0",
        "se_clustered_cr1", "se_governing", "t_naive", "t_clustered",
        "t_clustered_unguarded",
    ]
    out = pd.DataFrame.from_records(records)
    return out[cols]


def pooled_by_horizon(df: pd.DataFrame, cluster_col: str = "event_ticker") -> pd.DataFrame:
    """s6's 3 aggregate tests: all categories pooled, one per horizon, t > 2.0."""
    recs = []
    for horizon in HORIZONS:
        sub = df[df["horizon"] == horizon] if not df.empty else df
        if sub is None or len(sub) == 0:
            cell = calibration_cell([], [], [])
        else:
            cell = calibration_cell(
                sub["implied"].to_numpy(), sub["outcome"].to_numpy(), sub[cluster_col].to_numpy()
            )
        r = cell.to_dict()
        r.update(horizon=horizon, threshold=T_POOLED,
                 passes=bool(abs(r["t_clustered"]) > T_POOLED) if np.isfinite(r["t_clustered"]) else False)
        recs.append(r)
    return pd.DataFrame.from_records(recs)


def pooled_by_horizon_bucket(df: pd.DataFrame, cluster_col: str = "event_ticker") -> pd.DataFrame:
    """All categories pooled, per bucket, per horizon (30 cells).

    s8's "market is calibrated" test reads: "if the pooled test shows
    |realized - implied| within the fee floor at EVERY BUCKET, at all three horizons".
    That requires the pooled figure per bucket, which is this table.
    """
    recs = []
    for horizon in HORIZONS:
        for b in range(N_BUCKETS):
            sub = df[(df["horizon"] == horizon) & (df["bucket"] == b)] if not df.empty else df
            if sub is None or len(sub) == 0:
                cell = calibration_cell([], [], [])
            else:
                cell = calibration_cell(
                    sub["implied"].to_numpy(), sub["outcome"].to_numpy(), sub[cluster_col].to_numpy()
                )
            r = cell.to_dict()
            r.update(horizon=horizon, bucket=b, bucket_label=BUCKET_LABELS[b])
            recs.append(r)
    return pd.DataFrame.from_records(recs)


# ---------------------------------------------------------------------------
# Fee overlay (s6, BUILD step 7)
# ---------------------------------------------------------------------------

def fee_floor_table(df: pd.DataFrame) -> pd.DataFrame:
    """Fee-equivalent price error per bucket, at the realised mean price in each bucket.

    The floor is evaluated at the bucket's own mean implied price where observations
    exist, and at the bucket midpoint where they do not. The effective per-series
    fee multiplier is averaged over the observations in the bucket, so series with
    multiplier 0 correctly lower the floor they face.
    """
    recs = []
    for b in range(N_BUCKETS):
        lo, hi = BUCKET_EDGES[b], BUCKET_EDGES[b + 1]
        mid = (lo + hi) / 2.0
        sub = df[df["bucket"] == b] if not df.empty else None
        if sub is not None and len(sub) > 0:
            price = float(sub["mid_cents"].mean())
            mult = float(sub["fee_multiplier"].mean())
        else:
            price, mult = mid, 1.0
        recs.append(dict(
            bucket=b, bucket_label=BUCKET_LABELS[b], low_cents=lo, high_cents=hi,
            n_obs=int(len(sub)) if sub is not None else 0,
            mean_price_cents=price, mean_fee_multiplier=mult,
            fee_floor_cents_1leg=fee_equivalent_price_error_cents(price, mult, FEE_FLOOR_LEGS),
            fee_floor_cents_2leg=fee_equivalent_price_error_cents(price, mult, FEE_FLOOR_LEGS_ALTERNATE),
            fee_floor_cents_1leg_m1=fee_equivalent_price_error_cents(price, 1.0, 1),
            fee_floor_cents_2leg_m1=fee_equivalent_price_error_cents(price, 1.0, 2),
        ))
    return pd.DataFrame.from_records(recs)


def cell_fee_floors(df: pd.DataFrame) -> pd.DataFrame:
    """Fee floor for each of the 180 cells, at THAT CELL's own mean price and multiplier.

    The fee is quadratic in price, so evaluating it at a bucket-wide average pooled over
    all six categories and all three horizons would apply the wrong floor to any cell
    whose own mean price sits away from that average -- and the error is largest exactly
    at the bucket edges. s6 asks for the fee-equivalent price error "per bucket"; doing it
    per cell is the same quantity evaluated where it is actually used.

    Cells with no observations fall back to the bucket midpoint at multiplier 1, which is
    what the reported per-bucket table shows.
    """
    recs = []
    for horizon in HORIZONS:
        for category in CATEGORIES:
            for b in range(N_BUCKETS):
                lo, hi = BUCKET_EDGES[b], BUCKET_EDGES[b + 1]
                sub = df[
                    (df["horizon"] == horizon)
                    & (df["category"] == category)
                    & (df["bucket"] == b)
                ] if not df.empty else None
                if sub is not None and len(sub) > 0:
                    price = float(sub["mid_cents"].mean())
                    mult = float(sub["fee_multiplier"].mean())
                else:
                    price, mult = (lo + hi) / 2.0, 1.0
                recs.append(dict(
                    horizon=horizon, category=category, bucket=b,
                    cell_mean_price_cents=price, cell_mean_fee_multiplier=mult,
                    fee_floor_cents_1leg=fee_equivalent_price_error_cents(
                        price, mult, FEE_FLOOR_LEGS),
                    fee_floor_cents_2leg=fee_equivalent_price_error_cents(
                        price, mult, FEE_FLOOR_LEGS_ALTERNATE),
                ))
    return pd.DataFrame.from_records(recs)


def apply_fee_overlay(cells: pd.DataFrame, floors: pd.DataFrame,
                      df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Join the floor onto every cell and mark which clear BOTH gates.

    When `df` is supplied the floor is evaluated PER CELL (see cell_fee_floors); the
    bucket-level `floors` table is then used only for the reported per-bucket overlay.
    """
    if df is not None:
        cf = cell_fee_floors(df)
        out = cells.merge(cf, on=["horizon", "category", "bucket"], how="left")
    else:
        f = floors[["bucket", "fee_floor_cents_1leg", "fee_floor_cents_2leg"]]
        out = cells.merge(f, on="bucket", how="left")
    absdiff = out["difference_cents"].abs()
    out["abs_difference_cents"] = absdiff
    out["exceeds_fee_floor_1leg"] = absdiff > out["fee_floor_cents_1leg"]
    out["exceeds_fee_floor_2leg"] = absdiff > out["fee_floor_cents_2leg"]
    t = out["t_clustered"].abs()
    out["passes_corrected"] = t > T_INDIVIDUAL
    out["passes_uncorrected"] = t > T_UNCORRECTED
    out["is_finding_1leg"] = out["passes_corrected"] & out["exceeds_fee_floor_1leg"]
    out["is_finding_2leg"] = out["passes_corrected"] & out["exceeds_fee_floor_2leg"]
    return out


# ---------------------------------------------------------------------------
# Coarse re-clustering (DECISIONS_008 decision 11)
# ---------------------------------------------------------------------------

def recluster_hits(df: pd.DataFrame, cells: pd.DataFrame) -> pd.DataFrame:
    """Re-test every cell that cleared t > 3.5 under a strictly coarser cluster key.

    The coarse key is series_ticker + close date, which merges an NFL game's
    moneyline/spread/total events and a crypto ladder's sibling events. A finding must
    survive BOTH. This can only remove findings, never add them.
    """
    hits = cells[cells["passes_corrected"].fillna(False)]
    recs = []
    for _, row in hits.iterrows():
        sub = df[
            (df["horizon"] == row["horizon"])
            & (df["category"] == row["category"])
            & (df["bucket"] == row["bucket"])
        ]
        c = calibration_cell(
            sub["implied"].to_numpy(), sub["outcome"].to_numpy(), sub["coarse_cluster"].to_numpy()
        )
        r = c.to_dict()
        r.update(
            horizon=row["horizon"], category=row["category"], bucket=int(row["bucket"]),
            bucket_label=row["bucket_label"],
            t_event_clustered=row["t_clustered"],
            survives_coarse=bool(np.isfinite(c.t_clustered) and abs(c.t_clustered) > T_INDIVIDUAL),
        )
        recs.append(r)
    return pd.DataFrame.from_records(recs) if recs else pd.DataFrame(
        columns=["horizon", "category", "bucket", "survives_coarse"]
    )


# ---------------------------------------------------------------------------
# Permutation null (BUILD step 8)
# ---------------------------------------------------------------------------

@dataclass
class NullResult:
    """Result of one null test over the whole 180-cell table."""
    label: str
    n_replications: int
    cells_passing_corrected: list[int]
    cells_passing_uncorrected: list[int]
    max_abs_t_per_replication: list[float]
    max_abs_diff_cents_per_replication: list[float]
    passed: bool
    governs: bool
    note: str = ""


@dataclass
class PermutationResult:
    n_permutations: int
    cells_passing_corrected: list[int]
    cells_passing_uncorrected: list[int]
    max_abs_t_per_permutation: list[float]
    passed: bool

    def summary(self) -> str:
        return (
            f"{self.n_permutations} permutations; cells passing t>{T_INDIVIDUAL} per "
            f"permutation = {self.cells_passing_corrected}; "
            f"max |t| per permutation = "
            f"{[round(x, 2) for x in self.max_abs_t_per_permutation]}"
        )


NOMINAL_P_EXCEED = 2.0 * (1.0 - 0.9997673709)
"""Two-sided normal tail beyond |t| = 3.5, i.e. P(|Z| > 3.5) ~ 4.65e-4."""


def null_pass_criterion(observed_total: int, n_tests: int) -> dict:
    """Judge a null result against its own expectation instead of demanding exact zero.

    Requiring ZERO cells above t = 3.5 across every replication is the wrong bar. With
    180 cells and 8 replications there are ~1,440 tests, so even a perfectly calibrated
    pipeline is expected to throw about 0.7 exceedances and will show at least one
    roughly a quarter of the time. Demanding zero would stamp a correct run UNUSABLE by
    chance far too often.

    The criterion is instead: is the observed exceedance count consistent with the
    nominal rate? The threshold is the 99th percentile of Poisson(expected), so a correct
    pipeline fails at most 1% of the time, while a pipeline with genuinely broken standard
    errors -- which inflates the count by one to two orders of magnitude, as the 3.1%
    ladder bug did -- is caught immediately.
    """
    expected = n_tests * NOMINAL_P_EXCEED
    try:
        from scipy.stats import poisson
        threshold = int(poisson.ppf(0.99, max(expected, 1e-9)))
    except Exception:
        threshold = int(expected + 3.0 * math.sqrt(max(expected, 1e-9)) + 1)
    return {
        "n_tests": int(n_tests),
        "observed_exceedances": int(observed_total),
        "expected_exceedances": round(expected, 4),
        "threshold_99th_percentile": threshold,
        "passed": bool(observed_total <= threshold),
    }


def _score_table(perm: pd.DataFrame) -> tuple[int, int, float, float]:
    cells = build_cells(perm)
    t = cells["t_clustered"].abs()
    finite_t = t[np.isfinite(t)]
    pop = cells[cells["n_markets"] > 0]
    d = pop["difference_cents"].abs()
    return (
        int((t > T_INDIVIDUAL).sum()),
        int((t > T_UNCORRECTED).sum()),
        float(finite_t.max()) if len(finite_t) else float("nan"),
        float(d.max()) if len(d) else float("nan"),
    )


def _n_populated(df: pd.DataFrame) -> int:
    """Cells that actually carry observations -- the real number of tests per replication."""
    if df.empty:
        return 0
    return int(df.groupby(["horizon", "category", "bucket"]).size().shape[0])


def bernoulli_null(
    df: pd.DataFrame, n: int = PERMUTATIONS, seed: int = PERMUTATION_SEED
) -> NullResult:
    """Resample every outcome as Bernoulli(implied price).

    This is the null that actually tests BUILD step 8's stated concern -- "is the
    pipeline manufacturing significance?". Under it the market is PERFECTLY CALIBRATED
    BY CONSTRUCTION at every price, so the true difference in every cell is zero. Any
    cell reaching t > 3.5 therefore means the standard errors are too small: the
    clustering, the residuals or the table construction is inventing significance out of
    noise. That is exactly the failure the step exists to catch.

    The literal within-category permutation cannot serve this purpose: it destroys the
    price-outcome relationship, so it FORCES large deviations in the extreme buckets on
    any calibrated dataset. See `permutation_null` and DECISIONS_008 decision 14.
    """
    rng = np.random.default_rng(seed + 1)
    pc: list[int] = []
    pu: list[int] = []
    mt: list[float] = []
    md: list[float] = []
    p = df["implied"].to_numpy()
    for _ in range(n):
        rep = df.copy()
        rep["outcome"] = (rng.random(len(p)) < p).astype(int)
        a, b, c, d = _score_table(rep)
        pc.append(a); pu.append(b); mt.append(c); md.append(d)
    return NullResult(
        label="Bernoulli(implied price) resample -- calibrated by construction",
        n_replications=n,
        cells_passing_corrected=pc,
        cells_passing_uncorrected=pu,
        max_abs_t_per_replication=mt,
        max_abs_diff_cents_per_replication=md,
        passed=null_pass_criterion(sum(pc), n * _n_populated(df))["passed"],
        governs=True,
        note=(
            "Outcomes are redrawn from each market's own implied price, so the market is "
            "calibrated at every price by construction and the true difference in every "
            "cell is zero. A cell passing t > 3.5 here means the pipeline's standard "
            "errors are too small. THIS TEST GOVERNS whether results are usable."
        ),
    )


def clustered_bernoulli_null(
    df: pd.DataFrame, n: int = PERMUTATIONS, seed: int = PERMUTATION_SEED
) -> NullResult:
    """Bernoulli resample with MAXIMAL positive dependence inside each event.

    One uniform draw per EVENT, shared by every market in it: market i resolves YES iff
    u_g < p_i. Each market's marginal probability is still exactly p_i, so the market is
    calibrated by construction, but markets inside an event now move together perfectly --
    the comonotonic coupling, which is the worst case for a clustered standard error.

    This is the null that would have caught the bug described in stats.py: a nested
    threshold ladder inside one event_ticker ("temp above 68 / above 69 / above 70"),
    which is a real and common Kalshi structure. The plain `bernoulli_null` draws
    independently per market and therefore CANNOT see that failure mode -- under
    independence the naive binomial standard error happens to be correct.

    Any cell reaching t > 3.5 here means the clustering is not absorbing real within-event
    dependence.
    """
    rng = np.random.default_rng(seed + 2)
    pc: list[int] = []
    pu: list[int] = []
    mt: list[float] = []
    md: list[float] = []
    p = df["implied"].to_numpy()
    ev = df["event_ticker"].to_numpy().astype(str)
    uniq, inverse = np.unique(ev, return_inverse=True)
    for _ in range(n):
        u_event = rng.random(len(uniq))
        rep = df.copy()
        rep["outcome"] = (u_event[inverse] < p).astype(int)
        a, b, c, d = _score_table(rep)
        pc.append(a); pu.append(b); mt.append(c); md.append(d)
    return NullResult(
        label="Bernoulli resample, comonotonic within each event -- worst-case dependence",
        n_replications=n,
        cells_passing_corrected=pc,
        cells_passing_uncorrected=pu,
        max_abs_t_per_replication=mt,
        max_abs_diff_cents_per_replication=md,
        passed=null_pass_criterion(sum(pc), n * _n_populated(df))["passed"],
        governs=True,
        note=(
            "One uniform per event shared by all its markets. Marginals are exactly the "
            "implied prices, so the market is calibrated by construction, but within-event "
            "dependence is maximal. This is the adversarial case for the clustered standard "
            "error and it GOVERNS alongside the independent Bernoulli null."
        ),
    )


def permutation_null(
    df: pd.DataFrame, n: int = PERMUTATIONS, seed: int = PERMUTATION_SEED
) -> PermutationResult:
    """Permute settled outcomes WITHIN each category and re-run the whole table.

    BUILD step 8: "Permute settlement outcomes within each category, preserving the
    marginal YES rate... Expected: no cells pass t > 3.5. If cells pass under
    permutation, the pipeline is manufacturing significance and no result from it is
    usable."

    The shuffle is within-category, so each category's YES count -- and therefore its
    marginal YES rate -- is EXACTLY preserved in every replication, not merely preserved
    in expectation. Permutation is applied per horizon so that each horizon's own
    population is permuted within itself.
    """
    rng = np.random.default_rng(seed)
    passing_c: list[int] = []
    passing_u: list[int] = []
    max_t: list[float] = []
    for _ in range(n):
        perm = df.copy()
        shuffled = np.empty(len(perm), dtype=int)
        for horizon in perm["horizon"].unique():
            m = (perm["horizon"] == horizon).to_numpy()
            shuffled[m] = permute_outcomes_within_group(
                perm.loc[m, "outcome"].to_numpy(),
                perm.loc[m, "category"].to_numpy(),
                rng,
            )
        perm["outcome"] = shuffled
        cells = build_cells(perm)
        t = cells["t_clustered"].abs()
        passing_c.append(int((t > T_INDIVIDUAL).sum()))
        passing_u.append(int((t > T_UNCORRECTED).sum()))
        finite = t[np.isfinite(t)]
        max_t.append(float(finite.max()) if len(finite) else float("nan"))
    return PermutationResult(
        n_permutations=n,
        cells_passing_corrected=passing_c,
        cells_passing_uncorrected=passing_u,
        max_abs_t_per_permutation=max_t,
        passed=all(c == 0 for c in passing_c),
    )


# ---------------------------------------------------------------------------
# Book-quality diagnostic
# ---------------------------------------------------------------------------

SPREAD_BANDS: tuple[tuple[float, float, str], ...] = (
    (-0.01, 2.0, "spread <= 2c"),
    (2.0, 5.0, "2c < spread <= 5c"),
    (5.0, 10.0, "5c < spread <= 10c"),
    (10.0, 20.0, "10c < spread <= 20c"),
    (20.0, 1e9, "spread > 20c"),
)


def book_quality_table(df: pd.DataFrame) -> pd.DataFrame:
    """Calibration split by how real the price actually is.

    s3 says "mid price" without saying what to do when the book barely exists. On Kalshi
    it frequently barely exists: a snapshot of `yes_bid = 0.0000, yes_ask = 0.94` has a
    "mid" of 47c, which lands in the [40,50) bucket, but it is not a price -- it means
    nobody is bidding and someone is offering at 94c.

    s9 warned that "a large, clean miscalibration would be surprising and should be
    treated as a bug first". This table is that check. It is a LIQUIDITY-CONDITIONED
    split, which s2 forbids for the headline result, so it is reported as a diagnostic
    only and changes no reported cell.
    """
    recs = []

    def row(label: str, sub: pd.DataFrame, group: str) -> None:
        if not len(sub):
            return
        c = calibration_cell(
            sub["implied"].to_numpy(), sub["outcome"].to_numpy(), sub["event_ticker"].to_numpy()
        )
        r = c.to_dict()
        r.update(stratum=label, group=group, share_of_snapshots=len(sub) / max(len(df), 1))
        recs.append(r)

    if df.empty:
        return pd.DataFrame(columns=["stratum", "group"])
    row("all snapshots", df, "all")
    row("two-sided book", df[~df["one_sided_book"]], "sidedness")
    row("one-sided book", df[df["one_sided_book"]], "sidedness")
    for lo, hi, lab in SPREAD_BANDS:
        row(lab, df[(df["spread_cents"] > lo) & (df["spread_cents"] <= hi)], "spread")
    tight = df[(~df["one_sided_book"]) & (df["spread_cents"] <= 5.0)]
    for horizon in HORIZONS:
        row(f"{horizon}: two-sided and spread <= 5c", tight[tight["horizon"] == horizon],
            "tight_by_horizon")
    return pd.DataFrame.from_records(recs)


# ---------------------------------------------------------------------------
# Robustness checks
# ---------------------------------------------------------------------------

def fresh_subset(df: pd.DataFrame) -> pd.DataFrame:
    """Decision 12: snapshots no staler than one horizon-period."""
    if df.empty:
        return df
    limit = df["horizon"].map(FRESH_LIMITS)
    return df[df["staleness_s"] <= limit]


def all_three_horizons_subset(df: pd.DataFrame) -> pd.DataFrame:
    """Decision 6: the s2 reading -- markets qualifying at ALL THREE horizons."""
    if df.empty:
        return df
    counts = df.groupby("ticker")["horizon"].nunique()
    keep = set(counts[counts == len(HORIZONS)].index)
    return df[df["ticker"].isin(keep)]


# ---------------------------------------------------------------------------
# s8 conclusion
# ---------------------------------------------------------------------------

def prereg_conclusion(cells: pd.DataFrame, pooled_bucket: pd.DataFrame, floors: pd.DataFrame,
                      recluster: pd.DataFrame) -> dict:
    """The s8 decision, computed mechanically from the tables. No judgement applied."""
    findings = cells[cells["is_finding_1leg"].fillna(False)]
    if not recluster.empty and len(findings):
        survivors = {
            (r["horizon"], r["category"], int(r["bucket"]))
            for _, r in recluster.iterrows() if r.get("survives_coarse")
        }
        findings = findings[
            findings.apply(
                lambda r: (r["horizon"], r["category"], int(r["bucket"])) in survivors, axis=1
            )
        ]

    # s8's second bullet: "The same directional bias visible at two or more of the three
    # horizons". VISIBLE, not "also a finding" -- so the sign is read off the FULL cells
    # table for that category+bucket, not off the subset that cleared every gate.
    directional_ok = False
    detail = []
    if len(findings):
        for (cat, b), _grp in findings.groupby(["category", "bucket"]):
            same = cells[
                (cells["category"] == cat) & (cells["bucket"] == b) & (cells["n_markets"] > 0)
            ]
            signs = [int(np.sign(v)) for v in same["difference_cents"] if np.isfinite(v) and v != 0]
            horizons_hit = sorted(same["horizon"].unique())
            n_same_sign = max(signs.count(1), signs.count(-1)) if signs else 0
            ok = n_same_sign >= 2
            directional_ok = directional_ok or ok
            detail.append(dict(
                category=cat, bucket=int(b), horizons_measured=horizons_hit,
                n_horizons_measured=len(horizons_hit),
                n_horizons_same_direction=n_same_sign, meets_two_horizon_rule=ok,
            ))

    # s8's "market is calibrated" requires the pooled deviation inside the fee floor
    # "at every bucket, at all three horizons". A bucket-horizon that was never measured
    # is not evidence of calibration, so incomplete coverage BLOCKS the verdict rather
    # than being silently dropped.
    pb = pooled_bucket.merge(floors[["bucket", "fee_floor_cents_1leg"]], on="bucket", how="left")
    pb_pop = pb[pb["n_markets"] > 0]
    n_expected = N_BUCKETS * len(HORIZONS)
    full_coverage = int(len(pb_pop)) == n_expected
    all_inside = bool(
        len(pb_pop) > 0
        and (pb_pop["difference"].abs() * 100.0 <= pb_pop["fee_floor_cents_1leg"]).all()
    )
    within_floor_everywhere = bool(full_coverage and all_inside)

    if len(findings) and directional_ok:
        verdict = "exploitable miscalibration exists"
    elif within_floor_everywhere:
        verdict = "market is calibrated"
    else:
        verdict = "descriptive only"

    return dict(
        verdict=verdict,
        n_findings_after_all_gates=int(len(findings)),
        directional_consistency_met=(directional_ok if len(findings) else None),
        directional_consistency_note=(
            None if len(findings) else
            "not evaluated: s8's second bullet only applies to cells that cleared the "
            "first bullet, and no cell did"
        ),
        pooled_within_fee_floor_at_every_bucket=within_floor_everywhere,
        pooled_bucket_horizon_cells_measured=int(len(pb_pop)),
        pooled_bucket_horizon_cells_expected=n_expected,
        full_bucket_horizon_coverage=full_coverage,
        all_measured_buckets_inside_fee_floor=all_inside,
        finding_detail=detail,
    )
