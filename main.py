"""
IO Testing Results Analysis – Command-line entry point.

Usage examples
--------------
Analyse with default sample data:
    python main.py

Analyse a real results folder:
    python main.py --path "\\\\server\\Results" --output "C:\\Reports\\ww09"

Analyse with a custom Cpk target and report title:
    python main.py --path /data/Results --output ./reports --cpk-target 1.67 \
                   --title "IO EFV Analysis – WW09'26"
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from io_analysis.config import AnalysisConfig
from io_analysis.data.loader import DataLoader
from io_analysis.analysis.analyzer import IOAnalyzer
from io_analysis.plotting.plotter import IOPlotter
from io_analysis.reporting.report_generator import ReportGenerator


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="io_analysis",
        description="Analyse Electrical Validation IO test results and generate a report.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--path",
        default=None,
        help=(
            "Root directory that contains the Flow1 and Flow2 sub-folders. "
            "Defaults to the bundled sample data in tests/sample_data/."
        ),
    )
    parser.add_argument(
        "--output",
        default="output",
        help="Directory where plots and the HTML report will be written.",
    )
    parser.add_argument(
        "--flows",
        nargs="+",
        default=["Flow1", "Flow2"],
        metavar="FLOW",
        help="Names of the flow sub-folders to analyse.",
    )
    parser.add_argument(
        "--cpk-target",
        type=float,
        default=1.33,
        dest="cpk_target",
        help="Minimum acceptable Cpk value (used for colouring in charts and report).",
    )
    parser.add_argument(
        "--title",
        default="IO Electrical Validation – Test Results Analysis",
        help="Title shown in the HTML report header.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=150,
        help="Resolution (DPI) for saved plot images.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose (DEBUG) logging.",
    )
    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(args=None) -> int:
    parser = build_parser()
    ns = parser.parse_args(args)

    if ns.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Resolve results root
    if ns.path:
        results_root = ns.path
    else:
        # Fall back to the bundled sample data
        results_root = os.path.join(
            os.path.dirname(__file__), "tests", "sample_data"
        )
        logger.info("No --path provided. Using bundled sample data at: %s", results_root)

    # Build configuration
    config = AnalysisConfig(
        results_root=results_root,
        output_dir=ns.output,
        flow_folders=ns.flows,
        report_title=ns.title,
        figure_dpi=ns.dpi,
        cpk_target=ns.cpk_target,
    )
    config.ensure_output_dir()

    logger.info("Results root : %s", config.results_root)
    logger.info("Output dir   : %s", os.path.abspath(config.output_dir))
    logger.info("Flows        : %s", config.flow_folders)

    # ── 1. Load data ──────────────────────────────────────────────────────
    loader = DataLoader(config)
    flows = loader.load_all()

    total_records = sum(len(fd.records) for fd in flows.values())
    if total_records == 0:
        logger.error(
            "No records loaded from '%s'. "
            "Please check that Flow1 / Flow2 sub-folders exist and contain CSV or Excel files.",
            results_root,
        )
        return 1

    logger.info("Total records loaded: %d across %d flow(s)", total_records, len(flows))

    # ── 2. Analyse ────────────────────────────────────────────────────────
    analyzer = IOAnalyzer(config)
    analysis = analyzer.analyze(flows)
    logger.info("Analysis complete. Summary rows: %d", len(analysis["summary"]))

    # ── 3. Plot ───────────────────────────────────────────────────────────
    plotter = IOPlotter(config)
    plot_paths = plotter.plot_all(flows, analysis)
    logger.info("Generated %d plot(s)", len(plot_paths))

    # ── 4. Report ─────────────────────────────────────────────────────────
    reporter = ReportGenerator(config)
    report_path = reporter.generate(flows, analysis, plot_paths)
    logger.info("Report written to: %s", os.path.abspath(report_path))

    print(f"\n✔  Analysis complete. Report: {os.path.abspath(report_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
