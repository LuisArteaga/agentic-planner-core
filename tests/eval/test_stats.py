"""Unit tests for the statistical agreement metrics (issue #43 AC).

Covers Cohen's Kappa, MAE, Hard Flips, Verbosity Bias, and percentile helpers.
"""

import math

import pytest

from planner.eval.stats import (
    VERBOSITY_BIAS_THRESHOLD,
    cohen_kappa,
    hard_flips,
    mae,
    median,
    p95,
    percentile,
    pearson_r,
    verbosity_bias,
)


# ----------------------------- Cohen's Kappa -------------------------------


def test_cohen_kappa_perfect_agreement():
    assert cohen_kappa([True, False, True, False], [True, False, True, False]) == 1.0


def test_cohen_kappa_better_than_chance():
    # 3/4 agree, kappa should be positive and below 1
    k = cohen_kappa([True, True, True, False], [True, True, False, False])
    assert k is not None
    assert 0.0 < k < 1.0


def test_cohen_kappa_complete_disagreement():
    # On a balanced set, total disagreement gives kappa < 0
    k = cohen_kappa([True, False, True, False], [False, True, False, True])
    assert k is not None
    assert k < 0.0


def test_cohen_kappa_too_few_samples_returns_none():
    assert cohen_kappa([True], [True]) is None


def test_cohen_kappa_length_mismatch_returns_none():
    assert cohen_kappa([True, False], [True]) is None


def test_cohen_kappa_both_constant_identical_returns_none():
    # p_e == 1 => undefined
    assert cohen_kappa([True, True, True], [True, True, True]) is None


# ----------------------------------- MAE ------------------------------------


def test_mae_basic():
    assert mae([1.0, 0.0, 1.0], [1.0, 1.0, 0.0]) == (0.0 + 1.0 + 1.0) / 3.0


def test_mae_perfect():
    assert mae([0.0, 1.0, 0.0], [0.0, 1.0, 0.0]) == 0.0


def test_mae_empty_returns_none():
    assert mae([], []) is None


def test_mae_length_mismatch_returns_none():
    assert mae([1.0], [1.0, 0.0]) is None


# ------------------------------- Hard Flips --------------------------------


def test_hard_flips_none():
    count, idx = hard_flips([True, False, True], [True, False, True])
    assert count == 0
    assert idx == []


def test_hard_flips_all():
    count, idx = hard_flips([True, False], [False, True])
    assert count == 2
    assert idx == [0, 1]


def test_hard_flips_partial():
    count, idx = hard_flips([True, True, False], [True, False, False])
    assert count == 1
    assert idx == [1]


def test_hard_flips_length_mismatch_raises():
    import pytest

    with pytest.raises(ValueError):
        hard_flips([True], [True, False])


# ----------------------------- Verbosity Bias ------------------------------


def test_verbosity_bias_no_correlation():
    # x ascending, y = [1,-1,-1,1] has zero covariance with x => r == 0.
    r, flagged = verbosity_bias([10, 20, 30, 40], [1, -1, -1, 1])
    assert r == 0.0
    assert flagged is False


def test_verbosity_bias_strong_positive_flagged():
    # score diff grows with diff length => strong positive r
    r, flagged = verbosity_bias([10, 20, 30, 40], [1, 2, 3, 4])
    assert r is not None and r > VERBOSITY_BIAS_THRESHOLD
    assert flagged is True


def test_verbosity_bias_constant_diff_tokens_returns_none():
    # zero variance in x => undefined
    r, flagged = verbosity_bias([10, 10, 10], [1, 2, 3])
    assert r is None
    assert flagged is False


# --------------------------- Percentile / median ----------------------------


def test_percentile_sorted():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    assert percentile(vals, 0) == 1.0
    assert percentile(vals, 100) == 10.0
    assert percentile(vals, 50) == 5.5  # median of 10 values


def test_percentile_empty_returns_none():
    assert percentile([], 50) is None


def test_median_basic():
    assert median([3.0, 1.0, 2.0]) == 2.0


def test_median_single():
    assert median([5.0]) == 5.0


def test_p95_basic():
    # 95th percentile of 1..100
    vals = list(range(1, 101))
    p = p95([float(v) for v in vals])
    assert p is not None
    assert 95.0 <= p <= 96.0


def test_pearson_r_identity():
    # perfect linear correlation
    assert pearson_r([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)


def test_pearson_r_negative():
    r = pearson_r([1, 2, 3, 4], [4, 3, 2, 1])
    assert r is not None and r < 0.0


def test_pearson_r_too_few_returns_none():
    assert pearson_r([1], [1]) is None


# ----------------------- Integration: full metric set ----------------------


def test_full_metric_pipeline_matches_gold_standard():
    """A judge that agrees 3/4 with a balanced gold standard."""
    pred_passed = [True, True, True, False]
    gold_passed = [True, True, False, False]

    k = cohen_kappa(pred_passed, gold_passed)
    count, idx = hard_flips(pred_passed, gold_passed)
    err = mae(
        [1.0 if p else 0.0 for p in pred_passed],
        [1.0 if g else 0.0 for g in gold_passed],
    )

    # 3/4 agreement on balanced labels: kappa is positive
    assert k is not None and 0.0 < k <= 1.0
    assert count == 1
    assert idx == [2]
    assert err is not None
    assert math.isclose(err, 0.25)
