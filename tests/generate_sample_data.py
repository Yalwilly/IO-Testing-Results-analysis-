"""
Generate synthetic IO test data that mirrors typical Electrical Validation
result files.  Creates Flow1/ and Flow2/ sub-folders under tests/sample_data/.

Run directly:  python tests/generate_sample_data.py
"""

from __future__ import annotations

import os
import random

import numpy as np
import pandas as pd

RANDOM_SEED = 42
np.random.seed(RANDOM_SEED)
random.seed(RANDOM_SEED)

# --------------------------------------------------------------------------- #
# Parameter specifications: (mean, std, low_limit, high_limit, unit)          #
# --------------------------------------------------------------------------- #
PARAM_SPECS = {
    "VOH":  (3.0,   0.08,  2.4,  3.6,  "V"),
    "VOL":  (0.15,  0.04,  0.0,  0.4,  "V"),
    "VIH":  (2.8,   0.10,  2.0,  3.6,  "V"),
    "VIL":  (0.35,  0.05,  0.0,  0.8,  "V"),
    "IOH":  (-4.0,  0.50, -8.0,  0.0,  "mA"),
    "IOL":  (4.0,   0.50,  0.0,  8.0,  "mA"),
    "IIH":  (0.04,  0.01,  0.0,  0.1,  "mA"),
    "IIL":  (-0.04, 0.01, -0.1,  0.0,  "mA"),
    "tpd":  (5.0,   0.40,  0.0, 10.0,  "ns"),
    "tr":   (2.0,   0.20,  0.0,  5.0,  "ns"),
    "tf":   (2.1,   0.22,  0.0,  5.0,  "ns"),
    "Skew": (0.1,   0.30, -2.0,  2.0,  "ns"),
}

DUT_COUNT = 20
CONDITIONS = ["TYP", "FF", "SS", "SF", "FS"]
PINS = [f"IO{i}" for i in range(1, 9)]


def _generate_flow_df(
    flow_name: str,
    mean_shift: float = 0.0,
    fail_inject_rate: float = 0.02,
) -> pd.DataFrame:
    """Create a DataFrame with synthetic test records for one flow."""
    rows = []
    for dut in range(1, DUT_COUNT + 1):
        dut_id = f"DUT_{dut:03d}"
        for cond in CONDITIONS:
            for pin in PINS:
                for param, (mean, std, lo, hi, unit) in PARAM_SPECS.items():
                    value = float(np.random.normal(mean + mean_shift * std, std))
                    # Randomly inject failures
                    if random.random() < fail_inject_rate:
                        # Push value outside limits
                        if random.random() < 0.5:
                            value = lo - abs(np.random.normal(0, std))
                        else:
                            value = hi + abs(np.random.normal(0, std))
                    status = "PASS" if lo <= value <= hi else "FAIL"
                    rows.append({
                        "Parameter": param,
                        "Value": round(value, 6),
                        "Unit": unit,
                        "DUT": dut_id,
                        "Pin": pin,
                        "Condition": cond,
                        "LowLimit": lo,
                        "HighLimit": hi,
                        "Status": status,
                        "Flow": flow_name,
                    })
    return pd.DataFrame(rows)


def generate(base_dir: str) -> None:
    """Generate sample CSV files for Flow1 and Flow2 under *base_dir*."""
    for flow_name, shift, fail_rate in [
        ("Flow1", 0.0,   0.02),
        ("Flow2", 0.05,  0.03),   # slight mean shift + slightly higher fail rate
    ]:
        flow_dir = os.path.join(base_dir, flow_name)
        os.makedirs(flow_dir, exist_ok=True)
        df = _generate_flow_df(flow_name, mean_shift=shift, fail_inject_rate=fail_rate)
        out_path = os.path.join(flow_dir, "results_merged.csv")
        df.to_csv(out_path, index=False)
        print(f"Generated {len(df):,} rows → {out_path}")


if __name__ == "__main__":
    base = os.path.join(os.path.dirname(__file__), "sample_data")
    generate(base)
    print("Sample data generation complete.")
