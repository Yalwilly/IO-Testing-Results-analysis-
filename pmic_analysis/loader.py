"""
PMIC DC2DC Validation Data Loader.
Reads Intel SVT CSV files (75-line metadata header + column row + data).
Supports: StaticTest, Quiescencetest, PowerOn, TransientResponse,
          VoltageTransitionsTest, AutoModeTransitions, PowerSetupVerifier
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# File layout constants (0-indexed)
_META_LINES   = 75    # lines 0-74 are $$Key$$,Value metadata
_LABEL_LINE   = 75    # "Test results:,,,,,Data,Data,..."  (skip)
_HEADER_LINE  = 76    # actual column names (leading comma → col[0]='')
_DATA_START   = 77    # first real data row


def _classify_test(fname_lower: str) -> str:
    """Return coarse test-type key from filename."""
    if "powersetupverifier" in fname_lower:
        return "SetupVerifier"
    if "poweron" in fname_lower:
        return "PowerOn"
    if "static" in fname_lower:
        return "Static"           # subdivided per-row below
    if "quiescence" in fname_lower:
        return "Quiescence"
    if "transientresponse" in fname_lower or "transient" in fname_lower:
        return "Transient"
    if "voltagetransitions" in fname_lower:
        return "VoltageTransitions"
    if "automode" in fname_lower:
        return "AutoMode"
    return "Unknown"


def _to_float(s, default=None):
    try:
        v = float(str(s).strip())
        return v if v == v else default   # NaN check
    except (ValueError, TypeError):
        return default


def _read_text(path: Path) -> Optional[str]:
    for enc in ("utf-8-sig", "latin-1", "cp1252"):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return None


def parse_pmic_csv(path: Path) -> list:
    """
    Parse one PMIC CSV. Returns list of row-dicts with extra keys:
      _chip_id   – from $$Chip ID$$ metadata
      _test_type – 'Static_Load', 'Static_Line', 'Quiescence', 'PowerOn',
                   'Transient', 'VoltageTransitions', 'AutoMode', 'SetupVerifier'
    """
    content = _read_text(path)
    if content is None:
        logger.warning("Cannot read %s", path)
        return []

    lines = content.splitlines()
    if len(lines) < _DATA_START + 1:
        logger.warning("File too short: %s", path.name)
        return []

    # ── Extract chip_id from metadata ──────────────────────────────────────
    chip_id = ""
    for ln in lines[:_META_LINES]:
        if "* Chip ID" in ln:
            parts = ln.split(",")
            if len(parts) >= 2:
                chip_id = parts[-1].strip()
                break

    # ── Column headers ──────────────────────────────────────────────────────
    raw_hdr = lines[_HEADER_LINE].split(",")
    headers = [h.strip() for h in raw_hdr]
    # headers[0] is '' (leading comma artefact) – leave it, index by name

    # ── Classify test type ──────────────────────────────────────────────────
    base_type = _classify_test(path.name.lower())

    # ── Data rows ───────────────────────────────────────────────────────────
    rows = []
    for raw_line in lines[_DATA_START:]:
        if not raw_line.strip():
            continue
        vals = raw_line.split(",")
        row: dict = {}
        for i, h in enumerate(headers):
            if h and i < len(vals):
                row[h] = vals[i].strip()
        if not row:
            continue
        # Skip repeated header lines that sometimes appear
        if row.get("Exec Status", "").lower() in ("exec status",):
            continue
        # Skip rows with no execution status (incomplete rows)
        if "Exec Status" not in row:
            continue

        row["_chip_id"] = chip_id

        # Sub-classify Static files per row
        if base_type == "Static":
            llr = row.get("Load Line Regulation", "").strip().lower()
            row["_test_type"] = "Static_Load" if llr == "load" else "Static_Line"
        else:
            row["_test_type"] = base_type

        rows.append(row)

    logger.debug("  %s → %d rows (chip %s)", path.name, len(rows), chip_id)
    return rows


# ── Key name aliases (different files use slightly different spellings) ─────
_ALIASES = {
    "Iout [A]":         ["Iout [A]", "IoutSMU"],
    "Vin_setpoint":     ["Vin"],
    "Vout_setpoint":    ["Vout"],
    "RiseTime [uS]":    ["RiseTime [uS]", "Rise Time [uS]"],
    "FallTime [pSec]":  ["Measured Fall Time [pSec]", "Fall Time [pSec]"],
    "Undershoot [V]":   ["Undershoot [V]", "Vout Min"],
    "Overshoot [V]":    ["Overshoot [V]"],
    "Load_step_high":   ["Load step current high "],
    "Load_step_low":    ["Load step current low "],
    "Slope":            ["Slope"],
}


def _get(row: dict, *keys) -> Optional[str]:
    """Return first non-empty value for any of the given column names."""
    for k in keys:
        v = row.get(k, "")
        if v not in ("", None):
            return v
    return None


def _unique_sorted(values, numeric: bool = False) -> list:
    seen = set()
    out = []
    for v in values:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    if numeric:
        out.sort(key=lambda x: (_to_float(x, float("inf")), x))
    else:
        out.sort()
    return out


@dataclass
class PMICData:
    """All loaded PMIC test data, indexed by test type."""
    rows_by_test: dict = field(default_factory=dict)   # test_type → [row_dict]
    chip_ids:     list = field(default_factory=list)
    regulators:   list = field(default_factory=list)   # ['DC2DC_ANA', 'DC2DC_DIG']
    temps:        list = field(default_factory=list)   # ['0', '25', '80']
    modes:        list = field(default_factory=list)   # ['AUTO_PFM', 'PWM', ...]
    vout_per_reg: dict = field(default_factory=dict)   # regulator → [vout_str]

    def get_rows(self, test_type: str,
                 regulator: Optional[str] = None,
                 mode:      Optional[str] = None,
                 temp:      Optional[str] = None,
                 chip_id:   Optional[str] = None,
                 ok_only:   bool = True) -> list:
        rows = list(self.rows_by_test.get(test_type, []))
        if ok_only:
            rows = [r for r in rows
                    if r.get("Exec Status", "").strip().upper() in ("OK", "")]
        if regulator:
            rows = [r for r in rows
                    if r.get("Regulator Name", "").strip() == regulator]
        if mode:
            rows = [r for r in rows
                    if r.get("DCDC Efficiency Mode", "").strip() == mode]
        if temp:
            rows = [r for r in rows
                    if r.get("Temperature", "").strip() == temp]
        if chip_id:
            rows = [r for r in rows if r.get("_chip_id", "") == chip_id]
        return rows


def load_pmic_data(data_dir: Path) -> PMICData:
    """
    Load all PMIC CSV files.
    Searches: data_dir/Merge/*.csv  then  data_dir/*.csv
    File naming is case-insensitive; both legacy 'Power_*' prefix and
    newer unprefixed names (e.g. 'automodetransitions_*') are accepted.
    Any CSV whose name matches a known test keyword is loaded; others are
    classified as 'Unknown' and contribute no rows.
    """
    data_dir = Path(data_dir)
    csv_files: list = []

    merge_dir = data_dir / "Merge"
    if merge_dir.exists():
        csv_files += sorted(
            f for f in merge_dir.iterdir()
            if f.is_file() and f.suffix.lower() == ".csv"
        )
    # Also check root
    csv_files += sorted(
        f for f in data_dir.iterdir()
        if f.is_file() and f.suffix.lower() == ".csv"
    )
    # De-duplicate (a file might appear in both lists if Merge/ is root)
    seen: set = set()
    csv_files = [f for f in csv_files if not (f in seen or seen.add(f))]

    if not csv_files:
        logger.warning("No PMIC CSV files found in %s", data_dir)

    all_rows: list = []
    for fpath in csv_files:
        rows = parse_pmic_csv(fpath)
        all_rows.extend(rows)
        logger.info("Loaded %d rows from %s", len(rows), fpath.name)

    # ── Organise by test type ───────────────────────────────────────────────
    rows_by_test: dict = {}
    for row in all_rows:
        tt = row.get("_test_type", "Unknown")
        rows_by_test.setdefault(tt, []).append(row)

    # ── Collect unique filter dimensions ───────────────────────────────────
    chip_ids   = _unique_sorted([r.get("_chip_id", "")           for r in all_rows])
    regulators = _unique_sorted([r.get("Regulator Name", "").strip() for r in all_rows])
    temps      = _unique_sorted([r.get("Temperature", "").strip()    for r in all_rows],
                                numeric=True)
    modes      = _unique_sorted([r.get("DCDC Efficiency Mode", "").strip() for r in all_rows])

    # Vout targets per regulator (from 'Vout' setpoint column)
    vout_per_reg: dict = {}
    for reg in regulators:
        reg_rows = [r for r in all_rows if r.get("Regulator Name", "").strip() == reg]
        vout_per_reg[reg] = _unique_sorted(
            [r.get("Vout", "").strip() for r in reg_rows], numeric=True
        )

    data = PMICData(
        rows_by_test=rows_by_test,
        chip_ids=chip_ids,
        regulators=regulators,
        temps=temps,
        modes=modes,
        vout_per_reg=vout_per_reg,
    )

    logger.info("PMIC data: %d rows, %d files", len(all_rows), len(csv_files))
    logger.info("  Tests:  %s", list(rows_by_test.keys()))
    logger.info("  Chips:  %s", chip_ids)
    logger.info("  Regs:   %s", regulators)
    logger.info("  Temps:  %s", temps)
    logger.info("  Modes:  %s", modes)
    return data
