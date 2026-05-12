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
    """Build a detailed summary tab, separated by Vout and efficiency mode."""
    import statistics as _stats
    import math as _math

    def _fv(v, decimals=3):
        if v is None: return "—"
        try:    return f"{float(v):.{decimals}f}"
        except: return str(v)

    def _flt(r, *cols):
        for col in cols:
            try:
                v = float(r.get(col, "").strip())
                if v == v: return v      # not NaN
            except Exception:
                pass
        return None

    def _table_hdr(extra_cols=()):
        cols = ["Metric"] + list(extra_cols) + ["Min", "Mean", "Max", "N"]
        ths  = "".join(f'<th style="padding:5px 8px;white-space:nowrap">{_h(c)}</th>' for c in cols)
        return f'<tr style="background:#2c3e50;color:#fff">{ths}</tr>'

    def _stat_row(label, values, unit="", decimals=3, good_hi=True, extra_cells=()):
        vals = [v for v in values if v is not None]
        if not vals:
            nc = 4 + len(extra_cells)
            return (f'<tr><td style="padding:4px 8px">{_h(label)}</td>'
                    + "".join(f'<td>{_h(c)}</td>' for c in extra_cells)
                    + f'<td colspan="{nc}" style="color:#aaa;padding:4px 8px">no data</td></tr>')
        mn, mx, mu = min(vals), max(vals), _stats.mean(vals)
        colour = "#2ecc71" if good_hi else "#e74c3c"
        bar_w  = max(2, min(60, int(abs(mx - mn) / max(abs(mu), 1e-9) * 25)))
        mean_cell = (f'<td style="white-space:nowrap;padding:4px 8px">'
                     f'<span style="display:inline-block;width:{bar_w}px;height:7px;'
                     f'background:{colour};border-radius:3px;margin-right:5px;'
                     f'vertical-align:middle"></span>'
                     f'{_fv(mu, decimals)}{_h(" " + unit) if unit else ""}</td>')
        extra = "".join(f'<td style="padding:4px 8px">{_h(c)}</td>' for c in extra_cells)
        return (f'<tr>'
                f'<td style="padding:4px 8px;white-space:nowrap">{_h(label)}</td>'
                f'{extra}'
                f'<td style="color:#3498db;padding:4px 8px">{_fv(mn, decimals)}{_h(" " + unit) if unit else ""}</td>'
                f'{mean_cell}'
                f'<td style="color:#e74c3c;padding:4px 8px">{_fv(mx, decimals)}{_h(" " + unit) if unit else ""}</td>'
                f'<td style="color:#7f8c8d;font-size:10px;padding:4px 8px">n={len(vals)}</td></tr>')

    def _table(rows_html, extra_cols=()):
        return (f'<div style="overflow-x:auto"><table style="border-collapse:collapse;'
                f'width:100%;margin-bottom:4px;font-size:12px">'
                f'{_table_hdr(extra_cols)}{"".join(rows_html)}</table></div>')

    def _section(title, body_html, colour="#2c3e50"):
        return (f'<div style="margin-bottom:20px;border-left:3px solid {colour};padding-left:10px">'
                f'<h3 style="margin:0 0 6px;font-size:13px;color:{colour}">{_h(title)}</h3>'
                f'{body_html}</div>')

    def _group(rows, *keys):
        """Group rows into dict keyed by tuple of values."""
        g = {}
        for r in rows:
            k = tuple(r.get(k2, "").strip() for k2 in keys)
            g.setdefault(k, []).append(r)
        return g

    html_parts = []

    # ════════════════════════════════════════════════════════════════════
    # 1. Static Load Regulation
    # ════════════════════════════════════════════════════════════════════
    load_rows = data.get_rows("Static_Load")
    if load_rows:
        html_parts.append('<h2 style="font-size:15px;color:#2c3e50;margin:16px 0 6px;'
                          'border-bottom:2px solid #ecf0f1;padding-bottom:4px">Static Load Regulation</h2>')
        grp = _group(load_rows, "Regulator Name", "Vout", "DCDC Efficiency Mode")
        for (reg, vout, mode) in sorted(grp.keys()):
            rr = grp[(reg, vout, mode)]
            reg_lbl = REG_LABELS.get(reg, reg)

            # ── Efficiency binned by load range ────────────────────────
            # Collect (iout, eff) pairs
            iout_eff = []
            for r in rr:
                iout = _flt(r, "Iout [A]", "IoutSMU")
                eff  = _flt(r, "Efficiency [Pout/Pin %]")
                if iout is not None and eff is not None:
                    iout_eff.append((iout, eff))

            bin_rows = []
            if iout_eff:
                mn_i = min(x[0] for x in iout_eff)
                mx_i = max(x[0] for x in iout_eff)
                # Create ~5 equal-width load bins
                n_bins = 5
                step = (mx_i - mn_i) / n_bins if mx_i > mn_i else 1
                bins  = [(mn_i + i * step, mn_i + (i + 1) * step)
                         for i in range(n_bins)]
                for lo, hi in bins:
                    effs = [eff for iout, eff in iout_eff if lo <= iout <= hi]
                    if not effs: continue
                    bin_lbl = f"{lo:.3f}–{hi:.3f} A"
                    mu  = _stats.mean(effs)
                    bin_rows.append(
                        _stat_row(f"Eff @ {bin_lbl}", effs, "%", 1, good_hi=True))

            # ── Vout load regulation (ΔVout over full Iout range) ──────
            vout_vals = [_flt(r, "Vout [V]") for r in rr]
            vout_clean = [v for v in vout_vals if v is not None]
            dvout_row = []
            if len(vout_clean) >= 2:
                dvout = max(vout_clean) - min(vout_clean)
                dvout_row = [f'<tr><td style="padding:4px 8px">ΔVout (load reg.)</td>'
                              f'<td colspan="4" style="padding:4px 8px;color:#8e44ad;font-weight:bold">'
                              f'{dvout*1000:.2f} mV  '
                              f'({dvout/float(vout) * 100:.3f}% of {vout}V)</td></tr>'
                             if vout else
                             f'<tr><td style="padding:4px 8px">ΔVout (load reg.)</td>'
                             f'<td colspan="4" style="padding:4px 8px">{dvout*1000:.2f} mV</td></tr>']

            all_rows = bin_rows + dvout_row
            if all_rows:
                body = _table(all_rows)
                html_parts.append(_section(f"{reg_lbl}  Vout={vout}V  [{mode}]", body, "#8e44ad"))

    # ════════════════════════════════════════════════════════════════════
    # 2. Static Line Regulation
    # ════════════════════════════════════════════════════════════════════
    line_rows = data.get_rows("Static_Line")
    if line_rows:
        html_parts.append('<h2 style="font-size:15px;color:#2c3e50;margin:16px 0 6px;'
                          'border-bottom:2px solid #ecf0f1;padding-bottom:4px">Static Line Regulation</h2>')
        grp = _group(line_rows, "Regulator Name", "Vout", "DCDC Efficiency Mode")
        for (reg, vout, mode) in sorted(grp.keys()):
            rr = grp[(reg, vout, mode)]
            reg_lbl = REG_LABELS.get(reg, reg)

            # Collect (vin, vout_meas) pairs
            vin_vout = []
            for r in rr:
                vin   = _flt(r, "Vin")
                vmeas = _flt(r, "Vout [V]")
                if vin is not None and vmeas is not None:
                    vin_vout.append((vin, vmeas))

            bin_rows = []
            if vin_vout:
                mn_v = min(x[0] for x in vin_vout)
                mx_v = max(x[0] for x in vin_vout)
                n_bins = min(5, max(1, len({x[0] for x in vin_vout})))
                step = (mx_v - mn_v) / n_bins if mx_v > mn_v else 1
                bins = [(mn_v + i * step, mn_v + (i + 1) * step)
                        for i in range(n_bins)]
                for lo, hi in bins:
                    vmeas_list = [vm for vin, vm in vin_vout if lo <= vin <= hi]
                    if not vmeas_list: continue
                    bin_rows.append(
                        _stat_row(f"Vout @ Vin {lo:.2f}–{hi:.2f}V",
                                  vmeas_list, "V", 4, good_hi=True))

            # ΔVout across full Vin range
            all_v = [v for _, v in vin_vout]
            dvout_row = []
            if len(all_v) >= 2:
                dvout = max(all_v) - min(all_v)
                dvout_row = [f'<tr><td style="padding:4px 8px">ΔVout (line reg.)</td>'
                              f'<td colspan="4" style="padding:4px 8px;color:#8e44ad;font-weight:bold">'
                              f'{dvout*1000:.2f} mV</td></tr>']

            all_rows = bin_rows + dvout_row
            if all_rows:
                html_parts.append(_section(f"{reg_lbl}  Vout={vout}V  [{mode}]",
                                           _table(all_rows), "#2980b9"))

    # ════════════════════════════════════════════════════════════════════
    # 3. Quiescence
    # ════════════════════════════════════════════════════════════════════
    q_rows = data.get_rows("Quiescence", ok_only=False)
    if q_rows:
        html_parts.append('<h2 style="font-size:15px;color:#2c3e50;margin:16px 0 6px;'
                          'border-bottom:2px solid #ecf0f1;padding-bottom:4px">Quiescence & Shutdown</h2>')
        grp = _group(q_rows, "Regulator Name", "Vout")
        for (reg, vout) in sorted(grp.keys()):
            rr = grp[(reg, vout)]
            reg_lbl = REG_LABELS.get(reg, reg)
            rows = [
                _stat_row("Iin Disable", [_flt(r, "IinDisable [A]") for r in rr], "µA", 3, good_hi=False),
                _stat_row("Iin Enable",  [_flt(r, "IinEnable [A]")  for r in rr], "µA", 3, good_hi=False),
                _stat_row("Delta",       [_flt(r, "Delta [A]")       for r in rr], "µA", 3, good_hi=False),
            ]
            html_parts.append(_section(f"{reg_lbl}  Vout={vout}V", _table(rows), "#16a085"))

    # ════════════════════════════════════════════════════════════════════
    # 4. Power On
    # ════════════════════════════════════════════════════════════════════
    pon_rows = data.get_rows("PowerOn")
    if pon_rows:
        html_parts.append('<h2 style="font-size:15px;color:#2c3e50;margin:16px 0 6px;'
                          'border-bottom:2px solid #ecf0f1;padding-bottom:4px">Power On</h2>')
        grp = _group(pon_rows, "Regulator Name", "Vout", "DCDC Efficiency Mode")
        for (reg, vout, mode) in sorted(grp.keys()):
            rr = grp[(reg, vout, mode)]
            reg_lbl = REG_LABELS.get(reg, reg)
            rows = [
                _stat_row("Rise Time",  [_flt(r, "RiseTime [uS]", "Rise Time [uS]") for r in rr],
                          "µs", 2, good_hi=False),
                _stat_row("Overshoot",  [_flt(r, "Overshoot [V]") for r in rr],
                          "V",  4, good_hi=False),
            ]
            html_parts.append(_section(f"{reg_lbl}  Vout={vout}V  [{mode}]", _table(rows), "#e67e22"))

    # ════════════════════════════════════════════════════════════════════
    # 5. Transient Response
    # ════════════════════════════════════════════════════════════════════
    tr_rows = data.get_rows("Transient")
    if tr_rows:
        html_parts.append('<h2 style="font-size:15px;color:#2c3e50;margin:16px 0 6px;'
                          'border-bottom:2px solid #ecf0f1;padding-bottom:4px">Transient Response</h2>')
        grp = _group(tr_rows, "Regulator Name", "Vout", "DCDC Efficiency Mode")
        for (reg, vout, mode) in sorted(grp.keys()):
            rr = grp[(reg, vout, mode)]
            reg_lbl = REG_LABELS.get(reg, reg)
            vmax_vals = [_flt(r, "Vout Max") for r in rr]
            vmin_vals = [_flt(r, "Vout Min") for r in rr]
            rows = [
                _stat_row("Vout Max (step↓)", vmax_vals, "V", 4, good_hi=True),
                _stat_row("Vout Min (step↑)", vmin_vals, "V", 4, good_hi=True),
            ]
            html_parts.append(_section(f"{reg_lbl}  Vout={vout}V  [{mode}]", _table(rows), "#c0392b"))

    # ════════════════════════════════════════════════════════════════════
    # 6. Voltage Transitions
    # ════════════════════════════════════════════════════════════════════
    vt_rows = data.get_rows("VoltageTransitions")
    if vt_rows:
        html_parts.append('<h2 style="font-size:15px;color:#2c3e50;margin:16px 0 6px;'
                          'border-bottom:2px solid #ecf0f1;padding-bottom:4px">Voltage Transitions</h2>')
        grp = _group(vt_rows, "Regulator Name", "Vout", "DCDC Efficiency Mode")
        for (reg, vout, mode) in sorted(grp.keys()):
            rr = grp[(reg, vout, mode)]
            reg_lbl = REG_LABELS.get(reg, reg)
            def _col_ci(row, *cands):
                rl = {k.lower().strip(): row[k] for k in row}
                for c in cands:
                    v = rl.get(c.lower().strip())
                    try:
                        fv = float(v)
                        if fv == fv: return fv
                    except Exception:
                        pass
                return None
            rows = [
                _stat_row("Vout Max", [_flt(r, "Vout Max ", "Vout Max") for r in rr], "V", 4),
                _stat_row("Vout Min", [_flt(r, "Vout Min ", "Vout Min") for r in rr], "V", 4),
                _stat_row("Rise Time",
                          [_col_ci(r, "RiseTime [uS]", "Rise Time [uS]",
                                   "RiseTime [us]", "Rise Time [us]")
                           for r in rr if r.get("Slope","").strip().upper()=="P"],
                          "µs", 2, good_hi=False),
                _stat_row("Fall Time",
                          [_col_ci(r, "Measured Fall Time [uS]", "Measured Fall Time [us]",
                                   "Fall Time [uS]", "Fall Time [us]",
                                   "Measured Fall Time [pSec]", "Fall Time [pSec]")
                           for r in rr if r.get("Slope","").strip().upper()=="N"],
                          "µs", 2, good_hi=False),
            ]
            html_parts.append(_section(f"{reg_lbl}  Vout={vout}V  [{mode}]", _table(rows), "#27ae60"))

    # ════════════════════════════════════════════════════════════════════
    # 7. Auto Mode Transitions
    # ════════════════════════════════════════════════════════════════════
    am_rows = data.get_rows("AutoMode")
    if am_rows:
        html_parts.append('<h2 style="font-size:15px;color:#2c3e50;margin:16px 0 6px;'
                          'border-bottom:2px solid #ecf0f1;padding-bottom:4px">Auto Mode Transitions</h2>')
        grp = _group(am_rows, "Regulator Name", "Vout")
        for (reg, vout) in sorted(grp.keys()):
            rr    = grp[(reg, vout)]
            reg_lbl = REG_LABELS.get(reg, reg)

            # Efficiency binned by Iout
            iout_eff = [(i, e)
                        for r in rr
                        for i in [_flt(r, "Iout [A]", "IoutSMU")]
                        for e in [_flt(r, "Efficiency [Pout/Pin %]")]
                        if i is not None and e is not None]
            bin_rows = []
            if iout_eff:
                mn_i = min(x[0] for x in iout_eff)
                mx_i = max(x[0] for x in iout_eff)
                n_bins = 5
                step = (mx_i - mn_i) / n_bins if mx_i > mn_i else 1
                for i in range(n_bins):
                    lo, hi = mn_i + i * step, mn_i + (i + 1) * step
                    effs = [e for ii, e in iout_eff if lo <= ii <= hi]
                    if effs:
                        bin_rows.append(_stat_row(f"Eff @ {lo:.3f}–{hi:.3f}A",
                                                  effs, "%", 1, good_hi=True))

            rows = bin_rows + [
                _stat_row("Vout Min", [_flt(r, "Vout Min ", "Vout Min") for r in rr], "V", 4),
                _stat_row("Vout Max", [_flt(r, "Vout Max ", "Vout Max") for r in rr], "V", 4),
            ]
            html_parts.append(_section(f"{reg_lbl}  Vout={vout}V", _table(rows), "#d35400"))

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
           grid-template-columns:repeat(var(--plot-cols,1),1fr);
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

document.addEventListener('DOMContentLoaded',()=>{{ _initSets(); document.documentElement.style.setProperty('--plot-cols',1); }});

// ── Drag-to-Zoom (viewBox-based, with undo stack) ─────────────────────────
var _zoomEnabled = false;
var _panEnabled  = false;

(function(){{
  // Per-SVG undo history: WeakMap<SVGElement, Array<string>>
  var _history = new WeakMap();   // stack of previous viewBox strings
  var _original = new WeakMap();  // original viewBox string

  // Drag state
  var _dragging = false;
  var _dragSvg  = null;
  var _dragRect = null;   // SVG <rect> rubber-band element
  var _x0 = 0, _y0 = 0;  // start in SVG coords

  // Pan state
  var _panSvg = null, _panStartX = 0, _panStartY = 0;
  var _panStartVB = null, _panStartVBStr = '', _panScaleX = 1, _panScaleY = 1;

  // ── helpers ──────────────────────────────────────────────────────────
  function _svgCoords(svg, e){{
    var pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    return pt.matrixTransform(svg.getScreenCTM().inverse());
  }}

  function _getVB(svg){{
    var vb = svg.getAttribute('viewBox');
    if(vb) return vb.trim().split(/[\s,]+/).map(Number);
    var w = +svg.getAttribute('width') || svg.getBoundingClientRect().width;
    var h = +svg.getAttribute('height') || svg.getBoundingClientRect().height;
    return [0, 0, w, h];
  }}

  function _setVB(svg, x, y, w, h){{
    svg.setAttribute('viewBox', x + ' ' + y + ' ' + w + ' ' + h);
  }}

  function _pushHistory(svg){{
    var cur = svg.getAttribute('viewBox');
    var stack = _history.get(svg) || [];
    stack.push(cur);
    _history.set(svg, stack);
  }}

  function _initSvg(svg){{
    if(!_original.has(svg))
      _original.set(svg, _getVB(svg).join(' '));
  }}

  // ── rubber-band rect in SVG overlay ──────────────────────────────────
  function _startRect(svg){{
    if(_dragRect && _dragRect.parentNode) _dragRect.parentNode.removeChild(_dragRect);
    _dragRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    _dragRect.setAttribute('fill',           'rgba(41,128,185,0.15)');
    _dragRect.setAttribute('stroke',         '#2980b9');
    _dragRect.setAttribute('stroke-width',   '1.5');
    _dragRect.setAttribute('stroke-dasharray','5,3');
    _dragRect.setAttribute('pointer-events', 'none');
    svg.appendChild(_dragRect);
  }}

  function _updateRect(x0, y0, x1, y1){{
    if(!_dragRect) return;
    var rx = Math.min(x0,x1), ry = Math.min(y0,y1);
    var rw = Math.abs(x1-x0),  rh = Math.abs(y1-y0);
    _dragRect.setAttribute('x', rx); _dragRect.setAttribute('y', ry);
    _dragRect.setAttribute('width', rw); _dragRect.setAttribute('height', rh);
  }}

  function _removeRect(){{
    if(_dragRect && _dragRect.parentNode)
      _dragRect.parentNode.removeChild(_dragRect);
    _dragRect = null;
  }}

  // ── apply zoom from rubber-band selection ────────────────────────────
  function _applyZoom(svg, x0, y0, x1, y1){{
    var rx = Math.min(x0,x1), ry = Math.min(y0,y1);
    var rw = Math.abs(x1-x0),   rh = Math.abs(y1-y0);
    if(rw < 2 || rh < 2) return;   // too small — ignore
    _pushHistory(svg);
    _setVB(svg, rx, ry, rw, rh);
    _refreshUndoBtn();
  }}

  // ── undo one zoom step ────────────────────────────────────────────────
  function zoomUndo(){{
    // Operate on the most recently zoomed SVG if focus not known
    var svgs = document.querySelectorAll('.plot-box svg');
    for(var i = 0; i < svgs.length; i++){{
      var stack = _history.get(svgs[i]);
      if(stack && stack.length){{
        svg.setAttribute('viewBox', stack.pop());
        _history.set(svgs[i], stack);
        _refreshUndoBtn();
        return;
      }}
    }}
  }}

  // ── exposed globals ───────────────────────────────────────────────────
  window._zoomUndo = function(){{
    // Find the last SVG that has history
    var svgs = Array.from(document.querySelectorAll('.plot-box svg')).reverse();
    for(var i = 0; i < svgs.length; i++){{
      var stack = _history.get(svgs[i]);
      if(stack && stack.length){{
        svgs[i].setAttribute('viewBox', stack.pop());
        _history.set(svgs[i], stack);
        _refreshUndoBtn();
        return;
      }}
    }}
  }};

  window._zoomReset = function(){{
    document.querySelectorAll('.plot-box svg').forEach(function(svg){{
      var orig = _original.get(svg);
      if(orig) svg.setAttribute('viewBox', orig);
      _history.set(svg, []);
    }});
    _refreshUndoBtn();
  }};

  function _refreshUndoBtn(){{
    var btn = document.getElementById('_zoom_undo_btn');
    if(!btn) return;
    var hasHistory = Array.from(document.querySelectorAll('.plot-box svg'))
      .some(function(s){{ var st = _history.get(s); return st && st.length > 0; }});
    btn.disabled = !hasHistory;
    btn.style.opacity = hasHistory ? '1' : '0.4';
  }}

  // ── mouse events ──────────────────────────────────────────────────────
  document.addEventListener('mousedown', function(e){{
    if(!_zoomEnabled && !_panEnabled) return;
    var el = e.target;
    var svg = el && el.ownerSVGElement ? el.ownerSVGElement
            : (el && el.tagName && el.tagName.toLowerCase()==='svg' ? el : null);
    if(!svg && el){{
      var pb = el.closest ? el.closest('.plot-box') : null;
      if(pb) svg = pb.querySelector('svg');
    }}
    if(!svg) return;
    e.preventDefault();
    _initSvg(svg);
    _dragging = true;
    _dragSvg  = svg;
    if(_panEnabled){{
      _panSvg        = svg;
      _panStartX     = e.clientX;
      _panStartY     = e.clientY;
      _panStartVB    = _getVB(svg);
      _panStartVBStr = svg.getAttribute('viewBox') || _panStartVB.join(' ');
      var bRect      = svg.getBoundingClientRect();
      _panScaleX     = _panStartVB[2] / (bRect.width  || 1);
      _panScaleY     = _panStartVB[3] / (bRect.height || 1);
      svg.style.cursor = 'grabbing';
      var _co = svg.querySelector('.cursor-overlay');
      if(_co) _co.style.cursor = 'grabbing';
    }} else {{
      var pt = _svgCoords(svg, e);
      _x0 = pt.x; _y0 = pt.y;
      _startRect(svg);
      _updateRect(_x0, _y0, _x0, _y0);
    }}
  }}, true);

  document.addEventListener('mousemove', function(e){{
    if(!_dragging || !_dragSvg) return;
    e.preventDefault();
    if(_panEnabled && _panSvg){{
      var dx = (e.clientX - _panStartX) * _panScaleX;
      var dy = (e.clientY - _panStartY) * _panScaleY;
      _setVB(_panSvg, _panStartVB[0]-dx, _panStartVB[1]-dy, _panStartVB[2], _panStartVB[3]);
    }} else if(_zoomEnabled){{
      var pt2 = _svgCoords(_dragSvg, e);
      _updateRect(_x0, _y0, pt2.x, pt2.y);
    }}
  }}, true);

  document.addEventListener('mouseup', function(e){{
    if(!_dragging || !_dragSvg) return;
    e.preventDefault();
    if(_panEnabled && _panSvg){{
      var finalVB = _panSvg.getAttribute('viewBox');
      if(finalVB && finalVB !== _panStartVBStr){{
        var stk = _history.get(_panSvg) || [];
        stk.push(_panStartVBStr);
        _history.set(_panSvg, stk);
        _refreshUndoBtn();
      }}
      _panSvg.style.cursor = 'grab';
      var _coUp = _panSvg.querySelector('.cursor-overlay');
      if(_coUp) _coUp.style.cursor = 'grab';
      _panSvg = null;
    }} else if(_zoomEnabled){{
      var pt3 = _svgCoords(_dragSvg, e);
      _removeRect();
      _applyZoom(_dragSvg, _x0, _y0, pt3.x, pt3.y);
    }}
    _dragging = false;
    _dragSvg  = null;
  }}, true);

  // Double-click resets that specific SVG
  document.addEventListener('dblclick', function(e){{
    if(!_zoomEnabled) return;
    var el = e.target;
    var svg = el && el.ownerSVGElement ? el.ownerSVGElement
            : (el && el.tagName && el.tagName.toLowerCase()==='svg' ? el : null);
    if(!svg) return;
    var orig = _original.get(svg);
    if(orig){{ svg.setAttribute('viewBox', orig); _history.set(svg, []); }}
    _refreshUndoBtn();
  }});

  // ── Right-click = undo one zoom step on that SVG ─────────────────────
  document.addEventListener('contextmenu', function(e){{
    if(!_zoomEnabled) return;
    var el = e.target;
    var svg = el && el.ownerSVGElement ? el.ownerSVGElement
            : (el && el.tagName && el.tagName.toLowerCase()==='svg' ? el : null);
    if(!svg && el){{
      var pb2 = el.closest ? el.closest('.plot-box') : null;
      if(pb2) svg = pb2.querySelector('svg');
    }}
    if(!svg) return;
    e.preventDefault();
    var stack = _history.get(svg);
    if(stack && stack.length){{
      svg.setAttribute('viewBox', stack.pop());
      _history.set(svg, stack);
    }} else {{
      // already at top level — restore original
      var orig2 = _original.get(svg);
      if(orig2) svg.setAttribute('viewBox', orig2);
    }}
    _refreshUndoBtn();
  }});

}})();

function toggleZoom(btn){{
  _zoomEnabled = !_zoomEnabled;
  btn.classList.toggle('active', _zoomEnabled);
  btn.textContent = _zoomEnabled ? '\u26f6 Zoom: ON' : '\u26f6 Zoom: OFF';
  if(_zoomEnabled && _panEnabled){{
    _panEnabled = false;
    var pbtn = document.getElementById('_pan_btn');
    if(pbtn){{ pbtn.classList.remove('active'); pbtn.textContent = '\u270b Pan: OFF'; }}
  }}
  var svgCur = _zoomEnabled ? 'zoom-in' : 'default';
  document.querySelectorAll('.plot-box svg').forEach(function(svg){{
    svg.style.cursor = svgCur;
  }});
  document.querySelectorAll('.cursor-overlay').forEach(function(ov){{
    ov.style.cursor = _zoomEnabled ? 'zoom-in' : (_cursorEnabled ? 'crosshair' : 'default');
  }});
  if(!_zoomEnabled){{
    document.querySelectorAll('.plot-box svg').forEach(function(svg){{
      if(!window._zoomOriginals) window._zoomOriginals = new WeakMap();
    }});
  }}
  var undoBar = document.getElementById('_zoom_undo_bar');
  if(undoBar) undoBar.style.display = (_zoomEnabled || _panEnabled) ? 'flex' : 'none';
}}

function togglePan(btn){{
  _panEnabled = !_panEnabled;
  btn.classList.toggle('active', _panEnabled);
  btn.textContent = _panEnabled ? '\u270b Pan: ON' : '\u270b Pan: OFF';
  if(_panEnabled && _zoomEnabled){{
    _zoomEnabled = false;
    var zbtn = document.getElementById('_zoom_btn');
    if(zbtn){{ zbtn.classList.remove('active'); zbtn.textContent = '\u26f6 Zoom: OFF'; }}
  }}
  var svgCur = _panEnabled ? 'grab' : 'default';
  document.querySelectorAll('.plot-box svg').forEach(function(svg){{
    svg.style.cursor = svgCur;
  }});
  document.querySelectorAll('.cursor-overlay').forEach(function(ov){{
    ov.style.cursor = _panEnabled ? 'grab' : (_cursorEnabled ? 'crosshair' : 'default');
  }});
  var undoBar = document.getElementById('_zoom_undo_bar');
  if(undoBar) undoBar.style.display = (_panEnabled || _zoomEnabled) ? 'flex' : 'none';
}}

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
    // stroke colors updated AFTER series detection below

    var tipW = 170, tipH = 48;
    var tx = mx + 12, ty = my - tipH - 8;
    // Use current viewBox bounds so tooltip stays in view when zoomed
    var _vbStr = svg.getAttribute('viewBox');
    var _vb = _vbStr ? _vbStr.trim().split(/[\s,]+/).map(Number)
                     : [0, 0, +svg.getAttribute('width')||1400, +svg.getAttribute('height')||520];
    var vbRight  = _vb[0] + _vb[2];
    var vbBottom = _vb[1] + _vb[3];
    if(tx + tipW > vbRight  - 5)  tx = mx - tipW - 14;
    if(tx < _vb[0] + 2)           tx = _vb[0] + 2;
    if(ty < ptt + 2)               ty = my + 10;
    if(ty + tipH > vbBottom - 2)   ty = my - tipH - 10;

    // ── Find nearest visible series ────────────────────────────────────────────
    var bestDist = Infinity, bestLabel = '', bestColor = null;
    svg.querySelectorAll('g.pmic-series').forEach(function(g){{
      if(g.style.display === 'none') return;
      var serColor = g.dataset.color || null;
      var serLabel = g.dataset.label || '';
      g.querySelectorAll('circle').forEach(function(c){{
        var cx2 = +c.getAttribute('cx'), cy2 = +c.getAttribute('cy');
        var dist = Math.hypot(cx2 - mx, cy2 - my);
        if(dist < bestDist){{ bestDist = dist; bestColor = serColor; bestLabel = serLabel; }}
      }});
    }});
    var SNAP = 40;  // SVG units — within this distance we highlight the series
    var lineColor  = (bestColor && bestDist < SNAP) ? bestColor : '#e74c3c';
    var activeColor = lineColor;

    cl.querySelector('.cur-v').setAttribute('stroke', activeColor);
    cl.querySelector('.cur-h').setAttribute('stroke', activeColor);

    var bg = cl.querySelector('.cur-tip-bg');
    bg.setAttribute('x', tx); bg.setAttribute('y', ty);
    bg.setAttribute('width', tipW); bg.setAttribute('height', tipH);
    bg.setAttribute('fill', (bestColor && bestDist < SNAP) ? bestColor : '#1a252f');
    bg.setAttribute('stroke', (bestColor && bestDist < SNAP) ? '#fff' : '#34495e');

    var ts = cl.querySelector('.cur-tip-s');
    ts.setAttribute('x', tx + 6); ts.setAttribute('y', ty + 11);
    if(bestColor && bestDist < SNAP){{
      var shortLbl = bestLabel.length > 34 ? bestLabel.slice(0,32)+'\u2026' : bestLabel;
      ts.textContent = shortLbl;
      ts.setAttribute('fill', '#fff');
    }} else {{
      ts.textContent = '';
    }}

    var tx1 = cl.querySelector('.cur-tip-x');
    tx1.setAttribute('x', tx + 6); tx1.setAttribute('y', ty + 26);
    tx1.textContent = 'X: ' + _fmtVal(dx);
    tx1.setAttribute('fill', '#ecf0f1');

    var ty1 = cl.querySelector('.cur-tip-y');
    ty1.setAttribute('x', tx + 6); ty1.setAttribute('y', ty + 40);
    ty1.textContent = 'Y: ' + _fmtVal(dy);
    ty1.setAttribute('fill', '#2ecc71');
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
    <span class="ftog" id="_zoom_btn" style="background:#27ae60;color:#fff;border-color:#1e8449"
          onclick="toggleZoom(this)">&#9974; Zoom: OFF</span>
  </div>
  <div class="filter-divider"></div>
  <div class="fg">
    <span class="ftog" id="_pan_btn" style="background:#8e44ad;color:#fff;border-color:#7d3c98"
          onclick="togglePan(this)">&#x270B; Pan: OFF</span>
  </div>
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
    <span class="size-btn active" data-cols="1" onclick="setCols(1,this)">1</span>
    <span class="size-btn" data-cols="2" onclick="setCols(2,this)">2</span>
  </div>
  {ref_divider_html}
</div>
<div id="_zoom_undo_bar" style="display:none;align-items:center;gap:8px;
     padding:6px 18px;background:#eaf4fb;border:1px solid #aed6f1;
     border-radius:6px;margin:4px 0;font-size:12px;color:#2c3e50">
  <strong>&#9974; Zoom mode</strong>
  <span style="color:#7f8c8d">— drag to select area &nbsp;·&nbsp; double-click to reset one plot</span>
  <button id="_zoom_undo_btn" onclick="_zoomUndo()" disabled
    style="margin-left:12px;padding:3px 12px;border:1.5px solid #2980b9;border-radius:5px;
           background:#2980b9;color:#fff;cursor:pointer;font-size:11px;opacity:0.4">
    ↩ Undo Zoom
  </button>
  <button onclick="_zoomReset()"
    style="padding:3px 12px;border:1.5px solid #e74c3c;border-radius:5px;
           background:#e74c3c;color:#fff;cursor:pointer;font-size:11px">
    ↺ Reset All
  </button>
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

