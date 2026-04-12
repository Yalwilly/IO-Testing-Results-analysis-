"""
Plotting utilities for IO test results.

All public methods save a figure to disk and return the file path so that
the report generator can embed the images.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

import matplotlib
matplotlib.use("Agg")   # non-interactive backend for server/CI use
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
import seaborn as sns

from ..config import AnalysisConfig
from ..data.models import FlowData, ParameterSummary

logger = logging.getLogger(__name__)

# Shared colour palette for Flow1 / Flow2
FLOW_COLORS = {"Flow1": "#1f77b4", "Flow2": "#ff7f0e"}
DEFAULT_COLORS = plt.rcParams["axes.prop_cycle"].by_key()["color"]

sns.set_theme(style="whitegrid", palette="muted")


class IOPlotter:
    """
    Generates all visualisations for the IO analysis report.

    Usage
    -----
    >>> plotter = IOPlotter(config)
    >>> paths = plotter.plot_all(flows, analysis_results)
    """

    def __init__(self, config: AnalysisConfig) -> None:
        self.config = config
        self.plots_dir = os.path.join(config.output_dir, "plots")
        os.makedirs(self.plots_dir, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Top-level entry point
    # ------------------------------------------------------------------ #

    def plot_all(
        self,
        flows: Dict[str, FlowData],
        analysis: Dict[str, pd.DataFrame],
    ) -> Dict[str, str]:
        """
        Generate all plots and return a dict mapping figure-key → file path.
        """
        paths: Dict[str, str] = {}

        # 1. Yield summary bar chart (one per flow + combined)
        paths["yield_bar"] = self.plot_yield_bar(analysis["yield_summary"])

        # 2. Per-parameter distribution histograms (both flows overlaid)
        paths["distributions"] = self.plot_distributions(flows)

        # 3. Box-plot comparison Flow1 vs Flow2
        paths["boxplot_comparison"] = self.plot_boxplot_comparison(flows)

        # 4. Cpk bar chart
        paths["cpk_bar"] = self.plot_cpk_bar(analysis["summary"])

        # 5. Cross-flow mean comparison scatter
        if not analysis["cross_flow"].empty:
            paths["cross_flow_scatter"] = self.plot_cross_flow_scatter(
                analysis["cross_flow"]
            )

        # 6. Per-parameter skew / cross-skew plot
        paths["skew_plot"] = self.plot_skew(analysis["summary"])

        # 7. Pass/Fail heatmap
        paths["passfail_heatmap"] = self.plot_passfail_heatmap(
            analysis["yield_summary"]
        )

        return paths

    # ------------------------------------------------------------------ #
    # Individual plot methods
    # ------------------------------------------------------------------ #

    def plot_yield_bar(self, yield_df: pd.DataFrame) -> str:
        """Grouped bar chart of yield % per parameter per flow."""
        if yield_df.empty:
            return ""
        fig, ax = plt.subplots(figsize=(max(10, len(yield_df["parameter"].unique()) * 0.8), 6))
        params = sorted(yield_df["parameter"].unique())
        flows = sorted(yield_df["flow"].unique())
        x = np.arange(len(params))
        width = 0.8 / max(len(flows), 1)

        for i, flow in enumerate(flows):
            sub = yield_df[yield_df["flow"] == flow].set_index("parameter")
            yields = [sub.loc[p, "yield_%"] if p in sub.index else 0.0 for p in params]
            color = FLOW_COLORS.get(flow, DEFAULT_COLORS[i % len(DEFAULT_COLORS)])
            bars = ax.bar(x + i * width - (len(flows) - 1) * width / 2,
                          yields, width, label=flow, color=color, alpha=0.85)
            for bar, val in zip(bars, yields):
                if val < 100:
                    ax.text(bar.get_x() + bar.get_width() / 2,
                            bar.get_height() + 0.5, f"{val:.1f}%",
                            ha="center", va="bottom", fontsize=7)

        ax.axhline(100, color="green", linestyle="--", linewidth=0.8, label="100% target")
        ax.set_xticks(x)
        ax.set_xticklabels(params, rotation=45, ha="right", fontsize=9)
        ax.set_ylim(0, 110)
        ax.set_ylabel("Yield (%)")
        ax.set_title("Test Yield by Parameter and Flow")
        ax.legend()
        plt.tight_layout()
        path = os.path.join(self.plots_dir, "yield_bar.png")
        fig.savefig(path, dpi=self.config.figure_dpi)
        plt.close(fig)
        logger.debug("Saved yield_bar to %s", path)
        return path

    # ------------------------------------------------------------------ #

    def plot_distributions(self, flows: Dict[str, FlowData]) -> str:
        """
        A grid of histograms (one subplot per parameter) with Flow1/Flow2 overlaid.
        """
        all_params = sorted({p for fd in flows.values() for p in fd.parameters})
        if not all_params:
            return ""

        n = len(all_params)
        ncols = min(4, n)
        nrows = int(np.ceil(n / ncols))
        fig, axes = plt.subplots(nrows, ncols,
                                  figsize=(5 * ncols, 4 * nrows),
                                  squeeze=False)

        flow_items = list(flows.items())

        for idx, param in enumerate(all_params):
            ax = axes[idx // ncols][idx % ncols]
            for i, (flow_name, flow_data) in enumerate(flow_items):
                s = flow_data.get_summary(param)
                if s is None or not s.values:
                    continue
                color = FLOW_COLORS.get(flow_name, DEFAULT_COLORS[i % len(DEFAULT_COLORS)])
                ax.hist(s.values, bins="auto", alpha=0.55,
                        color=color, label=flow_name, density=True)
                ax.axvline(s.mean, color=color, linestyle="--", linewidth=1.2)

            # Draw limit lines if available
            spec = self.config.get_param_spec(param)
            if spec:
                ax.axvline(spec["low_limit"], color="red", linestyle=":", linewidth=1,
                           label=f"LoLim={spec['low_limit']}")
                ax.axvline(spec["high_limit"], color="red", linestyle=":", linewidth=1,
                           label=f"HiLim={spec['high_limit']}")

            ax.set_title(param, fontsize=10)
            ax.set_xlabel(spec["unit"] if spec else "")
            ax.set_ylabel("Density")
            ax.legend(fontsize=7)

        # Hide empty subplots
        for idx in range(n, nrows * ncols):
            axes[idx // ncols][idx % ncols].set_visible(False)

        fig.suptitle("Parameter Distributions (Flow1 vs Flow2)", fontsize=14)
        plt.tight_layout()
        path = os.path.join(self.plots_dir, "distributions.png")
        fig.savefig(path, dpi=self.config.figure_dpi)
        plt.close(fig)
        return path

    # ------------------------------------------------------------------ #

    def plot_boxplot_comparison(self, flows: Dict[str, FlowData]) -> str:
        """Box plots of all parameters side-by-side for Flow1 vs Flow2."""
        all_params = sorted({p for fd in flows.values() for p in fd.parameters})
        if not all_params:
            return ""

        records = []
        for flow_name, flow_data in flows.items():
            for rec in flow_data.records:
                records.append({"parameter": rec.parameter,
                                  "value": rec.value,
                                  "flow": flow_name})

        df = pd.DataFrame(records).dropna(subset=["value"])
        if df.empty:
            return ""

        n = len(all_params)
        ncols = min(4, n)
        nrows = int(np.ceil(n / ncols))
        fig, axes = plt.subplots(nrows, ncols,
                                  figsize=(5 * ncols, 4 * nrows),
                                  squeeze=False)

        flow_palette = {k: v for k, v in FLOW_COLORS.items()}

        for idx, param in enumerate(all_params):
            ax = axes[idx // ncols][idx % ncols]
            sub = df[df["parameter"] == param]
            if sub.empty:
                ax.set_visible(False)
                continue
            sns.boxplot(data=sub, x="flow", y="value", hue="flow",
                        palette=flow_palette, legend=False, ax=ax)
            spec = self.config.get_param_spec(param)
            if spec:
                ax.axhline(spec["low_limit"], color="red", linestyle="--",
                           linewidth=0.9, label="Limits")
                ax.axhline(spec["high_limit"], color="red", linestyle="--",
                           linewidth=0.9)
            ax.set_title(param, fontsize=10)
            ax.set_xlabel("")
            unit = spec["unit"] if spec else ""
            ax.set_ylabel(unit)

        for idx in range(n, nrows * ncols):
            axes[idx // ncols][idx % ncols].set_visible(False)

        fig.suptitle("Box Plot Comparison – Flow1 vs Flow2", fontsize=14)
        plt.tight_layout()
        path = os.path.join(self.plots_dir, "boxplot_comparison.png")
        fig.savefig(path, dpi=self.config.figure_dpi)
        plt.close(fig)
        return path

    # ------------------------------------------------------------------ #

    def plot_cpk_bar(self, summary_df: pd.DataFrame) -> str:
        """Horizontal bar chart of Cpk per parameter/flow."""
        if summary_df.empty or "cpk" not in summary_df.columns:
            return ""

        df = summary_df[summary_df["cpk"] != "N/A"].copy()
        df["cpk"] = pd.to_numeric(df["cpk"], errors="coerce")
        df = df.dropna(subset=["cpk"])
        if df.empty:
            return ""

        df["label"] = df["parameter"] + " [" + df["flow"] + "]"
        df = df.sort_values("cpk", ascending=True)

        fig, ax = plt.subplots(figsize=(8, max(4, len(df) * 0.4)))
        colors = [
            "green" if v >= self.config.cpk_target else "red"
            for v in df["cpk"]
        ]
        ax.barh(df["label"], df["cpk"], color=colors, alpha=0.8)
        ax.axvline(self.config.cpk_target, color="navy", linestyle="--",
                   linewidth=1.2, label=f"Target Cpk={self.config.cpk_target}")
        ax.set_xlabel("Cpk")
        ax.set_title("Process Capability (Cpk) by Parameter and Flow")
        ax.legend()
        green_patch = mpatches.Patch(color="green", alpha=0.8, label="Meets target")
        red_patch = mpatches.Patch(color="red", alpha=0.8, label="Below target")
        ax.legend(handles=[green_patch, red_patch,
                            mpatches.Patch(color="navy", label=f"Target={self.config.cpk_target}")])
        plt.tight_layout()
        path = os.path.join(self.plots_dir, "cpk_bar.png")
        fig.savefig(path, dpi=self.config.figure_dpi)
        plt.close(fig)
        return path

    # ------------------------------------------------------------------ #

    def plot_cross_flow_scatter(self, cross_df: pd.DataFrame) -> str:
        """Scatter: mean(Flow1) vs mean(Flow2) for shared parameters."""
        if cross_df.empty:
            return ""

        mean_cols = [c for c in cross_df.columns if c.startswith("mean_")]
        if len(mean_cols) < 2:
            return ""

        col_a, col_b = mean_cols[0], mean_cols[1]
        fig, ax = plt.subplots(figsize=(7, 7))
        ax.scatter(cross_df[col_a], cross_df[col_b], alpha=0.8,
                   color="#2ca02c", edgecolors="black", linewidths=0.5, zorder=3)

        # Annotate each point with the parameter name
        for _, row in cross_df.iterrows():
            ax.annotate(row["parameter"], (row[col_a], row[col_b]),
                        textcoords="offset points", xytext=(5, 3), fontsize=7)

        # Diagonal reference line
        lo = min(cross_df[col_a].min(), cross_df[col_b].min())
        hi = max(cross_df[col_a].max(), cross_df[col_b].max())
        ax.plot([lo, hi], [lo, hi], "k--", linewidth=0.8, label="y = x")

        ax.set_xlabel(col_a.replace("mean_", "Mean "))
        ax.set_ylabel(col_b.replace("mean_", "Mean "))
        ax.set_title("Cross-Flow Mean Comparison")
        ax.legend()
        plt.tight_layout()
        path = os.path.join(self.plots_dir, "cross_flow_scatter.png")
        fig.savefig(path, dpi=self.config.figure_dpi)
        plt.close(fig)
        return path

    # ------------------------------------------------------------------ #

    def plot_skew(self, summary_df: pd.DataFrame) -> str:
        """Bar chart of distribution skewness per parameter/flow."""
        if summary_df.empty or "skewness" not in summary_df.columns:
            return ""

        df = summary_df[["parameter", "flow", "skewness"]].dropna()
        if df.empty:
            return ""

        flows = sorted(df["flow"].unique())
        params = sorted(df["parameter"].unique())
        x = np.arange(len(params))
        width = 0.8 / max(len(flows), 1)

        fig, ax = plt.subplots(figsize=(max(10, len(params) * 0.8), 5))
        for i, flow in enumerate(flows):
            sub = df[df["flow"] == flow].set_index("parameter")
            vals = [float(sub.loc[p, "skewness"]) if p in sub.index else 0.0
                    for p in params]
            color = FLOW_COLORS.get(flow, DEFAULT_COLORS[i % len(DEFAULT_COLORS)])
            ax.bar(x + i * width - (len(flows) - 1) * width / 2,
                   vals, width, label=flow, color=color, alpha=0.85)

        ax.axhline(0, color="black", linewidth=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels(params, rotation=45, ha="right", fontsize=9)
        ax.set_ylabel("Skewness")
        ax.set_title("Distribution Skewness by Parameter and Flow")
        ax.legend()
        plt.tight_layout()
        path = os.path.join(self.plots_dir, "skew_plot.png")
        fig.savefig(path, dpi=self.config.figure_dpi)
        plt.close(fig)
        return path

    # ------------------------------------------------------------------ #

    def plot_passfail_heatmap(self, yield_df: pd.DataFrame) -> str:
        """Heatmap of yield % (parameter × flow)."""
        if yield_df.empty:
            return ""

        pivot = yield_df.pivot_table(
            index="parameter", columns="flow", values="yield_%", aggfunc="mean"
        )
        if pivot.empty:
            return ""

        fig, ax = plt.subplots(figsize=(max(4, len(pivot.columns) * 1.5),
                                         max(4, len(pivot) * 0.5)))
        sns.heatmap(
            pivot, annot=True, fmt=".1f", cmap="RdYlGn",
            vmin=0, vmax=100, linewidths=0.5, ax=ax,
            cbar_kws={"label": "Yield (%)"},
        )
        ax.set_title("Pass/Fail Yield Heatmap (% Passing)")
        ax.set_xlabel("Flow")
        ax.set_ylabel("Parameter")
        plt.tight_layout()
        path = os.path.join(self.plots_dir, "passfail_heatmap.png")
        fig.savefig(path, dpi=self.config.figure_dpi)
        plt.close(fig)
        return path
