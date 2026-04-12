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


# Default IO Electrical Validation spec limits (generic)
DEFAULT_SPEC_LIMITS = {
    "VOH": SpecLimit("VOH", "V", spec_min=2.4, spec_max=None, spec_typical=3.3),
    "VOL": SpecLimit("VOL", "V", spec_min=None, spec_max=0.4, spec_typical=0.0),
    "VIH": SpecLimit("VIH", "V", spec_min=2.0, spec_max=None, spec_typical=2.0),
    "VIL": SpecLimit("VIL", "V", spec_min=None, spec_max=0.8, spec_typical=0.8),
    "IOH": SpecLimit("IOH", "mA", spec_min=-8.0, spec_max=None, spec_typical=-4.0),
    "IOL": SpecLimit("IOL", "mA", spec_min=None, spec_max=8.0, spec_typical=4.0),
    "Rise_Time": SpecLimit("Rise_Time", "ns", spec_min=None, spec_max=5.0, spec_typical=2.0),
    "Fall_Time": SpecLimit("Fall_Time", "ns", spec_min=None, spec_max=5.0, spec_typical=2.0),
    "Setup_Time": SpecLimit("Setup_Time", "ns", spec_min=1.0, spec_max=None, spec_typical=2.0),
    "Hold_Time": SpecLimit("Hold_Time", "ns", spec_min=0.5, spec_max=None, spec_typical=1.0),
    "Leakage_Current": SpecLimit("Leakage_Current", "uA", spec_min=None, spec_max=10.0, spec_typical=1.0),
    "Capacitance": SpecLimit("Capacitance", "pF", spec_min=None, spec_max=8.0, spec_typical=4.0),
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
    spec_line_color: str = "#e67e22"
    bar_alpha: float = 0.85
    style: str = "seaborn-v0_8-whitegrid"
    save_format: str = "png"


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
