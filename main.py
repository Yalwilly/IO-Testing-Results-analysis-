"""Main entry point for IO Testing Results Analysis.

Usage:
    python main.py --data-path ./sample_data --output ./output
    python main.py --data-path "\\\\server\\share\\Results" --output ./report
"""

import argparse
import logging
import sys
from pathlib import Path

from io_analysis.config import Config
from io_analysis.data.loader import load_all_flows
from io_analysis.analysis.analyzer import run_analysis
from io_analysis.plotting.plotter import generate_all_plots
from io_analysis.reporting.report_generator import generate_report


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="IO Electrical Validation Results Analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --data-path ./sample_data
  python main.py --data-path /path/to/results --output ./my_report
  python main.py --data-path "\\\\server\\share\\Results" --flows Flow1 Flow2
        """,
    )
    parser.add_argument(
        "--data-path", "-d",
        type=str,
        default="sample_data",
        help="Path to the data directory containing Flow subdirectories "
             "(default: sample_data)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="output",
        help="Output directory for plots and reports (default: output)",
    )
    parser.add_argument(
        "--flows", "-f",
        nargs="+",
        default=["Flow1", "Flow2"],
        help="Names of flow subdirectories (default: Flow1 Flow2)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose/debug logging",
    )
    parser.add_argument(
        "--title", "-t",
        type=str,
        default="IO Electrical Validation Results",
        help="Report title",
    )
    return parser.parse_args()


def main():
    """Main analysis pipeline."""
    args = parse_args()
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("IO Electrical Validation Results Analysis")
    logger.info("=" * 60)

    # Configuration
    config = Config(
        data_path=Path(args.data_path),
        output_path=Path(args.output),
        flow_dirs=args.flows,
    )
    config.report.title = args.title

    logger.info(f"Data path: {config.data_path}")
    logger.info(f"Output path: {config.output_path}")
    logger.info(f"Flows: {config.flow_dirs}")

    # Step 1: Load data
    logger.info("-" * 40)
    logger.info("Step 1: Loading data...")
    flows = load_all_flows(config)

    if not flows:
        logger.error(
            "No data loaded. Please check your data path and file formats.\n"
            f"  Expected: {config.data_path}/Flow1/*.csv or *.xlsx\n"
            f"  Expected: {config.data_path}/Flow2/*.csv or *.xlsx"
        )
        sys.exit(1)

    for name, fd in flows.items():
        logger.info(
            f"  {name}: {len(fd.raw_data)} measurements, "
            f"{fd.raw_data['Parameter'].nunique()} parameters, "
            f"{fd.raw_data['DUT_ID'].nunique()} DUTs"
        )

    # Step 2: Analyze
    logger.info("-" * 40)
    logger.info("Step 2: Running analysis...")
    result = run_analysis(flows, config)

    logger.info(f"  Overall pass rate: {result.total_pass_rate:.1f}%")
    logger.info(
        f"  Parameters with failures: "
        f"{result.overall_summary['parameters_with_fails']}"
    )

    # Step 3: Generate plots
    logger.info("-" * 40)
    logger.info("Step 3: Generating plots...")
    plot_paths = generate_all_plots(result, config)

    total_plots = sum(len(v) for v in plot_paths.values())
    logger.info(f"  Generated {total_plots} plots")

    # Step 4: Generate reports
    logger.info("-" * 40)
    logger.info("Step 4: Generating reports...")
    reports = generate_report(result, plot_paths, config)

    logger.info("=" * 60)
    logger.info("Analysis Complete!")
    logger.info(f"  CSV Report: {reports.get('csv', 'N/A')}")
    logger.info(f"  PPTX Report: {reports.get('pptx', 'N/A')}")
    logger.info(f"  Plots: {config.output_path / 'plots'}")
    logger.info("=" * 60)

    # Print summary to stdout
    print("\n" + "=" * 60)
    print("ANALYSIS SUMMARY")
    print("=" * 60)
    print(f"Pass Rate: {result.total_pass_rate:.1f}%")
    print(f"Total Measurements: {result.overall_summary['total_measurements']}")
    print(f"Parameters Tested: {result.overall_summary['total_parameters']}")
    print(f"Flows: {', '.join(result.all_flows)}")
    print("-" * 60)
    for comment in result.comments[:10]:
        print(f"  {comment}")
    print("=" * 60)
    print(f"\nReports saved to: {config.output_path}")


if __name__ == "__main__":
    main()
