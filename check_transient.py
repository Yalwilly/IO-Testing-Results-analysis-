from pmic_analysis.loader import load_pmic_data

data = load_pmic_data(r"Y:\2027 Projects\PeP2\SMV\EFV\SVT\TC Step\ww06'26 PeP_SVT_TC_EFV PMIC_unsorted cycle\Results")
rows = data.get_rows("Transient")

print("=== Columns ===")
print([k for k in rows[0].keys() if not k.startswith("_")])
print()

# Find the exact column names for load step and p2p
for col in rows[0].keys():
    if "load" in col.lower() or "step" in col.lower() or "p2p" in col.lower() or "over" in col.lower() or "under" in col.lower():
        vals = sorted({r.get(col,"").strip() for r in rows if r.get(col,"").strip()})
        print(f"  {col!r}: {vals[:10]}")

print()
print("=== Unique Modes ===")
print(sorted({r.get("DCDC Efficiency Mode","").strip() for r in rows}))

print()
print("=== Unique Load step high values ===")
for col in ["Load step current high ", "Load step current high"]:
    vals = sorted({r.get(col,"").strip() for r in rows if r.get(col,"").strip()})
    if vals:
        print(f"  {col!r}: {vals}")

print()
print("=== Unique Load step low values ===")
for col in ["Load step current low ", "Load step current low"]:
    vals = sorted({r.get(col,"").strip() for r in rows if r.get(col,"").strip()})
    if vals:
        print(f"  {col!r}: {vals}")

print()
print("=== Sample row ===")
for k, v in rows[0].items():
    if not k.startswith("_"):
        print(f"  {k!r}: {v!r}")
