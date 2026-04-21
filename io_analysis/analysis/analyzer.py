"""Analysis engine for IO Testing Results.

Computes pass/fail status, statistics, and Cpk.
Uses Python standard library only (no numpy/scipy).
"""

import math
import logging
import statistics as stats_module
from typing import Optional

from io_analysis.config import Config
from io_analysis.data.models import (
    AnalysisResult,
    FlowData,
    ParameterStats,
)

logger = logging.getLogger(__name__)


def _mean(values: list) -> float:
    return stats_module.mean(values) if values else 0.0


def _stdev(values: list) -> float:
    return stats_module.stdev(values) if len(values) > 1 else 0.0


def _median(values: list) -> float:
    return stats_module.median(values) if values else 0.0


def compute_cpk(values: list, spec_min: Optional[float],
                spec_max: Optional[float]) -> Optional[float]:
    """Compute Process Capability Index (Cpk)."""
    if len(values) < 2:
        return None
    mean = _mean(values)
    sigma = _stdev(values)
    if sigma == 0 or sigma < 1e-15:
        return None
    cpk_values = []
    if spec_max is not None:
        cpk_values.append((spec_max - mean) / (3 * sigma))
    if spec_min is not None:
        cpk_values.append((mean - spec_min) / (3 * sigma))
    return min(cpk_values) if cpk_values else None


def analyze_parameter(rows: list, parameter: str, flow_name: str,
                      config: Config) -> ParameterStats:
    """Analyze a single parameter from one flow."""
    values = []
    for row in rows:
        v = row.get("Value")
        if v is not None:
            try:
                f = float(v)
                if f == f:  # skip NaN
                    values.append(f)
            except (ValueError, TypeError):
                pass

    unit = ""
    for row in rows:
        u = row.get("Unit", "")
        if u:
            unit = u
            break

    spec_min = None
    spec_max = None
    for row in rows:
        if spec_min is None:
            v = row.get("Spec_Min")
            if v is not None:
                try:
                    spec_min = float(v)
                except (ValueError, TypeError):
                    pass
        if spec_max is None:
            v = row.get("Spec_Max")
            if v is not None:
                try:
                    spec_max = float(v)
                except (ValueError, TypeError):
                    pass
        if spec_min is not None and spec_max is not None:
            break

    pass_count = 0
    fail_count = 0
    for row in rows:
        # Use pre-computed Pass field when available (set by loader)
        p = row.get("Pass")
        if p is not None:
            if p:
                pass_count += 1
            else:
                fail_count += 1
        else:
            # Fallback: recompute from spec limits
            v = row.get("Value")
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            passed = True
            if spec_min is not None and v < spec_min:
                passed = False
            if spec_max is not None and v > spec_max:
                passed = False
            if passed:
                pass_count += 1
            else:
                fail_count += 1

    cpk = compute_cpk(values, spec_min, spec_max)

    logger.debug(
        f"  {flow_name}/{parameter}: {pass_count}/{len(values)} PASS"
        + (f", Cpk={cpk:.2f}" if cpk is not None else "")
    )

    return ParameterStats(
        parameter=parameter,
        unit=unit,
        flow=flow_name,
        count=len(values),
        mean=_mean(values),
        std=_stdev(values),
        minimum=min(values) if values else 0.0,
        maximum=max(values) if values else 0.0,
        median=_median(values),
        spec_min=spec_min,
        spec_max=spec_max,
        pass_count=pass_count,
        fail_count=fail_count,
        cpk=cpk,
        values=values,
    )


def analyze_flow(flow_data: FlowData, config: Config) -> dict:
    """Analyze all parameters in a single flow."""
    results = {}
    params = {row.get("Parameter", "") for row in flow_data.rows}
    excluded = tuple(ex + "_" for ex in (config.excluded_ios or []))
    for param in params:
        if not param:
            continue
        if excluded and param.startswith(excluded):
            logger.debug(f"Skipping excluded parameter: {param}")
            continue
        param_rows = flow_data.get_parameter_rows(param)
        results[param] = analyze_parameter(param_rows, param, flow_data.flow_name, config)
    return results


def compare_flows(flow_stats: dict, config: Config) -> dict:
    """Compare results across flows for each parameter."""
    all_params: set = set()
    for stats in flow_stats.values():
        all_params.update(stats.keys())

    comparisons = {}
    for param in sorted(all_params):
        comparison = {"parameter": param, "flows": {}, "comment": ""}
        means = []
        pass_rates = []
        flow_names = []

        for flow_name, stats in flow_stats.items():
            if param in stats:
                s = stats[param]
                comparison["flows"][flow_name] = {
                    "mean": s.mean, "std": s.std, "pass_rate": s.pass_rate,
                    "cpk": s.cpk, "status": s.status, "count": s.count,
                }
                means.append(s.mean)
                pass_rates.append(s.pass_rate)
                flow_names.append(flow_name)

        if len(means) > 1:
            mean_diff = abs(means[0] - means[1])
            stds = [flow_stats[fn][param].std for fn in flow_names if param in flow_stats[fn]]
            avg_std = sum(stds) / len(stds) if stds else 0

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
    """Run the complete analysis pipeline."""
    result = AnalysisResult()
    result.flow_data = flows

    flow_stats: dict = {}
    for flow_name, flow_data in flows.items():
        logger.info(f"Analyzing {flow_name}...")
        stats = analyze_flow(flow_data, config)
        flow_stats[flow_name] = stats
        for param, param_stats in stats.items():
            result.parameter_stats[(flow_name, param)] = param_stats

    if len(flow_stats) > 1:
        result.cross_flow_comparison = compare_flows(flow_stats, config)

    total_params = len({p for _, p in result.parameter_stats.keys()})
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

    for key, stats in result.parameter_stats.items():
        result.comments.append(stats.generate_comment(config.cpk_threshold))

    for param, comp in result.cross_flow_comparison.items():
        if comp["comment"]:
            result.comments.append(f"[Cross-Flow] {comp['comment']}")

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
