"""
IO Testing Results Analysis
============================
OOP-based framework for analyzing Electrical Validation IO raw test data.
"""

from .config import AnalysisConfig
from .data.loader import DataLoader
from .analysis.analyzer import IOAnalyzer
from .plotting.plotter import IOPlotter
from .reporting.report_generator import ReportGenerator

__version__ = "1.0.0"
__all__ = [
    "AnalysisConfig",
    "DataLoader",
    "IOAnalyzer",
    "IOPlotter",
    "ReportGenerator",
]
