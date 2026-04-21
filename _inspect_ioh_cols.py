"""Inspect IOH/IOL xlsx column headers and sample data rows."""
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

found = False
for flow in ["Flow1", "Flow2"]:
    flow_dir = BASE / flow
    if not flow_dir.exists():
        print(f"Directory not found: {flow_dir}")
        continue
    for f in sorted(flow_dir.glob("*.xlsx")):
        if "iohmax" not in f.name.lower() and "iohmaxiolmax" not in f.name.lower():
            continue
        print(f"\n{'='*70}")
        print(f"FILE: {f.name}")
        with zipfile.ZipFile(str(f)) as zf:
            ss = read_ss(zf)
            sheet = "xl/worksheets/sheet2.xml"
            if sheet not in zf.namelist():
                print("  No sheet2 found")
                continue
            root = ET.parse(zf.open(sheet)).getroot()
            all_rows = root.findall(f".//{{{NS}}}row")
            hdr = {}
            for c in all_rows[0].findall(f"{{{NS}}}c"):
                col = "".join(ch for ch in c.get("r", "") if ch.isalpha())
                t = c.get("t", "")
                v = c.find(f"{{{NS}}}v")
                val = ""
                if v is not None and v.text:
                    if t == "s":
                        val = ss[int(v.text)]
                    else:
                        val = v.text
                if val:
                    hdr[col] = val.lower().strip()

            print("  ALL COLUMNS:")
            for col, name in hdr.items():
                print(f"    {col}: {name}")

            ds_col = next((c for c, n in hdr.items() if n == "ds"), None)
            res_cols = [(c, n) for c, n in hdr.items() if "resist" in n or "spec" in n]
            print(f"\n  DS col: {ds_col}")
            print(f"  Resistance/spec cols: {res_cols}")

            # Sample first 5 data rows - show DS, resistance, spec
            print("\n  Sample rows (DS, resistance, spec columns):")
            for row in all_rows[1:6]:
                rv = {}
                for ce in row.findall(f"{{{NS}}}c"):
                    col = "".join(ch for ch in ce.get("r", "") if ch.isalpha())
                    t = ce.get("t", "")
                    v = ce.find(f"{{{NS}}}v")
                    val = ""
                    if v is not None and v.text:
                        if t == "s":
                            val = ss[int(v.text)]
                        else:
                            val = v.text
                    if col in hdr:
                        rv[hdr[col]] = val
                filtered = {k: v for k, v in rv.items()
                            if "resist" in k or k == "ds" or "spec" in k or "io name" in k}
                print(f"    {filtered}")
        found = True
        if found:
            break
    if found:
        break
