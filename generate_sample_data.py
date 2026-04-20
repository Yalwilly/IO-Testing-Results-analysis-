"""Generate sample IO Electrical Validation test data.

Creates realistic CSV files for Flow1 and Flow2 with various IO parameters,
some passing and some failing spec limits.
Uses Python standard library only (no pandas/numpy).
"""

import csv
import random
from pathlib import Path


def _normal(mean, std, n, rng):
    """Generate n approximately-normal values using Box-Muller transform."""
    values = []
    for _ in range((n + 1) // 2):
        import math
        u1 = max(rng.random(), 1e-10)
        u2 = rng.random()
        z0 = math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)
        z1 = math.sqrt(-2 * math.log(u1)) * math.sin(2 * math.pi * u2)
        values.extend([mean + std * z0, mean + std * z1])
    return values[:n]


def generate_sample_data(base_path: str = "sample_data", seed: int = 42):
    """Generate sample test data for Flow1 and Flow2."""
    rng = random.Random(seed)
    base = Path(base_path)

    parameters = {
        "VOH":            {"unit": "V",  "spec_min": 2.4,  "spec_max": None, "flow1_mean": 3.1,  "flow1_std": 0.15, "flow2_mean": 3.0,  "flow2_std": 0.18},
        "VOL":            {"unit": "V",  "spec_min": None, "spec_max": 0.4,  "flow1_mean": 0.15, "flow1_std": 0.06, "flow2_mean": 0.18, "flow2_std": 0.08},
        "VIH":            {"unit": "V",  "spec_min": 2.0,  "spec_max": None, "flow1_mean": 2.3,  "flow1_std": 0.1,  "flow2_mean": 2.25, "flow2_std": 0.12},
        "VIL":            {"unit": "V",  "spec_min": None, "spec_max": 0.8,  "flow1_mean": 0.55, "flow1_std": 0.08, "flow2_mean": 0.6,  "flow2_std": 0.1},
        "IOH":            {"unit": "mA", "spec_min": -8.0, "spec_max": None, "flow1_mean": -4.2, "flow1_std": 0.8,  "flow2_mean": -4.5, "flow2_std": 1.0},
        "IOL":            {"unit": "mA", "spec_min": None, "spec_max": 8.0,  "flow1_mean": 4.0,  "flow1_std": 0.9,  "flow2_mean": 4.3,  "flow2_std": 1.1},
        "Rise_Time":      {"unit": "ns", "spec_min": None, "spec_max": 5.0,  "flow1_mean": 2.1,  "flow1_std": 0.5,  "flow2_mean": 2.5,  "flow2_std": 0.7},
        "Fall_Time":      {"unit": "ns", "spec_min": None, "spec_max": 5.0,  "flow1_mean": 1.9,  "flow1_std": 0.4,  "flow2_mean": 2.3,  "flow2_std": 0.6},
        "Setup_Time":     {"unit": "ns", "spec_min": 1.0,  "spec_max": None, "flow1_mean": 2.0,  "flow1_std": 0.3,  "flow2_mean": 1.8,  "flow2_std": 0.35},
        "Hold_Time":      {"unit": "ns", "spec_min": 0.5,  "spec_max": None, "flow1_mean": 1.1,  "flow1_std": 0.2,  "flow2_mean": 0.95, "flow2_std": 0.25},
        "Leakage_Current":{"unit": "uA", "spec_min": None, "spec_max": 10.0, "flow1_mean": 2.0,  "flow1_std": 1.5,  "flow2_mean": 3.5,  "flow2_std": 2.5},
        "Capacitance":    {"unit": "pF", "spec_min": None, "spec_max": 8.0,  "flow1_mean": 4.2,  "flow1_std": 0.8,  "flow2_mean": 4.8,  "flow2_std": 1.2},
    }

    n_duts = 25
    dut_ids = [f"DUT_{i:03d}" for i in range(1, n_duts + 1)]
    fieldnames = ["Parameter", "Value", "Unit", "DUT_ID", "Spec_Min", "Spec_Max", "Test_Condition"]

    for flow_name, flow_idx in [("Flow1", 1), ("Flow2", 2)]:
        flow_dir = base / flow_name
        flow_dir.mkdir(parents=True, exist_ok=True)
        rows = []
        for param_name, spec in parameters.items():
            values = _normal(spec[f"flow{flow_idx}_mean"],
                             spec[f"flow{flow_idx}_std"], n_duts, rng)
            for dut_id, value in zip(dut_ids, values):
                rows.append({
                    "Parameter": param_name,
                    "Value": round(value, 6),
                    "Unit": spec["unit"],
                    "DUT_ID": dut_id,
                    "Spec_Min": spec["spec_min"] if spec["spec_min"] is not None else "",
                    "Spec_Max": spec["spec_max"] if spec["spec_max"] is not None else "",
                    "Test_Condition": f"{flow_name}_Nominal",
                })
        csv_path = flow_dir / f"{flow_name}_IO_Results.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"Generated: {csv_path} ({len(rows)} records)")

    print(f"\nSample data generated in: {base}")
    print(f"  {base}/Flow1/Flow1_IO_Results.csv")
    print(f"  {base}/Flow2/Flow2_IO_Results.csv")


if __name__ == "__main__":
    generate_sample_data()
