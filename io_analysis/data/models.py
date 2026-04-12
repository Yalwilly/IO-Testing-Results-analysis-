"""
Data models for IO analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Low-level record model
# ---------------------------------------------------------------------------

@dataclass
class TestRecord:
    """A single measurement record for one parameter on one DUT."""

    parameter: str
    value: float
    dut_id: str = ""
    pin: str = ""
    condition: str = ""
    unit: str = ""
    low_limit: Optional[float] = None
    high_limit: Optional[float] = None
    status: str = ""          # "PASS" | "FAIL" | "" (derived if empty)
    flow: str = ""

    def __post_init__(self) -> None:
        if not self.status and self.low_limit is not None and self.high_limit is not None:
            self.status = (
                "PASS" if self.low_limit <= self.value <= self.high_limit else "FAIL"
            )

    @property
    def is_pass(self) -> bool:
        return self.status.upper() == "PASS"


# ---------------------------------------------------------------------------
# Parameter-level summary (computed from a collection of TestRecords)
# ---------------------------------------------------------------------------

@dataclass
class ParameterSummary:
    """Statistical summary for one parameter inside one flow."""

    parameter: str
    flow: str
    unit: str = ""
    low_limit: Optional[float] = None
    high_limit: Optional[float] = None

    count: int = 0
    pass_count: int = 0
    fail_count: int = 0

    mean: float = float("nan")
    std: float = float("nan")
    minimum: float = float("nan")
    maximum: float = float("nan")
    median: float = float("nan")
    p5: float = float("nan")
    p95: float = float("nan")
    cpk: float = float("nan")

    values: List[float] = field(default_factory=list, repr=False)

    # ------------------------------------------------------------------ #
    @property
    def yield_pct(self) -> float:
        """Percentage of passing measurements."""
        return (self.pass_count / self.count * 100) if self.count else 0.0

    # ------------------------------------------------------------------ #
    @classmethod
    def from_records(
        cls,
        records: List[TestRecord],
        parameter: str,
        flow: str,
        low_limit: Optional[float] = None,
        high_limit: Optional[float] = None,
    ) -> "ParameterSummary":
        """Build a ParameterSummary from a list of TestRecord objects."""
        values = [r.value for r in records if not np.isnan(r.value)]
        units = [r.unit for r in records if r.unit]
        unit = units[0] if units else ""

        if not values:
            return cls(parameter=parameter, flow=flow, unit=unit,
                       low_limit=low_limit, high_limit=high_limit)

        arr = np.array(values, dtype=float)
        pass_count = sum(1 for r in records if r.is_pass)

        obj = cls(
            parameter=parameter,
            flow=flow,
            unit=unit,
            low_limit=low_limit,
            high_limit=high_limit,
            count=len(arr),
            pass_count=pass_count,
            fail_count=len(arr) - pass_count,
            mean=float(np.mean(arr)),
            std=float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0,
            minimum=float(np.min(arr)),
            maximum=float(np.max(arr)),
            median=float(np.median(arr)),
            p5=float(np.percentile(arr, 5)),
            p95=float(np.percentile(arr, 95)),
            values=values,
        )

        # Compute Cpk when limits are available and std > 0
        if (
            low_limit is not None
            and high_limit is not None
            and obj.std > 0
        ):
            cpu = (high_limit - obj.mean) / (3 * obj.std)
            cpl = (obj.mean - low_limit) / (3 * obj.std)
            obj.cpk = float(min(cpu, cpl))
        return obj

    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict:
        return {
            "parameter": self.parameter,
            "flow": self.flow,
            "unit": self.unit,
            "low_limit": self.low_limit,
            "high_limit": self.high_limit,
            "count": self.count,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "yield_%": round(self.yield_pct, 2),
            "mean": round(self.mean, 6),
            "std": round(self.std, 6),
            "min": round(self.minimum, 6),
            "max": round(self.maximum, 6),
            "median": round(self.median, 6),
            "p5": round(self.p5, 6),
            "p95": round(self.p95, 6),
            "cpk": round(self.cpk, 4) if not np.isnan(self.cpk) else "N/A",
        }


# ---------------------------------------------------------------------------
# Flow-level container
# ---------------------------------------------------------------------------

@dataclass
class FlowData:
    """All test records and summaries for a single flow (Flow1 or Flow2)."""

    name: str
    records: List[TestRecord] = field(default_factory=list)
    summaries: List[ParameterSummary] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    @property
    def dataframe(self) -> pd.DataFrame:
        """Convert all records to a flat DataFrame."""
        if not self.records:
            return pd.DataFrame()
        return pd.DataFrame([
            {
                "parameter": r.parameter,
                "value": r.value,
                "dut_id": r.dut_id,
                "pin": r.pin,
                "condition": r.condition,
                "unit": r.unit,
                "low_limit": r.low_limit,
                "high_limit": r.high_limit,
                "status": r.status,
                "flow": r.flow,
            }
            for r in self.records
        ])

    # ------------------------------------------------------------------ #
    @property
    def parameters(self) -> List[str]:
        """Unique parameter names in this flow."""
        return sorted({r.parameter for r in self.records})

    # ------------------------------------------------------------------ #
    def get_summary(self, parameter: str) -> Optional[ParameterSummary]:
        for s in self.summaries:
            if s.parameter == parameter:
                return s
        return None
