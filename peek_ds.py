"""Deep-dive into pivot table structure for all xlsx files."""
import zipfile, xml.etree.ElementTree as ET, pathlib

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
BASE = pathlib.Path(
    r"Y:\2027 Projects\PeP2\SMV\EFV\SVT\TC Step"
    r"\ww09'26 PeP_SVT_TC_EFV IO_cross Skew Materials cycle\Results"
)

def read_ss(zf):
    ss = []
    if "xl/sharedStrings.xml" in zf.namelist():
        root = ET.parse(zf.open("xl/sharedStrings.xml")).getroot()
        for si in root.findall(f"{{{NS}}}si"):
            t = si.find(f"{{{NS}}}t")
            ss.append((t.text or "") if t is not None else
                      "".join(x.text or "" for x in si.findall(f".//{{{NS}}}t")))
    return ss

def cell_val(cell, ss):
    t = cell.get("t", "")
    if t == "e": return "#ERR"
    v = cell.find(f"{{{NS}}}v")
    if v is None or not v.text: return ""
    if t == "s": idx = int(v.text); return ss[idx] if idx < len(ss) else ""
    return v.text

for flow in ["Flow1", "Flow2"]:
    for f in sorted((BASE / flow).glob("*.xlsx")):
        print(f"\n{'='*70}")
        print(f"FILE: {f.name}")
        with zipfile.ZipFile(str(f)) as zf:
            ss = read_ss(zf)
            sheet = "xl/worksheets/sheet2.xml"  # 1d raw data
            if sheet in zf.namelist():
                root = ET.parse(zf.open(sheet)).getroot()
                all_rows = root.findall(f".//{{{NS}}}row")
                # Get header
                hdr = {}
                for c in all_rows[0].findall(f"{{{NS}}}c"):
                    col = "".join(ch for ch in c.get("r","") if ch.isalpha())
                    val = cell_val(c, ss)
                    if val and col:
                        hdr[col] = val.lower().strip()
                # Find ds column
                ds_col = next((c for c, n in hdr.items() if n == "ds"), None)
                io_col = next((c for c, n in hdr.items() if n == "io name"), None)
                temp_col = next((c for c, n in hdr.items() if n == "temperature"), None)
                vin_gpio_col = next((c for c, n in hdr.items() if n == "vin gpio"), None)
                vin_core_col = next((c for c, n in hdr.items() if n == "vin core"), None)
                skew_col = next((c for c,n in hdr.items() if n == "* skew materials"), None)
                print(f"  Columns: ds={ds_col}, io={io_col}, temp={temp_col}, vio={vin_gpio_col}, vcore={vin_core_col}, skew={skew_col}")
                if ds_col:
                    ds_vals = set()
                    for row in all_rows[1:50]:
                        rv = {("".join(c for c in ce.get("r","") if c.isalpha())): cell_val(ce, ss)
                              for ce in row.findall(f"{{{NS}}}c")}
                        d = rv.get(ds_col,"")
                        if d: ds_vals.add(d)
                    print(f"  DS values (sample): {sorted(ds_vals)}")
                    # Show a few sample rows
                    print(f"  Sample rows [io, ds, temp, vio, vcore, skew]:")
                    seen = set()
                    for row in all_rows[1:]:
                        rv = {("".join(c for c in ce.get("r","") if c.isalpha())): cell_val(ce, ss)
                              for ce in row.findall(f"{{{NS}}}c")}
                        key = (rv.get(io_col,""), rv.get(ds_col,""), rv.get(temp_col,""), rv.get(vin_gpio_col,""))
                        if key not in seen and rv.get(io_col,"") in ("GPIO_0","RF_KILLN"):
                            seen.add(key)
                            print(f"    io={rv.get(io_col,'')} ds={rv.get(ds_col,'')} T={rv.get(temp_col,'')} VIO={rv.get(vin_gpio_col,'')} VC={rv.get(vin_core_col,'')} skew={rv.get(skew_col,'')}")
                        if len(seen) >= 8: break
                else:
                    print("  No 'ds' column in this test.")
