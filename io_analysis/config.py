"""Configuration module for IO Testing Results Analysis.

Manages default paths, spec limits, plot settings, and report templates.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SpecLimit:
    """Specification limit for an IO parameter."""
    parameter: str
    unit: str
    spec_min: Optional[float] = None
    spec_max: Optional[float] = None
    spec_typical: Optional[float] = None

    @property
    def has_min(self) -> bool:
        return self.spec_min is not None

    @property
    def has_max(self) -> bool:
        return self.spec_max is not None

    def is_within_spec(self, value: float) -> bool:
        """Check if a measured value is within spec limits."""
        if self.has_min and value < self.spec_min:
            return False
        if self.has_max and value > self.spec_max:
            return False
        return True


# ---------------------------------------------------------------------------
# IO Electrical Spec limits — sourced from IO_SPEC.pdf (April 2026)
#
# Two pin families tested:
#   PB16DSFS_18_18_H  (GPIO_0, BRI_DT)  — non-tolerant, DVDD=1.08-1.32V (nom 1.2V) or 1.8V
#   PB12DSFS_18_T33_H (RF_KILLN)        — tolerant,     DVDD=1.08-1.32V (nom 1.2V) or 3.3V
#
# VIH / VIL are DVDD-relative — per-row values are computed in loader.py.
# The constants below use DVDD=1.8V as a nominal reference for the fallback.
#
# VOL is constant (DVDD-independent) at 0.40 V (PB12) / 0.45 V (PB16).
# VOH min = 0.75 × DVDD (PB12) or 1.35 V absolute (PB16, Table 18 note);
#           per-row value from "vohmin spec" column in test file is preferred.
# ---------------------------------------------------------------------------
DEFAULT_SPEC_LIMITS = {
    # --- Voltage levels (PB16 nom DVDD=1.8V) ---
    "VOH":     SpecLimit("VOH",     "V",    spec_min=1.35),                   # 0.75×1.8 (Table 18)
    "VOL":     SpecLimit("VOL",     "V",    spec_max=0.45),                   # constant (Table 18)
    "VIH":     SpecLimit("VIH",     "V",    spec_min=1.17),                   # 0.65×1.8 (Table 18)
    "VIL":     SpecLimit("VIL",     "V",    spec_max=0.63),                   # 0.35×1.8 (Table 18)
    # Named variants used by Intel test files
    "VIH_Min": SpecLimit("VIH_Min", "V",    spec_max=1.17),                   # measured threshold ≤ 0.65×1.8 (PB16)
    "VIL_Max": SpecLimit("VIL_Max", "V",    spec_min=0.63),                   # measured threshold ≥ 0.35×1.8 (PB16)
    # --- Drive current (test conditions, not hard DC limits) ---
    "IOH":     SpecLimit("IOH",     "mA",   spec_min=-16.0, spec_max=None),   # 1-16 mA source
    "IOL":     SpecLimit("IOL",     "mA",   spec_min=None,  spec_max=16.0),   # 1-16 mA sink
    # --- Pull resistances (Table 18 PB16; PB12 overridden per-row in loader) ---
    "R_PullUp":   SpecLimit("R_PullUp",   "kOhm", spec_min=30.0,  spec_max=70.0),   # PB16
    "R_PullDown": SpecLimit("R_PullDown", "kOhm", spec_min=30.0,  spec_max=70.0),   # PB16
    # --- Leakage (Table 18/20: ±10 µA @T=125°C) ---
    "Leakage_Current": SpecLimit("Leakage_Current", "uA", spec_min=-10.0, spec_max=10.0),
    # --- Timing (AC — TBD in spec; kept from prior characterisation) ---
    "Rise_Time": SpecLimit("Rise_Time", "ns", spec_max=5.0),
    "Fall_Time": SpecLimit("Fall_Time", "ns", spec_max=5.0),
    "Setup_Time": SpecLimit("Setup_Time", "ns", spec_min=1.0),
    "Hold_Time":  SpecLimit("Hold_Time",  "ns", spec_min=0.5),
    "Capacitance": SpecLimit("Capacitance", "pF", spec_max=8.0),
}


@dataclass
class PlotConfig:
    """Configuration for plot generation."""
    figure_width: float = 12.0
    figure_height: float = 6.0
    dpi: int = 150
    font_size: int = 10
    title_font_size: int = 14
    pass_color: str = "#2ecc71"
    fail_color: str = "#e74c3c"
    spec_line_color: str = "#ff6d00"
    show_spec_lines: bool = True
    bar_alpha: float = 0.85
    style: str = "seaborn-v0_8-whitegrid"
    save_format: str = "svg"


@dataclass
class ReportConfig:
    """Configuration for report generation."""
    title: str = "IO Electrical Validation Results"
    subtitle: str = "Pass/Fail Analysis vs Specification"
    author: str = "IO Validation Team"
    slide_width_inches: float = 13.333
    slide_height_inches: float = 7.5
    max_params_per_slide: int = 6


@dataclass
class Config:
    """Main configuration for the analysis pipeline."""
    data_path: Path = field(default_factory=lambda: Path("sample_data"))
    output_path: Path = field(default_factory=lambda: Path("output"))
    flow_dirs: list = field(default_factory=lambda: ["Flow1", "Flow2"])
    file_extensions: list = field(default_factory=lambda: [".csv", ".xlsx", ".xls"])
    spec_limits: dict = field(default_factory=lambda: dict(DEFAULT_SPEC_LIMITS))
    plot: PlotConfig = field(default_factory=PlotConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    cpk_threshold: float = 1.33
    excluded_ios: list = field(default_factory=lambda: ["BRI_DT"])

    def __post_init__(self):
        self.data_path = Path(self.data_path)
        self.output_path = Path(self.output_path)
        self.output_path.mkdir(parents=True, exist_ok=True)

    def get_flow_paths(self) -> list:
        """Return list of resolved flow directory paths."""
        return [self.data_path / flow for flow in self.flow_dirs]

    def update_spec_limits(self, custom_limits: dict):
        """Update spec limits with custom values."""
        for param, limit in custom_limits.items():
            if isinstance(limit, SpecLimit):
                self.spec_limits[param] = limit
            elif isinstance(limit, dict):
                self.spec_limits[param] = SpecLimit(
                    parameter=param, **limit
                )
