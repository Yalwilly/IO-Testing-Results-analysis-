"""Data loader for IO Testing Results.

Handles Intel IO test xlsx files (4-sheet format: Contents, 1d, 1t, 1g)
and generic CSV / xlsx files.
Uses Python standard library only (no pandas/numpy/openpyxl).
"""

import csv
import logging
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from io_analysis.config import Config
from io_analysis.data.models import FlowData

logger = logging.getLogger(__name__)

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

# ---------------------------------------------------------------------------
# Intel test type configurations
# Each entry:  "key" = substring of filename (lowercase)
#              "test_name" = human-readable label
#              "measurements" = list of column descriptors
#   Descriptor keys:
#     col          – header name in sheet "1d" (case-insensitive match)
#     name         – short suffix added to io_name to form Parameter
#     unit         – measurement unit string
#     spec_min_col – header name whose numeric value is the lower spec limit
#     spec_max_col – header name whose numeric value is the upper spec limit
#     pf_col       – header name whose value is "Pass"/"Fail" per row
#     abs_value    – if True, take abs() of the numeric value
#     value_map    – dict mapping raw string → numeric value (categorical cols)
# ---------------------------------------------------------------------------
_INTEL_TEST_CONFIGS = [
    {
        "key": "iohmaxiolmax",
        "test_name": "IOH/IOL Max",
        "measurements": [
            {"col": "measured low voltage + load", "name": "VOL",
             "unit": "V", "spec_max_col": "volmax spec",
             "pf_col": "pass/fail low"},
            {"col": "measured high voltage + load", "name": "VOH",
             "unit": "V", "spec_min_col": "vohmin spec",
             "pf_col": "pass/fail high"},
            {"col": "measured_iol(+)", "name": "IOL_A",
             "unit": "mA", "scale": 1000},
            {"col": "measured_iohmax(-)", "name": "IOH_A",
             "unit": "mA", "scale": 1000, "abs_value": True},
            {"col": "resistancelow", "name": "R_Low",
             "unit": "Ohm", "abs_value": True},
            {"col": "resistancehigh", "name": "R_High",
             "unit": "Ohm", "abs_value": True},
        ],
    },
    {
        "key": "voh vol",
        "test_name": "VOH/VOL",
        "measurements": [
            {"col": "measured low voltage + load", "name": "VOL",
             "unit": "V", "spec_max_col": "volmax spec",
             "pf_col": "pass/fail low"},
            {"col": "measured high voltage + load", "name": "VOH",
             "unit": "V", "spec_min_col": "vohmin spec",
             "pf_col": "pass/fail high"},
            {"col": "measured_iol(+)", "name": "IOL_A", "unit": "mA", "scale": 1000},
            {"col": "measured_iohmax(-)", "name": "IOH_A", "unit": "mA", "scale": 1000, "abs_value": True},
        ],
    },
    {
        "key": "vihminvilmax",
        "test_name": "VIH/VIL",
        "measurements": [
            {"col": "measuredvilmax", "name": "VIL_Max",
             "unit": "V", "spec_max_col": "vilmaxspec",
             "pf_col": "pass/fail low"},
            {"col": "measuredvihmin", "name": "VIH_Min",
             "unit": "V", "spec_min_col": "vihminspec",
             "pf_col": "pass/fail high"},
        ],
    },
    {
        "key": "pulluppulldownresistance",
        "test_name": "Pull-up/Pull-down Resistance",
        "measurements": [
            {"col": "resistancepullup", "name": "R_PullUp",
             "unit": "kOhm", "abs_value": True, "scale": 0.001},
            {"col": "resistancepulldown", "name": "R_PullDown",
             "unit": "kOhm", "abs_value": True, "scale": 0.001},
        ],
    },
    {
        "key": "iostateafterpor",
        "test_name": "IO State After POR",
        "measurements": [
            {"col": "iostatehighlow", "name": "IO_State",
             "unit": "H=1/L=0",
             "value_map": {"h": 1.0, "high": 1.0, "l": 0.0, "low": 0.0},
             "pf_col": "exec status"},
            {"col": "iodirection", "name": "IO_Direction",
             "unit": "Out=1/In=0",
             "value_map": {"output": 1.0, "out": 1.0, "input": 0.0, "in": 0.0},
             "pf_col": "exec status"},
        ],
    },
    {
        "key": "risefalltime",
        "test_name": "Rise/Fall Time",
        "measurements": [
            {"col": "measured fall time [psec]", "name": "Fall_Time_ps",
             "unit": "ps"},
            {"col": "measured rise time [psec]", "name": "Rise_Time_ps",
             "unit": "ps"},
            # Alternate names used in some file versions
            {"col": "measured fall time", "name": "Fall_Time_ps", "unit": "ps"},
            {"col": "measured rise time", "name": "Rise_Time_ps", "unit": "ps"},
            {"col": "fall time [psec]", "name": "Fall_Time_ps", "unit": "ps"},
            {"col": "rise time [psec]", "name": "Rise_Time_ps", "unit": "ps"},
            {"col": "fall time", "name": "Fall_Time_ps", "unit": "ps"},
            {"col": "rise time", "name": "Rise_Time_ps", "unit": "ps"},
            {"col": "tfall", "name": "Fall_Time_ps", "unit": "ps"},
            {"col": "trise", "name": "Rise_Time_ps", "unit": "ps"},
            {"col": "falltime", "name": "Fall_Time_ps", "unit": "ps"},
            {"col": "risetime", "name": "Rise_Time_ps", "unit": "ps"},
            {"col": "measured_fall_time", "name": "Fall_Time_ps", "unit": "ps"},
            {"col": "measured_rise_time", "name": "Rise_Time_ps", "unit": "ps"},
            # Column header in some files is "risetime [us]" but values are in ps
            {"col": "risetime [us]", "name": "Rise_Time_ps", "unit": "ps"},
            {"col": "risetime", "name": "Rise_Time_ps", "unit": "ps"},
        ],
    },
]


def _detect_intel_test_type(file_path: Path) -> Optional[dict]:
    """Return the matching Intel test config for this file, or None."""
    name = file_path.name.lower()
    for cfg in _INTEL_TEST_CONFIGS:
        if cfg["key"] in name:
            return cfg
    return None


# ---------------------------------------------------------------------------
# Low-level xlsx helpers
# ---------------------------------------------------------------------------

def _read_shared_strings(zf: zipfile.ZipFile) -> list:
    ss: list = []
    if "xl/sharedStrings.xml" in zf.namelist():
        root = ET.parse(zf.open("xl/sharedStrings.xml")).getroot()
        for si in root.findall(f"{{{NS}}}si"):
            t = si.find(f"{{{NS}}}t")
            if t is not None:
                ss.append(t.text or "")
            else:
                texts = si.findall(f".//{{{NS}}}t")
                ss.append("".join(x.text or "" for x in texts))
    return ss


def _cell_value(cell, ss: list) -> str:
    t = cell.get("t", "")
    if t == "e":  # Excel error cell (#DIV/0!, #VALUE!, etc.) — treat as empty
        return ""
    v = cell.find(f"{{{NS}}}v")
    if v is None or v.text is None:
        return ""
    if t == "s":
        idx = int(v.text)
        return ss[idx] if idx < len(ss) else ""
    if t == "b":
        return "TRUE" if v.text == "1" else "FALSE"
    return v.text


def _col_letters(ref: str) -> str:
    return "".join(c for c in ref if c.isalpha())


# ---------------------------------------------------------------------------
# Intel xlsx reader: reads sheet "1d" (sheet2) and emits normalised rows
# ---------------------------------------------------------------------------

def _read_intel_xlsx(file_path: Path, test_cfg: dict) -> list:
    """
    Read an Intel IO test xlsx and return a list of normalised measurement rows.
    Each row has: Parameter, Value, Unit, DUT_ID, Spec_Min, Spec_Max,
                  Test_Condition, Raw_Pass_Fail, IO_Name, Test_Name, Source_File
    """
    rows: list = []
    try:
        with zipfile.ZipFile(str(file_path)) as zf:
            ss = _read_shared_strings(zf)
            sheet = "xl/worksheets/sheet2.xml"
            if sheet not in zf.namelist():
                logger.warning(f"No sheet2 in {file_path.name} — skipping")
                return rows

            root = ET.parse(zf.open(sheet)).getroot()
            all_rows = root.findall(f".//{{{NS}}}row")
            if not all_rows:
                return rows

            # Build header map: lower(name) → col_letter
            hdr: dict = {}
            for c in all_rows[0].findall(f"{{{NS}}}c"):
                name = _cell_value(c, ss).strip().lower()
                col = _col_letters(c.get("r", ""))
                if name and col:
                    hdr[name] = col

            def col_of(name: str) -> Optional[str]:
                return hdr.get(name.strip().lower()) if name else None

            # Standard metadata column letters
            io_col = col_of("io name")
            id_col = col_of("filetestpairid")
            chip_id_col = col_of("* chip id")
            temp_col = col_of("temperature")
            vin_gpio_col = col_of("vin gpio")
            vin_core_col = col_of("vin core")
            exec_col = col_of("exec status")
            skew_col = col_of("* skew materials")
            ds_col = col_of("ds")
            pull_mode_col = col_of("pull mode")
            dut_col = chip_id_col or id_col

            # Pre-resolve measurement column references
            resolved_meas: list = []
            seen_names: set = set()
            for m in test_cfg["measurements"]:
                meas_col = col_of(m["col"])
                if not meas_col:
                    continue
                meas_name = m["name"]
                if meas_name in seen_names:
                    continue  # deduplicate alternate column names
                seen_names.add(meas_name)
                resolved_meas.append({
                    **m,
                    "_meas_col": meas_col,
                    "_spec_min_col": col_of(m.get("spec_min_col", "")),
                    "_spec_max_col": col_of(m.get("spec_max_col", "")),
                    "_pf_col": col_of(m.get("pf_col", "")),
                })

            if not resolved_meas:
                logger.warning(
                    f"No recognised measurement columns in {file_path.name}"
                )
                return rows

            logger.info(
                f"  {file_path.name}: {len(resolved_meas)} measurement types, "
                f"reading {len(all_rows)-1} data rows from sheet '1d'"
            )

            for row_elem in all_rows[1:]:
                # Parse all cell values for this row
                rv: dict = {}
                for c in row_elem.findall(f"{{{NS}}}c"):
                    col = _col_letters(c.get("r", ""))
                    if col:
                        rv[col] = _cell_value(c, ss)

                if not rv:
                    continue

                io_name = rv.get(io_col, "") if io_col else ""
                dut_id = rv.get(dut_col, "") if dut_col else ""
                if not dut_id and id_col:
                    dut_id = rv.get(id_col, "")
                temperature = rv.get(temp_col, "") if temp_col else ""
                vin_gpio = rv.get(vin_gpio_col, "") if vin_gpio_col else ""
                vin_core = rv.get(vin_core_col, "") if vin_core_col else ""
                skew = rv.get(skew_col, "") if skew_col else ""
                ds = rv.get(ds_col, "") if ds_col else ""
                pull_mode = rv.get(pull_mode_col, "") if pull_mode_col else ""

                parts = []
                if temperature:
                    parts.append(f"T={temperature}C")
                if vin_gpio:
                    parts.append(f"VIO={vin_gpio}V")
                if vin_core:
                    parts.append(f"VCORE={vin_core}V")
                if skew:
                    parts.append(f"SKW={skew}")
                test_condition = " ".join(parts)

                for m in resolved_meas:
                    val_str = rv.get(m["_meas_col"], "")
                    value: Optional[float] = None

                    if "value_map" in m:
                        value = m["value_map"].get(val_str.strip().lower())
                    else:
                        try:
                            value = float(val_str)
                            if m.get("abs_value"):
                                value = abs(value)
                            if m.get("scale"):
                                value *= m["scale"]
                        except (ValueError, TypeError):
                            pass

                    if value is None:
                        continue

                    spec_min: Optional[float] = None
                    spec_max: Optional[float] = None
                    smin_c = m["_spec_min_col"]
                    smax_c = m["_spec_max_col"]
                    if smin_c:
                        try:
                            v = float(rv.get(smin_c, ""))
                            if v != 0.0 and v == v and abs(v) != float("inf"):
                                spec_min = v
                        except (ValueError, TypeError):
                            pass
                    if smax_c:
                        try:
                            v = float(rv.get(smax_c, ""))
                            if v != 0.0 and v == v and abs(v) != float("inf"):
                                spec_max = v
                        except (ValueError, TypeError):
                            pass

                    # --- PDF-spec fallback: compute limits when file has 0.0 or missing ---
                    # PB12 = RF_KILLN; everything else (GPIO_0, BRI_DT) = PB16
                    _meas_name = m["name"]
                    _is_pb12   = io_name.upper().strip() == "RF_KILLN"

                    if _meas_name == "VIH_Min" and spec_max is None and vin_gpio:
                        # PB16: VIH_min = 0.65 × DVDD  |  PB12: VIH_min = 0.70 × DVDD
                        # Measured threshold must be ≤ spec (not exceed it) → spec_max
                        try:
                            spec_max = round((0.70 if _is_pb12 else 0.65) * float(vin_gpio), 4)
                        except (ValueError, TypeError):
                            pass

                    elif _meas_name == "VIL_Max" and spec_min is None and vin_gpio:
                        # PB16: VIL_max = 0.35 × DVDD  |  PB12: VIL_max = 0.30 × DVDD
                        # Measured threshold must be ≥ spec (not fall below) → spec_min
                        try:
                            spec_min = round((0.30 if _is_pb12 else 0.35) * float(vin_gpio), 4)
                        except (ValueError, TypeError):
                            pass

                    elif _meas_name in ("R_PullUp", "R_PullDown"):
                        if spec_min is None and spec_max is None:
                            # PB16: 30–70 kΩ  |  PB12: 100–200 kΩ  (Table 18/20 in IO_SPEC)
                            if _is_pb12:
                                spec_min, spec_max = 100.0, 200.0
                            else:
                                spec_min, spec_max = 30.0, 70.0

                    elif _meas_name == "R_Low" and spec_max is None:
                        # R_Low spec_max = VOL_spec_max / IOL_test  (Ω = V / A)
                        # Higher resistance at the test current → higher VOL → fail
                        vol_spec_c = col_of("volmax spec")
                        iol_col_c  = col_of("measured_iol(+)")
                        if vol_spec_c and iol_col_c:
                            try:
                                vol_spv = float(rv.get(vol_spec_c, "") or "")
                                iol_v   = float(rv.get(iol_col_c,  "") or "")
                                if iol_v > 0 and 0 < vol_spv < 10:
                                    spec_max = round(vol_spv / iol_v, 2)
                            except (ValueError, TypeError):
                                pass

                    elif _meas_name == "R_High" and spec_max is None:
                        # R_High spec_max = (VIO − VOH_spec_min) / |IOH_test|
                        voh_spec_c = col_of("vohmin spec")
                        ioh_col_c  = col_of("measured_iohmax(-)")
                        if voh_spec_c and ioh_col_c and vin_gpio:
                            try:
                                voh_spv = float(rv.get(voh_spec_c, "") or "")
                                ioh_v   = abs(float(rv.get(ioh_col_c, "") or ""))
                                vio_v   = float(vin_gpio)
                                if ioh_v > 0 and voh_spv > 0 and vio_v > voh_spv:
                                    spec_max = round((vio_v - voh_spv) / ioh_v, 2)
                            except (ValueError, TypeError):
                                pass

                    # Raw pass/fail from test infrastructure
                    pf = ""
                    pf_c = m["_pf_col"]
                    if pf_c:
                        pf = rv.get(pf_c, "")
                    elif exec_col:
                        pf = "Pass" if rv.get(exec_col, "").strip().lower() == "ok" else "Fail"

                    param_name = (
                        f"{io_name}_{m['name']}" if io_name else m["name"]
                    )

                    rows.append({
                        "Parameter": param_name,
                        "Value": value,
                        "Unit": m.get("unit", ""),
                        "DUT_ID": dut_id,
                        "Spec_Min": spec_min,
                        "Spec_Max": spec_max,
                        "Test_Condition": test_condition,
                        "Raw_Pass_Fail": pf,
                        "IO_Name": io_name,
                        "DS": ds,
                        "Pull_Mode": pull_mode,
                        "Temperature": temperature,
                        "Skew": skew,
                        "Test_Name": test_cfg["test_name"],
                        "Source_File": file_path.name,
                    })

    except Exception as e:
        logger.error(f"Error reading Intel xlsx {file_path}: {e}", exc_info=True)

    return rows


# ---------------------------------------------------------------------------
# Generic xlsx reader (fallback for non-Intel files)
# ---------------------------------------------------------------------------

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

STANDARD_NAMES = {
    "parameter": "Parameter",
    "value": "Value",
    "unit": "Unit",
    "dut_id": "DUT_ID",
    "spec_min": "Spec_Min",
    "spec_max": "Spec_Max",
    "test_condition": "Test_Condition",
}


def _col_to_num(col: str) -> int:
    """Convert column letter(s) to 1-based number: A=1, B=2, Z=26, AA=27..."""
    num = 0
    for c in col.upper():
        num = num * 26 + (ord(c) - ord("A") + 1)
    return num


def _try_float(val) -> Optional[float]:
    """Try to convert value to float, return None on failure (rejects NaN/inf)."""
    if val is None or val == "":
        return None
    try:
        f = float(val)
        if f != f or abs(f) == float("inf"):  # reject NaN and infinity
            return None
        return f
    except (ValueError, TypeError):
        return None


def _read_xlsx(file_path: Path) -> list:
    """Read the first sheet of an xlsx file using zipfile + ElementTree.
    Returns a list of dicts (header keys from the first row).
    """
    try:
        with zipfile.ZipFile(str(file_path), "r") as zf:
            names = zf.namelist()
            ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

            # ---- shared strings ----
            shared_strings: list = []
            if "xl/sharedStrings.xml" in names:
                with zf.open("xl/sharedStrings.xml") as f:
                    root = ET.parse(f).getroot()
                    for si in root.findall(f"{{{ns}}}si"):
                        t = si.find(f"{{{ns}}}t")
                        if t is not None:
                            shared_strings.append(t.text or "")
                        else:
                            texts = si.findall(f".//{{{ns}}}t")
                            shared_strings.append("".join(t.text or "" for t in texts))

            # ---- find first sheet ----
            sheet_file = "xl/worksheets/sheet1.xml"
            if sheet_file not in names:
                for n in sorted(names):
                    if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"):
                        sheet_file = n
                        break
                else:
                    logger.warning(f"No worksheets found in {file_path}")
                    return []

            # ---- parse sheet ----
            with zf.open(sheet_file) as f:
                root = ET.parse(f).getroot()

            raw_rows: list = []
            for row_elem in root.findall(f".//{{{ns}}}row"):
                row_data: dict = {}
                for cell in row_elem.findall(f"{{{ns}}}c"):
                    ref = cell.get("r", "")
                    cell_type = cell.get("t", "")
                    v_elem = cell.find(f"{{{ns}}}v")
                    col_letter = "".join(c for c in ref if c.isalpha())
                    if v_elem is not None and v_elem.text is not None:
                        if cell_type == "s":
                            idx = int(v_elem.text)
                            val = shared_strings[idx] if idx < len(shared_strings) else ""
                        elif cell_type == "b":
                            val = "TRUE" if v_elem.text == "1" else "FALSE"
                        else:
                            val = v_elem.text
                    else:
                        val = ""
                    if col_letter:
                        row_data[col_letter] = val
                if row_data:
                    raw_rows.append(row_data)

            if not raw_rows:
                return []

            # sort columns A→Z→AA→AB...
            all_cols = set()
            for row in raw_rows:
                all_cols.update(row.keys())
            sorted_cols = sorted(all_cols, key=_col_to_num)

            # first row = headers
            header_row = raw_rows[0]
            headers = {col: (header_row.get(col) or col) for col in sorted_cols}

            result = []
            for row in raw_rows[1:]:
                if not any(row.values()):
                    continue
                d = {headers[col]: row.get(col, "") for col in sorted_cols}
                result.append(d)
            return result

    except Exception as e:
        logger.error(f"Error reading xlsx {file_path}: {e}")
        return []


def _read_csv_file(file_path: Path) -> list:
    """Read a CSV file and return list of dicts."""
    for encoding in ["utf-8", "latin-1", "cp1252"]:
        for sep in [",", "\t", ";"]:
            try:
                with open(file_path, encoding=encoding, newline="") as f:
                    reader = csv.DictReader(f, delimiter=sep)
                    rows = list(reader)
                if rows and len(rows[0]) > 1:
                    return [{k: v for k, v in row.items() if k} for row in rows]
            except (UnicodeDecodeError, csv.Error):
                continue
    logger.warning(f"Could not parse CSV: {file_path}")
    return []


def _normalize_columns(rows: list) -> list:
    """Rename columns to standard names via COLUMN_ALIASES."""
    if not rows:
        return rows
    existing = list(rows[0].keys())
    lower_map = {h.lower().strip(): h for h in existing}
    col_map: dict = {}
    for std_key, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lower_map:
                col_map[lower_map[alias]] = STANDARD_NAMES[std_key]
                break
    if not col_map:
        return rows
    return [{col_map.get(k, k): v for k, v in row.items()} for row in rows]


def _detect_wide_format(rows: list) -> bool:
    """Return True if the data looks like wide format (DUTs as columns)."""
    if not rows:
        return False
    headers = [h.lower().strip() for h in rows[0].keys()]
    if "parameter" in headers and "value" in headers:
        return False
    numeric_count = sum(
        1 for v in rows[0].values()
        if v and _try_float(v) is not None
    )
    return numeric_count > 3


def _wide_to_long(rows: list) -> list:
    """Convert wide format (DUTs as columns) to long format."""
    if not rows:
        return rows
    headers = list(rows[0].keys())
    if not headers:
        return rows

    param_col = headers[0]
    meta_cols = [param_col]
    dut_cols = []
    for h in headers[1:]:
        sample = [row.get(h, "") for row in rows[:5] if row.get(h, "")]
        numeric = sum(1 for v in sample if _try_float(v) is not None)
        if sample and numeric >= len(sample) * 0.6:
            dut_cols.append(h)
        else:
            meta_cols.append(h)

    long_rows = []
    for row in rows:
        param = row.get(param_col, "")
        meta = {k: row.get(k, "") for k in meta_cols[1:]}
        for dut_col in dut_cols:
            val = row.get(dut_col, "")
            if val != "" and val is not None:
                new_row = {"Parameter": param, "DUT_ID": dut_col, "Value": val}
                new_row.update(meta)
                long_rows.append(new_row)
    return long_rows


def load_single_file(file_path: Path) -> Optional[list]:
    """Load a single CSV or Excel file. Returns list of row dicts or None."""
    try:
        ext = file_path.suffix.lower()
        if ext == ".xlsx":
            # Try Intel format first
            test_cfg = _detect_intel_test_type(file_path)
            if test_cfg:
                rows = _read_intel_xlsx(file_path, test_cfg)
                if rows:
                    logger.info(
                        f"Loaded {len(rows)} measurement rows "
                        f"(Intel format) from {file_path.name}"
                    )
                    return rows
                logger.warning(
                    f"Intel reader returned 0 rows for {file_path.name}; "
                    f"falling back to generic reader"
                )
            rows = _read_xlsx(file_path)
        elif ext == ".csv":
            rows = _read_csv_file(file_path)
        elif ext == ".xls":
            logger.warning(
                f"Old .xls format requires xlrd: {file_path}. "
                f"Re-save as .xlsx or .csv and retry."
            )
            return None
        else:
            logger.warning(f"Unsupported file format: {file_path}")
            return None

        if not rows:
            logger.warning(f"Empty file: {file_path}")
            return None

        logger.info(f"Loaded {len(rows)} rows from {file_path}")
        return rows

    except Exception as e:
        logger.error(f"Error loading {file_path}: {e}")
        return None


def load_flow_data(flow_path: Path, flow_name: str,
                   config: Config) -> Optional[FlowData]:
    """Load all data files from a flow directory."""
    if not flow_path.exists():
        logger.warning(f"Flow directory not found: {flow_path}")
        return None

    all_rows: list = []

    for ext in config.file_extensions:
        # Search files directly in the flow folder AND exactly one level deep
        # in subdirectories (e.g. Flow1/SubFolder/file.xlsx).
        # Does NOT recurse further than one subdirectory level.
        patterns = [f"*{ext}", f"*/*{ext}"]
        found: list = []
        for pattern in patterns:
            found.extend(flow_path.glob(pattern))
        for file_path in sorted(set(found)):
            if file_path.name.startswith(("~", ".")):
                continue
            # Skip derived subdirectories: "Merge" folder contains per-DUT
            # CSV replicas of the xlsx data; numbered folders (e.g. 040/, 046/)
            # are per-DUT exports that duplicate the aggregate xlsx file.
            parent_name = file_path.parent.name
            if parent_name.lower() == "merge" or parent_name.isdigit():
                logger.debug(f"Skipping derived subfolder: {file_path}")
                continue
            rows = load_single_file(file_path)
            if rows is None:
                continue
            # Intel-format rows already carry proper keys — skip generic recoding
            if rows and "Raw_Pass_Fail" not in rows[0]:
                rows = _normalize_columns(rows)
                if _detect_wide_format(rows):
                    rows = _wide_to_long(rows)
                    rows = _normalize_columns(rows)
            for row in rows:
                if "Source_File" not in row:
                    row["Source_File"] = file_path.name
            all_rows.extend(rows)

    if not all_rows:
        logger.warning(f"No valid data files found in {flow_path}")
        return None

    all_keys: set = set()
    for row in all_rows:
        all_keys.update(row.keys())

    if "Parameter" not in all_keys:
        logger.error(f"No 'Parameter' column found in {flow_name} data")
        return None
    if "Value" not in all_keys:
        logger.error(f"No 'Value' column found in {flow_name} data")
        return None

    clean_rows = []
    for i, row in enumerate(all_rows):
        val = _try_float(row.get("Value"))
        if val is None:
            continue
        row["Value"] = val
        if not row.get("Unit"):
            row["Unit"] = ""
        if not row.get("DUT_ID"):
            row["DUT_ID"] = f"DUT_{i}"
        if "Test_Condition" not in row:
            row["Test_Condition"] = ""
        row["Spec_Min"] = _try_float(row.get("Spec_Min"))
        row["Spec_Max"] = _try_float(row.get("Spec_Max"))

        # Determine Pass boolean
        spec_min = row["Spec_Min"]
        spec_max = row["Spec_Max"]
        v = row["Value"]
        if spec_min is not None or spec_max is not None:
            passed = True
            if spec_min is not None and v < spec_min:
                passed = False
            if spec_max is not None and v > spec_max:
                passed = False
        elif "Raw_Pass_Fail" in row:
            pf = str(row["Raw_Pass_Fail"]).strip().lower()
            passed = pf in ("pass", "ok")
        else:
            passed = True
        row["Pass"] = passed

        clean_rows.append(row)

    # Apply spec limits from config
    for row in clean_rows:
        param = row.get("Parameter", "")
        if param in config.spec_limits:
            spec = config.spec_limits[param]
            if spec.has_min and row["Spec_Min"] is None:
                row["Spec_Min"] = spec.spec_min
            if spec.has_max and row["Spec_Max"] is None:
                row["Spec_Max"] = spec.spec_max
            if not row.get("Unit"):
                row["Unit"] = spec.unit

    unique_params = len({r["Parameter"] for r in clean_rows})
    logger.info(
        f"Flow '{flow_name}': {len(clean_rows)} measurements, "
        f"{unique_params} parameters"
    )
    return FlowData(flow_name=flow_name, rows=clean_rows)


def load_all_flows(config: Config) -> dict:
    """Load data from all configured flow directories."""
    flows: dict = {}
    for flow_dir in config.flow_dirs:
        flow_path = config.data_path / flow_dir
        flow_data = load_flow_data(flow_path, flow_dir, config)
        if flow_data is not None:
            flows[flow_dir] = flow_data
            logger.info(f"Loaded {flow_dir}: {flow_data.record_count} records")

    if not flows:
        logger.error(f"No data loaded from {config.data_path}")

    return flows
