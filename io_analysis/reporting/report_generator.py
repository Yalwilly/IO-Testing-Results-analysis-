"""Report generator for IO Testing Results Analysis.

Generates a self-contained HTML report and a CSV summary.
Uses Python standard library only (no pptx/pandas).
"""

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from io_analysis.config import Config
from io_analysis.data.models import AnalysisResult

logger = logging.getLogger(__name__)


def _h(text: str) -> str:
    """Escape HTML special characters."""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# Per-parameter spec limit descriptions (keyed by full param name)
_SPEC_LABELS = {
    # GPIO_0 = PB16DSFS (16 DS steps, 1 mA each)
    "GPIO_0_IOL_A":  ("\u2014", "PB16 per DS 1\u201316 mA"),
    "GPIO_0_IOH_A":  ("\u2014", "PB16 per DS 1\u201316 mA"),
    "GPIO_0_R_Low":  ("\u2014", "Per DS 22.5\u2013320 \u03a9"),
    "GPIO_0_R_High": ("\u2014", "Per DS 22.5\u2013320 \u03a9"),
    # RF_KILLN = PB12DSFS (4 DS steps: 2, 4, 8, 12 mA)
    "RF_KILLN_IOL_A":  ("\u2014", "PB12 per DS 2,4,8,12 mA"),
    "RF_KILLN_IOH_A":  ("\u2014", "PB12 per DS 2,4,8,12 mA"),
    "RF_KILLN_R_Low":  ("\u2014", "Per DS 25\u2013110 \u03a9"),
    "RF_KILLN_R_High": ("\u2014", "Per DS 25\u2013110 \u03a9"),
}

def _spec_strs(param: str, s) -> tuple:
    """Return (smin, smax) display strings for a ParameterStats object."""
    if param in _SPEC_LABELS:
        return _SPEC_LABELS[param]
    smin  = f"{s.spec_min:.4g}"  if s.spec_min  is not None else "\u2014"
    smax_s = f"{s.spec_max:.4g}" if s.spec_max  is not None else "\u2014"
    return smin, smax_s


def generate_csv_report(result: AnalysisResult, config: Config) -> Path:
    """Generate a CSV summary report."""
    rows = []
    for (flow_name, param), stats in sorted(result.parameter_stats.items()):
        rows.append({
            "Flow": flow_name,
            "Parameter": param,
            "Unit": stats.unit,
            "Spec_Min": stats.spec_min if stats.spec_min is not None else "",
            "Spec_Max": stats.spec_max if stats.spec_max is not None else "",
            "Mean": f"{stats.mean:.6f}",
            "Std": f"{stats.std:.6f}",
            "Min": f"{stats.minimum:.6f}",
            "Max": f"{stats.maximum:.6f}",
            "Median": f"{stats.median:.6f}",
            "Sample_Count": stats.count,
            "Pass_Count": stats.pass_count,
            "Fail_Count": stats.fail_count,
            "Pass_Rate_%": f"{stats.pass_rate:.2f}",
            "Cpk": f"{stats.cpk:.4f}" if stats.cpk is not None else "",
            "Status": stats.status,
            "Comment": stats.generate_comment(config.cpk_threshold),
        })

    csv_path = config.output_path / "analysis_results.csv"
    if rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    logger.info(f"CSV report saved: {csv_path}")
    return csv_path


def _svg_embed(path: Path) -> str:
    """Return inline SVG content from a file."""
    if path.exists():
        txt = path.read_text(encoding="utf-8")
        if "<?xml" in txt:
            txt = txt[txt.index("<svg"):]
        return txt
    return f'<p style="color:red">Plot not found: {_h(path.name)}</p>'


def generate_html_report(result: AnalysisResult, plot_paths: dict,
                         config: Config, selected_tests=None) -> Path:
    """Generate a self-contained HTML report organised into 6 test sections.
    selected_tests: set of test_name strings to include, or None for all.
    """
    from io_analysis.plotting.plotter import (
        REPORT_IOS, TEST_SECTION_ORDER, SECTION_MEASUREMENTS
    )
    active_tests = selected_tests if selected_tests is not None else set(TEST_SECTION_ORDER)

    # ---- build helper maps ----
    # map parameter_name → test_name
    param_test_map: dict = {}
    for fd in result.flow_data.values():
        for row in fd.rows:
            p, t = row.get("Parameter"), row.get("Test_Name")
            if p and t and p not in param_test_map:
                param_test_map[p] = t

    # Collect all unique filter values from raw rows
    all_rows_flat = [r for fd in result.flow_data.values() for r in fd.rows]

    def _parse_cond(s):
        out = {}
        for tok in s.split():
            if "=" in tok:
                k, v = tok.split("=", 1)
                out[k] = v.rstrip("VC").rstrip("c")
        return out

    _viocores = sorted(
        {
            f"{c.get('VCORE','?')}/{c.get('VIO','?')}"
            for r in all_rows_flat
            for c in [_parse_cond(r.get("Test_Condition", ""))]
            if c.get("VIO") and c.get("VCORE")
        },
        key=lambda s: float(s.split("/")[0]) if s.split("/")[0].replace(".","").isdigit() else 0
    )
    _skews = sorted({str(r.get("Skew", "")) for r in all_rows_flat if r.get("Skew", "")})
    _ios   = list(REPORT_IOS)

    # group parameters (filtered to REPORT_IOS) per test section
    # Route parameters to sections using SECTION_MEASUREMENTS as the authority.
    # param_test_map (from raw Test_Name) is unreliable — VOH/VOL appear in the
    # IOH/IOL Max file, causing them to land in the wrong section.
    _suffix_to_section = {
        meas: test_name
        for test_name, meas_list in SECTION_MEASUREMENTS.items()
        for meas in meas_list
    }
    section_params: dict = {t: [] for t in TEST_SECTION_ORDER}
    for param in sorted(result.all_parameters):
        placed = False
        # Prefixed param (e.g. 'GPIO_0_VOH') — route by measurement suffix
        for io in REPORT_IOS:
            if param.startswith(io + "_"):
                suffix = param[len(io) + 1:]
                t = _suffix_to_section.get(suffix)
                if t and t in section_params and param not in section_params[t]:
                    section_params[t].append(param)
                    placed = True
                break
        if not placed:
            # Bare param (e.g. 'VOH') — match by name directly
            t = _suffix_to_section.get(param)
            if t and t in section_params and param not in section_params[t]:
                section_params[t].append(param)

    section_plots = plot_paths.get("section_plots", {})

    # ---- overall summary metrics (all data, not filtered) ----
    summary = result.overall_summary
    pass_rate = summary.get("overall_pass_rate", 0)
    rate_color = ("#27ae60" if pass_rate >= 99
                  else ("#e67e22" if pass_rate >= 95 else "#e74c3c"))

    # ---- HTML head ----
    html = []
    html.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{_h(config.report.title)}</title>
<style>
*{{box-sizing:border-box}}
body{{font-family:Arial,sans-serif;margin:0;padding:0;background:#f5f6fa;color:#333}}
.hdr{{background:#2c3e50;color:#fff;padding:18px 36px}}
.hdr h1{{margin:0 0 4px;font-size:24px}}
.hdr p{{margin:0;color:#bdc3c7;font-size:13px}}
.wrap{{max-width:1500px;margin:0 auto;padding:18px 36px}}
.cards{{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}}
.card{{background:#fff;border-radius:8px;padding:14px 18px;box-shadow:0 2px 6px rgba(0,0,0,.08);min-width:140px;flex:1}}
.card .val{{font-size:28px;font-weight:bold;margin:4px 0}}
.card .lbl{{font-size:11px;color:#7f8c8d;text-transform:uppercase;letter-spacing:.5px}}
.sec{{background:#fff;border-radius:8px;padding:18px;margin:16px 0;box-shadow:0 2px 6px rgba(0,0,0,.08)}}
.sec h2{{margin:0 0 4px;font-size:20px;color:#2c3e50;border-bottom:2px solid #ecf0f1;padding-bottom:6px}}
.sec h3{{margin:12px 0 6px;font-size:14px;color:#34495e;text-transform:uppercase;letter-spacing:.4px}}
.sec-desc{{font-size:12px;color:#7f8c8d;margin:0 0 12px}}
table{{border-collapse:collapse;width:100%;font-size:12px;margin-bottom:4px}}
th{{background:#2c3e50;color:#fff;padding:7px 9px;text-align:center;white-space:nowrap}}
td{{padding:5px 9px;border:1px solid #ecf0f1;text-align:center}}
tr:nth-child(even) td{{background:#f8f9fa}}
.io-hdr td{{background:#ecf0f1;font-weight:bold;text-align:left;color:#2c3e50;font-size:12px}}
.pass{{background:#d5f5e3!important;color:#1a7a3d;font-weight:bold}}
.fail{{background:#fadbd8!important;color:#a93226;font-weight:bold}}
.marginal{{background:#fdeacd!important;color:#b7460e;font-weight:bold}}
.plots-row{{display:grid;grid-template-columns:repeat(var(--plot-cols,3),1fr);gap:16px;margin-top:12px}}
.plot-box{{border:1px solid #ecf0f1;border-radius:6px;overflow-x:auto;background:#fff}}
.plot-box h4{{margin:0;padding:6px 10px;font-size:12px;background:#f8f9fa;border-bottom:1px solid #ecf0f1;color:#555}}
.plot-box svg,.plot-box object{{width:100%;height:auto;display:block}}
.size-btn{{padding:3px 9px;border:1.5px solid #bdc3c7;border-radius:6px;cursor:pointer;
  font-size:11px;font-weight:bold;background:#f8f9fa;color:#555;transition:all .12s;user-select:none;min-width:26px;text-align:center}}
.size-btn.active{{border-color:#2c3e50;background:#2c3e50;color:#fff}}
.size-btn:hover{{border-color:#2980b9;background:#eaf4fb}}
#legend-fs-val,#axis-fs-val{{font-size:11px;color:#555;min-width:30px;text-align:center}}
.tabs{{display:flex;gap:4px;margin-bottom:0;flex-wrap:wrap;border-bottom:2px solid #2c3e50;padding-bottom:0}}
.tabs button{{padding:8px 16px;border:1px solid #ddd;border-bottom:none;border-radius:6px 6px 0 0;
  cursor:pointer;background:#ecf0f1;font-size:13px;transition:all .15s}}
.tabs button.active{{background:#2c3e50;color:#fff;border-color:#2c3e50}}
.tab-content{{display:none;padding-top:0}}
.tab-content.active{{display:block}}
.badge{{padding:2px 8px;border-radius:10px;font-size:10px;font-weight:bold;margin-right:5px}}
.bp{{background:#2ecc71;color:#fff}}.bf{{background:#e74c3c;color:#fff}}.bw{{background:#e67e22;color:#fff}}
.filter-bar{{background:#fff;border-radius:8px;padding:12px 18px;margin:10px 0 4px;
  box-shadow:0 2px 6px rgba(0,0,0,.08);display:flex;flex-wrap:wrap;gap:10px;align-items:center;
  position:sticky;top:0;z-index:100;border:1px solid #dce1e7}}
.filter-bar .fg{{display:flex;flex-wrap:wrap;gap:6px;align-items:center}}
.filter-bar label{{font-size:11px;font-weight:bold;color:#7f8c8d;text-transform:uppercase;
  letter-spacing:.5px;margin-right:2px;white-space:nowrap}}
.ftog{{padding:3px 10px;border:1.5px solid #bdc3c7;border-radius:14px;cursor:pointer;
  font-size:11px;background:#f8f9fa;color:#555;transition:all .12s;user-select:none}}
.ftog.active{{border-color:#2c3e50;background:#2c3e50;color:#fff}}
.ftog:hover{{border-color:#2980b9;background:#eaf4fb}}
.filter-divider{{width:1px;height:24px;background:#dce1e7}}
@media print{{.tab-content{{display:block!important}}.filter-bar{{display:none}}}}
</style>
<script>
function showSec(secId,btn){{
  document.querySelectorAll('.tab-content').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.tabs button').forEach(b=>b.classList.remove('active'));
  document.getElementById(secId).classList.add('active');
  btn.classList.add('active');
}}

// ---- Filter logic ----
const _active = {{viocore:new Set(), skews:new Set()}};

function _initSets(){{
  document.querySelectorAll('.ftog[data-viocore]').forEach(b=>_active.viocore.add(b.dataset.viocore));
  document.querySelectorAll('.ftog[data-skew]').forEach(b=>_active.skews.add(b.dataset.skew));
}}

function toggleFilter(btn, kind){{
  const val = btn.dataset[kind];
  const set = kind==='viocore' ? _active.viocore : _active.skews;
  if(set.has(val)){{ set.delete(val); btn.classList.remove('active'); }}
  else{{ set.add(val); btn.classList.add('active'); }}
  applyFilters();
}}

function resetFilters(){{
  document.querySelectorAll('.ftog').forEach(b=>b.classList.add('active'));
  _initSets();
  applyFilters();
}}

function applyFilters(){{
  document.querySelectorAll('g.series, g.legend-item').forEach(g=>{{
    const vcAttr = g.dataset.viocore;
    const s = g.dataset.skew;
    // viocore: if the element has data-viocore, check it's active; otherwise pass through
    const vcOk = !vcAttr || _active.viocore.has(vcAttr);
    const sOk = !s || _active.skews.has(s);
    g.style.display = (vcOk && sOk) ? '' : 'none';
  }});
  // Stats table rows
  document.querySelectorAll('.stats-row').forEach(r=>{{
    const rowSkew = r.dataset.skew;
    const sOk = !rowSkew || _active.skews.has(rowSkew);
    r.style.display = sOk ? '' : 'none';
  }});
}}

document.addEventListener('DOMContentLoaded', ()=>{{ _initSets(); }});

// ---- Plot size controls ----
function setCols(n, btn){{
  document.documentElement.style.setProperty('--plot-cols', n);
  document.querySelectorAll('.size-btn[data-cols]').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  localStorage.setItem('plotCols', n);
}}
function _scaleSvgText(els, scale){{
  els.forEach(el=>{{
    if(!el.dataset.origFs) el.dataset.origFs = el.getAttribute('font-size') || '11';
    el.setAttribute('font-size', Math.round(parseFloat(el.dataset.origFs) * scale));
  }});
}}
function setLegendFs(v){{
  _scaleSvgText(document.querySelectorAll('.plot-box g.legend-item text'), parseFloat(v));
  document.getElementById('legend-fs-val').textContent = Math.round(v*100)+'%';
  localStorage.setItem('legendFs', v);
}}
function setAxisFs(v){{
  const els = [];
  document.querySelectorAll('.plot-box svg text').forEach(el=>{{
    if(!el.closest('g.legend-item')) els.push(el);
  }});
  _scaleSvgText(els, parseFloat(v));
  document.getElementById('axis-fs-val').textContent = Math.round(v*100)+'%';
  localStorage.setItem('axisFs', v);
}}
function setPlotH(v){{
  v = parseInt(v);
  const svgs = document.querySelectorAll('.plot-box svg');
  if(v <= 0){{
    svgs.forEach(s=>{{ s.style.width='100%'; s.style.height='auto'; }});
    document.getElementById('plot-h-val').textContent = 'Auto';
    localStorage.removeItem('plotH');
  }} else {{
    svgs.forEach(s=>{{ s.style.width=v+'px'; s.style.height='auto'; }});
    document.getElementById('plot-h-val').textContent = v+'px';
    localStorage.setItem('plotH', v);
  }}
}}
function restorePlotPrefs(){{
  const c = localStorage.getItem('plotCols');
  if(c){{
    document.documentElement.style.setProperty('--plot-cols', c);
    const btn = document.querySelector(`.size-btn[data-cols='${{c}}']`);
    if(btn){{ document.querySelectorAll('.size-btn[data-cols]').forEach(b=>b.classList.remove('active')); btn.classList.add('active'); }}
  }}
  const lfs = localStorage.getItem('legendFs');
  if(lfs){{ document.getElementById('legend-fs-slider').value = lfs; setLegendFs(parseFloat(lfs)); }}
  const afs = localStorage.getItem('axisFs');
  if(afs){{ document.getElementById('axis-fs-slider').value = afs; setAxisFs(parseFloat(afs)); }}
  const ph = localStorage.getItem('plotH');
  if(ph){{ document.getElementById('plot-h-slider').value = ph; setPlotH(parseInt(ph)); }}
  const sc = localStorage.getItem('specColor');
  if(sc){{ document.getElementById('spec-color-pick').value = sc; }}
  const sw = localStorage.getItem('specWidth');
  if(sw){{ document.getElementById('spec-w-slider').value = sw; document.getElementById('spec-w-val').textContent = sw+'px'; }}
  const sv = localStorage.getItem('specVisible');
  if(sv === '0'){{ const btn = document.getElementById('spec-toggle'); if(btn) toggleSpecLines(btn); }}
  applySpecStyle();
}}

// ---- Spec line controls ----
function applySpecStyle(){{
  const color = document.getElementById('spec-color-pick').value;
  const width = parseFloat(document.getElementById('spec-w-slider').value);
  document.querySelectorAll('g.spec-el line, g.spec-el path').forEach(el=>{{
    el.setAttribute('stroke', color);
    el.setAttribute('stroke-width', width);
  }});
  document.querySelectorAll('g.spec-el text').forEach(el=>{{
    el.setAttribute('fill', color);
  }});
  localStorage.setItem('specColor', color);
  localStorage.setItem('specWidth', width);
}}
function toggleSpecLines(btn){{
  const visible = btn.classList.contains('active');
  if(visible){{
    btn.classList.remove('active'); btn.textContent = '\u25cb Off';
    document.querySelectorAll('g.spec-el').forEach(g=>g.style.display='none');
    localStorage.setItem('specVisible','0');
  }} else {{
    btn.classList.add('active'); btn.textContent = '\u25cf On';
    document.querySelectorAll('g.spec-el').forEach(g=>g.style.display='');
    localStorage.setItem('specVisible','1');
    applySpecStyle();
  }}
}}
document.addEventListener('DOMContentLoaded', ()=>{{ _initSets(); restorePlotPrefs(); }});
</script>
</head>
<body>
<div class="hdr">
  <h1>{_h(config.report.title)}</h1>
  <p>{_h(config.report.subtitle)} &nbsp;|&nbsp; Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
     &nbsp;|&nbsp; {_h(config.report.author)}
     &nbsp;|&nbsp; IOs shown: {', '.join(REPORT_IOS)}</p>
</div>
<div class="wrap">
""")

    # ---- Filter bar ----
    viocore_btns = " ".join(
        f'<span class="ftog active" data-viocore="{_h(vc)}" '
        f'onclick="toggleFilter(this,\'viocore\')">{_h(vc)}</span>'
        for vc in _viocores
    )
    skew_btns = " ".join(
        f'<span class="ftog active" data-skew="{_h(s)}" '
        f'onclick="toggleFilter(this,\'skew\')">{_h(s)}</span>'
        for s in _skews
    )
    html.append(f'''<div class="filter-bar">
  <div class="fg"><label>Vin Core / GPIO (VCORE/VIO)</label>{viocore_btns}</div>
  <div class="filter-divider"></div>
  <div class="fg"><label>Skew</label>{skew_btns}</div>
  <div class="filter-divider"></div>
  <button class="ftog" onclick="resetFilters()" style="border-color:#27ae60;color:#27ae60">&#8635; Reset</button>
  <div class="filter-divider"></div>
  <div class="fg"><label>Columns</label>
    <span class="size-btn" data-cols="1" onclick="setCols(1,this)">1</span>
    <span class="size-btn" data-cols="2" onclick="setCols(2,this)">2</span>
    <span class="size-btn active" data-cols="3" onclick="setCols(3,this)">3</span>
    <span class="size-btn" data-cols="4" onclick="setCols(4,this)">4</span>
  </div>
  <div class="filter-divider"></div>
  <div class="fg"><label>Legend Font</label>
    <input id="legend-fs-slider" type="range" min="0.6" max="2.0" step="0.05" value="1"
      oninput="setLegendFs(this.value)" style="width:90px;cursor:pointer">
    <span id="legend-fs-val">100%</span>
  </div>
  <div class="filter-divider"></div>
  <div class="fg"><label>Axis Font</label>
    <input id="axis-fs-slider" type="range" min="0.6" max="2.0" step="0.05" value="1"
      oninput="setAxisFs(this.value)" style="width:90px;cursor:pointer">
    <span id="axis-fs-val">100%</span>
  </div>
  <div class="filter-divider"></div>
  <div class="fg"><label>Plot Size</label>
    <input id="plot-h-slider" type="range" min="0" max="3000" step="50" value="0"
      oninput="setPlotH(this.value)" style="width:100px;cursor:pointer">
    <span id="plot-h-val">Auto</span>
    <span class="size-btn" onclick="document.getElementById('plot-h-slider').value=0;setPlotH(0)" style="margin-left:4px">&#8634;</span>
  </div>
  <div class="filter-divider"></div>
  <div class="fg" style="align-items:center;gap:6px">
    <label>Spec Lines</label>
    <input type="color" id="spec-color-pick" value="#ff6d00" title="Spec line colour"
      oninput="applySpecStyle()" style="width:34px;height:26px;padding:1px;border:1.5px solid #bdc3c7;border-radius:5px;cursor:pointer">
    <input id="spec-w-slider" type="range" min="1" max="10" step="0.5" value="4"
      oninput="applySpecStyle();document.getElementById('spec-w-val').textContent=this.value+'px'"
      style="width:70px;cursor:pointer" title="Spec line width">
    <span id="spec-w-val" style="font-size:11px;color:#555;min-width:28px">4px</span>
    <span class="size-btn active" id="spec-toggle" onclick="toggleSpecLines(this)" title="Show/hide spec lines">&#x25cf; On</span>
  </div>
</div>'''
)

    # ---- Summary cards ----
    html.append('<div class="cards">')
    for lbl, val, color in [
        ("Overall Pass Rate", f"{pass_rate:.1f}%", rate_color),
        ("Total Measurements", str(summary.get("total_measurements", 0)), "#2c3e50"),
        ("Pass", str(summary.get("total_pass", 0)), "#27ae60"),
        ("Fail", str(summary.get("total_fail", 0)), "#c0392b"),
        ("Parameters", str(summary.get("total_parameters", 0)), "#2c3e50"),
        ("DUTs", str(max(len(fd.dut_ids) for fd in result.flow_data.values()) if result.flow_data else 0), "#2c3e50"),
    ]:
        html.append(
            f'<div class="card"><div class="lbl">{_h(lbl)}</div>'
            f'<div class="val" style="color:{color}">{_h(val)}</div></div>'
        )
    html.append("</div>")

    # ---- Section tabs ----
    active_section_order = [t for t in TEST_SECTION_ORDER if t in active_tests]
    html.append('<div class="tabs">')
    for i, test_name in enumerate(active_section_order):
        cls = "active" if i == 0 else ""
        sec_id = f"sec_{i}"
        html.append(
            f'<button class="{cls}" onclick="showSec(\'{sec_id}\',this)">'
            f'{_h(test_name)}</button>'
        )
    html.append("</div>")

    # ---- Section descriptions ----
    SECTION_DESC = {
        "IOH/IOL Max":
            "Measures IO output current drive capability and resistance vs. DS setting. "
            "IOL = sink current (output low); IOH = source current (output high). "
            "R_Low / R_High = output resistance derived from VOL / VOH under load.",
        "IO State After POR":
            "Verifies IO pin state and direction after the chip initialisation process. "
            "Shows Pull Mode, IO State (High/Low), and IO Direction (Output/Input) "
            "for each temperature and skew condition.",
        "Pull-up/Pull-down Resistance":
            "Measures internal pull-up and pull-down resistance values across all IO pins.",
        "VIH/VIL":
            "Input threshold test: VIH = minimum input high voltage; VIL = maximum input low voltage.",
        "VOH/VOL":
            "Output voltage under load: VOH = output high (must be ≥ spec min); "
            "VOL = output low (must be ≤ spec max).",
        "Rise/Fall Time":
            "Signal transition timing: measures edge rise/fall time in picoseconds.",
    }

    # ---- Render each section tab ----
    for i, test_name in enumerate(active_section_order):
        sec_id = f"sec_{i}"
        cls = "active" if i == 0 else ""
        params = section_params.get(test_name, [])
        html.append(f'<div id="{sec_id}" class="tab-content {cls}">')
        html.append(f'<div class="sec">')
        html.append(f'<h2>{_h(test_name)}</h2>')
        html.append(f'<p class="sec-desc">{_h(SECTION_DESC.get(test_name, ""))}</p>')

        if params:
            if test_name == "IO State After POR":
                # ---- POR state summary table ----
                html.append('<h3>IO State Summary</h3>')
                por_rows = [
                    r for r in all_rows_flat
                    if r.get("Test_Name") == "IO State After POR"
                    and r.get("IO_Name") in REPORT_IOS
                ]
                if por_rows:
                    html.append(
                        '<table><tr>'
                        '<th>IO Signal</th><th>Pull Mode</th>'
                        '<th>Temperature (°C)</th><th>Skew</th>'
                        '<th>IO State</th><th>IO Direction</th><th>DUT Count</th>'
                        '</tr>'
                    )
                    por_groups: dict = {}
                    for r in por_rows:
                        key = (
                            r.get("IO_Name", ""),
                            r.get("Pull_Mode", ""),
                            r.get("Temperature", ""),
                            r.get("Skew", ""),
                        )
                        if key not in por_groups:
                            por_groups[key] = {"states": [], "dirs": [], "duts": set()}
                        param_r = r.get("Parameter", "")
                        val = r.get("Value")
                        dut = r.get("DUT_ID", "")
                        if dut:
                            por_groups[key]["duts"].add(dut)
                        if param_r.endswith("_IO_State") and val is not None:
                            por_groups[key]["states"].append(val)
                        elif param_r.endswith("_IO_Direction") and val is not None:
                            por_groups[key]["dirs"].append(val)

                    def _val_summary(vals, map_fn):
                        if not vals:
                            return "—"
                        labels = [map_fn(v) for v in vals]
                        unique = sorted(set(labels))
                        if len(unique) == 1:
                            return unique[0]
                        return ", ".join(
                            f"{lbl}×{labels.count(lbl)}" for lbl in unique
                        )

                    io_order = {io: i for i, io in enumerate(REPORT_IOS)}
                    sorted_keys = sorted(
                        por_groups.keys(),
                        key=lambda k: (
                            io_order.get(k[0], 99),
                            k[1],
                            float(k[2]) if str(k[2]).replace(".", "").lstrip("-").isdigit() else 0,
                            k[3],
                        )
                    )
                    prev_io = None
                    for key in sorted_keys:
                        io, pull_mode, temp, skew = key
                        g = por_groups[key]
                        if io != prev_io:
                            html.append(
                                f'<tr class="io-hdr"><td colspan="7">{_h(io)}</td></tr>'
                            )
                            prev_io = io
                        state_txt = _val_summary(
                            g["states"], lambda v: "High" if v == 1.0 else "Low"
                        )
                        dir_txt = _val_summary(
                            g["dirs"], lambda v: "Output" if v == 1.0 else "Input"
                        )
                        n_duts = len(g["duts"])
                        temp_disp = f"{_h(temp)}°C" if temp else "—"
                        state_cls = "pass" if state_txt not in ("—",) else ""
                        html.append(
                            f'<tr>'
                            f'<td>{_h(io)}</td>'
                            f'<td>{_h(pull_mode) if pull_mode else "—"}</td>'
                            f'<td>{temp_disp}</td>'
                            f'<td>{_h(skew) if skew else "—"}</td>'
                            f'<td class="{state_cls}"><b>{_h(state_txt)}</b></td>'
                            f'<td><b>{_h(dir_txt)}</b></td>'
                            f'<td>{n_duts}</td>'
                            f'</tr>'
                        )
                    html.append("</table>")
                else:
                    html.append('<p style="color:#999">No IO State data available.</p>')
            else:
                # Stats table — one sub-header per IO
                html.append('<h3>Statistics</h3>')
                html.append(
                    '<table><tr>'
                    '<th>IO Signal</th><th>Measurement</th><th>Unit</th>'
                    '<th>Spec Min</th><th>Spec Max</th>'
                    '<th>Flow</th><th>Count</th><th>Pass%</th><th>Cpk</th>'
                    '<th>Mean</th><th>Std Dev</th><th>Min</th><th>Max</th>'
                    '<th>Status</th></tr>'
                )
                for io in REPORT_IOS:
                    io_params = [p for p in params if p.startswith(io + "_")]
                    if not io_params:
                        continue
                    html.append(
                        f'<tr class="io-hdr"><td colspan="14">{_h(io)}</td></tr>'
                    )
                    for param in sorted(io_params):
                        meas = param[len(io) + 1:] if param.startswith(io + "_") else param
                        any_row = False
                        for flow_name in result.all_flows:
                            key = (flow_name, param)
                            if key not in result.parameter_stats:
                                continue
                            s = result.parameter_stats[key]
                            any_row = True
                            status_cls = ("pass" if s.fail_count == 0
                                          else ("fail" if s.pass_count == 0 else "marginal"))
                            smin, smax_s = _spec_strs(param, s)
                            cpk_s = f"{s.cpk:.2f}" if s.cpk is not None else "—"
                            html.append(
                                f"<tr>"
                                f"<td>{_h(io)}</td>"
                                f"<td><b>{_h(meas)}</b></td>"
                                f"<td>{_h(s.unit)}</td>"
                                f"<td>{smin}</td><td>{smax_s}</td>"
                                f"<td>{_h(flow_name)}</td>"
                                f"<td>{s.count}</td>"
                                f"<td>{s.pass_rate:.1f}%</td>"
                                f"<td>{cpk_s}</td>"
                                f"<td>{s.mean:.4g}</td><td>{s.std:.3g}</td>"
                                f"<td>{s.minimum:.4g}</td><td>{s.maximum:.4g}</td>"
                                f'<td class="{status_cls}">{_h(s.status)}</td>'
                                f"</tr>"
                            )
                # Bare params (no IO prefix, e.g. 'VOH', 'VOL')
                bare_params = [
                    p for p in params
                    if not any(p.startswith(io + "_") for io in REPORT_IOS)
                ]
                if bare_params:
                    html.append(
                        '<tr class="io-hdr"><td colspan="14">All IOs (aggregated)</td></tr>'
                    )
                for param in sorted(bare_params):
                    meas = param
                    for flow_name in result.all_flows:
                        key = (flow_name, param)
                        if key not in result.parameter_stats:
                            continue
                        s = result.parameter_stats[key]
                        status_cls = ("pass" if s.fail_count == 0
                                      else ("fail" if s.pass_count == 0 else "marginal"))
                        smin, smax_s = _spec_strs(param, s)
                        cpk_s = f"{s.cpk:.2f}" if s.cpk is not None else "—"
                        html.append(
                            f"<tr>"
                            f"<td>—</td>"
                            f"<td><b>{_h(meas)}</b></td>"
                            f"<td>{_h(s.unit)}</td>"
                            f"<td>{smin}</td><td>{smax_s}</td>"
                            f"<td>{_h(flow_name)}</td>"
                            f"<td>{s.count}</td>"
                            f"<td>{s.pass_rate:.1f}%</td>"
                            f"<td>{cpk_s}</td>"
                            f"<td>{s.mean:.4g}</td><td>{s.std:.3g}</td>"
                            f"<td>{s.minimum:.4g}</td><td>{s.maximum:.4g}</td>"
                            f'<td class="{status_cls}">{_h(s.status)}</td>'
                            f"</tr>"
                        )
                html.append("</table>")
        else:
            html.append('<p style="color:#999">No data for this test section.</p>')

        # Section charts
        sec_chart_map = section_plots.get(test_name, {})
        chart_paths = [(m, p) for m, p in sec_chart_map.items() if p is not None]
        if chart_paths:
            html.append('<h3>Measurement Charts</h3>')
            html.append('<p style="font-size:11px;color:#7f8c8d">'
                        'For tests with Drive Strength (DS): X-axis = DS setting, '
                        'lines = Vin Core/GPIO (VCORE/VIO) × Skew combinations (worst-case chip shown in legend). '
                        'For other tests: X-axis = voltage corner conditions. '
                        'Dashed red lines = spec limits.</p>')
            html.append('<div class="plots-row">')
            for meas, path in chart_paths:
                html.append(f'<div class="plot-box"><h4>{_h(meas.replace("_", " "))} Chart</h4>')
                html.append(_svg_embed(path))
                html.append("</div>")
            html.append("</div>")

        html.append("</div></div>")  # close .sec and .tab-content

    html.append("</div></body></html>")

    html_path = config.output_path / "IO_Validation_Report.html"
    html_path.write_text("\n".join(html), encoding="utf-8")
    logger.info(f"HTML report saved: {html_path}")
    return html_path
    summary = result.overall_summary
    pass_rate = summary.get("overall_pass_rate", 0)
    rate_color = "#27ae60" if pass_rate >= 99 else ("#e67e22" if pass_rate >= 95 else "#e74c3c")

    html = []
    html.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{_h(config.report.title)}</title>
<style>
body{{font-family:Arial,sans-serif;margin:0;padding:0;background:#f5f6fa;color:#333}}
.hdr{{background:#2c3e50;color:#fff;padding:18px 36px}}
.hdr h1{{margin:0 0 4px;font-size:24px}}
.hdr p{{margin:0;color:#bdc3c7;font-size:13px}}
.wrap{{max-width:1400px;margin:0 auto;padding:18px 36px}}
.cards{{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}}
.card{{background:#fff;border-radius:8px;padding:14px 18px;box-shadow:0 2px 6px rgba(0,0,0,.08);min-width:140px;flex:1}}
.card .val{{font-size:30px;font-weight:bold;margin:4px 0}}
.card .lbl{{font-size:11px;color:#7f8c8d;text-transform:uppercase;letter-spacing:.5px}}
.sec{{background:#fff;border-radius:8px;padding:18px;margin:16px 0;box-shadow:0 2px 6px rgba(0,0,0,.08)}}
.sec h2{{margin:0 0 12px;font-size:19px;color:#2c3e50;border-bottom:2px solid #ecf0f1;padding-bottom:6px}}
.sec h3{{margin:12px 0 8px;font-size:15px;color:#34495e}}
table{{border-collapse:collapse;width:100%;font-size:12px}}
th{{background:#2c3e50;color:#fff;padding:7px 9px;text-align:center}}
td{{padding:5px 9px;border:1px solid #ecf0f1;text-align:center}}
tr:nth-child(even) td{{background:#f8f9fa}}
.pass{{background:#d5f5e3!important;color:#1a7a3d;font-weight:bold}}
.fail{{background:#fadbd8!important;color:#a93226;font-weight:bold}}
.marginal{{background:#fdeacd!important;color:#b7460e;font-weight:bold}}
.plots{{display:flex;flex-wrap:wrap;gap:16px}}
.plot{{flex:1;min-width:380px;border:1px solid #ecf0f1;border-radius:4px;overflow:hidden}}
.plot svg{{width:100%;height:auto}}
ul.findings{{list-style:none;padding:0;margin:0}}
ul.findings li{{padding:5px 0;border-bottom:1px solid #ecf0f1;font-size:13px}}
ul.findings li:last-child{{border-bottom:none}}
.badge{{padding:1px 7px;border-radius:10px;font-size:10px;font-weight:bold;margin-right:5px}}
.bp{{background:#2ecc71;color:#fff}}
.bf{{background:#e74c3c;color:#fff}}
.bw{{background:#e67e22;color:#fff}}
.tabs{{display:flex;gap:4px;margin-bottom:12px;flex-wrap:wrap}}
.tabs button{{padding:6px 14px;border:1px solid #ddd;border-radius:4px;cursor:pointer;background:#ecf0f1;font-size:12px}}
.tabs button.active{{background:#2c3e50;color:#fff;border-color:#2c3e50}}
.tab{{display:none}}
.tab.active{{display:block}}
@media print{{.tab{{display:block!important}}}}
</style>
<script>
function showTab(id,btn){{
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.tabs button').forEach(b=>b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}}
</script>
</head>
<body>
<div class="hdr">
  <h1>{_h(config.report.title)}</h1>
  <p>{_h(config.report.subtitle)} &nbsp;|&nbsp; Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} &nbsp;|&nbsp; {_h(config.report.author)}</p>
</div>
<div class="wrap">
""")

    # Summary cards
    html.append('<div class="cards">')
    cards = [
        ("Overall Pass Rate", f"{pass_rate:.1f}%", rate_color),
        ("Total Measurements", str(summary.get("total_measurements", 0)), "#2c3e50"),
        ("Pass", str(summary.get("total_pass", 0)), "#27ae60"),
        ("Fail", str(summary.get("total_fail", 0)), "#c0392b"),
        ("Parameters", str(summary.get("total_parameters", 0)), "#2c3e50"),
        ("Flows", str(summary.get("total_flows", 0)), "#2c3e50"),
        ("All-Pass Params", str(summary.get("parameters_all_pass", 0)), "#27ae60"),
        ("Params w/ Fails", str(summary.get("parameters_with_fails", 0)), "#c0392b"),
    ]
    for lbl, val, color in cards:
        html.append(
            f'<div class="card"><div class="lbl">{_h(lbl)}</div>'
            f'<div class="val" style="color:{color}">{_h(val)}</div></div>'
        )
    html.append("</div>")

    # Key findings
    html.append('<div class="sec"><h2>Key Findings</h2><ul class="findings">')
    for comment in result.comments[:15]:
        if "ALL PASS" in comment or "Both flows PASS" in comment:
            badge = '<span class="badge bp">PASS</span>'
        elif "FAIL" in comment and "Cross-Flow" not in comment:
            badge = '<span class="badge bf">FAIL</span>'
        elif "[Cross-Flow]" in comment:
            badge = '<span class="badge bw">CROSS-FLOW</span>'
        else:
            badge = ""
        html.append(f"<li>{badge}{_h(comment)}</li>")
    html.append("</ul></div>")

    # Results tables per flow
    html.append('<div class="sec"><h2>Detailed Results</h2>')
    if len(result.all_flows) > 1:
        html.append('<div class="tabs">')
        for i, fn in enumerate(result.all_flows):
            cls = "active" if i == 0 else ""
            html.append(
                f'<button class="{cls}" onclick="showTab(\'tab_{_h(fn)}\',this)">'
                f'{_h(fn)}</button>'
            )
        html.append("</div>")

    for i, fn in enumerate(result.all_flows):
        cls = "active" if i == 0 else ""
        html.append(f'<div id="tab_{_h(fn)}" class="tab {cls}">')
        html.append(f"<h3>{_h(fn)}</h3>")
        html.append(
            "<table><tr>"
            "<th>Parameter</th><th>Unit</th><th>Spec Min</th><th>Spec Max</th>"
            "<th>Mean</th><th>Std</th><th>Min</th><th>Max</th>"
            "<th>Pass</th><th>Fail</th><th>Pass%</th><th>Cpk</th><th>Status</th>"
            "</tr>"
        )
        for param in result.all_parameters:
            key = (fn, param)
            if key not in result.parameter_stats:
                continue
            s = result.parameter_stats[key]
            cls2 = "pass" if s.fail_count == 0 else ("fail" if s.pass_count == 0 else "marginal")
            smin, smax_s = _spec_strs(s.parameter, s)
            cpk_s = f"{s.cpk:.3f}" if s.cpk is not None else "\u2014"
            html.append(
                f"<tr>"
                f"<td><b>{_h(s.parameter)}</b></td><td>{_h(s.unit)}</td>"
                f"<td>{smin}</td><td>{smax_s}</td>"
                f"<td>{s.mean:.5g}</td><td>{s.std:.4g}</td>"
                f"<td>{s.minimum:.5g}</td><td>{s.maximum:.5g}</td>"
                f'<td style="color:#1a7a3d">{s.pass_count}</td>'
                f'<td style="color:#a93226">{s.fail_count}</td>'
                f"<td>{s.pass_rate:.1f}%</td><td>{cpk_s}</td>"
                f'<td class="{cls2}">{_h(s.status)}</td>'
                f"</tr>"
            )
        html.append("</table></div>")
    html.append("</div>")

    # Plot sections
    def _plots_section(title, paths):
        if not paths:
            return
        html.append(f'<div class="sec"><h2>{_h(title)}</h2><div class="plots">')
        for p in paths:
            html.append(f'<div class="plot">{_svg_embed(p)}</div>')
        html.append("</div></div>")

    _plots_section("Pass/Fail Summary", plot_paths.get("pass_fail_summary", []))
    _plots_section("Parameter vs Spec Limits", plot_paths.get("parameter_vs_spec", []))
    _plots_section("Value Distributions", plot_paths.get("distributions", []))
    _plots_section("Cross-Flow Comparison", plot_paths.get("cross_flow", []))
    _plots_section("Process Capability (Cpk)", plot_paths.get("cpk_summary", []))
    _plots_section("Per-DUT Results", plot_paths.get("scatter_dut", []))

    html.append("</div></body></html>")

    html_path = config.output_path / "IO_Validation_Report.html"
    html_path.write_text("\n".join(html), encoding="utf-8")
    logger.info(f"HTML report saved: {html_path}")
    return html_path


def generate_report(result: AnalysisResult, plot_paths: dict,
                    config: Config, selected_tests=None,
                    generate_pptx: bool = True) -> dict:
    """Generate all report outputs (CSV + HTML + optional PPTX).
    selected_tests: set of test_name strings to include, or None for all.
    """
    reports = {}
    reports["csv"]  = generate_csv_report(result, config)
    reports["html"] = generate_html_report(
        result, plot_paths, config, selected_tests=selected_tests
    )
    if generate_pptx:
        try:
            from io_analysis.reporting.pptx_generator import generate_pptx_report
            reports["pptx"] = generate_pptx_report(
                result, plot_paths, config, selected_tests=selected_tests
            )
        except Exception as exc:
            logger.warning(f"PPTX generation skipped: {exc}")
            reports["pptx"] = None
    else:
        reports["pptx"] = None
    logger.info(f"Reports generated in {config.output_path}")
    return reports

