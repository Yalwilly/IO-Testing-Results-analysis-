"""
Data loader for IO test results.

Supports CSV and Excel (.xlsx) files located inside Flow1 / Flow2 sub-folders
under a common results root path.  Column names are normalised using the alias
map defined in AnalysisConfig.
"""

from __future__ import annotations

import glob
import logging
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..config import AnalysisConfig
from .models import FlowData, ParameterSummary, TestRecord

logger = logging.getLogger(__name__)


class DataLoader:
    """
    Discovers, reads and normalises all test-result files for each flow.

    Usage
    -----
    >>> config = AnalysisConfig(results_root="/path/to/Results")
    >>> loader = DataLoader(config)
    >>> flows = loader.load_all()   # returns {"Flow1": FlowData, "Flow2": FlowData}
    """

    def __init__(self, config: AnalysisConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def load_all(self) -> Dict[str, FlowData]:
        """Load data for every configured flow folder and return a mapping."""
        result: Dict[str, FlowData] = {}
        for flow_name in self.config.flow_folders:
            flow_path = self.config.get_flow_path(flow_name)
            if not os.path.isdir(flow_path):
                logger.warning("Flow folder not found, skipping: %s", flow_path)
                flow_data = FlowData(name=flow_name)
            else:
                flow_data = self._load_flow(flow_name, flow_path)
            self._compute_summaries(flow_data)
            result[flow_name] = flow_data
            logger.info(
                "Loaded flow '%s': %d records, %d parameters",
                flow_name, len(flow_data.records), len(flow_data.parameters),
            )
        return result

    def load_flow(self, flow_name: str) -> FlowData:
        """Load a single named flow and return its FlowData."""
        flow_path = self.config.get_flow_path(flow_name)
        flow_data = self._load_flow(flow_name, flow_path)
        self._compute_summaries(flow_data)
        return flow_data

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _load_flow(self, flow_name: str, flow_path: str) -> FlowData:
        """Discover and parse all supported files inside *flow_path*."""
        flow_data = FlowData(name=flow_name)
        files = self._discover_files(flow_path)
        if not files:
            logger.warning("No data files found in: %s", flow_path)
            return flow_data

        dfs: List[pd.DataFrame] = []
        for filepath in files:
            try:
                df = self._read_file(filepath)
                if df is not None and not df.empty:
                    dfs.append(df)
                    logger.debug("Read %d rows from %s", len(df), filepath)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Failed to read %s: %s", filepath, exc)

        if not dfs:
            return flow_data

        combined = pd.concat(dfs, ignore_index=True)
        combined = self._normalise_columns(combined)
        combined["flow"] = flow_name
        flow_data.records = self._to_records(combined)
        return flow_data

    # ------------------------------------------------------------------ #

    def _discover_files(self, directory: str) -> List[str]:
        """Return all data files (recursively) inside *directory*."""
        found: List[str] = []
        for ext in self.config.file_extensions:
            pattern = os.path.join(directory, "**", f"*{ext}")
            found.extend(glob.glob(pattern, recursive=True))
        return sorted(found)

    # ------------------------------------------------------------------ #

    def _read_file(self, filepath: str) -> Optional[pd.DataFrame]:
        """Read a CSV or Excel file and return a raw DataFrame."""
        ext = os.path.splitext(filepath)[1].lower()
        if ext == ".csv":
            return pd.read_csv(filepath, low_memory=False)
        if ext in (".xlsx", ".xls"):
            return pd.read_excel(filepath, engine="openpyxl")
        logger.warning("Unsupported file type: %s", filepath)
        return None

    # ------------------------------------------------------------------ #

    def _normalise_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Rename columns using the alias map and fill in missing canonical cols."""
        # Strip whitespace from column names
        df.columns = [str(c).strip() for c in df.columns]
        rename_map = {
            raw: canonical
            for raw, canonical in self.config.column_aliases.items()
            if raw in df.columns
        }
        df = df.rename(columns=rename_map)

        # Ensure canonical columns exist
        for col in ("parameter", "value", "dut_id", "pin", "condition",
                    "unit", "low_limit", "high_limit", "status", "flow"):
            if col not in df.columns:
                df[col] = ""

        # Coerce value and limits to numeric
        for col in ("value", "low_limit", "high_limit"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # Upper-case status field for consistency
        df["status"] = df["status"].astype(str).str.upper().str.strip()
        df.loc[df["status"] == "NAN", "status"] = ""

        return df

    # ------------------------------------------------------------------ #

    def _to_records(self, df: pd.DataFrame) -> List[TestRecord]:
        """Convert a normalised DataFrame to a list of TestRecord objects."""
        records: List[TestRecord] = []
        for row in df.itertuples(index=False):
            param = str(getattr(row, "parameter", "")).strip()
            if not param:
                continue
            raw_value = getattr(row, "value", float("nan"))
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                value = float("nan")

            low = _to_float_or_none(getattr(row, "low_limit", None))
            high = _to_float_or_none(getattr(row, "high_limit", None))

            # If limits absent from file, fall back to config spec
            spec = self.config.get_param_spec(param)
            if spec and low is None:
                low = spec.get("low_limit")
            if spec and high is None:
                high = spec.get("high_limit")

            unit = str(getattr(row, "unit", "")).strip()
            if not unit and spec:
                unit = spec.get("unit", "")

            status = str(getattr(row, "status", "")).strip().upper()

            records.append(
                TestRecord(
                    parameter=param,
                    value=value,
                    dut_id=str(getattr(row, "dut_id", "")).strip(),
                    pin=str(getattr(row, "pin", "")).strip(),
                    condition=str(getattr(row, "condition", "")).strip(),
                    unit=unit,
                    low_limit=low,
                    high_limit=high,
                    status=status,
                    flow=str(getattr(row, "flow", "")).strip(),
                )
            )
        return records

    # ------------------------------------------------------------------ #

    def _compute_summaries(self, flow_data: FlowData) -> None:
        """Populate FlowData.summaries from its records."""
        from collections import defaultdict

        groups: dict = defaultdict(list)
        for rec in flow_data.records:
            groups[rec.parameter].append(rec)

        summaries: List[ParameterSummary] = []
        for param, recs in groups.items():
            spec = self.config.get_param_spec(param)
            low = spec["low_limit"] if spec else None
            high = spec["high_limit"] if spec else None
            # Override with limits from data if present
            data_lows = [r.low_limit for r in recs if r.low_limit is not None]
            data_highs = [r.high_limit for r in recs if r.high_limit is not None]
            if data_lows:
                low = data_lows[0]
            if data_highs:
                high = data_highs[0]
            summaries.append(
                ParameterSummary.from_records(recs, param, flow_data.name, low, high)
            )

        flow_data.summaries = sorted(summaries, key=lambda s: s.parameter)


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------

def _to_float_or_none(value) -> Optional[float]:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
