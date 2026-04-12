"""
Core analysis engine for IO test results.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from ..config import AnalysisConfig
from ..data.models import FlowData, ParameterSummary
from .statistics import (
    detect_outliers_iqr,
    shapiro_wilk,
    skew_analysis,
    two_sample_ttest,
)

logger = logging.getLogger(__name__)


class IOAnalyzer:
    """
    Performs per-parameter and cross-flow analysis of IO test results.

    Usage
    -----
    >>> analyzer = IOAnalyzer(config)
    >>> results = analyzer.analyze(flows)   # flows: Dict[str, FlowData]
    >>> summary_df = results["summary"]
    >>> cross_df   = results["cross_flow"]
    """

    def __init__(self, config: AnalysisConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def analyze(self, flows: Dict[str, FlowData]) -> Dict[str, pd.DataFrame]:
        """
        Run the full analysis pipeline and return a dict of DataFrames:

        - ``"summary"``     : per-parameter per-flow statistics
        - ``"cross_flow"``  : cross-flow comparison (where both flows share a param)
        - ``"outliers"``    : records flagged as statistical outliers
        - ``"normality"``   : Shapiro-Wilk test results per parameter/flow
        - ``"yield_summary"``: per-parameter pass/fail yield across flows
        """
        summary_rows: List[dict] = []
        normality_rows: List[dict] = []
        outlier_rows: List[dict] = []

        for flow_name, flow_data in flows.items():
            for summary in flow_data.summaries:
                row = summary.to_dict()

                # Skewness / kurtosis
                sk = skew_analysis(summary.values)
                row.update({"skewness": round(sk["skewness"], 4),
                             "kurtosis": round(sk["kurtosis"], 4)})

                summary_rows.append(row)

                # Normality
                w, p = shapiro_wilk(summary.values)
                normality_rows.append({
                    "parameter": summary.parameter,
                    "flow": flow_name,
                    "shapiro_W": round(w, 4) if not np.isnan(w) else "N/A",
                    "shapiro_p": round(p, 4) if not np.isnan(p) else "N/A",
                    "normal_at_0.05": (p > 0.05) if not np.isnan(p) else None,
                })

                # Outliers
                if len(summary.values) >= 4:
                    flags = detect_outliers_iqr(summary.values)
                    for rec, is_out in zip(flow_data.records, flags):
                        if rec.parameter == summary.parameter and is_out:
                            outlier_rows.append({
                                "parameter": rec.parameter,
                                "flow": flow_name,
                                "dut_id": rec.dut_id,
                                "pin": rec.pin,
                                "condition": rec.condition,
                                "value": rec.value,
                                "unit": rec.unit,
                            })

        summary_df = pd.DataFrame(summary_rows)
        normality_df = pd.DataFrame(normality_rows)
        outlier_df = pd.DataFrame(outlier_rows)

        cross_df = self._cross_flow_analysis(flows, summary_df)
        yield_df = self._yield_summary(flows)

        return {
            "summary": summary_df,
            "cross_flow": cross_df,
            "outliers": outlier_df,
            "normality": normality_df,
            "yield_summary": yield_df,
        }

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _cross_flow_analysis(
        self,
        flows: Dict[str, FlowData],
        summary_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Compare parameters that appear in both Flow1 and Flow2."""
        flow_names = list(flows.keys())
        if len(flow_names) < 2:
            return pd.DataFrame()

        rows: List[dict] = []
        flow_a_name, flow_b_name = flow_names[0], flow_names[1]
        flow_a = flows[flow_a_name]
        flow_b = flows[flow_b_name]

        shared_params = set(flow_a.parameters) & set(flow_b.parameters)

        for param in sorted(shared_params):
            sa = flow_a.get_summary(param)
            sb = flow_b.get_summary(param)
            if sa is None or sb is None:
                continue

            ttest = two_sample_ttest(sa.values, sb.values)

            rows.append({
                "parameter": param,
                f"mean_{flow_a_name}": round(sa.mean, 6),
                f"mean_{flow_b_name}": round(sb.mean, 6),
                f"std_{flow_a_name}": round(sa.std, 6),
                f"std_{flow_b_name}": round(sb.std, 6),
                f"cpk_{flow_a_name}": round(sa.cpk, 4) if not np.isnan(sa.cpk) else "N/A",
                f"cpk_{flow_b_name}": round(sb.cpk, 4) if not np.isnan(sb.cpk) else "N/A",
                f"yield%_{flow_a_name}": round(sa.yield_pct, 2),
                f"yield%_{flow_b_name}": round(sb.yield_pct, 2),
                "mean_diff": round(ttest["mean_diff"], 6),
                "t_stat": round(ttest["t_stat"], 4) if not np.isnan(ttest["t_stat"]) else "N/A",
                "p_value": round(ttest["p_value"], 4) if not np.isnan(ttest["p_value"]) else "N/A",
                "significant_diff": (
                    ttest["p_value"] < 0.05 if not np.isnan(ttest["p_value"]) else None
                ),
                "unit": sa.unit,
            })

        return pd.DataFrame(rows)

    # ------------------------------------------------------------------ #

    def _yield_summary(self, flows: Dict[str, FlowData]) -> pd.DataFrame:
        """Create a pivot table: parameters × flows showing yield %."""
        rows: List[dict] = []
        for flow_name, flow_data in flows.items():
            for s in flow_data.summaries:
                rows.append({
                    "parameter": s.parameter,
                    "flow": flow_name,
                    "total": s.count,
                    "pass": s.pass_count,
                    "fail": s.fail_count,
                    "yield_%": round(s.yield_pct, 2),
                })
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------ #

    def get_failing_parameters(
        self, flows: Dict[str, FlowData]
    ) -> pd.DataFrame:
        """Return all parameters that have at least one failing measurement."""
        rows: List[dict] = []
        for flow_name, flow_data in flows.items():
            for s in flow_data.summaries:
                if s.fail_count > 0:
                    rows.append({
                        "parameter": s.parameter,
                        "flow": flow_name,
                        "fail_count": s.fail_count,
                        "total": s.count,
                        "yield_%": round(s.yield_pct, 2),
                    })
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------ #

    def cpk_status(
        self, flows: Dict[str, FlowData]
    ) -> pd.DataFrame:
        """Return Cpk status for all parameters, flagging those below target."""
        target = self.config.cpk_target
        rows: List[dict] = []
        for flow_name, flow_data in flows.items():
            for s in flow_data.summaries:
                if not np.isnan(s.cpk):
                    rows.append({
                        "parameter": s.parameter,
                        "flow": flow_name,
                        "cpk": round(s.cpk, 4),
                        "cpk_target": target,
                        "meets_target": s.cpk >= target,
                        "unit": s.unit,
                    })
        return pd.DataFrame(rows)
