"""
Unit tests for DataLoader.
"""

import os
import sys
import pytest
import pandas as pd

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from io_analysis.config import AnalysisConfig
from io_analysis.data.loader import DataLoader
from io_analysis.data.models import FlowData, TestRecord


SAMPLE_DATA_DIR = os.path.join(os.path.dirname(__file__), "sample_data")


# ---------------------------------------------------------------------------

class TestDataLoaderWithSampleData:
    """Integration-style tests using the bundled sample CSV files."""

    @pytest.fixture(scope="class")
    def config(self):
        return AnalysisConfig(results_root=SAMPLE_DATA_DIR)

    @pytest.fixture(scope="class")
    def flows(self, config):
        loader = DataLoader(config)
        return loader.load_all()

    def test_both_flows_loaded(self, flows):
        assert "Flow1" in flows
        assert "Flow2" in flows

    def test_records_non_empty(self, flows):
        for name, fd in flows.items():
            assert len(fd.records) > 0, f"{name} should have records"

    def test_record_fields_populated(self, flows):
        rec = flows["Flow1"].records[0]
        assert rec.parameter != ""
        assert not (rec.value != rec.value)  # not NaN
        assert rec.flow == "Flow1"

    def test_summaries_computed(self, flows):
        for name, fd in flows.items():
            assert len(fd.summaries) > 0, f"{name} should have summaries"

    def test_summary_cpk_numeric(self, flows):
        import numpy as np
        for name, fd in flows.items():
            for s in fd.summaries:
                if not isinstance(s.cpk, float):
                    pytest.fail(f"{name}/{s.parameter}: cpk should be float")

    def test_pass_fail_status_set(self, flows):
        for rec in flows["Flow1"].records[:100]:
            assert rec.status in ("PASS", "FAIL"), f"status must be PASS or FAIL, got {rec.status!r}"

    def test_parameters_known(self, flows):
        expected = {"VOH", "VOL", "VIH", "VIL", "IOH", "IOL",
                    "IIH", "IIL", "tpd", "tr", "tf", "Skew"}
        for name, fd in flows.items():
            found = set(fd.parameters)
            assert expected.issubset(found), \
                f"{name} missing params: {expected - found}"

    def test_dataframe_property(self, flows):
        df = flows["Flow1"].dataframe
        assert isinstance(df, pd.DataFrame)
        assert len(df) == len(flows["Flow1"].records)
        assert "parameter" in df.columns
        assert "value" in df.columns


# ---------------------------------------------------------------------------

class TestDataLoaderMissingFolder:
    """DataLoader should not crash when a flow folder is absent."""

    def test_missing_flow_returns_empty(self, tmp_path):
        config = AnalysisConfig(
            results_root=str(tmp_path),
            flow_folders=["FlowX"],
        )
        loader = DataLoader(config)
        flows = loader.load_all()
        assert "FlowX" in flows
        assert flows["FlowX"].records == []


# ---------------------------------------------------------------------------

class TestDataLoaderColumnAliases:
    """Loader must handle alternative column name conventions."""

    def test_alternative_columns(self, tmp_path):
        # Create a CSV with non-standard column names
        df = pd.DataFrame({
            "Test":       ["VOH", "VOL"],
            "Result":     [3.1, 0.2],
            "UnitName":   ["V", "V"],
            "Device":     ["DUT_001", "DUT_001"],
            "PinName":    ["IO1", "IO1"],
            "Corner":     ["TYP", "TYP"],
            "LoLimit":    [2.4, 0.0],
            "HiLimit":    [3.6, 0.4],
            "PASS_FAIL":  ["PASS", "PASS"],
        })
        flow_dir = tmp_path / "Flow1"
        flow_dir.mkdir()
        df.to_csv(flow_dir / "data.csv", index=False)

        config = AnalysisConfig(results_root=str(tmp_path))
        loader = DataLoader(config)
        flows = loader.load_all()

        assert len(flows["Flow1"].records) == 2
        assert flows["Flow1"].records[0].parameter == "VOH"
        assert flows["Flow1"].records[0].value == pytest.approx(3.1)
