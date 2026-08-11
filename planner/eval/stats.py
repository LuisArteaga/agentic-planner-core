"""Statistical agreement metrics for judge calibration.

Pure functions with no external dependencies (no scikit-learn), following the
industry-standard judge-calibration loop described in the G-Eval / MT-Bench
literature: sample traces, label them on the rubric scale, then compute
Cohen's kappa (chance-corrected agreement) and MAE between the judge and the
human gold standard.

Reference: "Judging the Judges" (arXiv:2406.12624) — Cohen's kappa is the
robust alignment metric over raw percent agreement.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

# Verbosity-bias alert threshold for the Pearson correlation between the diff
# length (in tokens) and the absolute score difference (judge vs gold). Above
# this the suite flags a verbosity bias.
VERBOSITY_BIAS_THRESHOLD = 0.3


def cohen_kappa(labels_a: Sequence[bool], labels_b: Sequence[bool]) -> Optional[float]:
    """Cohen's kappa between two binary annotators.

    Returns ``None`` when there are fewer than two samples or when both
    annotators are constant and identical ( kappa is undefined because the
    expected agreement ``p_e`` equals 1).
    """
    n = len(labels_a)
    if n < 2 or n != len(labels_b):
        return None

    a = [1 if x else 0 for x in labels_a]
    b = [1 if x else 0 for x in labels_b]

    # Observed agreement
    p_o = sum(1 for x, y in zip(a, b) if x == y) / n

    # Expected (chance) agreement
    p_a1 = sum(a) / n
    p_a0 = 1 - p_a1
    p_b1 = sum(b) / n
    p_b0 = 1 - p_b1
    p_e = p_a1 * p_b1 + p_a0 * p_b0

    if p_e == 1.0:
        # Both annotators perfectly constant and identical => no information.
        return None

    return (p_o - p_e) / (1.0 - p_e)


def mean_absolute_error(
    pred: Sequence[float], gold: Sequence[float]
) -> Optional[float]:
    """Mean absolute error between predicted and gold scores."""
    n = len(pred)
    if n == 0 or n != len(gold):
        return None
    return sum(abs(p - g) for p, g in zip(pred, gold)) / n


# Short alias used throughout the eval suite.
mae = mean_absolute_error


def hard_flips(
    pred_passed: Sequence[bool],
    gold_passed: Sequence[bool],
) -> Tuple[int, List[int]]:
    """Count and locate samples where the judge flipped the verdict.

    A *hard flip* is a sample where ``pred_passed`` differs from
    ``gold_passed`` — i.e. the model change regressed the verdict relative to
    the human gold standard. Returns ``(count, indices)``.
    """
    if len(pred_passed) != len(gold_passed):
        raise ValueError(
            f"length mismatch: pred={len(pred_passed)} gold={len(gold_passed)}"
        )
    indices = [i for i, (p, g) in enumerate(zip(pred_passed, gold_passed)) if p != g]
    return len(indices), indices


def pearson_r(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    """Pearson correlation coefficient. Returns ``None`` if undefined."""
    n = len(x)
    if n < 2 or n != len(y):
        return None
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    den_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
    den_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)


def verbosity_bias(
    diff_token_counts: Sequence[float],
    score_diffs: Sequence[float],
) -> Tuple[Optional[float], bool]:
    """Pearson r between diff length and |judge_score - gold_score|.

    Returns ``(r, flagged)`` where ``flagged`` is ``True`` when ``r`` exceeds
    :data:`VERBOSITY_BIAS_THRESHOLD`.
    """
    r = pearson_r(diff_token_counts, score_diffs)
    return r, r is not None and r > VERBOSITY_BIAS_THRESHOLD


def percentile(sorted_values: Sequence[float], pct: float) -> Optional[float]:
    """Linear-interpolation percentile of an already-sorted sequence.

    ``pct`` is in [0, 100]. Returns ``None`` for an empty sequence.
    """
    n = len(sorted_values)
    if n == 0:
        return None
    if n == 1:
        return float(sorted_values[0])
    if pct <= 0:
        return float(sorted_values[0])
    if pct >= 100:
        return float(sorted_values[-1])
    rank = (pct / 100.0) * (n - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return float(sorted_values[lo])
    frac = rank - lo
    return float(sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac)


def median(values: Sequence[float]) -> Optional[float]:
    """Median of a sequence (sorts internally)."""
    return percentile(sorted(values), 50.0) if values else None


def p95(values: Sequence[float]) -> Optional[float]:
    """95th percentile of a sequence (sorts internally)."""
    return percentile(sorted(values), 95.0) if values else None
