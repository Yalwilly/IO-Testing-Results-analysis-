import re
c = open('output_real/IO_Validation_Report.html', encoding='utf-8').read()

m = re.search(r'<div class="fg"><label>Temperature</label>(.*?)</div>', c)
print("TEMP BUTTONS:", m.group(1)[:400] if m else "NOT FOUND")
print()

series_temp = re.findall(r'data-temp="([^"]+)"', c)
print("data-temp count:", len(series_temp))
print("data-temp sample:", series_temp[:6])
print()

# find actual toggleFilter calls for temp
temp_onclick = [line.strip() for line in c.splitlines() if 'data-temp' in line and 'ftog' in line]
print("ftog temp lines:", temp_onclick[:3])
print()

# find applyFilters in JS
af_idx = c.find('function applyFilters')
print("applyFilters JS:", c[af_idx:af_idx+600])
