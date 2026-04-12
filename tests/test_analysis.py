"""Unit tests for IO Testing Results Analysis."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from io_analysis.config import Config, SpecLimit, PlotConfig
from io_analysis.data.models import (
    TestResult, ParameterStats, FlowData, AnalysisResult
)
from io_analysis.data.loader import load_single_file, load_flow_data, load_all_flows
from io_analysis.analysis.analyzer import (
    compute_cpk, analyze_parameter, run_analysis
)


class TestSpecLimit(unittest.TestCase):
    """Tests for SpecLimit configuration."""

    def test_within_spec_both_limits(self):
        spec = SpecLimit("VOH", "V", spec_min=2.4, spec_max=3.6)
        self.assertTrue(spec.is_within_spec(3.0))
        self.assertFalse(spec.is_within_spec(2.0))
        self.assertFalse(spec.is_within_spec(4.0))

    def test_within_spec_min_only(self):
        spec = SpecLimit("VOH", "V", spec_min=2.4)
        self.assertTrue(spec.is_within_spec(3.0))
        self.assertFalse(spec.is_within_spec(2.0))

    def test_within_spec_max_only(self):
        spec = SpecLimit("VOL", "V", spec_max=0.4)
        self.assertTrue(spec.is_within_spec(0.2))
        self.assertFalse(spec.is_within_spec(0.5))

    def test_no_limits(self):
        spec = SpecLimit("Test", "V")
        self.assertTrue(spec.is_within_spec(999))


class TestTestResult(unittest.TestCase):
    """Tests for TestResult model."""

    def test_pass_result(self):
        result = TestResult("VOH", 3.0, "V", "DUT_001",
                            spec_min=2.4, spec_max=3.6)
        self.assertTrue(result.passed)

    def test_fail_result_below_min(self):
        result = TestResult("VOH", 2.0, "V", "DUT_001",
                            spec_min=2.4, spec_max=3.6)
        self.assertFalse(result.passed)

    def test_fail_result_above_max(self):
        result = TestResult("VOL", 0.5, "V", "DUT_001",
                            spec_max=0.4)
        self.assertFalse(result.passed)

    def test_margin_calculation(self):
        result = TestResult("VOH", 3.0, "V", "DUT_001",
                            spec_min=2.4, spec_max=3.6)
        self.assertAlmostEqual(result.margin_to_spec, 0.6)

    def test_margin_negative_fail(self):
        result = TestResult("VOH", 2.0, "V", "DUT_001",
                            spec_min=2.4, spec_max=3.6)
        self.assertAlmostEqual(result.margin_to_spec, -0.4)


class TestParameterStats(unittest.TestCase):
    """Tests for ParameterStats model."""

    def test_pass_rate(self):
        stats = ParameterStats("VOH", "V", "Flow1",
                               pass_count=20, fail_count=5)
        self.assertAlmostEqual(stats.pass_rate, 80.0)

    def test_status_all_pass(self):
        stats = ParameterStats("VOH", "V", "Flow1",
                               pass_count=25, fail_count=0)
        self.assertEqual(stats.status, "PASS")

    def test_status_all_fail(self):
        stats = ParameterStats("VOH", "V", "Flow1",
                               pass_count=0, fail_count=25)
        self.assertEqual(stats.status, "FAIL")

    def test_status_marginal(self):
        stats = ParameterStats("VOH", "V", "Flow1",
                               pass_count=20, fail_count=5)
        self.assertIn("MARGINAL", stats.status)

    def test_generate_comment(self):
        stats = ParameterStats("VOH", "V", "Flow1",
                               count=25, mean=3.0, std=0.15,
                               minimum=2.6, maximum=3.4,
                               spec_min=2.4, spec_max=None,
                               pass_count=25, fail_count=0, cpk=1.5)
        comment = stats.generate_comment()
        self.assertIn("ALL PASS", comment)
        self.assertIn("Cpk=1.50", comment)
        self.assertIn("Capable", comment)


class TestCpk(unittest.TestCase):
    """Tests for Cpk computation."""

    def test_cpk_centered(self):
        values = np.array([4.9, 5.0, 5.1, 5.0, 4.95, 5.05])
        cpk = compute_cpk(values, spec_min=4.0, spec_max=6.0)
        self.assertIsNotNone(cpk)
        self.assertGreater(cpk, 1.0)

    def test_cpk_no_limits(self):
        values = np.array([1, 2, 3, 4, 5])
        cpk = compute_cpk(values, None, None)
        self.assertIsNone(cpk)

    def test_cpk_insufficient_data(self):
        values = np.array([5.0])
        cpk = compute_cpk(values, 4.0, 6.0)
        self.assertIsNone(cpk)

    def test_cpk_shifted_process(self):
        values = np.array([5.5, 5.6, 5.7, 5.8, 5.9, 5.95])
        cpk = compute_cpk(values, spec_min=4.0, spec_max=6.0)
        self.assertIsNotNone(cpk)
        # Process shifted toward upper limit
        self.assertLess(cpk, 1.0)


class TestDataLoader(unittest.TestCase):
    """Tests for data loading functionality."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config = Config(
            data_path=Path(self.tmpdir),
            output_path=Path(self.tmpdir) / "output",
        )

    def _create_test_csv(self, flow_name, n_duts=10):
        """Create a test CSV file."""
        flow_dir = Path(self.tmpdir) / flow_name
        flow_dir.mkdir(exist_ok=True)

        rows = []
        for param, mean, std, unit, smin, smax in [
            ("VOH", 3.0, 0.15, "V", 2.4, None),
            ("VOL", 0.2, 0.05, "V", None, 0.4),
        ]:
            for i in range(n_duts):
                value = np.random.normal(mean, std)
                rows.append({
                    "Parameter": param,
                    "Value": round(value, 4),
                    "Unit": unit,
                    "DUT_ID": f"DUT_{i:03d}",
                    "Spec_Min": smin,
                    "Spec_Max": smax,
                })

        df = pd.DataFrame(rows)
        csv_path = flow_dir / f"{flow_name}_results.csv"
        df.to_csv(csv_path, index=False)
        return csv_path

    def test_load_single_csv(self):
        csv_path = self._create_test_csv("Flow1")
        df = load_single_file(csv_path)
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 20)  # 2 params * 10 DUTs

    def test_load_flow_data(self):
        self._create_test_csv("Flow1")
        flow_path = Path(self.tmpdir) / "Flow1"
        fd = load_flow_data(flow_path, "Flow1", self.config)
        self.assertIsNotNone(fd)
        self.assertEqual(fd.flow_name, "Flow1")
        self.assertGreater(len(fd.raw_data), 0)

    def test_load_all_flows(self):
        self._create_test_csv("Flow1")
        self._create_test_csv("Flow2")
        flows = load_all_flows(self.config)
        self.assertEqual(len(flows), 2)
        self.assertIn("Flow1", flows)
        self.assertIn("Flow2", flows)

    def test_load_missing_directory(self):
        flows = load_all_flows(self.config)
        self.assertEqual(len(flows), 0)


class TestAnalyzer(unittest.TestCase):
    """Tests for the analysis engine."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config = Config(
            data_path=Path(self.tmpdir),
            output_path=Path(self.tmpdir) / "output",
        )

    def _create_flow_data(self, flow_name, n_duts=20):
        """Create FlowData with test measurements."""
        np.random.seed(42)
        rows = []
        for param, mean, std, unit, smin, smax in [
            ("VOH", 3.0, 0.15, "V", 2.4, None),
            ("VOL", 0.2, 0.05, "V", None, 0.4),
            ("Rise_Time", 2.5, 0.5, "ns", None, 5.0),
        ]:
            for i in range(n_duts):
                value = np.random.normal(mean, std)
                rows.append({
                    "Parameter": param,
                    "Value": round(value, 4),
                    "Unit": unit,
                    "DUT_ID": f"DUT_{i:03d}",
                    "Spec_Min": smin,
                    "Spec_Max": smax,
                    "Test_Condition": "Nominal",
                })

        df = pd.DataFrame(rows)
        return FlowData(flow_name=flow_name, raw_data=df)

    def test_analyze_parameter(self):
        fd = self._create_flow_data("Flow1")
        param_df = fd.raw_data[fd.raw_data["Parameter"] == "VOH"]
        stats = analyze_parameter(param_df, "VOH", "Flow1", self.config)

        self.assertEqual(stats.parameter, "VOH")
        self.assertEqual(stats.count, 20)
        self.assertGreater(stats.mean, 0)
        self.assertEqual(stats.pass_count + stats.fail_count, 20)

    def test_run_analysis(self):
        flows = {
            "Flow1": self._create_flow_data("Flow1"),
            "Flow2": self._create_flow_data("Flow2"),
        }
        result = run_analysis(flows, self.config)

        self.assertIsInstance(result, AnalysisResult)
        self.assertGreater(len(result.parameter_stats), 0)
        self.assertGreater(len(result.comments), 0)
        self.assertIn("OVERALL:", result.comments[0])

    def test_cross_flow_comparison(self):
        flows = {
            "Flow1": self._create_flow_data("Flow1"),
            "Flow2": self._create_flow_data("Flow2"),
        }
        result = run_analysis(flows, self.config)
        self.assertGreater(len(result.cross_flow_comparison), 0)


if __name__ == "__main__":
    unittest.main()
