"""
Statistical helpers for IO analysis.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy import stats


# ---------------------------------------------------------------------------
# Cpk / Cp
# ---------------------------------------------------------------------------

def compute_cpk(
    values: List[float],
    low_limit: Optional[float],
    high_limit: Optional[float],
) -> float:
    """Return Cpk; NaN when limits are missing or std == 0."""
    if low_limit is None or high_limit is None or len(values) < 2:
        return float("nan")
    arr = np.asarray(values, dtype=float)
    mean = np.mean(arr)
    std = np.std(arr, ddof=1)
    if std == 0:
        return float("nan")
    cpu = (high_limit - mean) / (3 * std)
    cpl = (mean - low_limit) / (3 * std)
    return float(min(cpu, cpl))


def compute_cp(
    values: List[float],
    low_limit: Optional[float],
    high_limit: Optional[float],
) -> float:
    """Return Cp (process capability); NaN when limits missing or std == 0."""
    if low_limit is None or high_limit is None or len(values) < 2:
        return float("nan")
    std = float(np.std(np.asarray(values, dtype=float), ddof=1))
    if std == 0:
        return float("nan")
    return (high_limit - low_limit) / (6 * std)


# ---------------------------------------------------------------------------
# Normality
# ---------------------------------------------------------------------------

def shapiro_wilk(values: List[float]) -> Tuple[float, float]:
    """
    Return (W-statistic, p-value) from Shapiro-Wilk test.
    Falls back to (nan, nan) for <3 samples or scipy unavailable.
    """
    arr = np.asarray(values, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 3:
        return float("nan"), float("nan")
    w, p = stats.shapiro(arr[:5000])   # shapiro limit
    return float(w), float(p)


# ---------------------------------------------------------------------------
# Outlier detection (IQR method)
# ---------------------------------------------------------------------------

def detect_outliers_iqr(
    values: List[float],
    multiplier: float = 1.5,
) -> List[bool]:
    """
    Return a boolean list (same length as *values*) where True marks an outlier
    according to the IQR method.
    """
    arr = np.asarray(values, dtype=float)
    q1, q3 = np.percentile(arr, [25, 75])
    iqr = q3 - q1
    lower = q1 - multiplier * iqr
    upper = q3 + multiplier * iqr
    return [bool(v < lower or v > upper) for v in arr]


# ---------------------------------------------------------------------------
# Cross-flow comparison
# ---------------------------------------------------------------------------

def two_sample_ttest(
    values_a: List[float],
    values_b: List[float],
) -> Dict[str, float]:
    """
    Welch's t-test between two independent samples.

    Returns dict with keys: t_stat, p_value, mean_diff.
    """
    a = np.asarray(values_a, dtype=float)
    b = np.asarray(values_b, dtype=float)
    if len(a) < 2 or len(b) < 2:
        return {"t_stat": float("nan"), "p_value": float("nan"), "mean_diff": float("nan")}
    t_stat, p_value = stats.ttest_ind(a, b, equal_var=False)
    return {
        "t_stat": float(t_stat),
        "p_value": float(p_value),
        "mean_diff": float(np.mean(a) - np.mean(b)),
    }


def skew_analysis(values: List[float]) -> Dict[str, float]:
    """Return skewness and kurtosis of the distribution."""
    arr = np.asarray(values, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 3:
        return {"skewness": float("nan"), "kurtosis": float("nan")}
    return {
        "skewness": float(stats.skew(arr)),
        "kurtosis": float(stats.kurtosis(arr)),
    }
