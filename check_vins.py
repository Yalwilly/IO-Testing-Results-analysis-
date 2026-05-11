from pmic_analysis.loader import load_pmic_data
from pathlib import Path
from collections import defaultdict

data = load_pmic_data(Path(r"Y:\2027 Projects\PeP2\SMV\EFV\SVT\TC Step\ww06'26 PeP_SVT_TC_EFV PMIC_unsorted cycle\Results"))
all_rows = [r for v in data.rows_by_test.values() for r in v]

vins = sorted(
    set(r.get("Vin","").strip() for r in all_rows if r.get("Vin","").strip()),
    key=lambda x: (float(x) if x.replace(".","").lstrip("-").isdigit() else 0)
)
print("All unique Vin setpoints:", vins)

per_test = defaultdict(set)
for r in all_rows:
    v = r.get("Vin","").strip()
    if v:
        per_test[r.get("_test_type","")].add(v)

for t, vs in sorted(per_test.items()):
    print(f"  {t}: {sorted(vs, key=lambda x: float(x) if x.replace('.','').lstrip('-').isdigit() else 0)}")
