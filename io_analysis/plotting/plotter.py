"""Plotting module for IO Testing Results Analysis.

Generates publication-quality plots for pass/fail results, distributions,
spec limit comparisons, and cross-flow analysis. All plots are sized and
styled for PowerPoint compatibility.
"""

import logging
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from io_analysis.config import Config, PlotConfig
from io_analysis.data.models import AnalysisResult, ParameterStats

logger = logging.getLogger(__name__)


def _apply_style(config: PlotConfig):
    """Apply consistent plot styling."""
    try:
        plt.style.use(config.style)
    except OSError:
        plt.style.use("seaborn-v0_8")
    plt.rcParams.update({
        "font.size": config.font_size,
        "axes.titlesize": config.title_font_size,
        "figure.dpi": config.dpi,
        "figure.figsize": (config.figure_width, config.figure_height),
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.2,
    })


def plot_pass_fail_summary(result: AnalysisResult, config: Config,
                           output_dir: Path) -> list:
    """Generate pass/fail bar chart for all parameters per flow.

    Returns list of saved file paths.
    """
    _apply_style(config.plot)
    saved_files = []

    for flow_name in result.all_flows:
        params = []
        pass_rates = []
        fail_rates = []

        for param in result.all_parameters:
            key = (flow_name, param)
            if key in result.parameter_stats:
                stats = result.parameter_stats[key]
                params.append(param)
                pass_rates.append(stats.pass_rate)
                fail_rates.append(stats.fail_rate)

        if not params:
            continue

        fig, ax = plt.subplots(figsize=(config.plot.figure_width,
                                        config.plot.figure_height))

        x = np.arange(len(params))
        width = 0.6

        bars_pass = ax.bar(x, pass_rates, width,
                           color=config.plot.pass_color,
                           alpha=config.plot.bar_alpha, label="Pass %")
        bars_fail = ax.bar(x, fail_rates, width, bottom=pass_rates,
                           color=config.plot.fail_color,
                           alpha=config.plot.bar_alpha, label="Fail %")

        # Add percentage labels
        for i, (pr, fr) in enumerate(zip(pass_rates, fail_rates)):
            if pr > 5:
                ax.text(i, pr / 2, f"{pr:.0f}%", ha="center", va="center",
                        fontweight="bold", fontsize=9, color="white")
            if fr > 5:
                ax.text(i, pr + fr / 2, f"{fr:.0f}%", ha="center",
                        va="center", fontweight="bold", fontsize=9,
                        color="white")

        ax.set_xlabel("IO Parameter")
        ax.set_ylabel("Percentage (%)")
        ax.set_title(f"Pass/Fail Summary – {flow_name}", fontsize=16,
                     fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels(params, rotation=45, ha="right")
        ax.set_ylim(0, 105)
        ax.legend(loc="upper right")
        ax.axhline(y=100, color="gray", linestyle="--", linewidth=0.5)

        plt.tight_layout()
        fpath = output_dir / f"pass_fail_summary_{flow_name}.{config.plot.save_format}"
        fig.savefig(fpath, dpi=config.plot.dpi)
        plt.close(fig)
        saved_files.append(fpath)
        logger.info(f"Saved: {fpath}")

    return saved_files


def plot_parameter_vs_spec(result: AnalysisResult, config: Config,
                           output_dir: Path) -> list:
    """Generate box plots of measured values vs spec limits for each parameter.

    Returns list of saved file paths.
    """
    _apply_style(config.plot)
    saved_files = []

    for param in result.all_parameters:
        flow_data_list = []
        flow_names = []
        spec_min = None
        spec_max = None

        for flow_name in result.all_flows:
            key = (flow_name, param)
            if key in result.parameter_stats:
                stats = result.parameter_stats[key]
                flow_data_list.append(stats.values)
                flow_names.append(flow_name)
                if stats.spec_min is not None:
                    spec_min = stats.spec_min
                if stats.spec_max is not None:
                    spec_max = stats.spec_max

        if not flow_data_list:
            continue

        unit = result.parameter_stats.get(
            (result.all_flows[0], param),
            result.parameter_stats.get(
                (result.all_flows[-1], param)
            )
        )
        unit_str = f" ({unit.unit})" if unit and unit.unit else ""

        fig, ax = plt.subplots(figsize=(config.plot.figure_width * 0.7,
                                        config.plot.figure_height))

        bp = ax.boxplot(flow_data_list, labels=flow_names, patch_artist=True,
                        widths=0.5)

        colors = plt.cm.Set2(np.linspace(0, 1, len(flow_names)))
        for patch, color in zip(bp["boxes"], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)

        # Add individual data points (jittered)
        for i, data in enumerate(flow_data_list):
            jitter = np.random.normal(0, 0.04, size=len(data))
            x_vals = np.full(len(data), i + 1) + jitter
            ax.scatter(x_vals, data, alpha=0.3, s=15, color="navy", zorder=5)

        # Spec limit lines
        if spec_min is not None:
            ax.axhline(y=spec_min, color=config.plot.spec_line_color,
                       linestyle="--", linewidth=2, label=f"Spec Min: {spec_min}")
        if spec_max is not None:
            ax.axhline(y=spec_max, color=config.plot.spec_line_color,
                       linestyle="-.", linewidth=2, label=f"Spec Max: {spec_max}")

        ax.set_ylabel(f"Value{unit_str}")
        ax.set_title(f"{param} – Measured vs Spec Limits", fontsize=14,
                     fontweight="bold")
        ax.legend(loc="best", fontsize=9)
        ax.grid(axis="y", alpha=0.3)

        plt.tight_layout()
        fpath = output_dir / f"param_vs_spec_{param}.{config.plot.save_format}"
        fig.savefig(fpath, dpi=config.plot.dpi)
        plt.close(fig)
        saved_files.append(fpath)
        logger.info(f"Saved: {fpath}")

    return saved_files


def plot_distribution_histograms(result: AnalysisResult, config: Config,
                                 output_dir: Path) -> list:
    """Generate histograms with spec limit overlays for each parameter.

    Returns list of saved file paths.
    """
    _apply_style(config.plot)
    saved_files = []

    for param in result.all_parameters:
        fig, ax = plt.subplots(figsize=(config.plot.figure_width * 0.8,
                                        config.plot.figure_height))

        spec_min = None
        spec_max = None
        has_data = False

        for flow_name in result.all_flows:
            key = (flow_name, param)
            if key not in result.parameter_stats:
                continue
            stats = result.parameter_stats[key]
            if not stats.values:
                continue

            has_data = True
            values = np.array(stats.values)
            ax.hist(values, bins=min(30, max(10, len(values) // 3)),
                    alpha=0.6, label=flow_name, edgecolor="black",
                    linewidth=0.5)

            if stats.spec_min is not None:
                spec_min = stats.spec_min
            if stats.spec_max is not None:
                spec_max = stats.spec_max

        if not has_data:
            plt.close(fig)
            continue

        if spec_min is not None:
            ax.axvline(x=spec_min, color="red", linestyle="--", linewidth=2,
                       label=f"Spec Min: {spec_min}")
        if spec_max is not None:
            ax.axvline(x=spec_max, color="red", linestyle="-.", linewidth=2,
                       label=f"Spec Max: {spec_max}")

        unit_str = ""
        for flow_name in result.all_flows:
            key = (flow_name, param)
            if key in result.parameter_stats:
                u = result.parameter_stats[key].unit
                if u:
                    unit_str = f" ({u})"
                    break

        ax.set_xlabel(f"Value{unit_str}")
        ax.set_ylabel("Count")
        ax.set_title(f"{param} – Distribution", fontsize=14, fontweight="bold")
        ax.legend(loc="best", fontsize=9)

        plt.tight_layout()
        fpath = output_dir / f"histogram_{param}.{config.plot.save_format}"
        fig.savefig(fpath, dpi=config.plot.dpi)
        plt.close(fig)
        saved_files.append(fpath)

    return saved_files


def plot_cross_flow_comparison(result: AnalysisResult, config: Config,
                               output_dir: Path) -> list:
    """Generate side-by-side comparison of flows for all parameters.

    Returns list of saved file paths.
    """
    _apply_style(config.plot)
    saved_files = []

    if len(result.all_flows) < 2:
        return saved_files

    params = result.all_parameters
    n_flows = len(result.all_flows)

    fig, ax = plt.subplots(figsize=(config.plot.figure_width,
                                    config.plot.figure_height + 1))

    x = np.arange(len(params))
    width = 0.8 / n_flows
    colors = plt.cm.Set2(np.linspace(0, 1, n_flows))

    for i, flow_name in enumerate(result.all_flows):
        means = []
        stds = []
        for param in params:
            key = (flow_name, param)
            if key in result.parameter_stats:
                s = result.parameter_stats[key]
                means.append(s.mean)
                stds.append(s.std)
            else:
                means.append(0)
                stds.append(0)

        offset = (i - n_flows / 2 + 0.5) * width
        ax.bar(x + offset, means, width, yerr=stds, label=flow_name,
               color=colors[i], alpha=0.8, capsize=3, edgecolor="black",
               linewidth=0.5)

    ax.set_xlabel("IO Parameter")
    ax.set_ylabel("Mean Value (± Std Dev)")
    ax.set_title("Cross-Flow Comparison – Mean ± Std Dev", fontsize=16,
                 fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(params, rotation=45, ha="right")
    ax.legend(loc="upper right")
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    fpath = output_dir / f"cross_flow_comparison.{config.plot.save_format}"
    fig.savefig(fpath, dpi=config.plot.dpi)
    plt.close(fig)
    saved_files.append(fpath)

    return saved_files


def plot_cpk_summary(result: AnalysisResult, config: Config,
                     output_dir: Path) -> list:
    """Generate Cpk bar chart for all parameters.

    Returns list of saved file paths.
    """
    _apply_style(config.plot)
    saved_files = []

    for flow_name in result.all_flows:
        params = []
        cpk_values = []

        for param in result.all_parameters:
            key = (flow_name, param)
            if key in result.parameter_stats:
                stats = result.parameter_stats[key]
                if stats.cpk is not None:
                    params.append(param)
                    cpk_values.append(stats.cpk)

        if not params:
            continue

        fig, ax = plt.subplots(figsize=(config.plot.figure_width,
                                        config.plot.figure_height))

        x = np.arange(len(params))
        colors_list = []
        for cpk in cpk_values:
            if cpk >= config.cpk_threshold:
                colors_list.append(config.plot.pass_color)
            elif cpk >= 1.0:
                colors_list.append(config.plot.spec_line_color)
            else:
                colors_list.append(config.plot.fail_color)

        bars = ax.bar(x, cpk_values, 0.6, color=colors_list,
                      alpha=config.plot.bar_alpha, edgecolor="black",
                      linewidth=0.5)

        # Add value labels
        for i, (cpk, bar) in enumerate(zip(cpk_values, bars)):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                    f"{cpk:.2f}", ha="center", va="bottom", fontsize=9,
                    fontweight="bold")

        ax.axhline(y=config.cpk_threshold, color="green", linestyle="--",
                   linewidth=1.5, label=f"Target Cpk ({config.cpk_threshold})")
        ax.axhline(y=1.0, color="orange", linestyle=":", linewidth=1.5,
                   label="Cpk = 1.0")

        # Legend
        legend_patches = [
            mpatches.Patch(color=config.plot.pass_color,
                           label=f"Cpk ≥ {config.cpk_threshold} (Capable)"),
            mpatches.Patch(color=config.plot.spec_line_color,
                           label="1.0 ≤ Cpk < 1.33 (Marginal)"),
            mpatches.Patch(color=config.plot.fail_color,
                           label="Cpk < 1.0 (Not Capable)"),
        ]
        ax.legend(handles=legend_patches, loc="upper right", fontsize=9)

        ax.set_xlabel("IO Parameter")
        ax.set_ylabel("Cpk")
        ax.set_title(f"Process Capability (Cpk) – {flow_name}", fontsize=16,
                     fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels(params, rotation=45, ha="right")
        ax.grid(axis="y", alpha=0.3)

        plt.tight_layout()
        fpath = output_dir / f"cpk_summary_{flow_name}.{config.plot.save_format}"
        fig.savefig(fpath, dpi=config.plot.dpi)
        plt.close(fig)
        saved_files.append(fpath)

    return saved_files


def plot_scatter_by_dut(result: AnalysisResult, config: Config,
                        output_dir: Path) -> list:
    """Generate scatter plots of measured values per DUT with spec limits.

    Returns list of saved file paths.
    """
    _apply_style(config.plot)
    saved_files = []

    for param in result.all_parameters:
        fig, ax = plt.subplots(figsize=(config.plot.figure_width,
                                        config.plot.figure_height))

        spec_min = None
        spec_max = None
        has_data = False

        for flow_idx, flow_name in enumerate(result.all_flows):
            key = (flow_name, param)
            if key not in result.parameter_stats:
                continue

            flow_data = result.flow_data[flow_name]
            param_df = flow_data.raw_data[
                flow_data.raw_data["Parameter"] == param
            ].copy()

            if param_df.empty:
                continue

            has_data = True
            stats = result.parameter_stats[key]
            if stats.spec_min is not None:
                spec_min = stats.spec_min
            if stats.spec_max is not None:
                spec_max = stats.spec_max

            # Color points by pass/fail
            values = param_df["Value"].values
            passed = np.ones(len(values), dtype=bool)
            if spec_min is not None:
                passed &= values >= spec_min
            if spec_max is not None:
                passed &= values <= spec_max

            dut_ids = param_df["DUT_ID"].values
            unique_duts = sorted(set(dut_ids))
            dut_to_x = {dut: i for i, dut in enumerate(unique_duts)}
            x_vals = [dut_to_x[d] + flow_idx * 0.3 for d in dut_ids]

            ax.scatter(
                [x for x, p in zip(x_vals, passed) if p],
                [v for v, p in zip(values, passed) if p],
                color=config.plot.pass_color, alpha=0.7, s=30,
                label=f"{flow_name} Pass" if flow_idx == 0 else "",
                marker="o",
            )
            ax.scatter(
                [x for x, p in zip(x_vals, passed) if not p],
                [v for v, p in zip(values, passed) if not p],
                color=config.plot.fail_color, alpha=0.9, s=50,
                label=f"{flow_name} Fail" if flow_idx == 0 else "",
                marker="x", linewidths=2,
            )

        if not has_data:
            plt.close(fig)
            continue

        if spec_min is not None:
            ax.axhline(y=spec_min, color="red", linestyle="--", linewidth=1.5,
                       label=f"Spec Min: {spec_min}")
        if spec_max is not None:
            ax.axhline(y=spec_max, color="red", linestyle="-.", linewidth=1.5,
                       label=f"Spec Max: {spec_max}")

        ax.set_xlabel("DUT Index")
        ax.set_ylabel("Value")
        ax.set_title(f"{param} – Per-DUT Results", fontsize=14, fontweight="bold")
        ax.legend(loc="best", fontsize=8)
        ax.grid(alpha=0.3)

        plt.tight_layout()
        fpath = output_dir / f"scatter_dut_{param}.{config.plot.save_format}"
        fig.savefig(fpath, dpi=config.plot.dpi)
        plt.close(fig)
        saved_files.append(fpath)

    return saved_files


def generate_all_plots(result: AnalysisResult, config: Config) -> dict:
    """Generate all plots and return paths organized by category.

    Args:
        result: Complete AnalysisResult.
        config: Configuration.

    Returns:
        Dictionary mapping plot category -> list of file paths.
    """
    plots_dir = config.output_path / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    all_plots = {}

    logger.info("Generating pass/fail summary plots...")
    all_plots["pass_fail_summary"] = plot_pass_fail_summary(
        result, config, plots_dir)

    logger.info("Generating parameter vs spec plots...")
    all_plots["parameter_vs_spec"] = plot_parameter_vs_spec(
        result, config, plots_dir)

    logger.info("Generating distribution histograms...")
    all_plots["distributions"] = plot_distribution_histograms(
        result, config, plots_dir)

    logger.info("Generating cross-flow comparison...")
    all_plots["cross_flow"] = plot_cross_flow_comparison(
        result, config, plots_dir)

    logger.info("Generating Cpk summary...")
    all_plots["cpk_summary"] = plot_cpk_summary(result, config, plots_dir)

    logger.info("Generating per-DUT scatter plots...")
    all_plots["scatter_dut"] = plot_scatter_by_dut(result, config, plots_dir)

    total_plots = sum(len(v) for v in all_plots.values())
    logger.info(f"Generated {total_plots} plots in {plots_dir}")

    return all_plots
