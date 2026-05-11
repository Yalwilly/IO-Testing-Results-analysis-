from pmic_analysis.loader import load_pmic_data

data = load_pmic_data(r"Y:\2027 Projects\PeP2\SMV\EFV\SVT\TC Step\ww06'26 PeP_SVT_TC_EFV PMIC_unsorted cycle\Results")
line_rows = data.get_rows("Static_Line")

# Check all potentially-useful columns for current level
print("=== Unique IoutSMU values in Static_Line ===")
print(sorted({r.get("IoutSMU","").strip() for r in line_rows if r.get("IoutSMU","").strip()}))

print("\n=== Unique Iout [A] values in Static_Line ===")
iout_vals = sorted({r.get("Iout [A]","").strip() for r in line_rows if r.get("Iout [A]","").strip()})
print(iout_vals[:20], "(total:", len(iout_vals), ")")

print("\n=== Unique Vin values in Static_Line (setpoint) ===")
vin_set = sorted({r.get("Vin","").strip() for r in line_rows if r.get("Vin","").strip()})
print(vin_set[:10])

print("\n=== Unique 'Iout' setpoint col? ===")
# check if there's an Iout setpoint (not measured)
for col in ["Iout", "IoutSetpoint", "IStep", "IStepPwm", "IStepPfm"]:
    vals = sorted({r.get(col,"").strip() for r in line_rows if r.get(col,"").strip()})
    if vals:
        print(f"  {col!r}: {vals}")

print("\n=== Unique USE SMU AS LOAD ===")
print(sorted({r.get("USE SMU AS LOAD","").strip() for r in line_rows}))

print("\n=== Check files for Static_Line rows ===")
from collections import Counter
file_iouts = {}
for r in line_rows:
    fn = r.get("_source_file","?")
    iout = r.get("IoutSMU","?").strip()
    if fn not in file_iouts:
        file_iouts[fn] = set()
    file_iouts[fn].add(iout)
for fn, iouts in sorted(file_iouts.items()):
    print(f"  {fn[-50:]}: IoutSMU={sorted(iouts)[:5]}")
