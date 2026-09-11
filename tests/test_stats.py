import math

import numpy as np

from kalshi008.stats import calibration_cell, permute_outcomes_within_group


def test_clustering_inflates_se_when_markets_share_an_event():
    p = [0.4] * 10
    y = [1, 1, 1, 1, 1, 0, 0, 0, 0, 0]
    indep = calibration_cell(p, y, [f"e{i}" for i in range(10)])
    dep = calibration_cell(p, y, ["A"] * 5 + ["B"] * 5)
    assert math.isclose(indep.se_naive, dep.se_naive, rel_tol=1e-12)
    assert indep.difference == dep.difference
    assert dep.se_clustered_cr1 > indep.se_clustered_cr1
    assert abs(dep.t_clustered) < abs(indep.t_clustered)
    assert indep.n_events == 10 and dep.n_events == 2


def test_effective_n_is_events_not_markets():
    c = calibration_cell([0.4] * 30, [1] * 15 + [0] * 15, ["E1"] * 20 + ["E2"] * 10)
    assert c.n_markets == 30
    assert c.n_events == 2


def test_single_cluster_yields_no_clustered_se():
    c = calibration_cell([0.5] * 5, [1, 0, 1, 0, 1], ["only"] * 5)
    assert c.n_events == 1
    assert math.isnan(c.se_clustered_cr1)
    assert math.isnan(c.t_clustered)


def test_cr1_is_more_conservative_than_cr0():
    c = calibration_cell([0.5] * 12, [1, 0] * 6, [f"e{i//3}" for i in range(12)])
    assert c.se_clustered_cr1 > c.se_clustered_cr0


def test_perfectly_calibrated_data_gives_zero_difference():
    c = calibration_cell([0.5] * 4, [1, 0, 1, 0], ["a", "b", "c", "d"])
    assert math.isclose(c.difference, 0.0, abs_tol=1e-12)
    assert math.isclose(c.mean_implied_price, 0.5)
    assert math.isclose(c.realized_frequency, 0.5)


def test_permutation_preserves_each_groups_yes_count_exactly():
    rng = np.random.default_rng(1)
    y = np.array([1, 1, 0, 0, 0, 1, 0, 0, 1, 1, 1, 0])
    g = np.array(["A"] * 6 + ["B"] * 6)
    for _ in range(50):
        out = permute_outcomes_within_group(y, g, rng)
        for grp in ("A", "B"):
            m = g == grp
            assert out[m].sum() == y[m].sum()
        assert out.sum() == y.sum()


def test_permutation_actually_shuffles():
    rng = np.random.default_rng(2)
    y = np.array([1] * 10 + [0] * 10)
    g = np.array(["A"] * 20)
    seen = {tuple(permute_outcomes_within_group(y, g, rng)) for _ in range(30)}
    assert len(seen) > 1


def test_nested_ladder_degeneracy_cannot_manufacture_a_finding():
    p = [0.5] * 30
    y = [0] * 30
    ev = [f"E{i // 5}" for i in range(30)]
    c = calibration_cell(p, y, ev)

    assert c.n_events == 6
    assert c.se_clustered_cr1 == 0.0
    assert math.isnan(c.t_clustered_unguarded)
    assert math.isclose(c.se_binomial, 0.0912870929, rel_tol=1e-6)
    assert math.isclose(c.se_binomial_clustered, 0.5 / math.sqrt(6), rel_tol=1e-9)
    assert c.se_governing == c.se_binomial_clustered
    assert abs(c.t_clustered) < 2.5
    assert abs(c.t_clustered) < 3.5


def test_clustered_model_se_collapses_to_the_independent_one_when_each_market_is_its_own_event():
    p = [0.06, 0.05, 0.09, 0.09, 0.08, 0.07, 0.05, 0.05, 0.08]
    c = calibration_cell(p, [0] * 9, [f"e{i}" for i in range(9)])
    assert math.isclose(c.se_binomial_clustered, c.se_binomial, rel_tol=1e-12)


def test_clustered_model_se_is_never_smaller_than_the_independent_one():
    import numpy as _np
    rng = _np.random.default_rng(4)
    for _ in range(50):
        n = int(rng.integers(4, 40))
        p = list(rng.uniform(0.02, 0.98, n))
        y = list(rng.integers(0, 2, n))
        ev = [f"E{int(v)}" for v in rng.integers(0, max(2, n // 3), n)]
        c = calibration_cell(p, y, ev)
        assert c.se_binomial_clustered >= c.se_binomial - 1e-12


def test_exact_enumeration_false_positive_rate_is_zero():
    import itertools
    p = [0.5] * 30
    ev = [f"E{i // 5}" for i in range(30)]
    passing = 0
    for bits in itertools.product([0, 1], repeat=6):
        y = [bits[i // 5] for i in range(30)]
        c = calibration_cell(p, y, ev)
        t = abs(c.t_clustered) if not math.isnan(c.t_clustered) else 0.0
        if t > 3.5:
            passing += 1
    assert passing == 0, f"{passing}/64 false positives on calibrated data"
