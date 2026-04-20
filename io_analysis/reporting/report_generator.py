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
    section_params: dict = {t: [] for t in TEST_SECTION_ORDER}
    for param in sorted(result.all_parameters):
        t = param_test_map.get(param)
        if t in section_params:
            if any(param.startswith(io + "_") for io in REPORT_IOS):
                if param not in section_params[t]:
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
.plots-row{{display:flex;flex-wrap:wrap;gap:16px;margin-top:12px}}
.plot-box{{flex:1;min-width:420px;border:1px solid #ecf0f1;border-radius:6px;overflow:hidden;background:#fff}}
.plot-box h4{{margin:0;padding:6px 10px;font-size:12px;background:#f8f9fa;border-bottom:1px solid #ecf0f1;color:#555}}
.plot-box svg,.plot-box object{{width:100%;height:auto}}
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
</div>''')

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
            "Maximum output current test: measures output voltage under load current. "
            "VOL = output low voltage (must be ≤ spec max); "
            "VOH = output high voltage (must be ≥ spec min).",
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
                            smin = f"{s.spec_min:.4g}" if s.spec_min is not None else "—"
                            smax_s = f"{s.spec_max:.4g}" if s.spec_max is not None else "—"
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
            smin = f"{s.spec_min:.4g}" if s.spec_min is not None else "â€“"
            smax_s = f"{s.spec_max:.4g}" if s.spec_max is not None else "â€“"
            cpk_s = f"{s.cpk:.3f}" if s.cpk is not None else "â€“"
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

