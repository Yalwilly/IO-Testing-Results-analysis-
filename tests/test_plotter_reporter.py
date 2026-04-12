"""
Unit tests for IOPlotter and ReportGenerator.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from io_analysis.config import AnalysisConfig
from io_analysis.data.loader import DataLoader
from io_analysis.analysis.analyzer import IOAnalyzer
from io_analysis.plotting.plotter import IOPlotter
from io_analysis.reporting.report_generator import ReportGenerator


SAMPLE_DATA_DIR = os.path.join(os.path.dirname(__file__), "sample_data")


@pytest.fixture(scope="module")
def full_run(tmp_path_factory):
    """Perform a full analysis run and return all artifacts."""
    out_dir = str(tmp_path_factory.mktemp("output"))
    config = AnalysisConfig(
        results_root=SAMPLE_DATA_DIR,
        output_dir=out_dir,
        figure_dpi=72,           # lower DPI for faster tests
    )
    loader = DataLoader(config)
    flows = loader.load_all()
    analyzer = IOAnalyzer(config)
    analysis = analyzer.analyze(flows)
    plotter = IOPlotter(config)
    plot_paths = plotter.plot_all(flows, analysis)
    reporter = ReportGenerator(config)
    report_path = reporter.generate(flows, analysis, plot_paths)
    return {
        "config": config,
        "flows": flows,
        "analysis": analysis,
        "plot_paths": plot_paths,
        "report_path": report_path,
    }


# ---------------------------------------------------------------------------
# Plotter tests
# ---------------------------------------------------------------------------

class TestIOPlotter:

    def test_yield_bar_created(self, full_run):
        path = full_run["plot_paths"].get("yield_bar", "")
        assert path and os.path.isfile(path), f"yield_bar plot not found: {path}"

    def test_distributions_created(self, full_run):
        path = full_run["plot_paths"].get("distributions", "")
        assert path and os.path.isfile(path)

    def test_boxplot_created(self, full_run):
        path = full_run["plot_paths"].get("boxplot_comparison", "")
        assert path and os.path.isfile(path)

    def test_cpk_bar_created(self, full_run):
        path = full_run["plot_paths"].get("cpk_bar", "")
        assert path and os.path.isfile(path)

    def test_cross_flow_scatter_created(self, full_run):
        path = full_run["plot_paths"].get("cross_flow_scatter", "")
        assert path and os.path.isfile(path)

    def test_skew_plot_created(self, full_run):
        path = full_run["plot_paths"].get("skew_plot", "")
        assert path and os.path.isfile(path)

    def test_passfail_heatmap_created(self, full_run):
        path = full_run["plot_paths"].get("passfail_heatmap", "")
        assert path and os.path.isfile(path)

    def test_all_plots_are_png(self, full_run):
        for key, path in full_run["plot_paths"].items():
            if path:
                assert path.endswith(".png"), f"Expected .png, got: {path}"
                assert os.path.getsize(path) > 0, f"Empty file: {path}"


# ---------------------------------------------------------------------------
# Report generator tests
# ---------------------------------------------------------------------------

class TestReportGenerator:

    def test_report_file_created(self, full_run):
        path = full_run["report_path"]
        assert os.path.isfile(path), f"Report file not found: {path}"
        assert os.path.getsize(path) > 0

    def test_report_is_html(self, full_run):
        path = full_run["report_path"]
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
        assert "<!DOCTYPE html>" in content.upper() or "<html" in content.lower()

    def test_report_contains_title(self, full_run):
        config = full_run["config"]
        path = full_run["report_path"]
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
        # The report title should appear somewhere in the HTML
        assert "IO Electrical Validation" in content

    def test_csv_exports_created(self, full_run):
        out_dir = full_run["config"].output_dir
        for name in ("summary", "yield_summary"):
            csv_path = os.path.join(out_dir, f"{name}.csv")
            assert os.path.isfile(csv_path), f"Missing CSV export: {csv_path}"
