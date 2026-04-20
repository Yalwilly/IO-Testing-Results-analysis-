"""Data models for IO Testing Results Analysis.

Defines core data structures used throughout the analysis pipeline.
Uses Python standard library only (no pandas/numpy).
"""

from dataclasses import dataclass, field
from typing import Optional


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
        if self.spec_min is not None and self.value < self.spec_min:
            return False
        if self.spec_max is not None and self.value > self.spec_max:
            return False
        return True


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
        return (self.pass_count / self.total * 100) if self.total > 0 else 0.0

    @property
    def fail_rate(self) -> float:
        return (self.fail_count / self.total * 100) if self.total > 0 else 0.0

    @property
    def status(self) -> str:
        if self.fail_count == 0:
            return "PASS"
        elif self.pass_count == 0:
            return "FAIL"
        else:
            return f"MARGINAL ({self.fail_rate:.1f}% fail)"

    def generate_comment(self, cpk_threshold: float = 1.33) -> str:
        parts = []
        if self.fail_count == 0:
            parts.append(f"{self.parameter}: ALL PASS ({self.count} samples)")
        else:
            parts.append(
                f"{self.parameter}: {self.fail_count}/{self.total} FAIL "
                f"({self.fail_rate:.1f}%)"
            )
        if self.spec_min is not None:
            margin_min = self.minimum - self.spec_min
            parts.append(f"Min margin to spec_min: {margin_min:.4f} {self.unit}")
        if self.spec_max is not None:
            margin_max = self.spec_max - self.maximum
            parts.append(f"Min margin to spec_max: {margin_max:.4f} {self.unit}")
        if self.cpk is not None:
            if self.cpk >= cpk_threshold:
                parts.append(f"Cpk={self.cpk:.2f} (Capable)")
            elif self.cpk >= 1.0:
                parts.append(f"Cpk={self.cpk:.2f} (Marginal)")
            else:
                parts.append(f"Cpk={self.cpk:.2f} (Not Capable)")
        parts.append(
            f"Range: [{self.minimum:.4f}, {self.maximum:.4f}] {self.unit}, "
            f"Mean={self.mean:.4f}, Std={self.std:.4f}"
        )
        return " | ".join(parts)


@dataclass
class FlowData:
    """Container for all test data from a single flow.

    rows: list of dicts, each dict is one measurement row with keys:
          Parameter, Value, Unit, DUT_ID, Spec_Min, Spec_Max, Test_Condition, ...
    """
    flow_name: str
    rows: list = field(default_factory=list)
    parameters: list = field(default_factory=list)
    dut_ids: list = field(default_factory=list)

    def __post_init__(self):
        if self.rows:
            self._extract_metadata()

    def _extract_metadata(self):
        params = set()
        duts = set()
        for row in self.rows:
            p = row.get("Parameter")
            if p:
                params.add(p)
            d = row.get("DUT_ID")
            if d:
                duts.add(str(d))
        self.parameters = sorted(params)
        self.dut_ids = sorted(duts)

    @property
    def record_count(self) -> int:
        return len(self.rows)

    def get_parameter_rows(self, param: str) -> list:
        return [r for r in self.rows if r.get("Parameter") == param]


@dataclass
class AnalysisResult:
    """Complete analysis result across all flows."""
    flow_data: dict = field(default_factory=dict)
    parameter_stats: dict = field(default_factory=dict)
    cross_flow_comparison: dict = field(default_factory=dict)
    overall_summary: dict = field(default_factory=dict)
    comments: list = field(default_factory=list)

    @property
    def all_parameters(self) -> list:
        params = set()
        for fd in self.flow_data.values():
            params.update(fd.parameters)
        return sorted(params)

    @property
    def all_flows(self) -> list:
        return sorted(self.flow_data.keys())

    @property
    def total_pass_rate(self) -> float:
        total_pass = sum(s.pass_count for s in self.parameter_stats.values())
        total_count = sum(s.total for s in self.parameter_stats.values())
        return (total_pass / total_count * 100) if total_count > 0 else 0.0
