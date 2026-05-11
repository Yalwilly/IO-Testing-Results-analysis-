"""Read and print headers + sample rows from PMIC CSVs."""
import csv, os, io

BASE = r"Y:\2027 Projects\PeP2\SMV\EFV\SVT\TC Step\ww06'26 PeP_SVT_TC_EFV PMIC_unsorted cycle\Results\Merge"

FILES = [
    "Power_Static_PeP_TC_21988__UnknownULT__21-45-52.csv",
    "Power_Quiescencetest_PeP_TC_21988__UnknownULT__00-28-44.csv",
    "Power_PowerOn_PeP_TC_21988__UnknownULT__00-18-53.csv",
    "Power_TransientResponse_PeP_TC_21988__UnknownULT__23-24-59.csv",
    "Power_VoltageTransitions_PeP_TC_21988__UnknownULT__00-33-45.csv",
    "Power_AutoModeTransitions_PeP_TC_21988__UnknownULT__00-55-05.csv",
    "Power_PowerSetupVerifier_PeP_TC_21988__UnknownULT__21-45-10.csv",
]

OUT = open("pmic_schema.txt", "w", encoding="utf-8")

def p(s=""):
    print(s)
    OUT.write(s + "\n")

for fname in FILES:
    path = os.path.join(BASE, fname)
    p(f"\n{'='*70}")
    p(f"FILE: {fname}")
    p('='*70)
    try:
        # Try UTF-8 first, fall back to latin-1
        for enc in ("utf-8-sig", "utf-16", "latin-1"):
            try:
                raw = open(path, encoding=enc).read()
                break
            except Exception:
                continue

        lines = raw.splitlines()
        # Find where header row is (skip metadata lines)
        header_idx = None
        for i, line in enumerate(lines):
            # Header row usually has many commas and recognisable column names
            if line.count(",") >= 3 and any(kw in line.lower() for kw in
                    ["chip", "temp", "vin", "power", "mode", "freq", "efficiency",
                     "iload", "vout", "slew", "undershoot", "overshoot", "voltage",
                     "test", "result", "status", "pass", "fail", "skew"]):
                header_idx = i
                break

        if header_idx is None:
            # Just print first 30 lines raw
            p("(could not detect header - raw first 30 lines:)")
            for ln in lines[:30]:
                p(f"  {ln}")
        else:
            p(f"(metadata lines 0-{header_idx-1}):")
            for ln in lines[:header_idx]:
                p(f"  META: {ln}")
            p(f"\nHEADER (line {header_idx}):")
            p(f"  {lines[header_idx]}")
            cols = [c.strip() for c in lines[header_idx].split(",")]
            p(f"\nCOLUMNS ({len(cols)} total):")
            for i, c in enumerate(cols):
                p(f"  [{i:2d}] {c}")
            p(f"\nSAMPLE DATA ROWS (lines {header_idx+1} to {min(header_idx+6, len(lines)-1)}):")
            for ln in lines[header_idx+1:header_idx+6]:
                p(f"  {ln}")
    except Exception as e:
        p(f"ERROR: {e}")

OUT.close()
print("\nDone — see pmic_schema.txt")
