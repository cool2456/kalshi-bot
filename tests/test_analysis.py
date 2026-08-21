"""Table construction, the fee overlay, exclusion logic and the s8 conclusion."""
import numpy as np
import pandas as pd
import pytest

from kalshi008 import analysis
from kalshi008.config import CATEGORIES, HORIZONS, N_CELLS, T_INDIVIDUAL


def make_snapshot(ticker, event, horizon, mid_cents, outcome, category="Sports",
                  staleness=0, series="S1", close_ts=1_000_000, fee_mult=1.0):
    return dict(
        ticker=ticker, event_ticker=event, series_ticker=series, category=category,
        horizon=horizon, target_ts=close_ts - HORIZONS[horizon],
        source_candle_ts=close_ts - HORIZONS[horizon] - staleness,
        staleness_s=staleness, mid_cents=mid_cents,
        bucket=min(int(mid_cents // 10), 9), outcome=outcome, one_sided_book=False,
        yes_bid_cents=mid_cents - 1.0, yes_ask_cents=mid_cents + 1.0, spread_cents=2.0,
        close_ts=close_ts, settlement_ts=close_ts + 1800, fee_multiplier=fee_mult,
    )


def test_always_exactly_180_cells_even_with_no_data():
    df = analysis.snapshots_to_frame([])
    cells = analysis.build_cells(df)
    assert len(cells) == N_CELLS == 180
    assert set(cells["horizon"]) == set(HORIZONS)
    assert set(cells["category"]) == set(CATEGORIES)
    assert set(cells["bucket"]) == set(range(10))


def test_180_cells_with_data_present():
    snaps = [make_snapshot(f"m{i}", f"e{i}", "T-24h", 45.0, i % 2) for i in range(20)]
    cells = analysis.build_cells(analysis.snapshots_to_frame(snaps))
    assert len(cells) == 180
    filled = cells[cells["n_markets"] > 0]
    assert len(filled) == 1
    assert int(filled.iloc[0]["n_markets"]) == 20


def test_difference_sign_means_what_the_report_says():
    """diff < 0 means the market OVERPRICED YES."""
    # implied 80c, only 20% resolve yes -> overpriced -> negative difference
    snaps = [make_snapshot(f"m{i}", f"e{i}", "T-24h", 80.0, 1 if i < 2 else 0) for i in range(10)]
    cells = analysis.build_cells(analysis.snapshots_to_frame(snaps))
    row = cells[(cells["n_markets"] > 0)].iloc[0]
    assert row["difference_cents"] == pytest.approx(-60.0)


def test_fee_overlay_marks_only_cells_clearing_both_gates():
    snaps = [make_snapshot(f"m{i}", f"e{i}", "T-24h", 45.0, 1 if i < 9 else 0) for i in range(60)]
    df = analysis.snapshots_to_frame(snaps)
    cells = analysis.build_cells(df)
    floors = analysis.fee_floor_table(df)
    overlaid = analysis.apply_fee_overlay(cells, floors)
    row = overlaid[overlaid["n_markets"] > 0].iloc[0]
    # a 30-point miss is far beyond any fee floor
    assert row["abs_difference_cents"] > row["fee_floor_cents_1leg"]
    assert row["exceeds_fee_floor_1leg"]
    assert bool(row["is_finding_1leg"]) == bool(row["passes_corrected"])


def test_zero_fee_multiplier_series_face_a_zero_floor():
    snaps = [make_snapshot(f"m{i}", f"e{i}", "T-24h", 45.0, i % 2, fee_mult=0.0) for i in range(10)]
    floors = analysis.fee_floor_table(analysis.snapshots_to_frame(snaps))
    assert floors[floors["bucket"] == 4].iloc[0]["fee_floor_cents_1leg"] == 0.0


def test_pooled_table_has_exactly_three_tests():
    snaps = [make_snapshot(f"m{i}", f"e{i}", h, 50.0, i % 2)
             for h in HORIZONS for i in range(10)]
    pooled = analysis.pooled_by_horizon(analysis.snapshots_to_frame(snaps))
    assert len(pooled) == 3


def test_pooled_by_bucket_has_thirty_rows():
    pooled_b = analysis.pooled_by_horizon_bucket(analysis.snapshots_to_frame([]))
    assert len(pooled_b) == 30


def _calibrated_frame(n=400, seed=0):
    """Snapshots that are calibrated by construction: outcome ~ Bernoulli(price)."""
    rng = np.random.default_rng(seed)
    snaps = []
    for i in range(n):
        p = float(rng.integers(5, 95))
        snaps.append(make_snapshot(f"m{i}", f"e{i}", "T-24h", p, int(rng.random() < p / 100.0)))
    return analysis.snapshots_to_frame(snaps)


def test_bernoulli_null_finds_nothing_on_calibrated_data():
    """The null that GOVERNS (DECISIONS decision 14).

    Outcomes redrawn from each market's own implied price, so the market is calibrated
    at every price by construction and the true difference in every cell is zero. Any
    cell reaching t > 3.5 would mean the standard errors are too small.
    """
    res = analysis.bernoulli_null(_calibrated_frame(), n=6)
    assert res.governs
    assert all(c == 0 for c in res.cells_passing_corrected), res.cells_passing_corrected
    assert all(t < T_INDIVIDUAL for t in res.max_abs_t_per_replication)
    assert res.passed


def test_within_category_permutation_forces_the_artifact_it_is_blamed_for():
    """BUILD step 8 as literally written cannot pass on calibrated data.

    Shuffling outcomes ACROSS price buckets drives every bucket's realized frequency to
    the category mean, so the extreme buckets show huge deviations by construction. This
    test pins that behaviour down so the FINDINGS explanation is backed by a test rather
    than by an argument.
    """
    df = _calibrated_frame()
    real = analysis.build_cells(df)
    real_pop = real[real["n_markets"] > 0]
    assert real_pop["difference_cents"].abs().max() < 15.0

    res = analysis.permutation_null(df, n=3)
    assert res.n_permutations == 3
    # the permuted table is wildly "miscalibrated" purely because of the shuffle
    rng = np.random.default_rng(7)
    from kalshi008.stats import permute_outcomes_within_group
    perm = df.copy()
    perm["outcome"] = permute_outcomes_within_group(
        df["outcome"].to_numpy(), df["category"].to_numpy(), rng)
    pcells = analysis.build_cells(perm)
    pop = pcells[pcells["n_markets"] > 0]
    assert pop["difference_cents"].abs().max() > 30.0
    # and the marginal YES rate is preserved exactly
    assert perm["outcome"].sum() == df["outcome"].sum()


def test_degenerate_cell_cannot_manufacture_a_huge_t():
    """The regression test for the defect the Bernoulli null caught.

    18 contracts priced near 7c, all resolving NO, is a ~27% likely outcome. The sample
    -variance standard error called it a 20-sigma event because with every outcome
    identical the residual spread measures the spread of PRICES, not of OUTCOMES.
    """
    from kalshi008.stats import calibration_cell
    p = [0.06, 0.05, 0.09, 0.09, 0.08, 0.07, 0.05, 0.05, 0.08,
         0.07, 0.05, 0.09, 0.06, 0.08, 0.09, 0.07, 0.06, 0.09]
    y = [0] * 18
    c = calibration_cell(p, y, [f"e{i}" for i in range(18)])
    assert abs(c.t_clustered_unguarded) > 15          # what the raw estimator says
    assert abs(c.t_clustered) < 2.0                   # what the guarded estimator says
    assert c.se_governing == c.se_binomial            # the guard bound
    assert c.se_binomial > 10 * c.se_naive


def test_fresh_subset_filters_on_staleness_per_horizon():
    snaps = [
        make_snapshot("a", "e1", "T-1h", 50.0, 1, staleness=100),        # fresh
        make_snapshot("b", "e2", "T-1h", 50.0, 1, staleness=7200),       # 2h > 1h -> stale
        make_snapshot("c", "e3", "T-7d", 50.0, 1, staleness=86400),      # 1d < 7d -> fresh
    ]
    df = analysis.snapshots_to_frame(snaps)
    fresh = analysis.fresh_subset(df)
    assert set(fresh["ticker"]) == {"a", "c"}


def test_all_three_horizons_subset_is_the_prereg_s2_reading():
    snaps = [make_snapshot("a", "e1", h, 50.0, 1) for h in HORIZONS]
    snaps += [make_snapshot("b", "e2", "T-1h", 50.0, 0)]
    df = analysis.snapshots_to_frame(snaps)
    sub = analysis.all_three_horizons_subset(df)
    assert set(sub["ticker"]) == {"a"}


def test_coarse_cluster_key_merges_same_series_same_day():
    snaps = [
        make_snapshot("a", "eA", "T-24h", 50.0, 1, series="KXNFLGAME", close_ts=1_000_000),
        make_snapshot("b", "eB", "T-24h", 50.0, 0, series="KXNFLGAME", close_ts=1_000_000),
    ]
    df = analysis.snapshots_to_frame(snaps)
    assert df["event_ticker"].nunique() == 2
    assert df["coarse_cluster"].nunique() == 1


def test_conclusion_is_calibrated_when_everything_sits_inside_the_fee_floor():
    rng = np.random.default_rng(5)
    snaps = []
    for i in range(600):
        p = float(rng.integers(5, 95))
        snaps.append(make_snapshot(f"m{i}", f"e{i}", "T-24h", p, int(rng.random() < p / 100)))
    df = analysis.snapshots_to_frame(snaps)
    cells = analysis.build_cells(df)
    floors = analysis.fee_floor_table(df)
    cells = analysis.apply_fee_overlay(cells, floors)
    pooled_b = analysis.pooled_by_horizon_bucket(df)
    recl = analysis.recluster_hits(df, cells)
    concl = analysis.prereg_conclusion(cells, pooled_b, floors, recl)
    assert concl["verdict"] in {"market is calibrated", "descriptive only"}
    assert concl["n_findings_after_all_gates"] == 0


def test_fee_floor_is_evaluated_per_cell_not_at_a_pooled_bucket_average():
    """The fee is quadratic in price, so a bucket-wide average applies the wrong floor.

    Two cells in the SAME bucket [40,50) whose own mean prices differ must get different
    floors: 40c -> 7*0.4*0.6 = 1.68c, 49c -> 7*0.49*0.51 = 1.7493c.
    """
    snaps = [make_snapshot(f"a{i}", f"ea{i}", "T-24h", 40.0, i % 2, category="Sports")
             for i in range(10)]
    snaps += [make_snapshot(f"b{i}", f"eb{i}", "T-24h", 49.0, i % 2, category="Weather")
              for i in range(10)]
    df = analysis.snapshots_to_frame(snaps)
    cf = analysis.cell_fee_floors(df)
    sports = cf[(cf["horizon"] == "T-24h") & (cf["category"] == "Sports") & (cf["bucket"] == 4)]
    weather = cf[(cf["horizon"] == "T-24h") & (cf["category"] == "Weather") & (cf["bucket"] == 4)]
    assert sports.iloc[0]["fee_floor_cents_1leg"] == pytest.approx(1.68, abs=1e-9)
    assert weather.iloc[0]["fee_floor_cents_1leg"] == pytest.approx(1.7493, abs=1e-9)
    assert len(cf) == 180


def test_cell_fee_floor_uses_that_cells_own_fee_multiplier():
    snaps = [make_snapshot(f"z{i}", f"ez{i}", "T-24h", 50.0, i % 2,
                           category="Financial", fee_mult=0.0) for i in range(10)]
    cf = analysis.cell_fee_floors(analysis.snapshots_to_frame(snaps))
    row = cf[(cf["category"] == "Financial") & (cf["bucket"] == 5) & (cf["horizon"] == "T-24h")]
    assert row.iloc[0]["fee_floor_cents_1leg"] == 0.0


def test_overlay_prefers_per_cell_floors_when_the_frame_is_supplied():
    snaps = [make_snapshot(f"a{i}", f"ea{i}", "T-24h", 40.0, i % 2, category="Sports")
             for i in range(10)]
    df = analysis.snapshots_to_frame(snaps)
    cells = analysis.build_cells(df)
    floors = analysis.fee_floor_table(df)
    per_cell = analysis.apply_fee_overlay(cells, floors, df=df)
    assert len(per_cell) == 180
    row = per_cell[(per_cell["category"] == "Sports") & (per_cell["bucket"] == 4)
                   & (per_cell["horizon"] == "T-24h")].iloc[0]
    assert row["fee_floor_cents_1leg"] == pytest.approx(1.68, abs=1e-9)


def test_book_quality_table_separates_tight_from_wide_books():
    """§9's "treat a large miscalibration as a bug first" check.

    A midpoint computed on `yes_bid = 0.00 / yes_ask = 0.94` is 47c but is not a price.
    The diagnostic must separate those from genuinely tight two-sided books.
    """
    snaps = []
    # tight, two-sided, well calibrated
    for i in range(60):
        s = make_snapshot(f"t{i}", f"et{i}", "T-24h", 50.0, i % 2)
        s.update(yes_bid_cents=49.0, yes_ask_cents=51.0, spread_cents=2.0, one_sided_book=False)
        snaps.append(s)
    # wide, one-sided, "mid" is meaningless and almost everything resolves NO
    for i in range(60):
        s = make_snapshot(f"w{i}", f"ew{i}", "T-24h", 47.0, 1 if i < 6 else 0)
        s.update(yes_bid_cents=0.0, yes_ask_cents=94.0, spread_cents=94.0, one_sided_book=True)
        snaps.append(s)
    df = analysis.snapshots_to_frame(snaps)
    bq = analysis.book_quality_table(df)
    by = {r["stratum"]: r for _, r in bq.iterrows()}
    assert abs(by["spread <= 2c"]["difference"]) < 0.02
    assert by["spread > 20c"]["difference"] < -0.30
    assert by["two-sided book"]["n_markets"] == 60
    assert by["one-sided book"]["n_markets"] == 60


def test_book_quality_table_is_empty_safe():
    assert analysis.book_quality_table(analysis.snapshots_to_frame([])).empty
