"""
Unit tests for IOAnalyzer.
"""

import os
import sys
import pytest
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from io_analysis.config import AnalysisConfig
from io_analysis.data.loader import DataLoader
from io_analysis.analysis.analyzer import IOAnalyzer
from io_analysis.analysis.statistics import (
    compute_cpk,
    compute_cp,
    detect_outliers_iqr,
    two_sample_ttest,
    skew_analysis,
    shapiro_wilk,
)


SAMPLE_DATA_DIR = os.path.join(os.path.dirname(__file__), "sample_data")


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

class TestStatisticsHelpers:

    def test_cpk_perfect_centre(self):
        # Values right at centre of limits → Cpk ≈ Cp
        values = np.random.normal(5.0, 0.1, 100).tolist()
        cpk = compute_cpk(values, low_limit=4.0, high_limit=6.0)
        assert cpk > 1.0

    def test_cpk_nan_without_limits(self):
        cpk = compute_cpk([1, 2, 3], None, None)
        assert np.isnan(cpk)

    def test_cp_symmetric(self):
        values = np.random.normal(0, 1, 200).tolist()
        cp = compute_cp(values, -3, 3)
        assert cp > 0

    def test_outlier_detection(self):
        values = [1.0] * 18 + [100.0, -100.0]  # 2 obvious outliers
        flags = detect_outliers_iqr(values)
        assert flags[-1] is True
        assert flags[-2] is True
        assert sum(flags) == 2

    def test_t_test_same_distribution(self):
        rng = np.random.default_rng(0)
        a = rng.normal(5, 0.1, 50).tolist()
        b = rng.normal(5, 0.1, 50).tolist()
        result = two_sample_ttest(a, b)
        # Should NOT be significant (large p-value expected for same distribution)
        assert result["p_value"] > 0.01

    def test_t_test_different_means(self):
        rng = np.random.default_rng(1)
        a = rng.normal(5.0, 0.05, 50).tolist()
        b = rng.normal(5.5, 0.05, 50).tolist()
        result = two_sample_ttest(a, b)
        assert result["p_value"] < 0.05

    def test_skew_analysis_returns_keys(self):
        vals = np.random.normal(0, 1, 100).tolist()
        result = skew_analysis(vals)
        assert "skewness" in result
        assert "kurtosis" in result

    def test_shapiro_wilk_normal(self):
        vals = np.random.normal(0, 1, 50).tolist()
        w, p = shapiro_wilk(vals)
        assert not np.isnan(w)
        assert not np.isnan(p)
        assert 0 <= p <= 1

    def test_shapiro_wilk_too_few(self):
        w, p = shapiro_wilk([1.0, 2.0])
        assert np.isnan(w)


# ---------------------------------------------------------------------------
# Analyzer integration tests
# ---------------------------------------------------------------------------

class TestIOAnalyzer:

    @pytest.fixture(scope="class")
    def analysis_results(self):
        config = AnalysisConfig(results_root=SAMPLE_DATA_DIR)
        loader = DataLoader(config)
        flows = loader.load_all()
        analyzer = IOAnalyzer(config)
        return analyzer.analyze(flows), flows

    def test_returns_expected_keys(self, analysis_results):
        results, _ = analysis_results
        for key in ("summary", "cross_flow", "outliers", "normality", "yield_summary"):
            assert key in results

    def test_summary_has_rows(self, analysis_results):
        results, _ = analysis_results
        assert not results["summary"].empty

    def test_summary_columns(self, analysis_results):
        results, _ = analysis_results
        df = results["summary"]
        for col in ("parameter", "flow", "mean", "std", "cpk", "yield_%"):
            assert col in df.columns, f"Missing column: {col}"

    def test_cross_flow_has_both_flows(self, analysis_results):
        results, _ = analysis_results
        cf = results["cross_flow"]
        assert not cf.empty
        # Should have mean columns for both flows (exclude mean_diff)
        mean_cols = [c for c in cf.columns if c.startswith("mean_") and c != "mean_diff"]
        assert len(mean_cols) == 2

    def test_yield_summary_100_or_less(self, analysis_results):
        results, _ = analysis_results
        df = results["yield_summary"]
        assert (df["yield_%"] <= 100).all()
        assert (df["yield_%"] >= 0).all()

    def test_failing_parameters_method(self, analysis_results):
        results, flows = analysis_results
        config = AnalysisConfig(results_root=SAMPLE_DATA_DIR)
        analyzer = IOAnalyzer(config)
        failing = analyzer.get_failing_parameters(flows)
        # There should be some failures (we injected 2% fail rate)
        assert not failing.empty

    def test_cpk_status_method(self, analysis_results):
        results, flows = analysis_results
        config = AnalysisConfig(results_root=SAMPLE_DATA_DIR)
        analyzer = IOAnalyzer(config)
        cpk_df = analyzer.cpk_status(flows)
        assert not cpk_df.empty
        assert "meets_target" in cpk_df.columns
