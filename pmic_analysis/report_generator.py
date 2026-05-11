"""
PMIC DC2DC Validation — HTML Report Generator.
Produces a self-contained HTML file similar in style to the IO report.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

REG_LABELS = {
    "DC2DC_ANA": "Analog DC2DC",
    "DC2DC_DIG": "Digital DC2DC",
}

TEST_ORDER = [
    "Static_Load",
    "Static_Line",
    "Quiescence",
    "PowerOn",
    "Transient",
    "VoltageTransitions",
    "AutoMode",
]

TEST_LABELS = {
    "Static_Load":        "Static — Load Reg.",
    "Static_Line":        "Static — Line Reg.",
    "Quiescence":         "Quiescence & Shutdown",
    "PowerOn":            "Power On",
    "Transient":          "Transient Response",
    "VoltageTransitions": "Voltage Transitions",
    "AutoMode":           "Auto Mode",
}

TEST_DESCS = {
    "Static_Load":
        "Output current (Iload) sweep at fixed Vin. "
        "Shows converter efficiency vs. load current for each operating point.",
    "Static_Line":
        "Input voltage (Vin) sweep at light load. "
        "Shows output regulation across the Vin range.",
    "Quiescence":
        "Quiescence & shutdown current measured for each Temperature × Vin × Power-Mode. "
        "Delta = I_enable − I_disable.",
    "PowerOn":
        "Output voltage rise time (slew rate) vs. Vin for each temperature condition.",
    "Transient":
        "Output voltage variation (peak-to-peak) in response to a load step. "
        "↑ = load applied (risk of undershoot), ↓ = load removed (risk of overshoot).",
    "VoltageTransitions":
        "Maximum and minimum Vout reached during a programmed voltage transition, "
        "grouped by power mode and Vin.",
    "AutoMode":
        "Auto-mode (PFM↔PWM auto-switching): efficiency and minimum output voltage "
        "across the load-current range.",
}


def _h(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _safe_attr(s) -> str:
    """Make a value safe for use in an HTML attribute (no quotes/spaces)."""
    return str(s).replace('"', "").replace("'", "").replace(" ", "_")


def _svg_inline(path: Path) -> str:
    if path and path.exists():
        txt = path.read_text(encoding="utf-8")
        if "<?xml" in txt:
            txt = txt[txt.index("<svg"):]
        return txt
    return f'<p style="color:#c0392b">Plot not found: {_h(path.name if path else "?")}</p>'


def _fmt(v, decimals=4) -> str:
    if v is None:
        return "—"
    try:
        fmt = f"{float(v):.{decimals}f}"
        return fmt
    except Exception:
        return str(v)


# ── Quiescence table ───────────────────────────────────────────────────────

def _quiescence_html(q_data: dict) -> str:
    """Render quiescence data as HTML tables per regulator."""
    if not q_data:
        return "<p>No quiescence data found.</p>"

    html = []
    for reg in sorted(q_data.keys()):
        rows = q_data[reg]
        if not rows:
            continue
        reg_lbl = REG_LABELS.get(reg, reg)
        html.append(f'<h3>{_h(reg_lbl)}</h3>')

        # Sort rows by (temp, vin, mode)
        def _sort_key(r):
            try:
                t = float(r["temp"])
            except Exception:
                t = 0.0
            try:
                v = float(r["vin"])
            except Exception:
                v = 0.0
            return (t, v, r["mode"], r["chip"])

        rows_sorted = sorted(rows, key=_sort_key)

        html.append('<div style="overflow-x:auto"><table>')
        html.append(
            '<tr><th>Temp [°C]</th><th>Vin [V]</th><th>Mode</th>'
            '<th>Chip</th><th>Iin Disable [A]</th>'
            '<th>Iin Enable [A]</th><th>Delta [A]</th><th>Status</th></tr>'
        )
        for r in rows_sorted:
            status = r.get("status", "OK").upper()
            cls = "pass" if status == "OK" else "fail"
            vin_attr  = _safe_attr(r["vin"])
            chip_attr = _safe_attr(r["chip"])
            temp_attr = _safe_attr(r["temp"])
            mode_attr = _safe_attr(r["mode"])
            is_ref    = r.get("is_ref", False)
            row_style = ' style="opacity:0.72;font-style:italic"' if is_ref else ''
            ref_cls   = ' ref-overlay' if is_ref else ''
            html.append(
                f'<tr class="q-row{ref_cls}" data-vin="{vin_attr}" data-chip="{chip_attr}"'
                f' data-temp="{temp_attr}" data-mode="{mode_attr}"{row_style}>'
                f'<td>{_h(r["temp"])}</td>'
                f'<td>{_h(r["vin"])}</td>'
                f'<td>{_h(r["mode"])}</td>'
                f'<td>{_h(r["chip"])}</td>'
                f'<td>{_fmt(r["iin_disable"], 6)}</td>'
                f'<td>{_fmt(r["iin_enable"], 6)}</td>'
                f'<td>{_fmt(r["delta"], 6)}</td>'
                f'<td class="{cls}">{_h(status)}</td>'
                f'</tr>'
            )
        html.append("</table></div>")

    return "\n".join(html)


# ── Summary tab ────────────────────────────────────────────────────────────

def _summary_html(data) -> str:
    """Build a summary tab with key statistics for each test type."""
    import statistics as _stats

    def _fv(v, decimals=3):
        if v is None: return "—"
        try:    return f"{float(v):.{decimals}f}"
        except: return str(v)

    def _stat_row(label, values, unit="", decimals=3, good_hi=True):
        """Return an HTML <tr> with min/mean/max and a coloured bar."""
        vals = [v for v in values if v is not None]
        if not vals:
            return f'<tr><td>{_h(label)}</td><td colspan="4" style="color:#aaa">no data</td></tr>'
        mn, mx, mu = min(vals), max(vals), _stats.mean(vals)
        rng = mx - mn or 1
        bar_w = int(min(100, max(2, (mx - mn) / max(abs(mu), 1e-9) * 30)))
        colour = "#2ecc71" if good_hi else "#e74c3c"
        cell = (f'<td style="white-space:nowrap">'
                f'<span style="display:inline-block;width:{bar_w}px;height:8px;'
                f'background:{colour};border-radius:3px;margin-right:6px;vertical-align:middle"></span>'
                f'{_fv(mu, decimals)} {_h(unit)}</td>')
        return (f'<tr><td style="padding-right:12px">{_h(label)}</td>'
                f'<td style="color:#3498db">{_fv(mn, decimals)} {_h(unit)}</td>'
                f'{cell}'
                f'<td style="color:#e74c3c">{_fv(mx, decimals)} {_h(unit)}</td>'
                f'<td style="color:#7f8c8d;font-size:10px">n={len(vals)}</td></tr>')

    def _table(rows_html):
        hdr = ('<tr style="background:#2c3e50;color:#fff">'
               '<th style="text-align:left;padding:5px 10px">Metric</th>'
               '<th style="padding:5px 10px">Min</th>'
               '<th style="padding:5px 10px">Mean</th>'
               '<th style="padding:5px 10px">Max</th>'
               '<th style="padding:5px 10px">N</th></tr>')
        return (f'<div style="overflow-x:auto"><table style="border-collapse:collapse;'
                f'width:100%;margin-bottom:18px;font-size:12px">'
                f'{hdr}{"".join(rows_html)}</table></div>')

    def _section(title, rows_html):
        if not rows_html:
            return ""
        return (f'<div style="margin-bottom:24px">'
                f'<h3 style="margin:0 0 8px;font-size:14px;color:#2c3e50">{_h(title)}</h3>'
                f'{_table(rows_html)}</div>')

    def _flt(r, col):
        try:    return float(r.get(col, "").strip())
        except: return None

    html_parts = []

    # ── Static Load ──────────────────────────────────────────────────────
    load_rows = data.get_rows("Static_Load")
    if load_rows:
        for reg in sorted({r.get("Regulator Name","") for r in load_rows}):
            rr = [r for r in load_rows if r.get("Regulator Name","") == reg]
            eff_vals  = [_flt(r,"Efficiency [Pout/Pin %]") for r in rr]
            vout_vals = [_flt(r,"Vout [V]") for r in rr]
            iout_vals = [_flt(r,"Iout [A]") for r in rr]
            reg_lbl = REG_LABELS.get(reg, reg)
            rows = [
                _stat_row("Efficiency",          eff_vals,  "%",  1, good_hi=True),
                _stat_row("Measured Vout",        vout_vals, "V",  4, good_hi=True),
                _stat_row("Measured Iout",        iout_vals, "A",  3, good_hi=True),
            ]
            html_parts.append(_section(f"Static Load — {reg_lbl}", rows))

    # ── Static Line ──────────────────────────────────────────────────────
    line_rows = data.get_rows("Static_Line")
    if line_rows:
        for reg in sorted({r.get("Regulator Name","") for r in line_rows}):
            rr = [r for r in line_rows if r.get("Regulator Name","") == reg]
            vout_vals = [_flt(r,"Vout [V]") for r in rr]
            eff_vals  = [_flt(r,"Efficiency [Pout/Pin %]") for r in rr]
            reg_lbl = REG_LABELS.get(reg, reg)
            rows = [
                _stat_row("Measured Vout",  vout_vals, "V", 4, good_hi=True),
                _stat_row("Line Efficiency",eff_vals,  "%", 1, good_hi=True),
            ]
            html_parts.append(_section(f"Static Line — {reg_lbl}", rows))

    # ── Quiescence ───────────────────────────────────────────────────────
    q_rows = data.get_rows("Quiescence", ok_only=False)
    if q_rows:
        dis_vals   = [_flt(r,"IinDisable [A]") for r in q_rows]
        en_vals    = [_flt(r,"IinEnable [A]")  for r in q_rows]
        delta_vals = [_flt(r,"Delta [A]")       for r in q_rows]
        rows = [
            _stat_row("Iin Disable", dis_vals,   "A", 6, good_hi=False),
            _stat_row("Iin Enable",  en_vals,     "A", 6, good_hi=False),
            _stat_row("Delta",       delta_vals,  "A", 6, good_hi=False),
        ]
        html_parts.append(_section("Quiescence & Shutdown", rows))

    # ── Power On ─────────────────────────────────────────────────────────
    pon_rows = data.get_rows("PowerOn")
    if pon_rows:
        rise_vals     = [_flt(r,"RiseTime [uS]") for r in pon_rows]
        overshoot_v   = [_flt(r,"Overshoot [V]") for r in pon_rows]
        rows = [
            _stat_row("Rise Time",   rise_vals,   "µs", 2, good_hi=False),
            _stat_row("Overshoot",   overshoot_v, "V",  4, good_hi=False),
        ]
        html_parts.append(_section("Power On", rows))

    # ── Transient ────────────────────────────────────────────────────────
    tr_rows = data.get_rows("Transient")
    if tr_rows:
        for reg in sorted({r.get("Regulator Name","") for r in tr_rows}):
            for mode in sorted({r.get("DCDC Efficiency Mode","") for r in tr_rows
                                if r.get("Regulator Name","") == reg}):
                rr = [r for r in tr_rows
                      if r.get("Regulator Name","") == reg
                      and r.get("DCDC Efficiency Mode","") == mode]
                def _mv(r, col, sign):
                    vn = _flt(r,"Vout"); m = _flt(r,col)
                    if vn is None or m is None: return None
                    v = sign*(m-vn)*1000; return max(v,0)
                over_mv  = [_mv(r,"Vout Max",+1) for r in rr]
                under_mv = [_mv(r,"Vout Min",-1) for r in rr]
                reg_lbl  = REG_LABELS.get(reg, reg)
                rows = [
                    _stat_row("Overshoot",  over_mv,  "mV", 1, good_hi=False),
                    _stat_row("Undershoot", under_mv, "mV", 1, good_hi=False),
                ]
                html_parts.append(_section(f"Transient — {reg_lbl} [{mode}]", rows))

    # ── AutoMode ─────────────────────────────────────────────────────────
    am_rows = data.get_rows("AutoMode")
    if am_rows:
        for reg in sorted({r.get("Regulator Name","") for r in am_rows}):
            rr = [r for r in am_rows if r.get("Regulator Name","") == reg]
            eff_vals  = [_flt(r,"Efficiency [Pout/Pin %]") for r in rr]
            vmin_vals = [_flt(r,"Vout Min ") for r in rr]
            reg_lbl = REG_LABELS.get(reg, reg)
            rows = [
                _stat_row("Efficiency",  eff_vals,  "%", 1, good_hi=True),
                _stat_row("Vout Min",    vmin_vals, "V", 4, good_hi=True),
            ]
            html_parts.append(_section(f"Auto Mode — {reg_lbl}", rows))

    if not html_parts:
        return "<p>No data available for summary.</p>"
    return "\n".join(html_parts)


# ── Section renderers ──────────────────────────────────────────────────────

def _plot_section(test_type: str, plot_paths: dict) -> str:
    """Render SVG plots for one test type, split by regulator."""
    plots_by_reg = plot_paths.get(test_type, {})
    if not plots_by_reg:
        return '<p style="color:#888">No plots generated for this section.</p>'

    html = []
    for reg in sorted(plots_by_reg.keys()):
        paths = plots_by_reg[reg]
        if not paths:
            continue
        reg_lbl = REG_LABELS.get(reg, reg)
        html.append(f'<h3 class="reg-hdr">{_h(reg_lbl)}</h3>')
        html.append('<div class="plots-row">')
        for p in paths:
            html.append(
                f'<div class="plot-box">'
                f'<h4>{_h(p.stem)}</h4>'
                f'{_svg_inline(p)}'
                f'</div>'
            )
        html.append("</div>")
    return "\n".join(html)


# ── CSS ────────────────────────────────────────────────────────────────────

_CSS = """
*{box-sizing:border-box}
body{font-family:Arial,sans-serif;margin:0;padding:0;background:#f5f6fa;color:#333}
.hdr{background:#1a252f;color:#fff;padding:18px 36px}
.hdr h1{margin:0 0 4px;font-size:24px}
.hdr p{margin:0;color:#bdc3c7;font-size:13px}
.wrap{max-width:1600px;margin:0 auto;padding:18px 36px}
.cards{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}
.card{background:#fff;border-radius:8px;padding:14px 18px;
      box-shadow:0 2px 6px rgba(0,0,0,.08);min-width:140px;flex:1}
.card .val{font-size:28px;font-weight:bold;margin:4px 0}
.card .lbl{font-size:11px;color:#7f8c8d;text-transform:uppercase;letter-spacing:.5px}
.sec{background:#fff;border-radius:8px;padding:18px;margin:16px 0;
     box-shadow:0 2px 6px rgba(0,0,0,.08)}
.sec h2{margin:0 0 4px;font-size:20px;color:#2c3e50;
        border-bottom:2px solid #ecf0f1;padding-bottom:6px}
.sec h3{margin:12px 0 6px;font-size:14px;color:#34495e;
        text-transform:uppercase;letter-spacing:.4px}
.sec-desc{font-size:12px;color:#7f8c8d;margin:0 0 12px}
.reg-hdr{background:#ecf0f1;padding:5px 10px;border-radius:4px;
         color:#2c3e50;font-size:13px;margin:14px 0 6px}
table{border-collapse:collapse;width:100%;font-size:12px;margin-bottom:4px}
th{background:#2c3e50;color:#fff;padding:7px 9px;text-align:center;white-space:nowrap}
td{padding:5px 9px;border:1px solid #ecf0f1;text-align:center}
tr:nth-child(even) td{background:#f8f9fa}
.pass{background:#d5f5e3!important;color:#1a7a3d;font-weight:bold}
.fail{background:#fadbd8!important;color:#a93226;font-weight:bold}
.plots-row{display:grid;
           grid-template-columns:repeat(var(--plot-cols,2),1fr);
           gap:16px;margin-top:12px}
.plot-box{border:1px solid #ecf0f1;border-radius:6px;overflow-x:auto;background:#fff}
.plot-box h4{margin:0;padding:6px 10px;font-size:11px;background:#f8f9fa;
             border-bottom:1px solid #ecf0f1;color:#555}
.plot-box svg{width:100%;height:auto;display:block}
.tabs{display:flex;gap:4px;flex-wrap:wrap;border-bottom:2px solid #2c3e50;padding-bottom:0}
.tabs button{padding:8px 14px;border:1px solid #ddd;border-bottom:none;
             border-radius:6px 6px 0 0;cursor:pointer;background:#ecf0f1;
             font-size:12px;transition:all .15s}
.tabs button.active{background:#2c3e50;color:#fff;border-color:#2c3e50}
.tab-content{display:none;padding-top:8px}
.tab-content.active{display:block}
.filter-bar{background:#fff;border-radius:8px;padding:12px 18px;margin:10px 0 4px;
            box-shadow:0 2px 6px rgba(0,0,0,.08);display:flex;flex-wrap:wrap;
            gap:10px;align-items:center;position:sticky;top:0;z-index:100;
            border:1px solid #dce1e7}
.filter-bar .fg{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.filter-bar label{font-size:11px;font-weight:bold;color:#7f8c8d;text-transform:uppercase;
                  letter-spacing:.5px;margin-right:2px;white-space:nowrap}
.ftog{padding:3px 10px;border:1.5px solid #bdc3c7;border-radius:14px;cursor:pointer;
      font-size:11px;background:#f8f9fa;color:#555;transition:all .12s;user-select:none}
.ftog.active{border-color:#2c3e50;background:#2c3e50;color:#fff}
.ftog:hover{border-color:#2980b9;background:#eaf4fb}
.filter-divider{width:1px;height:24px;background:#dce1e7}
.size-btn{padding:3px 9px;border:1.5px solid #bdc3c7;border-radius:6px;cursor:pointer;
          font-size:11px;font-weight:bold;background:#f8f9fa;color:#555;
          transition:all .12s;user-select:none;min-width:26px;text-align:center}
.size-btn.active{border-color:#2c3e50;background:#2c3e50;color:#fff}
@media print{.tab-content{display:block!important}.filter-bar{display:none}}
"""


# ── JavaScript ──────────────────────────────────────────────────────────────

def _build_js(chips, temps, modes, vins) -> str:
    chips_js  = ", ".join(f'"{c}"' for c in chips)
    temps_js  = ", ".join(f'"{t}"' for t in temps)
    modes_js  = ", ".join(f'"{m}"' for m in modes)
    vins_js   = ", ".join(f'"{v}"' for v in vins)
    return f"""
function showTab(id,btn){{
  document.querySelectorAll('.tab-content').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.tabs button').forEach(b=>b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}}

const _active = {{
  chips: new Set([{chips_js}]),
  temps: new Set([{temps_js}]),
  modes: new Set([{modes_js}]),
  vins:  new Set([{vins_js}]),
}};

function _initSets(){{
  document.querySelectorAll('.ftog[data-chip]').forEach(b=>_active.chips.add(b.dataset.chip));
  document.querySelectorAll('.ftog[data-temp]').forEach(b=>_active.temps.add(b.dataset.temp));
  document.querySelectorAll('.ftog[data-mode]').forEach(b=>_active.modes.add(b.dataset.mode));
  document.querySelectorAll('.ftog[data-vin]').forEach(b=>_active.vins.add(b.dataset.vin));
}}

function toggleFilter(btn,kind){{
  const val = btn.dataset[kind];
  const set = kind==='chip' ? _active.chips
            : kind==='temp' ? _active.temps
            : kind==='vin'  ? _active.vins
            : _active.modes;
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
  var refBtn = document.querySelector('[data-ref-on]');
  var refOn  = !refBtn || refBtn.dataset.refOn === 'true';

  document.querySelectorAll('g.pmic-series, g.legend-item').forEach(g=>{{
    const isRef = g.classList.contains('ref-overlay');
    // If ref toggle is OFF, hide all ref series regardless of other filters
    if (isRef && !refOn) {{ g.style.display = 'none'; return; }}

    const ch  = g.dataset.chip;
    const t   = g.dataset.temp;
    const m   = g.dataset.mode;
    const vi  = g.dataset.vin;
    const chOk  = !ch || _active.chips.has(ch);
    const tOk   = !t  || _active.temps.has(t);
    const mOk   = !m  || _active.modes.has(m);
    const vinOk = !vi || _active.vins.has(vi);
    g.style.display = (chOk && tOk && mOk && vinOk) ? '' : 'none';
  }});
  // Quiescence table rows
  document.querySelectorAll('tr.q-row').forEach(tr=>{{
    const isRef = tr.classList.contains('ref-overlay');
    if (isRef && !refOn) {{ tr.style.display = 'none'; return; }}

    const ch  = tr.dataset.chip;
    const t   = tr.dataset.temp;
    const m   = tr.dataset.mode;
    const vi  = tr.dataset.vin;
    const chOk  = !ch || _active.chips.has(ch);
    const tOk   = !t  || _active.temps.has(t);
    const mOk   = !m  || _active.modes.has(m);
    const vinOk = !vi || _active.vins.has(vi);
    tr.style.display = (chOk && tOk && mOk && vinOk) ? '' : 'none';
  }});
}}

function setCols(n,btn){{
  document.documentElement.style.setProperty('--plot-cols',n);
  document.querySelectorAll('.size-btn[data-cols]').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
}}

document.addEventListener('DOMContentLoaded',()=>{{ _initSets(); }});

// ── Real-time cursor ────────────────────────────────────────────────────
var _cursorEnabled = false;

function toggleCursor(btn){{
  _cursorEnabled = !_cursorEnabled;
  btn.classList.toggle('active', _cursorEnabled);
  btn.textContent = _cursorEnabled ? '\u271c Cursor: ON' : '\u271c Cursor: OFF';
  if(!_cursorEnabled){{
    document.querySelectorAll('.cursor-layer').forEach(function(cl){{ cl.style.display='none'; }});
    document.querySelectorAll('.cursor-overlay').forEach(function(ov){{ ov.style.cursor='default'; }});
  }} else {{
    document.querySelectorAll('.cursor-overlay').forEach(function(ov){{ ov.style.cursor='crosshair'; }});
  }}
}}

(function(){{
  var _activeSvg = null;

  function _svgPt(svgEl, e){{
    var pt = svgEl.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    return pt.matrixTransform(svgEl.getScreenCTM().inverse());
  }}

  function _fmtVal(v){{
    if(v === undefined || v === null || isNaN(v)) return '?';
    var a = Math.abs(v);
    if(a === 0) return '0';
    if(a >= 1000 || (a < 0.001)) return v.toExponential(3);
    if(a < 0.1)  return v.toPrecision(3);
    if(a < 10)   return v.toPrecision(4);
    return v.toPrecision(5);
  }}

  function _hideCursor(){{
    if(_activeSvg){{
      var cl = _activeSvg.querySelector('.cursor-layer');
      if(cl) cl.style.display = 'none';
      _activeSvg = null;
    }}
  }}

  document.addEventListener('mousemove', function(e){{
    if(!_cursorEnabled) return;
    var el = e.target;
    if(!el || !el.classList || !el.classList.contains('cursor-overlay')){{
      _hideCursor();
      return;
    }}
    var svg = el.closest ? el.closest('svg') : null;
    if(!svg){{
      var p = el.parentNode;
      while(p && p.tagName && p.tagName.toLowerCase() !== 'svg') p = p.parentNode;
      svg = p;
    }}
    if(!svg) return;

    if(_activeSvg && _activeSvg !== svg) _hideCursor();
    _activeSvg = svg;

    var cl = svg.querySelector('.cursor-layer');
    if(!cl) return;
    cl.style.display = '';

    var pt = _svgPt(svg, e);
    var mx = pt.x, my = pt.y;

    var xmin = +el.dataset.xmin, xmax = +el.dataset.xmax;
    var ymin = +el.dataset.ymin, ymax = +el.dataset.ymax;
    var pl   = +el.dataset.pl,   pr   = +el.dataset.pr;
    var ptt  = +el.dataset.pt,   pb   = +el.dataset.pb;

    var dx = xmin + (mx - pl) / (pr - pl) * (xmax - xmin);
    var dy = ymax - (my - ptt) / (pb - ptt) * (ymax - ymin);

    cl.querySelector('.cur-v').setAttribute('x1', mx);
    cl.querySelector('.cur-v').setAttribute('x2', mx);
    cl.querySelector('.cur-h').setAttribute('y1', my);
    cl.querySelector('.cur-h').setAttribute('y2', my);

    var tipW = 150, tipH = 46;
    var tx = mx + 14, ty = my - tipH - 10;
    var svgW = +svg.getAttribute('width') || 1400;
    if(tx + tipW > svgW - 5) tx = mx - tipW - 14;
    if(ty < ptt + 2) ty = my + 10;

    var bg = cl.querySelector('.cur-tip-bg');
    bg.setAttribute('x', tx); bg.setAttribute('y', ty);
    bg.setAttribute('width', tipW); bg.setAttribute('height', tipH);

    var tx1 = cl.querySelector('.cur-tip-x');
    tx1.setAttribute('x', tx + 8); tx1.setAttribute('y', ty + 17);
    tx1.textContent = 'X: ' + _fmtVal(dx);

    var ty1 = cl.querySelector('.cur-tip-y');
    ty1.setAttribute('x', tx + 8); ty1.setAttribute('y', ty + 35);
    ty1.textContent = 'Y: ' + _fmtVal(dy);
  }}, false);

  document.addEventListener('mouseleave', _hideCursor, true);
}})();

// ── Reference overlay toggle ─────────────────────────────────────────────
function toggleRefOverlay(btn) {{
  var on = btn.dataset.refOn === 'true';
  on = !on;
  btn.dataset.refOn = on ? 'true' : 'false';
  btn.textContent = on ? '\u25cf Ref: ON' : '\u25cf Ref: OFF';
  btn.classList.toggle('active', on);
  btn.style.background = on ? '#8e44ad' : '#f8f9fa';
  btn.style.color = on ? '#fff' : '#555';
  btn.style.borderColor = on ? '#7d3c98' : '#bdc3c7';
  // Re-run full filter logic so ref visibility respects current chip/temp/mode/vin
  applyFilters();
}}
"""


# ── Main report function ────────────────────────────────────────────────────

def generate_pmic_report(data, plot_paths: dict,
                         output_path: Path,
                         title: str = "PMIC DC2DC Validation Results",
                         subtitle: str = "Analog & Digital Converter Characterisation",
                         author: str = "Power Validation Team",
                         has_ref: bool = False,
                         ref_label: str = "REF",
                         ref_data=None) -> Path:
    """Generate a self-contained HTML report for PMIC data.
    has_ref: when True, the Ref ON/OFF toggle is shown in the filter bar.
    ref_label: label used to describe the reference dataset (shown in toggle).
    ref_data: PMICData object for the reference dataset (used to add ref chip IDs to chip filter).
    """
    output_path = Path(output_path)
    output_path.mkdir(parents=True, exist_ok=True)
    report_file = output_path / "PMIC_Validation_Report.html"

    chips  = data.chip_ids
    temps  = data.temps
    modes  = data.modes
    regs   = data.regulators
    now    = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Chip IDs that exist only in reference data (not in primary)
    ref_only_chips = []
    if ref_data is not None:
        ref_only_chips = [c for c in ref_data.chip_ids if c not in chips]

    ref_divider_html = ""
    if has_ref:
        ref_divider_html = (
            f'<div class="filter-divider"></div>\n'
            f'  <div class="fg">\n'
            f'    <span class="ftog active" data-ref-on="true"\n'
            f'          style="background:#8e44ad;color:#fff;border-color:#7d3c98"\n'
            f'          onclick="toggleRefOverlay(this)">&#9679; {_h(ref_label)}: ON</span>\n'
            f'  </div>'
        )

    # Vin setpoints — exclude Static_Line sweep values
    vins = sorted(
        {r.get("Vin", "").strip()
         for tt, rows in data.rows_by_test.items()
         if tt not in ("Static_Line", "SetupVerifier")
         for r in rows
         if r.get("Vin", "").strip()},
        key=lambda x: float(x) if x.replace(".", "").lstrip("-").isdigit() else 0
    )

    # ── summary card values ────────────────────────────────────────────────
    total_rows = sum(len(v) for v in data.rows_by_test.values())
    n_tests    = len([k for k in data.rows_by_test if k != "Unknown"])

    # ── filter bar ─────────────────────────────────────────────────────────
    chip_btns = " ".join(
        f'<span class="ftog active" data-chip="{_h(c)}" '
        f'onclick="toggleFilter(this,\'chip\')">{_h(c)}</span>'
        for c in chips)
    # Ref-only chips rendered with a purple tint (&#9679; dot prefix) to distinguish them
    if ref_only_chips:
        ref_chip_btns = " ".join(
            f'<span class="ftog active" data-chip="{_h(c)}" '
            f'style="border-color:#8e44ad;" '
            f'onclick="toggleFilter(this,\'chip\')">&#9679;&nbsp;{_h(c)}</span>'
            for c in ref_only_chips)
        chip_btns = chip_btns + (" " if chip_btns else "") + ref_chip_btns
    temp_btns = " ".join(
        f'<span class="ftog active" data-temp="{_h(t)}" '
        f'onclick="toggleFilter(this,\'temp\')">{_h(t)}°C</span>'
        for t in temps)
    mode_btns = " ".join(
        f'<span class="ftog active" data-mode="{_h(m)}" '
        f'onclick="toggleFilter(this,\'mode\')">{_h(m)}</span>'
        for m in modes)
    vin_btns = " ".join(
        f'<span class="ftog active" data-vin="{_safe_attr(v)}" '
        f'onclick="toggleFilter(this,\'vin\')">{_h(v)} V</span>'
        for v in vins)

    filter_bar = f"""
<div class="filter-bar">
  <div class="fg"><label>Chip</label>{chip_btns}</div>
  <div class="filter-divider"></div>
  <div class="fg"><label>Temperature</label>{temp_btns}</div>
  <div class="filter-divider"></div>
  <div class="fg"><label>Power Mode</label>{mode_btns}</div>
  <div class="filter-divider"></div>
  <div class="fg"><label>Vin</label>{vin_btns}</div>
  <div class="filter-divider"></div>
  <div class="fg">
    <span class="ftog" style="background:#2980b9;color:#fff;border-color:#2471a3"
          onclick="toggleCursor(this)">&#10012; Cursor: OFF</span>
  </div>
  <div class="filter-divider"></div>
  <div class="fg">
    <span class="ftog" style="background:#e74c3c;color:#fff;border-color:#c0392b"
          onclick="resetFilters()">↺ Reset</span>
  </div>
  <div class="filter-divider"></div>
  <div class="fg">
    <label>Columns</label>
    <span class="size-btn active" data-cols="2" onclick="setCols(2,this)">2</span>
    <span class="size-btn" data-cols="1" onclick="setCols(1,this)">1</span>
    <span class="size-btn" data-cols="3" onclick="setCols(3,this)">3</span>
  </div>
  {ref_divider_html}
</div>"""

    # ── tabs and tab contents ───────────────────────────────────────────────
    tab_btns     = []
    tab_contents = []

    # Summary tab — always first
    tab_btns.append(
        '<button class="active" onclick="showTab(\'tab_summary\',this)">'
        '&#x2211; Summary</button>')
    tab_contents.append(
        '<div class="tab-content active" id="tab_summary">'
        '<p class="sec-desc">Key statistics (min / mean / max) across all chips, '
        'temperatures and Vin corners. Outliers are excluded from plots but still '
        'counted in raw statistics here.</p>'
        + _summary_html(data)
        + '</div>')

    for i, tt in enumerate(TEST_ORDER):
        if tt not in data.rows_by_test and tt not in plot_paths:
            continue
        tab_id = f"tab_{tt.lower().replace(' ', '_')}"
        active_cls = ""   # Summary tab is always the active default
        lbl = TEST_LABELS.get(tt, tt)
        n_rows = len(data.rows_by_test.get(tt, []))
        tab_btns.append(
            f'<button class="{active_cls.strip()}" onclick="showTab(\'{tab_id}\',this)">'
            f'{_h(lbl)} <span style="font-size:10px;opacity:.7">({n_rows})</span>'
            f'</button>')

        # Build tab body
        body_parts = [f'<p class="sec-desc">{_h(TEST_DESCS.get(tt, ""))}</p>']

        if tt == "Quiescence":
            q_data = plot_paths.get("Quiescence", {})
            body_parts.append(_quiescence_html(q_data))
        else:
            body_parts.append(_plot_section(tt, plot_paths))

        tab_contents.append(
            f'<div class="tab-content{active_cls}" id="{tab_id}">'
            + "\n".join(body_parts)
            + "</div>")


    tabs_html = '<div class="tabs">' + "".join(tab_btns) + "</div>"

    # ── assemble HTML ───────────────────────────────────────────────────────
    reg_list_str = ", ".join(REG_LABELS.get(r, r) for r in regs)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{_h(title)}</title>
<style>
{_CSS}
</style>
<script>
{_build_js(chips, temps, modes, vins)}
</script>
</head>
<body>
<div class="hdr">
  <h1>{_h(title)}</h1>
  <p>{_h(subtitle)} &nbsp;|&nbsp; {_h(author)} &nbsp;|&nbsp; Generated: {now}</p>
</div>
<div class="wrap">

  <!-- Summary cards -->
  <div class="cards">
    <div class="card"><div class="lbl">Chips Tested</div>
      <div class="val">{len(chips)}</div>
      <div style="font-size:11px;color:#7f8c8d">{", ".join(_h(c) for c in chips)}</div></div>
    <div class="card"><div class="lbl">Converters</div>
      <div class="val">{len(regs)}</div>
      <div style="font-size:11px;color:#7f8c8d">{_h(reg_list_str)}</div></div>
    <div class="card"><div class="lbl">Temperatures</div>
      <div class="val">{len(temps)}</div>
      <div style="font-size:11px;color:#7f8c8d">{", ".join(_h(t)+"°C" for t in temps)}</div></div>
    <div class="card"><div class="lbl">Power Modes</div>
      <div class="val">{len(modes)}</div>
      <div style="font-size:11px;color:#7f8c8d">{", ".join(_h(m) for m in modes)}</div></div>
    <div class="card"><div class="lbl">Total Rows</div>
      <div class="val">{total_rows:,}</div>
      <div style="font-size:11px;color:#7f8c8d">{n_tests} test types</div></div>
  </div>

  <!-- Filter bar -->
  {filter_bar}

  <!-- Test sections -->
  <div class="sec">
    {tabs_html}
    {"".join(tab_contents)}
  </div>

</div>
</body>
</html>
"""

    report_file.write_text(html, encoding="utf-8")
    logger.info("PMIC report saved: %s", report_file)
    return report_file


# ── Reference overlay injection ────────────────────────────────────────────

def inject_reference_overlays(report_path: "Path", ref_path: "Path") -> "Path":
    """
    Post-process a generated PMIC report HTML by injecting reference SVG series
    from a second report (ref_path) as styled overlaid series (dashed hollow).
    Matched by SVG <title> text. Reveals the Ref filter button in the report.
    Returns the patched report_path.
    """
    import re as _re

    report_path = Path(report_path)
    ref_path    = Path(ref_path)

    if not ref_path.exists():
        logger.warning("Reference report not found: %s", ref_path)
        return report_path

    report_html = report_path.read_text(encoding="utf-8")
    ref_html    = ref_path.read_text(encoding="utf-8")

    # ── Extract reference pmic-series groups, keyed by SVG title ─────────
    def _hollow_circle(m):
        tag = m.group(0)
        fill_m = _re.search(r'\bfill="([^"]+)"', tag)
        if not fill_m:
            return tag
        fill_color = fill_m.group(1)
        if fill_color.lower() in ("white", "#fff", "#ffffff", "none"):
            return tag
        # fill → none; stroke → fill_color
        tag = tag.replace(f'fill="{fill_color}"', 'fill="none"', 1)
        tag = _re.sub(r'\bstroke="[^"]+"', f'stroke="{fill_color}" stroke-width="2.2"', tag)
        if "stroke=" not in tag:
            tag = tag.replace("<circle", f'<circle stroke="{fill_color}" stroke-width="2.2"', 1)
        # enlarge radius
        r_m = _re.search(r'\br="([\d.]+)"', tag)
        if r_m:
            try:
                new_r = round(float(r_m.group(1)) + 1.5, 1)
                tag = tag[: r_m.start()] + f'r="{new_r}"' + tag[r_m.end():]
            except Exception:
                pass
        return tag

    ref_series: dict = {}          # title → list[group_html]
    pos = 0
    while True:
        svg_start = ref_html.find("<svg", pos)
        if svg_start == -1:
            break
        svg_end = ref_html.find("</svg>", svg_start)
        if svg_end == -1:
            break
        svg_end += 6
        svg_text = ref_html[svg_start:svg_end]
        pos = svg_end

        tm = _re.search(r"<title[^>]*>(.*?)</title>", svg_text, _re.DOTALL)
        if not tm:
            continue
        title = tm.group(1).strip()

        groups = []
        gpos = 0
        while True:
            gs = svg_text.find("<g ", gpos)
            if gs == -1:
                break
            tag_end = svg_text.find(">", gs)
            if tag_end == -1:
                break
            opening_tag = svg_text[gs: tag_end + 1]
            if "pmic-series" not in opening_tag:
                gpos = gs + 1
                continue
            ge = svg_text.find("</g>", tag_end)
            if ge == -1:
                break
            ge += 4
            group_html = svg_text[gs:ge]
            gpos = ge

            # Transform: dashed lines
            group_html = _re.sub(r"<path\b", '<path stroke-dasharray="7,4"', group_html)
            # Hollow circles
            group_html = _re.sub(r"<circle\b[^>]*/?>", _hollow_circle, group_html)
            # Add ref-overlay class and opacity
            group_html = _re.sub(
                r'class="([^"]*pmic-series[^"]*)"',
                r'class="\1 ref-overlay"',
                group_html, count=1,
            )
            group_html = group_html.replace("<g ", '<g style="opacity:0.75" ', 1)
            groups.append(group_html)

        if groups:
            ref_series[title] = groups

    if not ref_series:
        logger.warning("No pmic-series groups found in reference report: %s", ref_path)
        return report_path

    # ── Inject into report SVGs ───────────────────────────────────────────
    matched = 0

    def _patch_svg(m):
        nonlocal matched
        svg = m.group(0)
        tm2 = _re.search(r"<title[^>]*>(.*?)</title>", svg, _re.DOTALL)
        if not tm2:
            return svg
        groups2 = ref_series.get(tm2.group(1).strip())
        if not groups2:
            return svg
        matched += 1
        badge = (
            '<text class="ref-overlay" x="82" y="62" font-size="10" ' 
            'fill="#e74c3c" font-family="Arial,sans-serif" opacity="0.85">' 
            "&#9675; REF</text>"
        )
        inject = "\n" + "\n".join(groups2) + "\n" + badge + "\n"
        return svg[:-6] + inject + "</svg>"

    new_html = _re.sub(
        r"<svg\b[^>]*>.*?</svg>",
        _patch_svg,
        report_html,
        flags=_re.DOTALL | _re.IGNORECASE,
    )

    # Reveal ref toggle button in filter bar
    new_html = new_html.replace(
        'id="ref-divider" style="display:none"',
        'id="ref-divider"',
    )
    new_html = new_html.replace(
        'id="ref-toggle-wrap" style="display:none"',
        'id="ref-toggle-wrap"',
    )

    report_path.write_text(new_html, encoding="utf-8")
    logger.info(
        "Reference overlays injected: %d/%d plots matched (%s → %s)",
        matched, len(ref_series), ref_path.name, report_path.name,
    )
    return report_path

