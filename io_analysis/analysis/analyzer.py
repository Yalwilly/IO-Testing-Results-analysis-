"""Analysis engine for IO Testing Results.

Computes pass/fail status, statistics, Cpk, and cross-flow comparisons.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from io_analysis.config import Config
from io_analysis.data.models import (
    AnalysisResult,
    FlowData,
    ParameterStats,
    TestResult,
)

logger = logging.getLogger(__name__)


def compute_cpk(values: np.ndarray, spec_min: Optional[float],
                spec_max: Optional[float]) -> Optional[float]:
    """Compute Process Capability Index (Cpk).

    Cpk = min(CPU, CPL) where:
      CPU = (USL - mean) / (3 * sigma)
      CPL = (mean - LSL) / (3 * sigma)

    Returns None if not enough data or no spec limits.
    """
    if len(values) < 2:
        return None

    mean = np.mean(values)
    sigma = np.std(values, ddof=1)

    if sigma == 0 or sigma < 1e-15:
        return None

    cpk_values = []
    if spec_max is not None:
        cpk_values.append((spec_max - mean) / (3 * sigma))
    if spec_min is not None:
        cpk_values.append((mean - spec_min) / (3 * sigma))

    return min(cpk_values) if cpk_values else None


def analyze_parameter(df: pd.DataFrame, parameter: str, flow_name: str,
                      config: Config) -> ParameterStats:
    """Analyze a single parameter from one flow.

    Args:
        df: DataFrame filtered to a single parameter.
        parameter: Parameter name.
        flow_name: Name of the flow.
        config: Configuration object.

    Returns:
        ParameterStats with computed statistics and pass/fail counts.
    """
    values = df["Value"].dropna().values
    unit = df["Unit"].iloc[0] if "Unit" in df.columns and not df["Unit"].empty else ""

    spec_min = df["Spec_Min"].dropna().iloc[0] if (
        "Spec_Min" in df.columns and not df["Spec_Min"].dropna().empty
    ) else None
    spec_max = df["Spec_Max"].dropna().iloc[0] if (
        "Spec_Max" in df.columns and not df["Spec_Max"].dropna().empty
    ) else None

    # Compute pass/fail
    passed = np.ones(len(values), dtype=bool)
    if spec_min is not None:
        passed &= values >= spec_min
    if spec_max is not None:
        passed &= values <= spec_max

    pass_count = int(np.sum(passed))
    fail_count = len(values) - pass_count

    # Compute Cpk
    cpk = compute_cpk(values, spec_min, spec_max)

    param_stats = ParameterStats(
        parameter=parameter,
        unit=unit,
        flow=flow_name,
        count=len(values),
        mean=float(np.mean(values)) if len(values) > 0 else 0.0,
        std=float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
        minimum=float(np.min(values)) if len(values) > 0 else 0.0,
        maximum=float(np.max(values)) if len(values) > 0 else 0.0,
        median=float(np.median(values)) if len(values) > 0 else 0.0,
        spec_min=spec_min,
        spec_max=spec_max,
        pass_count=pass_count,
        fail_count=fail_count,
        cpk=cpk,
        values=values.tolist(),
    )

    logger.debug(
        f"  {flow_name}/{parameter}: {pass_count}/{len(values)} PASS, "
        f"Cpk={cpk:.2f}" if cpk else
        f"  {flow_name}/{parameter}: {pass_count}/{len(values)} PASS"
    )

    return param_stats


def analyze_flow(flow_data: FlowData, config: Config) -> dict:
    """Analyze all parameters in a single flow.

    Returns:
        Dictionary mapping parameter_name -> ParameterStats.
    """
    results = {}
    df = flow_data.raw_data

    for param in df["Parameter"].unique():
        param_df = df[df["Parameter"] == param]
        stats = analyze_parameter(param_df, param, flow_data.flow_name, config)
        results[param] = stats

    return results


def compare_flows(flow_stats: dict, config: Config) -> dict:
    """Compare results across flows for each parameter.

    Args:
        flow_stats: Dict of flow_name -> {param_name -> ParameterStats}.

    Returns:
        Dict of param -> comparison info.
    """
    all_params = set()
    for stats in flow_stats.values():
        all_params.update(stats.keys())

    comparisons = {}
    for param in sorted(all_params):
        comparison = {
            "parameter": param,
            "flows": {},
            "comment": "",
        }

        means = []
        pass_rates = []
        flow_names = []

        for flow_name, stats in flow_stats.items():
            if param in stats:
                s = stats[param]
                comparison["flows"][flow_name] = {
                    "mean": s.mean,
                    "std": s.std,
                    "pass_rate": s.pass_rate,
                    "cpk": s.cpk,
                    "status": s.status,
                    "count": s.count,
                }
                means.append(s.mean)
                pass_rates.append(s.pass_rate)
                flow_names.append(flow_name)

        # Generate cross-flow comparison comment
        if len(means) > 1:
            mean_diff = abs(means[0] - means[1])
            avg_std = np.mean([
                flow_stats[fn][param].std
                for fn in flow_names if param in flow_stats[fn]
            ])

            parts = []
            if all(pr == 100.0 for pr in pass_rates):
                parts.append(f"{param}: Both flows PASS")
            elif any(pr < 100.0 for pr in pass_rates):
                failing = [fn for fn, pr in zip(flow_names, pass_rates) if pr < 100]
                parts.append(f"{param}: Failures in {', '.join(failing)}")

            if avg_std > 0 and mean_diff > 2 * avg_std:
                parts.append(f"Significant mean shift between flows ({mean_diff:.4f})")
            else:
                parts.append(f"Consistent between flows (delta={mean_diff:.4f})")

            comparison["comment"] = " | ".join(parts)

        comparisons[param] = comparison

    return comparisons


def run_analysis(flows: dict, config: Config) -> AnalysisResult:
    """Run the complete analysis pipeline.

    Args:
        flows: Dict of flow_name -> FlowData (from loader).
        config: Configuration object.

    Returns:
        Complete AnalysisResult with statistics, comparisons, and comments.
    """
    result = AnalysisResult()
    result.flow_data = flows

    # Analyze each flow
    flow_stats = {}
    for flow_name, flow_data in flows.items():
        logger.info(f"Analyzing {flow_name}...")
        stats = analyze_flow(flow_data, config)
        flow_stats[flow_name] = stats

        for param, param_stats in stats.items():
            result.parameter_stats[(flow_name, param)] = param_stats

    # Cross-flow comparison
    if len(flow_stats) > 1:
        result.cross_flow_comparison = compare_flows(flow_stats, config)

    # Generate overall summary
    total_params = len(set(p for _, p in result.parameter_stats.keys()))
    total_pass = sum(s.pass_count for s in result.parameter_stats.values())
    total_fail = sum(s.fail_count for s in result.parameter_stats.values())
    total_measurements = total_pass + total_fail

    result.overall_summary = {
        "total_parameters": total_params,
        "total_flows": len(flows),
        "total_measurements": total_measurements,
        "total_pass": total_pass,
        "total_fail": total_fail,
        "overall_pass_rate": (
            total_pass / total_measurements * 100 if total_measurements > 0 else 0
        ),
        "parameters_all_pass": sum(
            1 for s in result.parameter_stats.values() if s.fail_count == 0
        ),
        "parameters_with_fails": sum(
            1 for s in result.parameter_stats.values() if s.fail_count > 0
        ),
    }

    # Generate comments for each parameter
    for key, stats in result.parameter_stats.items():
        comment = stats.generate_comment(config.cpk_threshold)
        result.comments.append(comment)

    # Add cross-flow comments
    for param, comp in result.cross_flow_comparison.items():
        if comp["comment"]:
            result.comments.append(f"[Cross-Flow] {comp['comment']}")

    # Overall summary comment
    result.comments.insert(0, (
        f"OVERALL: {total_pass}/{total_measurements} PASS "
        f"({result.overall_summary['overall_pass_rate']:.1f}%) | "
        f"{total_params} parameters across {len(flows)} flows | "
        f"{result.overall_summary['parameters_all_pass']} params all-pass, "
        f"{result.overall_summary['parameters_with_fails']} params with failures"
    ))

    logger.info(
        f"Analysis complete: {total_measurements} measurements, "
        f"{result.overall_summary['overall_pass_rate']:.1f}% pass rate"
    )

    return result
