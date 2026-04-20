from io_analysis.data.loader import load_all_flows
from io_analysis.config import Config
from io_analysis.plotting.plotter import _parse_condition
from pathlib import Path

config = Config(
    data_path=Path("Y:/2027 Projects/PeP2/SMV/EFV/SVT/TC Step/ww09'26 PeP_SVT_TC_EFV IO_cross Skew Materials cycle/Results"),
    output_path=Path("output_real")
)
flows = load_all_flows(config)
rows = [r for fd in flows.values() for r in fd.rows]

combos = sorted({
    (_parse_condition(r.get("Test_Condition","")).get("VIO","?"),
     _parse_condition(r.get("Test_Condition","")).get("VCORE","?"))
    for r in rows if r.get("Test_Condition","")
})
print("VIO/VCORE combos:", combos)

rise = [r for r in rows if "Rise" in str(r.get("Parameter",""))]
fall = [r for r in rows if "Fall" in str(r.get("Parameter",""))]
print("Rise rows:", len(rise))
print("Fall rows:", len(fall))
if rise:
    print("Rise sample:", rise[0])
