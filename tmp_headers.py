import zipfile, xml.etree.ElementTree as ET, pathlib

data_root = pathlib.Path(r"Y:\2027 Projects\PeP2\SMV\EFV\SVT\TC Step\ww09'26 PeP_SVT_TC_EFV IO_cross Skew Materials cycle\Results\Flow1")
files = list(data_root.glob('iohmaxiolmax*.xlsx'))
print('Found:', [f.name for f in files])
if not files:
    raise SystemExit("not found")
f = files[0]
NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
with zipfile.ZipFile(f) as zf:
    tree = ET.parse(zf.open('xl/sharedStrings.xml'))
    ss = [n.text or '' for n in tree.getroot().iter(f'{{{NS}}}t')]
    # try sheet named "1d" or sheet1
    sheet_names = [n for n in zf.namelist() if n.startswith('xl/worksheets/')]
    print("Sheets:", sheet_names)
    sheet = next((s for s in sheet_names if '1d' in s or 'sheet1' in s.lower()), sheet_names[0])
    tree2 = ET.parse(zf.open(sheet))
    root2 = tree2.getroot()
    rows = root2.findall(f'.//{{{NS}}}row')
    header_row = rows[0]
    headers = []
    for c in header_row.findall(f'{{{NS}}}c'):
        v = c.find(f'{{{NS}}}v')
        t = c.get('t', '')
        if v is not None:
            if t == 's':
                try: headers.append(ss[int(v.text)])
                except: headers.append(v.text or '')
            else:
                headers.append(v.text or '')
    for i, h in enumerate(headers):
        print(f'  col {i+1:3d}: {repr(h)}')
