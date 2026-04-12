"""Data loader for IO Testing Results.

Loads CSV and Excel files from Flow1/Flow2 directories and normalizes
them into a unified DataFrame format.
"""

import os
import logging
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

from io_analysis.config import Config, SpecLimit
from io_analysis.data.models import FlowData

logger = logging.getLogger(__name__)

# Expected column mappings (case-insensitive matching)
COLUMN_ALIASES = {
    "parameter": ["parameter", "param", "test_name", "test name", "signal",
                   "pin_name", "pin name", "io_name", "io name"],
    "value": ["value", "measured", "result", "measured_value", "measured value",
              "data", "reading"],
    "unit": ["unit", "units", "uom"],
    "dut_id": ["dut_id", "dut id", "dut", "sample", "sample_id", "sample id",
               "device", "device_id", "device id", "sn", "serial"],
    "spec_min": ["spec_min", "spec min", "min_spec", "min spec", "lsl",
                 "lower_spec", "lower spec", "low_limit", "low limit"],
    "spec_max": ["spec_max", "spec max", "max_spec", "max spec", "usl",
                 "upper_spec", "upper spec", "high_limit", "high limit"],
    "test_condition": ["test_condition", "test condition", "condition",
                       "corner", "temperature", "voltage"],
}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names to standard format."""
    col_map = {}
    lower_cols = {c.lower().strip(): c for c in df.columns}

    for standard_name, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lower_cols:
                col_map[lower_cols[alias]] = standard_name.capitalize() \
                    if standard_name != "dut_id" else "DUT_ID"
                break

    # Standard capitalization
    name_map = {
        "parameter": "Parameter",
        "value": "Value",
        "unit": "Unit",
        "dut_id": "DUT_ID",
        "spec_min": "Spec_Min",
        "spec_max": "Spec_Max",
        "test_condition": "Test_Condition",
    }

    final_map = {}
    for orig, std in col_map.items():
        for key, proper in name_map.items():
            if std.lower().replace("_", "") == key.replace("_", ""):
                final_map[orig] = proper
                break
        if orig not in final_map:
            final_map[orig] = std

    df = df.rename(columns=final_map)
    return df


def _detect_wide_format(df: pd.DataFrame) -> bool:
    """Detect if data is in wide format (DUTs as columns)."""
    # If we already have Parameter and Value columns, it's long format
    cols_lower = [c.lower().strip() for c in df.columns]
    if "parameter" in cols_lower and "value" in cols_lower:
        return False

    # Check if many columns are numeric (wide format indicator)
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    return len(numeric_cols) > 3


def _wide_to_long(df: pd.DataFrame) -> pd.DataFrame:
    """Convert wide-format data (parameters as rows, DUTs as columns) to long format."""
    # Try to identify the parameter column (first text column)
    text_cols = df.select_dtypes(include=["object"]).columns.tolist()
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()

    if not text_cols or not numeric_cols:
        return df

    param_col = text_cols[0]
    # Check for unit and spec columns
    meta_cols = []
    for col in text_cols[1:]:
        col_lower = col.lower().strip()
        if any(alias in col_lower for aliases in COLUMN_ALIASES.values()
               for alias in aliases if alias not in
               [a for a in COLUMN_ALIASES["parameter"]]):
            meta_cols.append(col)

    # Additional non-numeric metadata columns (unit, spec_min, spec_max)
    id_vars = [param_col] + meta_cols
    value_vars = numeric_cols

    melted = df.melt(
        id_vars=id_vars,
        value_vars=value_vars,
        var_name="DUT_ID",
        value_name="Value",
    )
    melted = melted.rename(columns={param_col: "Parameter"})
    return melted


def load_single_file(file_path: Path) -> Optional[pd.DataFrame]:
    """Load a single CSV or Excel file into a DataFrame."""
    try:
        ext = file_path.suffix.lower()
        if ext == ".csv":
            # Try different encodings and separators
            for encoding in ["utf-8", "latin-1", "cp1252"]:
                for sep in [",", "\t", ";"]:
                    try:
                        df = pd.read_csv(
                            file_path, encoding=encoding, sep=sep
                        )
                        if len(df.columns) > 1:
                            break
                    except (UnicodeDecodeError, pd.errors.ParserError):
                        continue
                else:
                    continue
                break
            else:
                logger.warning(f"Could not parse CSV: {file_path}")
                return None
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(file_path, engine="openpyxl" if ext == ".xlsx" else None)
        else:
            logger.warning(f"Unsupported file format: {file_path}")
            return None

        # Drop completely empty rows/columns
        df = df.dropna(how="all").dropna(axis=1, how="all")

        if df.empty:
            logger.warning(f"Empty file: {file_path}")
            return None

        logger.info(f"Loaded {len(df)} rows from {file_path}")
        return df

    except Exception as e:
        logger.error(f"Error loading {file_path}: {e}")
        return None


def load_flow_data(flow_path: Path, flow_name: str,
                   config: Config) -> Optional[FlowData]:
    """Load all data files from a flow directory.

    Args:
        flow_path: Path to the flow directory (e.g., data/Flow1/).
        flow_name: Name of the flow (e.g., "Flow1").
        config: Configuration object.

    Returns:
        FlowData object with all loaded and merged data, or None if no data found.
    """
    if not flow_path.exists():
        logger.warning(f"Flow directory not found: {flow_path}")
        return None

    all_dfs = []

    # Recursively find data files
    for ext in config.file_extensions:
        for file_path in sorted(flow_path.rglob(f"*{ext}")):
            # Skip temporary/hidden files
            if file_path.name.startswith(("~", ".")):
                continue

            df = load_single_file(file_path)
            if df is not None:
                # Normalize column names
                df = _normalize_columns(df)

                # Convert wide to long format if needed
                if _detect_wide_format(df):
                    df = _wide_to_long(df)
                    df = _normalize_columns(df)

                # Add source file info
                df["Source_File"] = file_path.name
                all_dfs.append(df)

    if not all_dfs:
        logger.warning(f"No valid data files found in {flow_path}")
        return None

    # Merge all DataFrames
    merged = pd.concat(all_dfs, ignore_index=True)

    # Ensure required columns exist
    if "Parameter" not in merged.columns:
        logger.error(f"No 'Parameter' column found in {flow_name} data")
        return None

    if "Value" not in merged.columns:
        logger.error(f"No 'Value' column found in {flow_name} data")
        return None

    # Ensure Value is numeric
    merged["Value"] = pd.to_numeric(merged["Value"], errors="coerce")
    merged = merged.dropna(subset=["Value"])

    # Fill missing columns with defaults
    if "Unit" not in merged.columns:
        merged["Unit"] = ""
    if "DUT_ID" not in merged.columns:
        merged["DUT_ID"] = [f"DUT_{i}" for i in range(len(merged))]
    if "Test_Condition" not in merged.columns:
        merged["Test_Condition"] = ""

    # Apply spec limits from config
    if "Spec_Min" not in merged.columns:
        merged["Spec_Min"] = np.nan
    if "Spec_Max" not in merged.columns:
        merged["Spec_Max"] = np.nan

    for param in merged["Parameter"].unique():
        mask = merged["Parameter"] == param
        if param in config.spec_limits:
            spec = config.spec_limits[param]
            # Only fill where not already specified in data
            if spec.has_min:
                merged.loc[mask & merged["Spec_Min"].isna(), "Spec_Min"] = spec.spec_min
            if spec.has_max:
                merged.loc[mask & merged["Spec_Max"].isna(), "Spec_Max"] = spec.spec_max
            if merged.loc[mask, "Unit"].eq("").all():
                merged.loc[mask, "Unit"] = spec.unit

    logger.info(
        f"Flow '{flow_name}': {len(merged)} measurements, "
        f"{merged['Parameter'].nunique()} parameters, "
        f"{merged['DUT_ID'].nunique()} DUTs"
    )

    return FlowData(flow_name=flow_name, raw_data=merged)


def load_all_flows(config: Config) -> dict:
    """Load data from all configured flow directories.

    Args:
        config: Configuration object.

    Returns:
        Dictionary mapping flow_name -> FlowData.
    """
    flows = {}
    for flow_dir in config.flow_dirs:
        flow_path = config.data_path / flow_dir
        flow_data = load_flow_data(flow_path, flow_dir, config)
        if flow_data is not None:
            flows[flow_dir] = flow_data
            logger.info(f"Loaded {flow_dir}: {len(flow_data.raw_data)} records")

    if not flows:
        logger.error(f"No data loaded from {config.data_path}")

    return flows
