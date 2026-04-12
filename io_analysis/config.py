"""
Configuration management for IO Analysis.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Default parameter specifications (typical Electrical Validation IO limits)
# Each entry: { "parameter": (low_limit, high_limit, unit) }
# ---------------------------------------------------------------------------
DEFAULT_PARAM_SPECS: Dict[str, dict] = {
    "VOH": {"low_limit": 2.4,  "high_limit": 3.6,  "unit": "V",  "description": "High-level Output Voltage"},
    "VOL": {"low_limit": 0.0,  "high_limit": 0.4,  "unit": "V",  "description": "Low-level Output Voltage"},
    "VIH": {"low_limit": 2.0,  "high_limit": 3.6,  "unit": "V",  "description": "High-level Input Voltage"},
    "VIL": {"low_limit": 0.0,  "high_limit": 0.8,  "unit": "V",  "description": "Low-level Input Voltage"},
    "IOH": {"low_limit": -8.0, "high_limit": 0.0,  "unit": "mA", "description": "High-level Output Current"},
    "IOL": {"low_limit": 0.0,  "high_limit": 8.0,  "unit": "mA", "description": "Low-level Output Current"},
    "IIH": {"low_limit": 0.0,  "high_limit": 0.1,  "unit": "mA", "description": "High-level Input Current"},
    "IIL": {"low_limit": -0.1, "high_limit": 0.0,  "unit": "mA", "description": "Low-level Input Current"},
    "tpd": {"low_limit": 0.0,  "high_limit": 10.0, "unit": "ns", "description": "Propagation Delay"},
    "tr":  {"low_limit": 0.0,  "high_limit": 5.0,  "unit": "ns", "description": "Rise Time"},
    "tf":  {"low_limit": 0.0,  "high_limit": 5.0,  "unit": "ns", "description": "Fall Time"},
    "Skew":{"low_limit": -2.0, "high_limit": 2.0,  "unit": "ns", "description": "Clock Skew"},
}

# Sub-folders that contain merged result CSVs/Excel files
FLOW_FOLDERS: List[str] = ["Flow1", "Flow2"]

# Column-name aliases accepted from raw data files
COLUMN_ALIASES: Dict[str, str] = {
    # Raw file column  →  internal canonical name
    "Parameter":  "parameter",
    "param":      "parameter",
    "Test":       "parameter",
    "Value":      "value",
    "Result":     "value",
    "Measured":   "value",
    "UnitName":   "unit",
    "Unit":       "unit",
    "DUT":        "dut_id",
    "Device":     "dut_id",
    "DUT_ID":     "dut_id",
    "Pin":        "pin",
    "PinName":    "pin",
    "Condition":  "condition",
    "Corner":     "condition",
    "Status":     "status",
    "PASS_FAIL":  "status",
    "Pass/Fail":  "status",
    "LowLimit":   "low_limit",
    "LoLimit":    "low_limit",
    "HighLimit":  "high_limit",
    "HiLimit":    "high_limit",
    "Flow":       "flow",
}


@dataclass
class AnalysisConfig:
    """
    Central configuration object for the IO analysis run.

    Parameters
    ----------
    results_root : str
        Root directory that contains Flow1 and Flow2 sub-folders.
    output_dir : str
        Directory where plots and the final report will be saved.
    flow_folders : list[str]
        Sub-folder names that hold merged result files (default: Flow1, Flow2).
    param_specs : dict
        Per-parameter specification dictionary (limits + units).
    file_extensions : list[str]
        Accepted data-file extensions (csv / xlsx).
    report_title : str
        Title printed on the generated HTML report.
    figure_dpi : int
        Resolution for saved plot images.
    cpk_target : float
        Minimum acceptable Cpk value (default: 1.33).
    """

    results_root: str = "."
    output_dir: str = "output"
    flow_folders: List[str] = field(default_factory=lambda: list(FLOW_FOLDERS))
    param_specs: Dict[str, dict] = field(default_factory=lambda: dict(DEFAULT_PARAM_SPECS))
    file_extensions: List[str] = field(default_factory=lambda: [".csv", ".xlsx"])
    report_title: str = "IO Electrical Validation – Test Results Analysis"
    figure_dpi: int = 150
    cpk_target: float = 1.33
    column_aliases: Dict[str, str] = field(default_factory=lambda: dict(COLUMN_ALIASES))

    # ------------------------------------------------------------------ #
    def ensure_output_dir(self) -> str:
        """Create output directory if it does not exist and return its path."""
        os.makedirs(self.output_dir, exist_ok=True)
        plots_dir = os.path.join(self.output_dir, "plots")
        os.makedirs(plots_dir, exist_ok=True)
        return self.output_dir

    # ------------------------------------------------------------------ #
    def get_flow_path(self, flow: str) -> str:
        """Return absolute path for a given flow sub-folder."""
        return os.path.join(self.results_root, flow)

    # ------------------------------------------------------------------ #
    def get_param_spec(self, parameter: str) -> Optional[dict]:
        """Return limit specification for *parameter*, or None if unknown."""
        return self.param_specs.get(parameter)

    # ------------------------------------------------------------------ #
    @classmethod
    def from_dict(cls, data: dict) -> "AnalysisConfig":
        """Construct from a plain dictionary (e.g. loaded from JSON/YAML)."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
