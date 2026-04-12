"""Data models for IO Testing Results Analysis.

Defines core data structures used throughout the analysis pipeline.
"""

from dataclasses import dataclass, field
from typing import Optional
import pandas as pd
import numpy as np


@dataclass
class TestResult:
    """A single test measurement result."""
    parameter: str
    value: float
    unit: str
    dut_id: str
    spec_min: Optional[float] = None
    spec_max: Optional[float] = None
    flow: str = ""
    test_condition: str = ""

    @property
    def passed(self) -> bool:
        """Check if the result passes spec limits."""
        if self.spec_min is not None and self.value < self.spec_min:
            return False
        if self.spec_max is not None and self.value > self.spec_max:
            return False
        return True

    @property
    def margin_to_spec(self) -> Optional[float]:
        """Calculate margin to nearest spec limit (positive = margin, negative = fail)."""
        margins = []
        if self.spec_min is not None:
            margins.append(self.value - self.spec_min)
        if self.spec_max is not None:
            margins.append(self.spec_max - self.value)
        return min(margins) if margins else None


@dataclass
class ParameterStats:
    """Statistical summary for a single IO parameter."""
    parameter: str
    unit: str
    flow: str
    count: int = 0
    mean: float = 0.0
    std: float = 0.0
    minimum: float = 0.0
    maximum: float = 0.0
    median: float = 0.0
    spec_min: Optional[float] = None
    spec_max: Optional[float] = None
    pass_count: int = 0
    fail_count: int = 0
    cpk: Optional[float] = None
    values: list = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.pass_count + self.fail_count

    @property
    def pass_rate(self) -> float:
        """Pass rate as a percentage."""
        return (self.pass_count / self.total * 100) if self.total > 0 else 0.0

    @property
    def fail_rate(self) -> float:
        """Fail rate as a percentage."""
        return (self.fail_count / self.total * 100) if self.total > 0 else 0.0

    @property
    def status(self) -> str:
        """Overall pass/fail status string."""
        if self.fail_count == 0:
            return "PASS"
        elif self.pass_count == 0:
            return "FAIL"
        else:
            return f"MARGINAL ({self.fail_rate:.1f}% fail)"

    def generate_comment(self, cpk_threshold: float = 1.33) -> str:
        """Generate a short analysis comment suitable for PowerPoint."""
        parts = []

        # Pass/fail summary
        if self.fail_count == 0:
            parts.append(f"{self.parameter}: ALL PASS ({self.count} samples)")
        else:
            parts.append(
                f"{self.parameter}: {self.fail_count}/{self.total} FAIL "
                f"({self.fail_rate:.1f}%)"
            )

        # Spec margin
        if self.spec_min is not None:
            margin_min = self.minimum - self.spec_min
            parts.append(f"Min margin to spec_min: {margin_min:.4f} {self.unit}")
        if self.spec_max is not None:
            margin_max = self.spec_max - self.maximum
            parts.append(f"Min margin to spec_max: {margin_max:.4f} {self.unit}")

        # Cpk assessment
        if self.cpk is not None:
            if self.cpk >= cpk_threshold:
                parts.append(f"Cpk={self.cpk:.2f} (Capable)")
            elif self.cpk >= 1.0:
                parts.append(f"Cpk={self.cpk:.2f} (Marginal)")
            else:
                parts.append(f"Cpk={self.cpk:.2f} (Not Capable)")

        # Distribution summary
        parts.append(
            f"Range: [{self.minimum:.4f}, {self.maximum:.4f}] {self.unit}, "
            f"Mean={self.mean:.4f}, Std={self.std:.4f}"
        )

        return " | ".join(parts)


@dataclass
class FlowData:
    """Container for all test data from a single flow."""
    flow_name: str
    raw_data: pd.DataFrame = field(default_factory=pd.DataFrame)
    parameters: list = field(default_factory=list)
    dut_ids: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.raw_data.empty:
            self._extract_metadata()

    def _extract_metadata(self):
        """Extract parameter names and DUT IDs from raw data."""
        if "Parameter" in self.raw_data.columns:
            self.parameters = sorted(self.raw_data["Parameter"].unique().tolist())
        if "DUT_ID" in self.raw_data.columns:
            self.dut_ids = sorted(self.raw_data["DUT_ID"].unique().tolist())


@dataclass
class AnalysisResult:
    """Complete analysis result across all flows."""
    flow_data: dict = field(default_factory=dict)  # flow_name -> FlowData
    parameter_stats: dict = field(default_factory=dict)  # (flow, param) -> ParameterStats
    cross_flow_comparison: dict = field(default_factory=dict)
    overall_summary: dict = field(default_factory=dict)
    comments: list = field(default_factory=list)

    @property
    def all_parameters(self) -> list:
        """Get sorted list of all unique parameters across flows."""
        params = set()
        for fd in self.flow_data.values():
            params.update(fd.parameters)
        return sorted(params)

    @property
    def all_flows(self) -> list:
        """Get sorted list of all flow names."""
        return sorted(self.flow_data.keys())

    @property
    def total_pass_rate(self) -> float:
        """Overall pass rate across all flows and parameters."""
        total_pass = sum(s.pass_count for s in self.parameter_stats.values())
        total_count = sum(s.total for s in self.parameter_stats.values())
        return (total_pass / total_count * 100) if total_count > 0 else 0.0
