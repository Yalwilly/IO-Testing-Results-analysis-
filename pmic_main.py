"""
PMIC DC2DC Validation — standalone entry point.

Usage:
    python pmic_main.py --data "Y:\\path\\to\\Results" --output ./output_pmic
    python pmic_main.py --data ./results --title "PeP TC PMIC" --author "John"
"""

import argparse
import logging
import sys
from pathlib import Path


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="PMIC DC2DC Validation Analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--data", "-d", required=True,
                        help="Path to directory containing Merge/*.csv files")
    parser.add_argument("--output", "-o", default="output_pmic",
                        help="Output directory (default: output_pmic)")
    parser.add_argument("--title",  default="PMIC DC2DC Validation Results")
    parser.add_argument("--subtitle", default="Analog & Digital Converter Characterisation")
    parser.add_argument("--author",   default="Power Validation Team")
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args()


def run_pmic_pipeline(data_path_str: str, output_str: str,
                      title: str = "PMIC DC2DC Validation Results",
                      subtitle: str = "Analog & Digital Converter Characterisation",
                      author: str = "Power Validation Team",
                      compare_data_str: str = None,
                      compare_label: str = "REF") -> Path:
    """
    Full PMIC analysis pipeline.
    Returns path to the generated HTML report.
    """
    logger = logging.getLogger(__name__)
    from pmic_analysis.loader import load_pmic_data
    from pmic_analysis.plotter import generate_all_pmic_plots
    from pmic_analysis.report_generator import generate_pmic_report

    data_path   = Path(data_path_str)
    output_path = Path(output_str)

    if not data_path.exists():
        raise FileNotFoundError(f"Data path not found: {data_path}")

    logger.info("=" * 55)
    logger.info("PMIC DC2DC Validation Analysis")
    logger.info("=" * 55)

    # Step 1 — Load
    logger.info("Step 1 — Loading data from %s", data_path)
    data = load_pmic_data(data_path)
    total_rows = sum(len(v) for v in data.rows_by_test.values())
    if total_rows == 0:
        raise RuntimeError(
            "No PMIC data loaded.  "
            "Ensure the path contains Power_*.csv files "
            "(directly or in a Merge/ subdirectory)."
        )
    logger.info("  Loaded %d rows across %d test types",
                total_rows, len(data.rows_by_test))

    # Step 2 — Reference data (optional)
    ref_data = None
    if compare_data_str:
        ref_path = Path(compare_data_str)
        if ref_path.exists():
            logger.info("Step 2a — Loading reference data from %s", ref_path)
            ref_data = load_pmic_data(ref_path)
            ref_rows = sum(len(v) for v in ref_data.rows_by_test.values())
            logger.info("  Reference: %d rows", ref_rows)
        else:
            logger.warning("Reference data path not found: %s", ref_path)

    # Step 2 — Plots
    logger.info("Step 2 — Generating plots")
    plot_paths = generate_all_pmic_plots(data, output_path,
                                         ref_data=ref_data, ref_label=compare_label)
    n_plots = sum(
        len(paths)
        for section in plot_paths.values()
        if isinstance(section, dict)
        for paths in section.values()
    )
    logger.info("  Generated %d plot files", n_plots)

    # Step 3 — Report
    logger.info("Step 3 — Building HTML report")
    report = generate_pmic_report(
        data, plot_paths, output_path,
        title=title, subtitle=subtitle, author=author,
        has_ref=(ref_data is not None), ref_label=compare_label,
        ref_data=ref_data,
    )

    logger.info("=" * 55)
    logger.info("Done!  Report: %s", report)
    logger.info("=" * 55)
    return report


def main():
    args = parse_args()
    setup_logging(args.verbose)
    try:
        report = run_pmic_pipeline(
            data_path_str=args.data,
            output_str=args.output,
            title=args.title,
            subtitle=args.subtitle,
            author=args.author,
        )
        print(f"\nReport saved: {report}")
    except Exception as exc:
        logging.getLogger(__name__).error("Failed: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
