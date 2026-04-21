import sys, pathlib
sys.path.insert(0, '.')
from io_analysis.data.loader import load_single_file

p = pathlib.Path("Y:/2027 Projects/PeP2/SMV/EFV/SVT/TC Step/ww09'26 PeP_SVT_TC_EFV IO_cross Skew Materials cycle/Results/Flow1")
files = list(p.glob("iohmaxiolmax*.xlsx"))
print("File:", files[0].name if files else "NOT FOUND")
if not files: raise SystemExit

rows = load_single_file(files[0])
# Find first IOL_A row
for r in rows:
    if r.get("Parameter","").endswith("_IOL_A"):
        print("IOL_A row keys:", list(r.keys()))
        print("IOL_A row:", {k:v for k,v in r.items()})
        break
# Find first R_Low row
for r in rows:
    if r.get("Parameter","").endswith("_R_Low"):
        print("R_Low row keys:", list(r.keys()))
        print("R_Low row:", {k:v for k,v in r.items()})
        break
