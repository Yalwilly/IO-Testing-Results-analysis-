from pmic_analysis.loader import load_pmic_data

data = load_pmic_data(r"Y:\2027 Projects\PeP2\SMV\EFV\SVT\TC Step\ww06'26 PeP_SVT_TC_EFV PMIC_unsorted cycle\Results")

# Static Load columns
load_rows = data.get_rows("Static_Load")
print("=== Static_Load columns ===")
print([k for k in load_rows[0].keys() if not k.startswith("_")])
print()

# Static Line columns + check Iout values to identify high/low current
line_rows = data.get_rows("Static_Line")
print("=== Static_Line columns ===")
print([k for k in line_rows[0].keys() if not k.startswith("_")])
print()

# Look at unique Iout values in Static_Line to understand high/low
iout_col = None
for candidate in ["Iout [A]", "IoutSMU", "Iout", "Load Current [A]"]:
    if any(r.get(candidate) for r in line_rows[:5]):
        iout_col = candidate
        break

print("Iout column found:", iout_col)
if iout_col:
    iouts = sorted({r.get(iout_col, "").strip() for r in line_rows if r.get(iout_col, "").strip()})
    print("Unique Iout values in Static_Line:", iouts[:30])
print()

# Print all cols with sample values
print("=== Static_Line sample row ===")
for k, v in line_rows[0].items():
    if not k.startswith("_"):
        print(f"  {k!r}: {v!r}")
