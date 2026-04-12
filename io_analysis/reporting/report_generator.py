"""
HTML Report Generator for IO test analysis results.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ..config import AnalysisConfig
from ..data.models import FlowData

logger = logging.getLogger(__name__)

try:
    from jinja2 import Environment, FileSystemLoader, pass_eval_context
    JINJA2_AVAILABLE = True
except ImportError:
    JINJA2_AVAILABLE = False
    logger.warning("jinja2 not installed – HTML report generation unavailable")


class ReportGenerator:
    """
    Generates an HTML report from analysis results and plot images.

    Usage
    -----
    >>> gen = ReportGenerator(config)
    >>> report_path = gen.generate(flows, analysis_results, plot_paths)
    """

    def __init__(self, config: AnalysisConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def generate(
        self,
        flows: Dict[str, FlowData],
        analysis: Dict[str, pd.DataFrame],
        plot_paths: Dict[str, str],
    ) -> str:
        """
        Render and save the HTML report.

        Returns the path to the generated report file.
        """
        if not JINJA2_AVAILABLE:
            return self._fallback_report(flows, analysis)

        self.config.ensure_output_dir()
        template = self._load_template()

        context = self._build_context(flows, analysis, plot_paths)
        html = template.render(**context)

        report_path = os.path.join(self.config.output_dir, "io_analysis_report.html")
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(html)

        logger.info("HTML report saved to: %s", report_path)

        # Also export CSV summaries
        self._export_csv(analysis)

        return report_path

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _load_template(self):
        templates_dir = os.path.join(os.path.dirname(__file__), "templates")
        env = Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=False,
        )

        # Custom filter: make image paths relative to the output_dir
        def relpath_filter(absolute: str) -> str:
            if not absolute:
                return ""
            try:
                return os.path.relpath(absolute, self.config.output_dir)
            except ValueError:
                return absolute

        env.filters["relpath"] = relpath_filter
        return env.get_template("report.html")

    # ------------------------------------------------------------------ #

    def _build_context(
        self,
        flows: Dict[str, FlowData],
        analysis: Dict[str, pd.DataFrame],
        plot_paths: Dict[str, str],
    ) -> dict:
        summary_df = analysis.get("summary", pd.DataFrame())
        yield_df = analysis.get("yield_summary", pd.DataFrame())
        cross_df = analysis.get("cross_flow", pd.DataFrame())
        outlier_df = analysis.get("outliers", pd.DataFrame())

        # KPI computations
        total_records = sum(len(fd.records) for fd in flows.values())
        all_params = sorted({p for fd in flows.values() for p in fd.parameters})
        total_pass = int(yield_df["pass"].sum()) if not yield_df.empty and "pass" in yield_df.columns else 0
        total_fail = int(yield_df["fail"].sum()) if not yield_df.empty and "fail" in yield_df.columns else 0
        overall_yield = (
            round(total_pass / (total_pass + total_fail) * 100, 1)
            if (total_pass + total_fail) > 0
            else 0.0
        )

        # Count parameters with Cpk below target
        low_cpk_count = 0
        if not summary_df.empty and "cpk" in summary_df.columns:
            cpk_series = pd.to_numeric(summary_df["cpk"], errors="coerce")
            low_cpk_count = int((cpk_series < self.config.cpk_target).sum())

        kpi = {
            "total_records": total_records,
            "parameters": len(all_params),
            "flows": len(flows),
            "overall_yield": overall_yield,
            "fail_count": total_fail,
            "low_cpk_count": low_cpk_count,
        }

        # Convert DataFrames to list of dicts (NaN → "N/A")
        def df_to_records(df: pd.DataFrame) -> List[dict]:
            if df.empty:
                return []
            return df.replace({float("nan"): "N/A"}).to_dict(orient="records")

        cross_flow_columns: List[str] = []
        cross_flow_table: List[dict] = []
        if not cross_df.empty:
            cross_flow_columns = list(cross_df.columns)
            cross_flow_table = df_to_records(cross_df)

        return {
            "title": self.config.report_title,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "results_root": self.config.results_root,
            "kpi": kpi,
            "cpk_target": self.config.cpk_target,
            "plot_paths": plot_paths,
            "yield_table": df_to_records(yield_df),
            "summary_table": df_to_records(summary_df),
            "cross_flow_columns": cross_flow_columns,
            "cross_flow_table": cross_flow_table,
            "outlier_table": df_to_records(outlier_df),
        }

    # ------------------------------------------------------------------ #

    def _export_csv(self, analysis: Dict[str, pd.DataFrame]) -> None:
        """Save each result DataFrame as a CSV file in the output directory."""
        for name, df in analysis.items():
            if df is not None and not df.empty:
                path = os.path.join(self.config.output_dir, f"{name}.csv")
                df.to_csv(path, index=False)
                logger.debug("Exported %s to %s", name, path)

    # ------------------------------------------------------------------ #

    def _fallback_report(
        self,
        flows: Dict[str, FlowData],
        analysis: Dict[str, pd.DataFrame],
    ) -> str:
        """Minimal plain-text report when Jinja2 is not installed."""
        lines = [
            self.config.report_title,
            "=" * 60,
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]
        for name, df in analysis.items():
            if df is not None and not df.empty:
                lines.append(f"\n--- {name.upper()} ---")
                lines.append(df.to_string(index=False))

        report_path = os.path.join(self.config.output_dir, "io_analysis_report.txt")
        os.makedirs(self.config.output_dir, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        return report_path
