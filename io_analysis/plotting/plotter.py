"""SVG plot generator for IO Testing Results Analysis.

Generates publication-quality SVG plots saved to disk.
Uses Python standard library only (no matplotlib/numpy).
"""

import logging
from pathlib import Path
from typing import Optional

from io_analysis.config import Config
from io_analysis.data.models import AnalysisResult, ParameterStats

logger = logging.getLogger(__name__)

C_PASS = "#2ecc71"
C_FAIL = "#e74c3c"
C_WARN = "#e67e22"
C_BLUE = "#3498db"
C_PURPLE = "#9b59b6"
C_TEAL = "#1abc9c"
C_DARK = "#2c3e50"
C_GRAY = "#7f8c8d"
C_SPEC = "#ff6d00"  # overridden per-call from config.plot.spec_line_color
_SHOW_SPEC_LINES = True  # overridden per-call from config.plot.show_spec_lines
FLOW_COLORS = [C_BLUE, C_WARN, C_PURPLE, C_TEAL, C_FAIL]

# ---- Fixed chart dimensions — uniform size/font across all section plots ----
_CHART_W   = 1400
_CHART_H   = 560
_CHART_ML  = 82    # left margin
_CHART_MT  = 72    # top margin
_CHART_MB  = 100   # bottom margin
_CHART_LEG = 260   # legend / right margin

# ---- Report filtering / section config ----
REPORT_IOS = ["GPIO_0", "RF_KILLN"]
IO_COLORS = {"GPIO_0": C_BLUE, "RF_KILLN": C_WARN}

# Worst-case aggregation per measurement suffix
# "max": higher value = harder corner (spec is upper limit)
# "min": lower value = harder corner (spec is lower limit)
MEAS_WORST_AGG = {
    "VOL":          "max",
    "VOH":          "min",
    "IOL_A":        "max",
    "IOH_A":        "min",
    "R_Low":        "max",
    "R_High":       "max",
    "VIL_Max":      "max",
    "VIH_Min":      "min",
    "R_PullUp":     "max",
    "R_PullDown":   "min",
    "Fall_Time_ps": "max",
    "Rise_Time_ps": "max",
    "IO_State":     "mean",
    "IO_Direction": "mean",
}

TEST_SECTION_ORDER = [
    "IOH/IOL Max",
    "IO State After POR",
    "Pull-up/Pull-down Resistance",
    "VIH/VIL",
    "VOH/VOL",
    "Rise/Fall Time",
]

SECTION_MEASUREMENTS = {
    "IOH/IOL Max":                  ["IOL_A", "IOH_A", "R_Low", "R_High"],
    "IO State After POR":           ["IO_State", "IO_Direction"],
    "Pull-up/Pull-down Resistance": ["R_PullUp", "R_PullDown"],
    "VIH/VIL":                      ["VIH_Min", "VIL_Max"],
    "VOH/VOL":                      ["VOL", "VOH"],
    "Rise/Fall Time":               ["Fall_Time_ps", "Rise_Time_ps"],
}


def _esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _linspace(start, stop, n):
    if n <= 1:
        return [start]
    step = (stop - start) / (n - 1)
    return [start + i * step for i in range(n)]


def _quartile(sd, q):
    n = len(sd)
    if n == 0:
        return 0.0
    if n == 1:
        return sd[0]
    idx = q * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    return sd[lo] * (1 - (idx - lo)) + sd[hi] * (idx - lo)


def _ys(v, y_min, y_max, pt, pb):
    if y_max == y_min:
        return (pt + pb) / 2.0
    return pb - (v - y_min) / (y_max - y_min) * (pb - pt)


def _pct_range(vals, pct_lo=2, pct_hi=98):
    """Percentile-based y-range that excludes sentinel/outlier values from plot axes.
    Always call before including spec limits with min/max."""
    if not vals:
        return 0.0, 1.0
    s = sorted(v for v in vals if v is not None and v == v and abs(v) != float("inf"))
    if not s:
        return 0.0, 1.0
    n = len(s)
    lo = s[max(0, int(n * pct_lo / 100))]
    hi = s[min(n - 1, int(n * pct_hi / 100))]
    if lo == hi:
        lo -= 0.5
        hi += 0.5
    return lo, hi


class SVG:
    def __init__(self, w, h, bg="#ffffff"):
        self.w, self.h = w, h
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
            f'<rect width="{w}" height="{h}" fill="{bg}"/>',
        ]

    def rect(self, x, y, w, h, fill, stroke="none", sw=1, opacity=1.0, rx=2):
        self.parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w,0):.1f}" height="{max(h,0):.1f}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}" opacity="{opacity}" rx="{rx}"/>'
        )

    def text(self, x, y, txt, fs=11, fw="normal", anchor="start", fill="#333", transform=None):
        t = (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{fs}" font-weight="{fw}" '
             f'text-anchor="{anchor}" fill="{fill}" font-family="Arial,sans-serif"')
        if transform:
            t += f' transform="{transform}"'
        t += f">{_esc(txt)}</text>"
        self.parts.append(t)

    def line(self, x1, y1, x2, y2, stroke="#999", sw=1, dash=None):
        s = (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
             f'stroke="{stroke}" stroke-width="{sw}"')
        if dash:
            s += f' stroke-dasharray="{dash}"'
        self.parts.append(s + "/>")

    def circle(self, cx, cy, r, fill, stroke="none", opacity=1.0):
        self.parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="{fill}" '
            f'stroke="{stroke}" opacity="{opacity}"/>'
        )

    def title(self, txt):
        self.text(self.w / 2, 28, txt, fs=16, fw="bold", anchor="middle", fill=C_DARK)

    def finish(self):
        self.parts.append("</svg>")
        return "\n".join(self.parts)


def _y_axis(svg, y_min, y_max, pl, pr, pt, pb, n=6):
    svg.line(pl, pt, pl, pb)
    for tick in _linspace(y_min, y_max, n):
        y = _ys(tick, y_min, y_max, pt, pb)
        svg.line(pl - 5, y, pl, y)
        svg.line(pl, y, pr, y, stroke="#e0e0e0", sw=0.8, dash="3,3")
        svg.text(pl - 8, y + 4, f"{tick:.3g}", fs=9, anchor="end", fill=C_GRAY)


def _save(svg, path):
    path.write_text(svg.finish(), encoding="utf-8")
    logger.info(f"Saved: {path}")
    return path


# ---- 1. Pass/Fail Summary ----

def plot_pass_fail_summary(result, config, output_dir):
    saved = []
    for flow_name in result.all_flows:
        params, prs, frs = [], [], []
        for param in result.all_parameters:
            key = (flow_name, param)
            if key in result.parameter_stats:
                s = result.parameter_stats[key]
                params.append(param)
                prs.append(s.pass_rate)
                frs.append(s.fail_rate)
        if not params:
            continue
        n = len(params)
        W, H = 900, 450
        ml, mr, mt, mb = 60, 40, 55, 120
        pl, pr, pt, pb = ml, W - mr, mt, H - mb
        pw, ph = pr - pl, pb - pt
        svg = SVG(W, H)
        svg.title(f"Pass/Fail Summary - {flow_name}")
        svg.line(pl, pb, pr, pb)
        for tick in range(0, 101, 20):
            y = pb - (tick / 100) * ph
            svg.line(pl - 5, y, pl, y)
            svg.line(pl, y, pr, y, stroke="#e0e0e0", sw=0.7, dash="3,3")
            svg.text(pl - 8, y + 4, f"{tick}%", fs=9, anchor="end", fill=C_GRAY)
        svg.text(14, H / 2, "Percentage (%)", fs=11, fill=C_GRAY,
                 transform=f"rotate(-90,14,{H/2})", anchor="middle")
        bw = pw / n * 0.72
        for i, (p, pr_v, fr_v) in enumerate(zip(params, prs, frs)):
            x = pl + i * pw / n + (pw / n - bw) / 2
            pass_h = pr_v / 100 * ph
            fail_h = fr_v / 100 * ph
            svg.rect(x, pb - pass_h, bw, pass_h, fill=C_PASS, opacity=0.88)
            if fail_h > 0:
                svg.rect(x, pb - pass_h - fail_h, bw, fail_h, fill=C_FAIL, opacity=0.88)
            if pass_h > 18:
                svg.text(x + bw / 2, pb - pass_h / 2 + 4, f"{pr_v:.0f}%",
                         fs=9, fw="bold", anchor="middle", fill="white")
            if fail_h > 18:
                svg.text(x + bw / 2, pb - pass_h - fail_h / 2 + 4, f"{fr_v:.0f}%",
                         fs=9, fw="bold", anchor="middle", fill="white")
            lx, ly = x + bw / 2, pb + 10
            svg.text(lx, ly, p, fs=10, anchor="end",
                     transform=f"rotate(-40,{lx:.1f},{ly:.1f})")
        svg.rect(W - 150, mt, 12, 12, fill=C_PASS, opacity=0.88)
        svg.text(W - 134, mt + 10, "Pass", fs=10)
        svg.rect(W - 150, mt + 18, 12, 12, fill=C_FAIL, opacity=0.88)
        svg.text(W - 134, mt + 28, "Fail", fs=10)
        saved.append(_save(svg, output_dir / f"pass_fail_summary_{flow_name}.svg"))
    return saved


# ---- 2. Parameter vs Spec (box plot) ----

def plot_parameter_vs_spec(result, config, output_dir):
    saved = []
    for param in result.all_parameters:
        flow_boxes, spec_min, spec_max, unit_str = [], None, None, ""
        for flow_name in result.all_flows:
            key = (flow_name, param)
            if key in result.parameter_stats:
                s = result.parameter_stats[key]
                if s.values:
                    flow_boxes.append((flow_name, sorted(
                        v for v in s.values if v is not None and v == v)))
                if s.spec_min is not None:
                    spec_min = s.spec_min
                if s.spec_max is not None:
                    spec_max = s.spec_max
                if s.unit:
                    unit_str = f" ({s.unit})"
        if not flow_boxes:
            continue
        all_vals = [v for _, vs in flow_boxes for v in vs]
        y_min, y_max = _pct_range(all_vals)
        if spec_min is not None:
            y_min = min(y_min, spec_min)
            y_max = max(y_max, spec_min)
        if spec_max is not None:
            y_max = max(y_max, spec_max)
            y_min = min(y_min, spec_max)
        pad = (y_max - y_min) * 0.25 or 0.1
        y_min -= pad
        y_max += pad
        n = len(flow_boxes)
        W, H = 900, 450
        ml, mr, mt, mb = 70, 90, 55, 60
        pl, pr_w, pt, pb = ml, W - mr, mt, H - mb
        pw = pr_w - pl
        svg = SVG(W, H)
        svg.title(f"{param} - Measured vs Spec{unit_str}")
        svg.line(pl, pb, pr_w, pb)
        _y_axis(svg, y_min, y_max, pl, pr_w, pt, pb)
        svg.text(14, H / 2, f"Value{unit_str}", fs=11, fill=C_GRAY,
                 transform=f"rotate(-90,14,{H/2})", anchor="middle")
        bw = min(70, pw / (n + 1) * 0.55)
        for idx, (flow_name, vs) in enumerate(flow_boxes):
            if not vs:
                continue
            xc = pl + (idx + 1) * pw / (n + 1)
            q1 = _quartile(vs, 0.25)
            med = _quartile(vs, 0.5)
            q3 = _quartile(vs, 0.75)
            iqr = q3 - q1
            _wl = [v for v in vs if v >= q1 - 1.5 * iqr]
            wl = min(_wl) if _wl else min(vs)
            _wh = [v for v in vs if v <= q3 + 1.5 * iqr]
            wh = max(_wh) if _wh else max(vs)
            outliers = [v for v in vs if v < q1 - 1.5 * iqr or v > q3 + 1.5 * iqr]
            color = FLOW_COLORS[idx % len(FLOW_COLORS)]
            yq1 = _ys(q1, y_min, y_max, pt, pb)
            yq3 = _ys(q3, y_min, y_max, pt, pb)
            ym = _ys(med, y_min, y_max, pt, pb)
            ywl = _ys(wl, y_min, y_max, pt, pb)
            ywh = _ys(wh, y_min, y_max, pt, pb)
            svg.rect(xc - bw / 2, yq3, bw, yq1 - yq3, fill=color, stroke=color, sw=1.5, opacity=0.25)
            svg.line(xc - bw / 2, ym, xc + bw / 2, ym, stroke=color, sw=2.5)
            svg.line(xc, yq1, xc, ywl, stroke=color)
            svg.line(xc, yq3, xc, ywh, stroke=color)
            svg.line(xc - bw / 4, ywl, xc + bw / 4, ywl, stroke=color)
            svg.line(xc - bw / 4, ywh, xc + bw / 4, ywh, stroke=color)
            for v in outliers:
                svg.circle(xc, _ys(v, y_min, y_max, pt, pb), 3, fill=color, opacity=0.8)
            svg.text(xc, pb + 18, flow_name, fs=11, anchor="middle")
            svg.rect(W - mr + 5, mt + idx * 18, 10, 10, fill=color, opacity=0.7)
            svg.text(W - mr + 18, mt + idx * 18 + 9, flow_name, fs=9)
        if _SHOW_SPEC_LINES:
            svg.parts.append('<g class="spec-el">')
            if spec_min is not None:
                ys2 = _ys(spec_min, y_min, y_max, pt, pb)
                svg.line(pl, ys2, pr_w, ys2, stroke=C_SPEC, sw=4)
                svg.text(pr_w + 3, ys2 + 4, f"Min:{spec_min:.3g}", fs=9, fill=C_SPEC)
            if spec_max is not None:
                ys2 = _ys(spec_max, y_min, y_max, pt, pb)
                svg.line(pl, ys2, pr_w, ys2, stroke=C_SPEC, sw=4)
                svg.text(pr_w + 3, ys2 + 4, f"Max:{spec_max:.3g}", fs=9, fill=C_SPEC)
            svg.parts.append('</g>')
        saved.append(_save(svg, output_dir / f"param_vs_spec_{param}.svg"))
    return saved


# ---- 3. Distribution histograms ----

def plot_distribution_histograms(result, config, output_dir):
    saved = []
    for param in result.all_parameters:
        fdlist, spec_min, spec_max, unit_str = [], None, None, ""
        for flow_name in result.all_flows:
            key = (flow_name, param)
            if key in result.parameter_stats:
                s = result.parameter_stats[key]
                if s.values:
                    fdlist.append((flow_name, s.values))
                if s.spec_min is not None:
                    spec_min = s.spec_min
                if s.spec_max is not None:
                    spec_max = s.spec_max
                if s.unit:
                    unit_str = f" ({s.unit})"
        if not fdlist:
            continue
        combined = [v for _, vs in fdlist for v in vs
                    if v is not None and v == v
                    and abs(v) != float("inf")]  # exclude None, NaN, inf
        x_min, x_max = _pct_range(combined)
        if spec_min is not None and spec_min == spec_min:  # not NaN
            x_min = min(x_min, spec_min)
            x_max = max(x_max, spec_min)
        if spec_max is not None and spec_max == spec_max:  # not NaN
            x_max = max(x_max, spec_max)
            x_min = min(x_min, spec_max)
        pad = (x_max - x_min) * 0.15 or 0.01
        x_min -= pad
        x_max += pad
        n_bins = min(25, max(8, len(combined) // 3))
        step = (x_max - x_min) / n_bins if x_max > x_min else 1
        max_count = 0
        hists = []
        for idx, (fn, vals) in enumerate(fdlist):
            counts = [0] * n_bins
            for v in vals:
                if v is None or v != v or abs(v) == float("inf"):  # skip None/NaN/inf
                    continue
                bi = max(0, min(int((v - x_min) / step), n_bins - 1))
                counts[bi] += 1
            max_count = max(max_count, max(counts) if counts else 0)
            hists.append((fn, counts, FLOW_COLORS[idx % len(FLOW_COLORS)]))
        if max_count == 0:
            continue
        W, H = 900, 450
        ml, mr, mt, mb = 65, 30, 55, 75
        pl, pr_w, pt, pb = ml, W - mr, mt, H - mb
        pw, ph = pr_w - pl, pb - pt
        svg = SVG(W, H)
        svg.title(f"{param} - Distribution{unit_str}")
        svg.line(pl, pb, pr_w, pb)
        svg.line(pl, pt, pl, pb)
        for tick in _linspace(0, max_count, 6):
            y = pb - (tick / max_count) * ph
            svg.line(pl - 5, y, pl, y)
            svg.line(pl, y, pr_w, y, stroke="#e0e0e0", sw=0.7, dash="3,3")
            svg.text(pl - 8, y + 4, str(int(tick)), fs=9, anchor="end", fill=C_GRAY)
        for tick in _linspace(x_min, x_max, min(8, n_bins + 1)):
            x = pl + (tick - x_min) / (x_max - x_min) * pw
            svg.line(x, pb, x, pb + 5)
            svg.text(x, pb + 17, f"{tick:.3g}", fs=9, anchor="middle", fill=C_GRAY)
        svg.text(W / 2, H - 5, f"Value{unit_str}", fs=11, anchor="middle", fill=C_GRAY)
        svg.text(14, H / 2, "Count", fs=11, fill=C_GRAY,
                 transform=f"rotate(-90,14,{H/2})", anchor="middle")
        n_flows = len(hists)
        bin_px = pw / n_bins
        sub_w = bin_px / n_flows * 0.85
        for idx, (fn, counts, color) in enumerate(hists):
            for bi, cnt in enumerate(counts):
                if cnt == 0:
                    continue
                bar_h = (cnt / max_count) * ph
                x = pl + bi * bin_px + idx * sub_w
                svg.rect(x, pb - bar_h, sub_w, bar_h, fill=color, opacity=0.72)
            svg.rect(pl + idx * 110, pt - 28, 12, 12, fill=color, opacity=0.72)
            svg.text(pl + idx * 110 + 15, pt - 19, fn, fs=10)
        if _SHOW_SPEC_LINES:
            svg.parts.append('<g class="spec-el">')
            if spec_min is not None:
                xs = pl + (spec_min - x_min) / (x_max - x_min) * pw
                svg.line(xs, pt, xs, pb, stroke=C_SPEC, sw=4)
                svg.text(xs + 3, pt + 12, f"Min:{spec_min:.3g}", fs=9, fill=C_SPEC)
            if spec_max is not None:
                xs = pl + (spec_max - x_min) / (x_max - x_min) * pw
                svg.line(xs, pt, xs, pb, stroke=C_SPEC, sw=4)
                svg.text(xs - 70, pt + 12, f"Max:{spec_max:.3g}", fs=9, fill=C_SPEC)
            svg.parts.append('</g>')
        saved.append(_save(svg, output_dir / f"histogram_{param}.svg"))
    return saved


# ---- 4. Cross-flow comparison ----

def plot_cross_flow_comparison(result, config, output_dir):
    if len(result.all_flows) < 2:
        return []
    params = result.all_parameters
    if not params:
        return []
    all_m, all_s = [], []
    for fn in result.all_flows:
        for p in params:
            key = (fn, p)
            if key in result.parameter_stats:
                s = result.parameter_stats[key]
                all_m.append(s.mean)
                all_s.append(s.std)
    if not all_m:
        return []
    y_min = min(m - s for m, s in zip(all_m, all_s))
    y_max = max(m + s for m, s in zip(all_m, all_s))
    pad = (y_max - y_min) * 0.25 or 0.1
    y_min -= pad
    y_max += pad
    n_p = len(params)
    n_f = len(result.all_flows)
    W, H = 900, 450
    ml, mr, mt, mb = 70, 30, 55, 130
    pl, pr_w, pt, pb = ml, W - mr, mt, H - mb
    pw, ph = pr_w - pl, pb - pt
    svg = SVG(W, H)
    svg.title("Cross-Flow Comparison - Mean +/- Std Dev")
    svg.line(pl, pb, pr_w, pb)
    _y_axis(svg, y_min, y_max, pl, pr_w, pt, pb)
    svg.text(14, H / 2, "Mean Value (+/-Std Dev)", fs=11, fill=C_GRAY,
             transform=f"rotate(-90,14,{H/2})", anchor="middle")
    group_w = pw / n_p
    bar_w = group_w * 0.75 / n_f
    y_zero = _ys(max(0.0, y_min), y_min, y_max, pt, pb)
    for pi, param in enumerate(params):
        for fi, fn in enumerate(result.all_flows):
            key = (fn, param)
            if key not in result.parameter_stats:
                continue
            s = result.parameter_stats[key]
            color = FLOW_COLORS[fi % len(FLOW_COLORS)]
            x = pl + pi * group_w + fi * bar_w + group_w * 0.125
            ym = _ys(s.mean, y_min, y_max, pt, pb)
            bar_h = abs(ym - y_zero)
            bar_top = min(ym, y_zero)
            svg.rect(x, bar_top, bar_w, bar_h, fill=color, opacity=0.82)
            if s.std > 0:
                yt = _ys(s.mean + s.std, y_min, y_max, pt, pb)
                yb = _ys(s.mean - s.std, y_min, y_max, pt, pb)
                xm = x + bar_w / 2
                svg.line(xm, yt, xm, yb, stroke=C_DARK, sw=1.5)
                svg.line(xm - 3, yt, xm + 3, yt, stroke=C_DARK)
                svg.line(xm - 3, yb, xm + 3, yb, stroke=C_DARK)
        lx = pl + pi * group_w + group_w / 2
        svg.text(lx, pb + 12, param, fs=10, anchor="end",
                 transform=f"rotate(-40,{lx:.1f},{pb + 12})")
    for fi, fn in enumerate(result.all_flows):
        svg.rect(pl + fi * 110, pt - 28, 12, 12,
                 fill=FLOW_COLORS[fi % len(FLOW_COLORS)], opacity=0.82)
        svg.text(pl + fi * 110 + 15, pt - 19, fn, fs=10)
    return [_save(svg, output_dir / "cross_flow_comparison.svg")]


# ---- 5. Cpk summary ----

def plot_cpk_summary(result, config, output_dir):
    saved = []
    for flow_name in result.all_flows:
        params, cpk_vals = [], []
        for param in result.all_parameters:
            key = (flow_name, param)
            if key in result.parameter_stats:
                s = result.parameter_stats[key]
                if s.cpk is not None:
                    params.append(param)
                    cpk_vals.append(s.cpk)
        if not params:
            continue
        y_max = max(max(cpk_vals), config.cpk_threshold) * 1.25
        y_min = min(0.0, min(cpk_vals)) - 0.15
        n = len(params)
        W, H = 900, 450
        ml, mr, mt, mb = 60, 120, 55, 120
        pl, pr_w, pt, pb = ml, W - mr, mt, H - mb
        pw, ph = pr_w - pl, pb - pt
        svg = SVG(W, H)
        svg.title(f"Process Capability (Cpk) - {flow_name}")
        svg.line(pl, pb, pr_w, pb)
        _y_axis(svg, y_min, y_max, pl, pr_w, pt, pb)
        svg.text(14, H / 2, "Cpk", fs=11, fill=C_GRAY,
                 transform=f"rotate(-90,14,{H/2})", anchor="middle")
        bw = pw / n * 0.72
        y_zero = _ys(0.0, y_min, y_max, pt, pb)
        for i, (param, cpk) in enumerate(zip(params, cpk_vals)):
            x = pl + i * pw / n + (pw / n - bw) / 2
            color = C_PASS if cpk >= config.cpk_threshold else (C_WARN if cpk >= 1.0 else C_FAIL)
            yc = _ys(cpk, y_min, y_max, pt, pb)
            bar_h = abs(yc - y_zero)
            bar_top = min(yc, y_zero)
            svg.rect(x, bar_top, bw, bar_h, fill=color, opacity=0.87)
            svg.text(x + bw / 2, bar_top - 6 if cpk >= 0 else y_zero + 14,
                     f"{cpk:.2f}", fs=9, fw="bold", anchor="middle")
            lx, ly = x + bw / 2, pb + 10
            svg.text(lx, ly, param, fs=10, anchor="end",
                     transform=f"rotate(-40,{lx:.1f},{ly:.1f})")
        yt = _ys(config.cpk_threshold, y_min, y_max, pt, pb)
        svg.line(pl, yt, pr_w, yt, stroke="#27ae60", sw=1.8, dash="8,4")
        svg.text(pr_w + 4, yt + 4, f"Target ({config.cpk_threshold})", fs=9, fill="#27ae60")
        y1 = _ys(1.0, y_min, y_max, pt, pb)
        svg.line(pl, y1, pr_w, y1, stroke=C_WARN, sw=1.5, dash="4,4")
        svg.text(pr_w + 4, y1 + 4, "1.0", fs=9, fill=C_WARN)
        saved.append(_save(svg, output_dir / f"cpk_summary_{flow_name}.svg"))
    return saved


# ---- 6. Per-DUT scatter ----

def plot_scatter_by_dut(result, config, output_dir):
    saved = []
    for param in result.all_parameters:
        spec_min, spec_max, unit_str = None, None, ""
        fpdata = []
        for flow_name in result.all_flows:
            key = (flow_name, param)
            if key not in result.parameter_stats:
                continue
            s = result.parameter_stats[key]
            if s.spec_min is not None:
                spec_min = s.spec_min
            if s.spec_max is not None:
                spec_max = s.spec_max
            if s.unit:
                unit_str = f" ({s.unit})"
            fd = result.flow_data[flow_name]
            dv = {}
            for row in fd.get_parameter_rows(param):
                dut = str(row.get("DUT_ID", "DUT"))
                v = row.get("Value")
                if v is not None:
                    try:
                        dv[dut] = float(v)
                    except (ValueError, TypeError):
                        pass
            if dv:
                fpdata.append((flow_name, dv))
        if not fpdata:
            continue
        all_vals = [v for _, dv in fpdata for v in dv.values()]
        y_min, y_max = _pct_range(all_vals)
        if spec_min is not None:
            y_min = min(y_min, spec_min)
            y_max = max(y_max, spec_min)
        if spec_max is not None:
            y_max = max(y_max, spec_max)
            y_min = min(y_min, spec_max)
        pad = (y_max - y_min) * 0.25 or 0.1
        y_min -= pad
        y_max += pad
        all_duts = sorted({d for _, dv in fpdata for d in dv})
        dut2x = {d: i for i, d in enumerate(all_duts)}
        n_duts = len(all_duts)
        W = max(900, 28 * n_duts + 150)
        H = 450
        ml, mr, mt, mb = 70, 30, 55, 90
        pl, pr_w, pt, pb = ml, W - mr, mt, H - mb
        pw, ph = pr_w - pl, pb - pt
        svg = SVG(W, H)
        svg.title(f"{param} - Per-DUT Results{unit_str}")
        svg.line(pl, pb, pr_w, pb)
        _y_axis(svg, y_min, y_max, pl, pr_w, pt, pb)
        svg.text(14, H / 2, f"Value{unit_str}", fs=11, fill=C_GRAY,
                 transform=f"rotate(-90,14,{H/2})", anchor="middle")
        for fi, (fn, dv) in enumerate(fpdata):
            offset = fi * 3
            for dut, val in dv.items():
                xi = dut2x[dut]
                x = pl + (xi + 0.5) * pw / max(n_duts, 1) + offset
                y = _ys(val, y_min, y_max, pt, pb)
                passed = not ((spec_min is not None and val < spec_min) or
                              (spec_max is not None and val > spec_max))
                svg.circle(x, y, 4, fill=C_PASS if passed else C_FAIL, opacity=0.78)
        step = max(1, n_duts // 20)
        for dut in all_duts[::step]:
            xi = dut2x[dut]
            x = pl + (xi + 0.5) * pw / max(n_duts, 1)
            svg.text(x, pb + 16, str(dut), fs=8, anchor="end",
                     transform=f"rotate(-45,{x:.1f},{pb + 16})")
        if _SHOW_SPEC_LINES:
            svg.parts.append('<g class="spec-el">')
            if spec_min is not None:
                svg.line(pl, _ys(spec_min, y_min, y_max, pt, pb),
                         pr_w, _ys(spec_min, y_min, y_max, pt, pb),
                         stroke=C_SPEC, sw=4)
            if spec_max is not None:
                svg.line(pl, _ys(spec_max, y_min, y_max, pt, pb),
                         pr_w, _ys(spec_max, y_min, y_max, pt, pb),
                         stroke=C_SPEC, sw=4)
            svg.parts.append('</g>')
        for fi, (fn, _) in enumerate(fpdata):
            svg.circle(pl + fi * 100 + 6, pt - 22, 5,
                       fill=FLOW_COLORS[fi % len(FLOW_COLORS)], opacity=0.78)
            svg.text(pl + fi * 100 + 14, pt - 18, fn, fs=10)
        nleg = len(fpdata)
        svg.circle(pl + nleg * 100 + 6, pt - 22, 5, fill=C_PASS, opacity=0.78)
        svg.text(pl + nleg * 100 + 14, pt - 18, "Pass", fs=10)
        svg.circle(pl + (nleg + 1) * 100 + 6, pt - 22, 5, fill=C_FAIL, opacity=0.78)
        svg.text(pl + (nleg + 1) * 100 + 14, pt - 18, "Fail", fs=10)
        saved.append(_save(svg, output_dir / f"scatter_dut_{param}.svg"))
    return saved


# ---- Entry point ----

def _parse_condition(cond: str) -> dict:
    """Parse 'T=20C VIO=1.8V VCORE=0.8V SKW=sstt' into a dict."""
    out = {}
    for tok in cond.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = v.rstrip("VC").rstrip("c")
    return out


def _try_float_val(s):
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


IO_TYPE_LABEL = {
    "GPIO_0":   "PB16DSFS_18_18_H",
    "BRI_DT":   "PB16DSFS_18_18_H",
    "RF_KILLN": "PB12DSFS_18_T33_H",
}


def plot_section_line_chart(all_rows, measurement_suffix, test_name,
                             io_name, spec_min, spec_max, unit,
                             worst_agg, output_path,
                             io_type_label="", ds_label="", force_corner=False,
                             chart_type="line"):
    """
    Line chart matching the Excel pivot chart style.

    DS tests:
      X-axis  = Temperature groups (primary) × DS setting (sub-ticks)
      Lines   = one per Skew material
      Dot tooltip = chip ID of worst-case DUT for that point

    Non-DS tests:
      X-axis  = Temperature groups (primary) × VIO/VCORE corner (sub-ticks)
      Lines   = one per Skew material
      Dot tooltip = chip ID of worst-case DUT
    """
    _PALETTE = [
        "#3498db", "#e74c3c", "#2ecc71", "#9b59b6",
        "#e67e22", "#1abc9c", "#c0392b", "#2980b9",
        "#27ae60", "#8e44ad", "#d35400", "#16a085",
    ]
    _DASHES = ["", "8,3", "4,3", "10,3,3,3"]

    param_name = f"{io_name}_{measurement_suffix}"
    relevant = [
        r for r in all_rows
        if r.get("Parameter") == param_name
        and r.get("Test_Name") == test_name
        and r.get("IO_Name") == io_name
    ]
    if not relevant:
        return None

    unit = unit or next((r.get("Unit", "") for r in relevant if r.get("Unit")), "")

    def safe_float(v):
        if v is None:
            return None
        try:
            f = float(v)
            return None if f != f or abs(f) == float("inf") else f
        except (ValueError, TypeError):
            return None

    def wcase_with_id(rows_subset):
        """Return (worst_value, chip_id) or (None, None)."""
        pairs = [(safe_float(r.get("Value")), str(r.get("DUT_ID", "")))
                 for r in rows_subset]
        pairs = [(v, cid) for v, cid in pairs if v is not None]
        if not pairs:
            return None, None
        if worst_agg == "max":
            return max(pairs, key=lambda x: x[0])
        if worst_agg == "min":
            return min(pairs, key=lambda x: x[0])
        avg = sum(v for v, _ in pairs) / len(pairs)
        return avg, pairs[0][1]

    has_ds = any(r.get("DS", "") for r in relevant)

    # ── DS-based chart ─────────────────────────────────────────────────────────
    if has_ds and not force_corner:
        def ds_sort_key(s):
            try:
                return int(s.replace("DS_", "").replace("ds_", ""))
            except ValueError:
                return 999

        all_temps = sorted(
            {r.get("Temperature", "?") for r in relevant},
            key=lambda t: _try_float_val(t)
        )
        all_ds = sorted(
            {r.get("DS", "") for r in relevant if r.get("DS", "")},
            key=ds_sort_key
        )
        all_skews = sorted({r.get("Skew", "?") for r in relevant})
        if not all_ds:
            return None

        def _viocore_key(r):
            """Return 'VCORE/VIO' string, e.g. '0.8/1.8'."""
            c = _parse_condition(r.get("Test_Condition", ""))
            vcor = c.get("VCORE", "?")
            vio  = c.get("VIO", "?")
            return f"{vcor}/{vio}"

        all_viocore = sorted(
            {_viocore_key(r) for r in relevant},
            key=lambda s: _try_float_val(s.split("/")[0])
        )

        # Group: {(viocore, temp, ds, skew, chip_id): [values]}
        # Also capture per-(temp,ds) spec (e.g. resistance spec varies per DS)
        grp: dict = {}
        ds_spec_max_map: dict = {}  # (temp, ds) -> spec_max
        ds_spec_min_map: dict = {}  # (temp, ds) -> spec_min
        for r in relevant:
            fv = safe_float(r.get("Value"))
            if fv is None or not r.get("DS"):
                continue
            vc   = _viocore_key(r)
            temp = r.get("Temperature", "?")
            ds   = r.get("DS", "")
            skew = r.get("Skew", "?")
            chip = str(r.get("DUT_ID", "?"))
            grp.setdefault((vc, temp, ds, skew, chip), []).append(fv)
            pair = (temp, ds)
            for attr, target in [("Spec_Max", ds_spec_max_map),
                                  ("Spec_Min", ds_spec_min_map)]:
                if pair not in target:
                    sv = r.get(attr)
                    if sv is not None:
                        try:
                            v = float(sv)
                            if v and v == v and abs(v) != float("inf"):
                                target[pair] = v
                        except (ValueError, TypeError):
                            pass

        # One series per (viocore, skew, chip_id) — all chips shown individually
        all_series_keys = sorted(
            {(vc, sk, ch) for vc, _t, _d, sk, ch in grp},
            key=lambda x: (x[1], x[2], x[0])  # skew, chip, viocore
        )
        if not all_series_keys:
            return None

        def _pick(vals):
            if not vals: return None
            if worst_agg == "max": return max(vals)
            if worst_agg == "min": return min(vals)
            return sum(vals) / len(vals)

        # X-axis: (temp, ds) pairs grouped by temperature
        x_pairs = [(t, d) for t in all_temps for d in all_ds]
        n = len(x_pairs)

        # Per-(vc, sk, chip) series: one value per x_pair
        series = {
            key: [_pick(grp.get((key[0], t, d, key[1], key[2]), [])) for t, d in x_pairs]
            for key in all_series_keys
        }

        all_vals = [v for pts in series.values() for v in pts if v is not None]
        if not all_vals:
            return None

        W, H = _CHART_W, _CHART_H
        ml, mr, mt, mb = _CHART_ML, _CHART_LEG, _CHART_MT, _CHART_MB
        pl, pr, pt_y, pb = ml, W - mr, mt, H - mb
        pw = pr - pl

        y_min, y_max = _pct_range(all_vals)
        if spec_min is not None and spec_min == spec_min:
            y_min = min(y_min, spec_min)
            y_max = max(y_max, spec_min)
        if spec_max is not None and spec_max == spec_max:
            y_max = max(y_max, spec_max)
            y_min = min(y_min, spec_max)
        # Always include per-DS spec values so they stay within the visible y-range
        for _v in ds_spec_max_map.values():
            if _v == _v and abs(_v) != float("inf"):
                y_max = max(y_max, _v)
        for _v in ds_spec_min_map.values():
            if _v == _v and abs(_v) != float("inf"):
                y_min = min(y_min, _v)
        # Current reference levels for IOL_A/IOH_A (IO_SPEC.pdf Table 18/20)
        # PB16 (GPIO_0): DS_0=1mA, DS_1=2mA, ..., DS_15=16mA
        # PB12 (RF_KILLN): DS_0=2mA, DS_1=4mA, DS_2=8mA, DS_3=12mA
        _ds_current_ref: dict = {}
        if measurement_suffix in ("IOL_A", "IOH_A"):
            _is_pb12_ref = io_name.upper().strip() == "RF_KILLN"
            _curr_table = [2, 4, 8, 12] if _is_pb12_ref else list(range(1, 17))
            for _t, _d in x_pairs:
                try:
                    _ds_idx = int(str(_d).replace("DS_", "").replace("ds_", ""))
                    if 0 <= _ds_idx < len(_curr_table):
                        _ds_current_ref[(_t, _d)] = float(_curr_table[_ds_idx])
                except (ValueError, TypeError):
                    pass
            for _cv in _ds_current_ref.values():
                y_max = max(y_max, _cv)
        span = y_max - y_min
        y_min -= (span * 0.25 or 0.05)
        y_max += (span * 0.25 or 0.05)

        unit_str = f" ({unit})" if unit else ""
        io_type_str = f"  [{io_type_label}]" if io_type_label else ""
        svg = SVG(W, H)
        svg.title(f"{io_name}{io_type_str} — {measurement_suffix}{unit_str} [{test_name}]")
        svg.line(pl, pb, pr, pb)
        svg.line(pl, pt_y, pl, pb)
        _y_axis(svg, y_min, y_max, pl, pr, pt_y, pb)
        svg.text(14, (pt_y + pb) / 2, f"{measurement_suffix}{unit_str}",
                 fs=10, fill=C_GRAY,
                 transform=f"rotate(-90,14,{(pt_y + pb) / 2:.1f})", anchor="middle")

        x_step = pw / n if n > 0 else pw

        # X-axis: DS sub-tick labels + Temperature group separators/headers
        prev_temp = None
        for i, (temp, ds) in enumerate(x_pairs):
            x = pl + (i + 0.5) * x_step
            svg.text(x, pb + 15, ds, fs=8, anchor="middle", fill=C_GRAY)
            if temp != prev_temp:
                if i > 0:
                    svg.line(pl + i * x_step, pt_y, pl + i * x_step, pb,
                             stroke="#cccccc", sw=1, dash="4,3")
                prev_temp = temp
        # Temperature group headers
        for i, (temp, _) in enumerate(x_pairs):
            if i == 0 or x_pairs[i-1][0] != temp:
                end = next((j for j in range(i, n) if x_pairs[j][0] != temp), n) - 1
                xc = pl + (i + end + 1) / 2 * x_step
                svg.text(xc, pt_y - 10, f"T={temp}°C", fs=10, fw="bold",
                         anchor="middle", fill=C_DARK)
        svg.text(pl + pw / 2, pb + 34, "Temperature  /  Drive Strength (DS)",
                 fs=11, anchor="middle", fill=C_DARK)

        # Lines — one per (viocore, skew, chip_id)
        for si, (vc, skew, chip) in enumerate(all_series_keys):
            color     = _PALETTE[si % len(_PALETTE)]
            dash      = _DASHES[si % len(_DASHES)]
            vc_safe   = str(vc).replace('"', '')
            s_safe    = str(skew).replace('"', '')
            chip_safe = str(chip).replace('"', '')
            svg.parts.append(
                f'<g class="series" data-viocore="{vc_safe}" '
                f'data-skew="{s_safe}" data-chip="{chip_safe}">'
            )
            pts_xy = [
                (pl + (i + 0.5) * x_step, _ys(v, y_min, y_max, pt_y, pb))
                for i, v in enumerate(series[(vc, skew, chip)])
                if v is not None
            ]
            if len(pts_xy) >= 2:
                d_path = " ".join(
                    f"{'M' if j == 0 else 'L'}{x:.1f},{y:.1f}"
                    for j, (x, y) in enumerate(pts_xy)
                )
                dash_attr = f'stroke-dasharray="{dash}" ' if dash else ""
                svg.parts.append(
                    f'<path d="{d_path}" fill="none" stroke="{color}" '
                    f'stroke-width="2.0" stroke-linejoin="round" '
                    f'{dash_attr}opacity="0.85"/>'
                )
            for x, y in pts_xy:
                tip = f"{io_name} {measurement_suffix} | {vc} | {skew} | Chip: {chip}"
                svg.parts.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" '
                    f'fill="{color}" opacity="0.9">'
                    f'<title>{tip}</title></circle>'
                )
            svg.parts.append('</g>')

        # Spec lines: per-DS variable (e.g. resistance) — always drawn if available
        _spec_leg = []  # entries for corner legend: (color, dash, label)
        _drawn_spec_dirs = set()  # track which directions (min/max) got a variable spec line
        if not _SHOW_SPEC_LINES:
            ds_spec_max_map = {}
            ds_spec_min_map = {}
            _ds_current_ref = {}
            spec_min = None
            spec_max = None
        svg.parts.append('<g class="spec-el">')
        for smap, lbl, sdash, direction in [(ds_spec_max_map, "Max spec", "4,4", "max"),
                                             (ds_spec_min_map, "Min spec", "8,4", "min")]:
            if not smap:
                continue
            valid_pts = [
                (pl + (i + 0.5) * x_step, smap[pair])
                for i, pair in enumerate(x_pairs)
                if pair in smap and y_min <= smap[pair] <= y_max
            ]
            if len(valid_pts) >= 2:
                d_path = " ".join(
                    f"{'M' if j == 0 else 'L'}{x:.1f},{_ys(v, y_min, y_max, pt_y, pb):.1f}"
                    for j, (x, v) in enumerate(valid_pts)
                )
                svg.parts.append(
                    f'<path d="{d_path}" fill="none" stroke="{C_SPEC}" '
                    f'stroke-width="4" opacity="1.0"/>'
                )
                _spec_leg.append((C_SPEC, None, lbl))
                _drawn_spec_dirs.add(direction)
        # Fixed horizontal spec lines — always drawn when spec is defined and not
        # already covered by a per-DS variable line in the same direction
        for spec_val, lbl, sdash, direction in [
            (spec_min, "Min spec", "8,4", "min"),
            (spec_max, "Max spec", "4,4", "max"),
        ]:
            if spec_val is None or spec_val != spec_val:
                continue
            if direction in _drawn_spec_dirs:
                continue
            if not (y_min <= spec_val <= y_max):
                continue
            ys = _ys(spec_val, y_min, y_max, pt_y, pb)
            svg.line(pl, ys, pr, ys, stroke=C_SPEC, sw=4)
            _spec_leg.append((C_SPEC, None, f"{lbl}: {spec_val:.3g}"))

        # Nominal test-current reference line (IO_SPEC.pdf Table 18/20)
        # Use same C_SPEC colour so it appears as an orange spec line on IOH/IOL
        _C_IREF = C_SPEC
        _pb12_lbl = io_name.upper().strip() == "RF_KILLN"
        if _ds_current_ref:
            _curr_pts = [
                (pl + (i + 0.5) * x_step, _ds_current_ref[(t, d)])
                for i, (t, d) in enumerate(x_pairs)
                if (t, d) in _ds_current_ref and y_min <= _ds_current_ref[(t, d)] <= y_max
            ]
            if len(_curr_pts) >= 2:
                _iref_path = " ".join(
                    f"{'M' if j == 0 else 'L'}{x:.1f},{_ys(v, y_min, y_max, pt_y, pb):.1f}"
                    for j, (x, v) in enumerate(_curr_pts)
                )
                svg.parts.append(
                    f'<path d="{_iref_path}" fill="none" stroke="{_C_IREF}" '
                    f'stroke-width="4" opacity="1.0"/>'
                )
                _spec_leg.append((_C_IREF, None,
                                   f"{'PB12' if _pb12_lbl else 'PB16'} Test I (mA)"))

        # ── Corner legend box for spec / reference lines (top-left of plot area) ──
        if _spec_leg:
            _blx = pl + 8
            _bly = pt_y + 8
            _bw  = 192
            _bh  = 10 + len(_spec_leg) * 20
            svg.parts.append(
                f'<rect x="{_blx}" y="{_bly}" width="{_bw}" height="{_bh}" '
                f'fill="white" fill-opacity="0.88" stroke="#cccccc" '
                f'stroke-width="0.8" rx="4"/>'
            )
            for _ei, (_ec, _ed, _et) in enumerate(_spec_leg):
                _ley = _bly + 16 + _ei * 20
                _da  = f'stroke-dasharray="{_ed}" ' if _ed else ""
                svg.parts.append(
                    f'<line x1="{_blx+6}" y1="{_ley-5}" x2="{_blx+30}" y2="{_ley-5}" '
                    f'stroke="{_ec}" stroke-width="4" {_da}/>'
                )
                svg.parts.append(
                    f'<text x="{_blx+34}" y="{_ley}" font-size="10" '
                    f'font-weight="bold" font-family="Arial,sans-serif" '
                    f'fill="{_ec}">{_esc(_et)}</text>'
                )

        svg.parts.append('</g>')  # close spec-el group

        # Legend — one entry per (viocore, skew, chip)
        for si, (vc, skew, chip) in enumerate(all_series_keys):
            ly        = mt + si * 22
            color     = _PALETTE[si % len(_PALETTE)]
            dash      = _DASHES[si % len(_DASHES)]
            lx        = W - mr + 8
            vc_safe   = str(vc).replace('"', '')
            s_safe    = str(skew).replace('"', '')
            chip_safe = str(chip).replace('"', '')
            dash_attr = f'stroke-dasharray="{dash}" ' if dash else ""
            lbl_text  = f"{chip} | {skew}"
            svg.parts.append(
                f'<g class="legend-item" data-viocore="{vc_safe}" '
                f'data-skew="{s_safe}" data-chip="{chip_safe}">'
            )
            svg.parts.append(
                f'<line x1="{lx}" y1="{ly+5}" x2="{lx+28}" y2="{ly+5}" '
                f'stroke="{color}" stroke-width="2.0" {dash_attr}/>'
            )
            svg.parts.append(f'<circle cx="{lx+14}" cy="{ly+5}" r="4" fill="{color}"/>')
            svg.parts.append(
                f'<text x="{lx+32}" y="{ly+9}" font-size="10" '
                f'font-family="Arial,sans-serif" fill="{C_DARK}">{_esc(lbl_text)}</text>'
            )
            svg.parts.append('</g>')

        return _save(svg, output_path)

    # ── Corner-based chart (no DS) ──────────────────────────────────────────────
    parse = _parse_condition

    # Group: {(temp, vio, vcore, skew, chip_id): [values]}
    corner_grp: dict = {}
    for r in relevant:
        fv = safe_float(r.get("Value"))
        if fv is None:
            continue
        c    = parse(r.get("Test_Condition", ""))
        temp = c.get("T", "?")
        vio  = c.get("VIO", "?")
        vcor = c.get("VCORE", "?")
        skew = r.get("Skew", "") or c.get("SKW", "?")
        chip = str(r.get("DUT_ID", "?"))
        corner_grp.setdefault((temp, vio, vcor, skew, chip), []).append(fv)

    all_conds = sorted(
        {(t, v, vc) for t, v, vc, _sk, _ch in corner_grp},
        key=lambda x: (_try_float_val(x[0]), _try_float_val(x[1]), _try_float_val(x[2]))
    )
    if not all_conds:
        return None

    # Dynamic spec: for VOH, spec_min = 0.75 × VIO at each corner condition
    dynamic_spec_min: dict = {}  # {(t, vio, vcor): float}
    if measurement_suffix == "VOH":
        for (t, vio, vcor) in all_conds:
            try:
                dynamic_spec_min[(t, vio, vcor)] = 0.75 * float(vio)
            except (ValueError, TypeError):
                pass

    all_series_corner = sorted(
        {(sk, ch) for _t, _v, _vc, sk, ch in corner_grp},
        key=lambda x: (x[0], x[1])
    )
    ns = len(all_series_corner)

    def _pick_c(vals):
        if not vals: return None
        if worst_agg == "max": return max(vals)
        if worst_agg == "min": return min(vals)
        return sum(vals) / len(vals)

    series_corner = {
        (sk, ch): [_pick_c(corner_grp.get((t, v, vc, sk, ch), [])) for t, v, vc in all_conds]
        for sk, ch in all_series_corner
    }

    all_vals = [v for pts in series_corner.values() for v in pts if v is not None]
    if not all_vals:
        return None

    n = len(all_conds)
    W, H = _CHART_W, _CHART_H
    ml, mr, mt, mb = _CHART_ML, _CHART_LEG, _CHART_MT, _CHART_MB
    pl, pr, pt_y, pb = ml, W - mr, mt, H - mb
    pw = pr - pl

    y_min, y_max = _pct_range(all_vals)
    if dynamic_spec_min:
        dyn_vals = list(dynamic_spec_min.values())
        y_min = min(y_min, min(dyn_vals))
        y_max = max(y_max, max(dyn_vals))
    elif spec_min is not None and spec_min == spec_min:
        y_min = min(y_min, spec_min)
        y_max = max(y_max, spec_min)
    if spec_max is not None and spec_max == spec_max:
        y_max = max(y_max, spec_max)
        y_min = min(y_min, spec_max)
    span = y_max - y_min
    y_min -= (span * 0.25 or 0.05)
    y_max += (span * 0.25 or 0.05)

    unit_str = f" ({unit})" if unit else ""
    io_type_str = f"  [{io_type_label}]" if io_type_label else ""
    ds_str = f"  DS={ds_label}" if ds_label else ""
    svg = SVG(W, H)
    svg.title(f"{io_name}{io_type_str} — {measurement_suffix}{unit_str}{ds_str}  [{test_name}]")
    svg.line(pl, pb, pr, pb)
    svg.line(pl, pt_y, pl, pb)
    _y_axis(svg, y_min, y_max, pl, pr, pt_y, pb)
    svg.text(14, (pt_y + pb) / 2, f"{measurement_suffix}{unit_str}",
             fs=10, fill=C_GRAY,
             transform=f"rotate(-90,14,{(pt_y + pb) / 2:.1f})", anchor="middle")

    x_step = pw / n if n > 0 else pw

    # X-axis: VIO/VCORE sub-ticks + Temperature group separators/headers
    prev_temp = None
    for i, (temp, vio, vcor) in enumerate(all_conds):
        if temp != prev_temp:
            if i > 0:
                svg.line(pl + i * x_step, pt_y, pl + i * x_step, pb,
                         stroke="#cccccc", sw=1, dash="4,3")
            prev_temp = temp
        x = pl + (i + 0.5) * x_step
        svg.text(x, pb + 14, f"VIO={vio}\nVC={vcor}", fs=8, anchor="end",
                 transform=f"rotate(-45,{x:.1f},{pb + 14})")
    for i, (temp, _, _) in enumerate(all_conds):
        if i == 0 or all_conds[i-1][0] != temp:
            end = next((j for j in range(i, n) if all_conds[j][0] != temp), n) - 1
            xc = pl + (i + end + 1) / 2 * x_step
            svg.text(xc, pt_y - 10, f"T={temp}°C", fs=10, fw="bold",
                     anchor="middle", fill=C_DARK)

    # Series — lines (default) or columns per (skew, chip_id)
    _bar_group_w = x_step * 0.82
    _bar_w = _bar_group_w / ns if ns > 0 else x_step
    for si, (skew, chip) in enumerate(all_series_corner):
        color     = _PALETTE[si % len(_PALETTE)]
        dash      = _DASHES[si % len(_DASHES)]
        s_safe    = str(skew).replace('"', '')
        chip_safe = str(chip).replace('"', '')
        svg.parts.append(
            f'<g class="series" data-skew="{s_safe}" data-chip="{chip_safe}">'
        )
        pts_xy = []
        for i, (t, v, vc) in enumerate(all_conds):
            val = _pick_c(corner_grp.get((t, v, vc, skew, chip), []))
            if val is None:
                continue
            xp = pl + (i + 0.5) * x_step
            yp = _ys(val, y_min, y_max, pt_y, pb)
            pts_xy.append((i, xp, yp, val))
        if chart_type == "column":
            for i, xp, yp, val in pts_xy:
                bx = pl + i * x_step + (x_step - _bar_group_w) / 2 + si * _bar_w
                bar_h = max(pb - yp, 0)
                svg.rect(bx, yp, _bar_w - 1, bar_h, fill=color, opacity=0.82)
                tip = f"{io_name} {measurement_suffix} | {skew} | Chip: {chip} | {val:.3g}"
                svg.parts.append(
                    f'<rect x="{bx:.1f}" y="{yp:.1f}" width="{max(_bar_w-1,0):.1f}" '
                    f'height="{max(bar_h,0):.1f}" fill="none" stroke="none">'
                    f'<title>{tip}</title></rect>'
                )
        else:
            line_pts = [(xp, yp) for _, xp, yp, _ in pts_xy]
            if len(line_pts) >= 2:
                d_path = " ".join(f"{'M' if j == 0 else 'L'}{x:.1f},{y:.1f}"
                                  for j, (x, y) in enumerate(line_pts))
                dash_attr = f'stroke-dasharray="{dash}" ' if dash else ""
                svg.parts.append(
                    f'<path d="{d_path}" fill="none" stroke="{color}" '
                    f'stroke-width="2.0" stroke-linejoin="round" '
                    f'{dash_attr}opacity="0.85"/>'
                )
            for _, xp, yp, val in pts_xy:
                tip = f"{io_name} {measurement_suffix} | {skew} | Chip: {chip}"
                svg.parts.append(
                    f'<circle cx="{xp:.1f}" cy="{yp:.1f}" r="5" '
                    f'fill="{color}" opacity="0.9">'
                    f'<title>{tip}</title></circle>'
                )
        svg.parts.append('</g>')

    # Spec lines: dynamic stepped for VOH, fixed horizontal otherwise
    svg.parts.append('<g class="spec-el">')
    if _SHOW_SPEC_LINES and dynamic_spec_min:
        valid_pts_dyn = [
            (pl + (i + 0.5) * x_step, dynamic_spec_min[cond])
            for i, cond in enumerate(all_conds)
            if cond in dynamic_spec_min and y_min <= dynamic_spec_min[cond] <= y_max
        ]
        if len(valid_pts_dyn) >= 2:
            d_path = " ".join(
                f"{'M' if j == 0 else 'L'}{x:.1f},{_ys(v, y_min, y_max, pt_y, pb):.1f}"
                for j, (x, v) in enumerate(valid_pts_dyn)
            )
            svg.parts.append(
                f'<path d="{d_path}" fill="none" stroke="{C_SPEC}" '
                f'stroke-width="4" opacity="1.0"/>'
            )
            last_x, last_v = valid_pts_dyn[-1]
            svg.text(
                pr + 5, _ys(last_v, y_min, y_max, pt_y, pb) + 4,
                "VOH Min (0.75×VIO)", fs=9, fill=C_SPEC
            )
        if spec_max is not None and spec_max == spec_max and y_min <= spec_max <= y_max:
            ys = _ys(spec_max, y_min, y_max, pt_y, pb)
            svg.line(pl, ys, pr, ys, stroke=C_SPEC, sw=4)
            svg.text(pr + 5, ys + 4, f"Max spec: {spec_max:.3g}", fs=9, fill=C_SPEC)
    else:
        if _SHOW_SPEC_LINES:
            for spec_val, lbl, _sdash in [(spec_min, "Min spec", "8,4"),
                                          (spec_max, "Max spec", "4,4")]:
                if spec_val is not None and spec_val == spec_val and y_min <= spec_val <= y_max:
                    ys = _ys(spec_val, y_min, y_max, pt_y, pb)
                    svg.line(pl, ys, pr, ys, stroke=C_SPEC, sw=4)
                    svg.text(pr + 5, ys + 4, f"{lbl}: {spec_val:.3g}", fs=9, fill=C_SPEC)
    svg.parts.append('</g>')  # close spec-el

    # Legend — one entry per (skew, chip)
    for si, (skew, chip) in enumerate(all_series_corner):
        ly        = mt + si * 22
        color     = _PALETTE[si % len(_PALETTE)]
        dash      = _DASHES[si % len(_DASHES)]
        lx        = W - mr + 8
        s_safe    = str(skew).replace('"', '')
        chip_safe = str(chip).replace('"', '')
        dash_attr = f'stroke-dasharray="{dash}" ' if dash else ""
        lbl_text  = f"{chip} | {skew}"
        svg.parts.append(
            f'<g class="legend-item" data-skew="{s_safe}" data-chip="{chip_safe}">'
        )
        svg.parts.append(
            f'<line x1="{lx}" y1="{ly+5}" x2="{lx+28}" y2="{ly+5}" '
            f'stroke="{color}" stroke-width="2.0" {dash_attr}/>'
        )
        svg.parts.append(f'<circle cx="{lx+14}" cy="{ly+5}" r="5" fill="{color}"/>')
        svg.parts.append(
            f'<text x="{lx+32}" y="{ly+9}" font-size="10" '
            f'font-family="Arial,sans-serif" fill="{C_DARK}">{_esc(lbl_text)}</text>'
        )
        svg.parts.append('</g>')

    return _save(svg, output_path)

    # ── DS-based chart (iohmaxiolmax, voh vol, risefalltime) ──────────────────
    if has_ds:
        def ds_sort_key(s):
            try:
                return int(s.replace("DS_", "").replace("ds_", ""))
            except ValueError:
                return 999

        all_ds = sorted({r.get("DS", "") for r in relevant if r.get("DS", "")},
                        key=ds_sort_key)
        if not all_ds:
            return None

        # Group: (temp, skew, ds) -> list of values
        groups: dict = {}
        for r in relevant:
            fv = safe_float(r.get("Value"))
            if fv is None:
                continue
            temp = r.get("Temperature", "?")
            skew = r.get("Skew", "?")
            ds   = r.get("DS", "")
            if not ds:
                continue
            groups.setdefault((temp, skew, ds), []).append(fv)

        # Unique (temp, skew) series — sorted by temp numeric then skew alpha
        all_series = sorted(
            {(t, s) for t, s, _d in groups},
            key=lambda x: (_try_float_val(x[0]), x[1])
        )

        # Build series data: (temp, skew) -> [worst-case per ds]
        series_data = {
            (t, s): [wcase(groups.get((t, s, d), [])) for d in all_ds]
            for t, s in all_series
        }

        all_vals = [v for pts in series_data.values() for v in pts if v is not None]
        if not all_vals:
            return None

        n = len(all_ds)
        ns = len(all_series)
        mr = max(175, ns * 0 + 40 + max((len(f"T={t}°C  {s}") for t, s in all_series), default=10) * 7)
        W = max(1000, n * 54 + 90 + mr)
        H = max(460, ns * 22 + 130)
        ml, mt, mb = 82, 64, 60
        pl, pr, pt_y, pb = ml, W - mr, mt, H - mb
        pw = pr - pl

        y_min, y_max = min(all_vals), max(all_vals)
        if spec_min is not None and spec_min == spec_min:
            y_min = min(y_min, spec_min)
            y_max = max(y_max, spec_min)
        if spec_max is not None and spec_max == spec_max:
            y_max = max(y_max, spec_max)
            y_min = min(y_min, spec_max)
        span = y_max - y_min
        y_min -= (span * 0.25 or 0.05)
        y_max += (span * 0.25 or 0.05)

        unit_str = f" ({unit})" if unit else ""
        svg = SVG(W, H)
        svg.title(f"{io_name} — {measurement_suffix}{unit_str} vs DS  [{test_name}]")
        svg.line(pl, pb, pr, pb)
        svg.line(pl, pt_y, pl, pb)
        _y_axis(svg, y_min, y_max, pl, pr, pt_y, pb)
        svg.text(14, (pt_y + pb) / 2, f"{measurement_suffix}{unit_str}",
                 fs=10, fill=C_GRAY,
                 transform=f"rotate(-90,14,{(pt_y + pb) / 2:.1f})", anchor="middle")

        x_step = pw / n if n > 0 else pw
        for i, ds in enumerate(all_ds):
            x = pl + (i + 0.5) * x_step
            svg.text(x, pb + 16, ds, fs=9, anchor="middle", fill=C_GRAY)
        svg.text(pl + pw / 2, pb + 34, "Drive Strength (DS)", fs=11,
                 anchor="middle", fill=C_DARK)

        # Lines — one per (temp, skew), each wrapped in a filterable <g>
        for si, (temp, skew) in enumerate(all_series):
            color = _PALETTE[si % len(_PALETTE)]
            dash  = _DASHES[si % len(_DASHES)]
            pts_xy = [
                (pl + (i + 0.5) * x_step, _ys(v, y_min, y_max, pt_y, pb))
                for i, v in enumerate(series_data[(temp, skew)])
                if v is not None
            ]
            t_safe = str(temp).replace('"', '')
            s_safe = str(skew).replace('"', '')
            svg.parts.append(
                f'<g class="series" data-temp="{t_safe}" data-skew="{s_safe}">'
            )
            if len(pts_xy) >= 2:
                d = " ".join(
                    f"{'M' if j == 0 else 'L'}{x:.1f},{y:.1f}"
                    for j, (x, y) in enumerate(pts_xy)
                )
                dash_attr = f'stroke-dasharray="{dash}" ' if dash else ""
                svg.parts.append(
                    f'<path d="{d}" fill="none" stroke="{color}" '
                    f'stroke-width="2.2" stroke-linejoin="round" '
                    f'{dash_attr}opacity="0.9"/>'
                )
            for x, y in pts_xy:
                svg.parts.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" '
                    f'fill="{color}" opacity="0.95"/>'
                )
            svg.parts.append('</g>')

        # Spec lines
        svg.parts.append('<g class="spec-el">')
        if _SHOW_SPEC_LINES:
            for spec_val, lbl, _sdash in [(spec_min, "Min spec", "8,4"),
                                          (spec_max, "Max spec", "4,4")]:
                if spec_val is not None and spec_val == spec_val:
                    if y_min <= spec_val <= y_max:
                        ys = _ys(spec_val, y_min, y_max, pt_y, pb)
                        svg.line(pl, ys, pr, ys, stroke=C_SPEC, sw=4)
                        svg.text(pr + 5, ys + 4, f"{lbl}: {spec_val:.3g}",
                                 fs=9, fill=C_SPEC)
        svg.parts.append('</g>')  # close spec-el

        # Legend — (temp, skew) series, also wrapped for filtering
        for si, (temp, skew) in enumerate(all_series):
            ly = mt + si * 22
            color = _PALETTE[si % len(_PALETTE)]
            dash  = _DASHES[si % len(_DASHES)]
            lx = W - mr + 8
            t_safe = str(temp).replace('"', '')
            s_safe = str(skew).replace('"', '')
            dash_attr = f'stroke-dasharray="{dash}" ' if dash else ""
            svg.parts.append(
                f'<g class="legend-item" data-temp="{t_safe}" data-skew="{s_safe}">'
            )
            svg.parts.append(
                f'<line x1="{lx}" y1="{ly+5}" x2="{lx+28}" y2="{ly+5}" '
                f'stroke="{color}" stroke-width="2.2" {dash_attr}/>'
            )
            svg.parts.append(
                f'<circle cx="{lx+14}" cy="{ly+5}" r="4" fill="{color}"/>'
            )
            svg.parts.append(
                f'<text x="{lx+32}" y="{ly+9}" font-size="10" '
                f'font-family="Arial,sans-serif" fill="{C_DARK}">'
                f'T={temp}°C  {skew}</text>'
            )
            svg.parts.append('</g>')

        return _save(svg, output_path)

    # ── Corner-based chart (no DS: iostateafterpor, resistance, vihvil) ───────
    parse = _parse_condition

    # Group: (temp, vio, vcore) -> {skew -> [values]}
    corner_skew: dict = {}
    for r in relevant:
        fv = safe_float(r.get("Value"))
        if fv is None:
            continue
        c    = parse(r.get("Test_Condition", ""))
        temp = c.get("T", "?")
        vio  = c.get("VIO", "?")
        vcor = c.get("VCORE", "?")
        skew = r.get("Skew", "") or c.get("SKW", "?")
        key  = (temp, vio, vcor)
        corner_skew.setdefault(key, {}).setdefault(skew, []).append(fv)

    all_conds = sorted(
        corner_skew.keys(),
        key=lambda x: (_try_float_val(x[0]), _try_float_val(x[1]), _try_float_val(x[2]))
    )
    if not all_conds:
        return None

    all_skews = sorted({s for cd in corner_skew.values() for s in cd})
    ns = len(all_skews)

    # Collect all values for y-range
    all_vals = [
        v
        for cd in corner_skew.values()
        for vals in cd.values()
        for v in vals
        if v is not None
    ]
    if not all_vals:
        return None

    n = len(all_conds)
    mr = max(155, max((len(s) for s in all_skews), default=4) * 8 + 50)
    W = max(860, n * 34 + 90 + mr)
    H = max(460, ns * 22 + 130)
    ml, mt, mb = 82, 64, 100
    pl, pr, pt_y, pb = ml, W - mr, mt, H - mb
    pw = pr - pl

    y_min, y_max = min(all_vals), max(all_vals)
    if spec_min is not None and spec_min == spec_min:
        y_min = min(y_min, spec_min)
        y_max = max(y_max, spec_min)
    if spec_max is not None and spec_max == spec_max:
        y_max = max(y_max, spec_max)
        y_min = min(y_min, spec_max)
    span = y_max - y_min
    y_min -= (span * 0.25 or 0.05)
    y_max += (span * 0.25 or 0.05)

    unit_str = f" ({unit})" if unit else ""
    svg = SVG(W, H)
    svg.title(f"{io_name} — {measurement_suffix}{unit_str}  [{test_name}]")
    svg.line(pl, pb, pr, pb)
    svg.line(pl, pt_y, pl, pb)
    _y_axis(svg, y_min, y_max, pl, pr, pt_y, pb)
    svg.text(14, (pt_y + pb) / 2, f"{measurement_suffix}{unit_str}",
             fs=10, fill=C_GRAY,
             transform=f"rotate(-90,14,{(pt_y + pb) / 2:.1f})", anchor="middle")

    x_step = pw / n if n > 0 else pw

    # X-axis tick labels (angled) + temperature group separators
    prev_temp = None
    for i, (temp, vio, vcor) in enumerate(all_conds):
        if temp != prev_temp:
            if i > 0:
                svg.line(pl + i * x_step, pt_y, pl + i * x_step, pb,
                         stroke="#cccccc", sw=1, dash="4,3")
            prev_temp = temp
        x = pl + (i + 0.5) * x_step
        svg.text(x, pb + 14, f"VIO={vio}\nVC={vcor}", fs=8, anchor="end",
                 transform=f"rotate(-45,{x:.1f},{pb + 14})")

    # Temperature group header labels
    for i, (temp, _, _) in enumerate(all_conds):
        if i == 0 or all_conds[i-1][0] != temp:
            end = next((j for j in range(i, n) if all_conds[j][0] != temp), n) - 1
            xc = pl + (i + end + 1) / 2 * x_step
            svg.text(xc, pt_y - 10, f"T={temp}°C", fs=10, fw="bold",
                     anchor="middle", fill=C_DARK)

# Lines — one per skew, wrapped in a filterable <g>
        for si, skew in enumerate(all_skews):
            color = _PALETTE[si % len(_PALETTE)]
            dash  = _DASHES[si % len(_DASHES)]
            s_safe = str(skew).replace('"', '')
            svg.parts.append(f'<g class="series" data-skew="{s_safe}">')
            pts_xy = []
            for i, cond_key in enumerate(all_conds):
                v = wcase(corner_skew[cond_key].get(skew, []))
                if v is None:
                    continue
                xp = pl + (i + 0.5) * x_step
                yp = _ys(v, y_min, y_max, pt_y, pb)
                pts_xy.append((xp, yp))
            if len(pts_xy) >= 2:
                d = " ".join(f"{'M' if j == 0 else 'L'}{x:.1f},{y:.1f}"
                             for j, (x, y) in enumerate(pts_xy))
                dash_attr = f'stroke-dasharray="{dash}" ' if dash else ""
                svg.parts.append(
                    f'<path d="{d}" fill="none" stroke="{color}" '
                    f'stroke-width="2.5" stroke-linejoin="round" '
                    f'{dash_attr}opacity="0.9"/>'
                )
            for x, y in pts_xy:
                svg.parts.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" '
                    f'fill="{color}" opacity="0.95"/>'
                )
            svg.parts.append('</g>')

    # Spec lines
        svg.parts.append('<g class="spec-el">')
        for spec_val, lbl, _sdash in [(spec_min, "Min spec", "8,4"),
                                      (spec_max, "Max spec", "4,4")]:
            if spec_val is not None and spec_val == spec_val:
                if y_min <= spec_val <= y_max:
                    ys = _ys(spec_val, y_min, y_max, pt_y, pb)
                    svg.line(pl, ys, pr, ys, stroke=C_SPEC, sw=4)
                    svg.text(pr + 5, ys + 4, f"{lbl}: {spec_val:.3g}",
                             fs=9, fill=C_SPEC)
        svg.parts.append('</g>')  # close spec-el

    # Legend — skew series, also wrapped for filtering
        for si, skew in enumerate(all_skews):
            ly = mt + si * 22
            color = _PALETTE[si % len(_PALETTE)]
            dash  = _DASHES[si % len(_DASHES)]
            lx = W - mr + 8
            s_safe = str(skew).replace('"', '')
            dash_attr = f'stroke-dasharray="{dash}" ' if dash else ""
            svg.parts.append(f'<g class="legend-item" data-skew="{s_safe}">')
            svg.parts.append(
                f'<line x1="{lx}" y1="{ly+5}" x2="{lx+28}" y2="{ly+5}" '
                f'stroke="{color}" stroke-width="2.5" {dash_attr}/>'
            )
            svg.parts.append(
                f'<circle cx="{lx+14}" cy="{ly+5}" r="5" fill="{color}"/>'
            )
            svg.parts.append(
                f'<text x="{lx+32}" y="{ly+9}" font-size="10" '
                f'font-family="Arial,sans-serif" fill="{C_DARK}">{skew}</text>'
            )
            svg.parts.append('</g>')

    return _save(svg, output_path)


def plot_voh_vol_chart(all_rows, measurement_suffix, test_name, io_name,
                      spec_min, spec_max, unit, worst_agg, output_path,
                      io_type_label=""):
    """
    VOH/VOL combined chart:
    - X-axis primary groups = DS settings
    - X-axis sub-ticks = VIO/VCORE corners (worst-case across temperatures)
    - Lines = one per (skew, chip)
    - Dynamic VOH spec line = 0.75 × VIO at each X-point
    """
    _PALETTE = [
        "#3498db", "#e74c3c", "#2ecc71", "#9b59b6",
        "#e67e22", "#1abc9c", "#c0392b", "#2980b9",
        "#27ae60", "#8e44ad", "#d35400", "#16a085",
    ]
    _DASHES = ["", "8,3", "4,3", "10,3,3,3"]

    param_name = f"{io_name}_{measurement_suffix}"
    relevant = [
        r for r in all_rows
        if r.get("Parameter") == param_name
        and r.get("Test_Name") == test_name
        and r.get("IO_Name") == io_name
    ]
    if not relevant:
        return None

    unit = unit or next((r.get("Unit", "") for r in relevant if r.get("Unit")), "")

    def safe_float(v):
        if v is None:
            return None
        try:
            f = float(v)
            return None if f != f or abs(f) == float("inf") else f
        except (ValueError, TypeError):
            return None

    def ds_sort_key(s):
        try:
            return int(s.replace("DS_", "").replace("ds_", ""))
        except ValueError:
            return 999

    parse = _parse_condition

    # Group: {(ds, vio, vcor, skew, chip): [values]} — aggregates across temperatures
    grp: dict = {}
    for r in relevant:
        fv = safe_float(r.get("Value"))
        if fv is None:
            continue
        ds = r.get("DS", "")
        if not ds:
            continue
        c = parse(r.get("Test_Condition", ""))
        vio  = c.get("VIO", "?")
        vcor = c.get("VCORE", "?")
        skew = r.get("Skew", "") or c.get("SKW", "?")
        chip = str(r.get("DUT_ID", "?"))
        grp.setdefault((ds, vio, vcor, skew, chip), []).append(fv)

    if not grp:
        return None

    all_ds = sorted({ds for ds, *_ in grp}, key=ds_sort_key)
    all_vio_vcor = sorted(
        {(vio, vcor) for _d, vio, vcor, _s, _c in grp},
        key=lambda x: (_try_float_val(x[0]), _try_float_val(x[1]))
    )
    all_series = sorted(
        {(sk, ch) for _d, _v, _vc, sk, ch in grp},
        key=lambda x: (x[0], x[1])
    )
    if not all_ds or not all_vio_vcor or not all_series:
        return None

    # X-axis: (vio, vcor, ds) — primary groups = VIO/VCORE corner, sub-ticks = DS
    x_triples = [(vio, vcor, ds) for vio, vcor in all_vio_vcor for ds in all_ds]
    n = len(x_triples)

    def _pick(vals):
        if not vals: return None
        if worst_agg == "max": return max(vals)
        if worst_agg == "min": return min(vals)
        return sum(vals) / len(vals)

    series = {
        (sk, ch): [_pick(grp.get((ds, vio, vcor, sk, ch), [])) for vio, vcor, ds in x_triples]
        for sk, ch in all_series
    }

    # Dynamic spec for VOH: spec_min = 0.75 × VIO — constant within each VIO corner group
    dynamic_spec_min: dict = {}
    if measurement_suffix == "VOH":
        for vio, vcor, ds in x_triples:
            try:
                dynamic_spec_min[(vio, vcor, ds)] = 0.75 * float(vio)
            except (ValueError, TypeError):
                pass

    all_vals = [v for pts in series.values() for v in pts if v is not None]
    if not all_vals:
        return None

    W, H = _CHART_W, _CHART_H
    ml, mr, mt, mb = _CHART_ML, _CHART_LEG, _CHART_MT, _CHART_MB
    pl, pr, pt_y, pb = ml, W - mr, mt, H - mb
    pw = pr - pl

    y_min, y_max = _pct_range(all_vals)
    if dynamic_spec_min:
        dyn_vals = list(dynamic_spec_min.values())
        y_min = min(y_min, min(dyn_vals))
        y_max = max(y_max, max(dyn_vals))
    elif spec_min is not None and spec_min == spec_min:
        y_min = min(y_min, spec_min)
        y_max = max(y_max, spec_min)
    if spec_max is not None and spec_max == spec_max:
        y_max = max(y_max, spec_max)
        y_min = min(y_min, spec_max)
    span = y_max - y_min
    y_min -= (span * 0.25 or 0.05)
    y_max += (span * 0.25 or 0.05)

    unit_str = f" ({unit})" if unit else ""
    io_type_str = f"  [{io_type_label}]" if io_type_label else ""
    svg = SVG(W, H)
    svg.title(f"{io_name}{io_type_str} \u2014 {measurement_suffix}{unit_str}  [{test_name}]")
    svg.line(pl, pb, pr, pb)
    svg.line(pl, pt_y, pl, pb)
    _y_axis(svg, y_min, y_max, pl, pr, pt_y, pb)
    svg.text(14, (pt_y + pb) / 2, f"{measurement_suffix}{unit_str}",
             fs=10, fill=C_GRAY,
             transform=f"rotate(-90,14,{(pt_y + pb) / 2:.1f})", anchor="middle")

    x_step = pw / n if n > 0 else pw

    # X-axis: DS angled sub-tick labels + VIO/VCORE group separators + corner headers
    prev_corner = None
    for i, (vio, vcor, ds) in enumerate(x_triples):
        x = pl + (i + 0.5) * x_step
        svg.text(x, pb + 14, ds, fs=8, anchor="end",
                 transform=f"rotate(-45,{x:.1f},{pb + 14})")
        corner = (vio, vcor)
        if corner != prev_corner:
            if i > 0:
                svg.line(pl + i * x_step, pt_y, pl + i * x_step, pb,
                         stroke="#aaaaaa", sw=1.5, dash="4,3")
            prev_corner = corner

    for i, (vio, vcor, _ds) in enumerate(x_triples):
        if i == 0 or (x_triples[i - 1][0], x_triples[i - 1][1]) != (vio, vcor):
            end = next((j for j in range(i, n)
                        if x_triples[j][0] != vio or x_triples[j][1] != vcor), n) - 1
            xc = pl + (i + end + 1) / 2 * x_step
            svg.text(xc, pt_y - 10, f"VIO={vio} / VC={vcor}", fs=10, fw="bold",
                     anchor="middle", fill=C_DARK)

    svg.text(pl + pw / 2, pb + 60, "VIO & VCORE Corner  /  Drive Strength (DS)",
             fs=11, anchor="middle", fill=C_DARK)

    # Lines — one per (skew, chip)
    for si, (skew, chip) in enumerate(all_series):
        color     = _PALETTE[si % len(_PALETTE)]
        dash      = _DASHES[si % len(_DASHES)]
        s_safe    = str(skew).replace('"', '')
        chip_safe = str(chip).replace('"', '')
        svg.parts.append(
            f'<g class="series" data-skew="{s_safe}" data-chip="{chip_safe}">'
        )
        pts_xy = [
            (pl + (i + 0.5) * x_step, _ys(v, y_min, y_max, pt_y, pb))
            for i, v in enumerate(series[(skew, chip)])
            if v is not None
        ]
        if len(pts_xy) >= 2:
            d_path = " ".join(
                f"{'M' if j == 0 else 'L'}{x:.1f},{y:.1f}"
                for j, (x, y) in enumerate(pts_xy)
            )
            dash_attr = f'stroke-dasharray="{dash}" ' if dash else ""
            svg.parts.append(
                f'<path d="{d_path}" fill="none" stroke="{color}" '
                f'stroke-width="2.0" stroke-linejoin="round" '
                f'{dash_attr}opacity="0.85"/>'
            )
        for x, y in pts_xy:
            tip = f"{io_name} {measurement_suffix} | {skew} | Chip: {chip}"
            svg.parts.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" '
                f'fill="{color}" opacity="0.9">'
                f'<title>{tip}</title></circle>'
            )
        svg.parts.append('</g>')

    # Spec lines: dynamic stepped for VOH, fixed for VOL
    svg.parts.append('<g class="spec-el">')
    if _SHOW_SPEC_LINES and dynamic_spec_min:
        valid_pts = [
            (pl + (i + 0.5) * x_step, dynamic_spec_min[triple])
            for i, triple in enumerate(x_triples)
            if triple in dynamic_spec_min
        ]
        if len(valid_pts) >= 2:
            d_path = " ".join(
                f"{'M' if j == 0 else 'L'}{x:.1f},{_ys(v, y_min, y_max, pt_y, pb):.1f}"
                for j, (x, v) in enumerate(valid_pts)
            )
            svg.parts.append(
                f'<path d="{d_path}" fill="none" stroke="{C_SPEC}" '
                f'stroke-width="4" opacity="1.0"/>'
            )
            last_x, last_v = valid_pts[-1]
            svg.text(pr + 5, _ys(last_v, y_min, y_max, pt_y, pb) + 4,
                     "VOH Min (0.75\u00d7VIO)", fs=9, fill=C_SPEC)
        if spec_max is not None and spec_max == spec_max and y_min <= spec_max <= y_max:
            ys = _ys(spec_max, y_min, y_max, pt_y, pb)
            svg.line(pl, ys, pr, ys, stroke=C_SPEC, sw=4)
            svg.text(pr + 5, ys + 4, f"Max spec: {spec_max:.3g}", fs=9, fill=C_SPEC)
    else:
        if _SHOW_SPEC_LINES:
            for spec_val, lbl, _sdash in [(spec_min, "Min spec", "8,4"),
                                          (spec_max, "Max spec", "4,4")]:
                if spec_val is not None and spec_val == spec_val and y_min <= spec_val <= y_max:
                    ys = _ys(spec_val, y_min, y_max, pt_y, pb)
                    svg.line(pl, ys, pr, ys, stroke=C_SPEC, sw=4)
                    svg.text(pr + 5, ys + 4, f"{lbl}: {spec_val:.3g}", fs=9, fill=C_SPEC)
    svg.parts.append('</g>')  # close spec-el

    # Legend
    for si, (skew, chip) in enumerate(all_series):
        ly        = mt + si * 22
        color     = _PALETTE[si % len(_PALETTE)]
        dash      = _DASHES[si % len(_DASHES)]
        lx        = W - mr + 8
        s_safe    = str(skew).replace('"', '')
        chip_safe = str(chip).replace('"', '')
        dash_attr = f'stroke-dasharray="{dash}" ' if dash else ""
        lbl_text  = f"{chip} | {skew}"
        svg.parts.append(
            f'<g class="legend-item" data-skew="{s_safe}" data-chip="{chip_safe}">'
        )
        svg.parts.append(
            f'<line x1="{lx}" y1="{ly+5}" x2="{lx+28}" y2="{ly+5}" '
            f'stroke="{color}" stroke-width="2.0" {dash_attr}/>'
        )
        svg.parts.append(f'<circle cx="{lx+14}" cy="{ly+5}" r="4" fill="{color}"/>')
        svg.parts.append(
            f'<text x="{lx+32}" y="{ly+9}" font-size="10" '
            f'font-family="Arial,sans-serif" fill="{C_DARK}">{_esc(lbl_text)}</text>'
        )
        svg.parts.append('</g>')

    return _save(svg, output_path)


def generate_section_plots(result, config, plots_dir, selected_tests=None):
    """
    Generate per-test-section line charts for GPIO_0 and RF_KILLN.
    DS-based tests: separate chart per IO per measurement, X=DS, lines=temperature.
    Non-DS tests: separate chart per IO per measurement, X=corners.
    Returns {test_name: {f'{io}_{meas}': Path or None}}.
    selected_tests: set of test_name strings to include, or None for all.
    """
    all_rows = [r for fd in result.flow_data.values() for r in fd.rows]

    # Build spec lookup: (io, measurement_suffix) -> (spec_min, spec_max, unit)
    spec_map: dict = {}
    for (_, param), stats in result.parameter_stats.items():
        for io in REPORT_IOS:
            if param.startswith(io + "_"):
                suffix = param[len(io) + 1:]
                key = (io, suffix)
                if key not in spec_map:
                    spec_map[key] = (stats.spec_min, stats.spec_max, stats.unit)

    section_plots: dict = {}
    active_tests = selected_tests if selected_tests is not None else set(TEST_SECTION_ORDER)
    for test_name in TEST_SECTION_ORDER:
        if test_name not in active_tests:
            section_plots[test_name] = {}
            continue
        section_plots[test_name] = {}

        # ── VOH/VOL: combined chart, X-axis = DS × VIO/VCORE, dynamic VOH spec ──
        if test_name == "VOH/VOL":
            for meas in SECTION_MEASUREMENTS.get(test_name, []):
                for io in REPORT_IOS:
                    spec_min, spec_max, unit = spec_map.get(
                        (io, meas),
                        spec_map.get(("GPIO_0", meas), (None, None, ""))
                    )
                    worst_agg = MEAS_WORST_AGG.get(meas, "max")
                    fname = f"sec_voh_vol_{io.lower()}_{meas.lower()}.svg"
                    path = plot_voh_vol_chart(
                        all_rows=all_rows,
                        measurement_suffix=meas,
                        test_name=test_name,
                        io_name=io,
                        spec_min=spec_min,
                        spec_max=spec_max,
                        unit=unit,
                        worst_agg=worst_agg,
                        output_path=plots_dir / fname,
                        io_type_label=IO_TYPE_LABEL.get(io, ""),
                    )
                    chart_key = f"{io}_{meas}"
                    section_plots[test_name][chart_key] = path
                    if path:
                        logger.info(f"Saved section chart: {path.name}")
            continue

        for meas in SECTION_MEASUREMENTS.get(test_name, []):
            for io in REPORT_IOS:
                spec_min, spec_max, unit = spec_map.get(
                    (io, meas),
                    spec_map.get(("GPIO_0", meas), (None, None, ""))
                )
                worst_agg = MEAS_WORST_AGG.get(meas, "max")
                safe = (test_name.lower()
                        .replace("/", "_").replace(" ", "_")
                        .replace("-", "_").replace("(", "").replace(")", ""))
                fname = f"sec_{safe}_{io.lower()}_{meas.lower()}.svg"
                path = plot_section_line_chart(
                    all_rows=all_rows,
                    measurement_suffix=meas,
                    test_name=test_name,
                    io_name=io,
                    spec_min=spec_min,
                    spec_max=spec_max,
                    unit=unit,
                    worst_agg=worst_agg,
                    output_path=plots_dir / fname,
                    io_type_label=IO_TYPE_LABEL.get(io, ""),
                    chart_type="column" if test_name == "Rise/Fall Time" else "line",
                )
                chart_key = f"{io}_{meas}"
                section_plots[test_name][chart_key] = path
                if path:
                    logger.info(f"Saved section chart: {path.name}")

    return section_plots


def generate_all_plots(result: AnalysisResult, config: Config,
                       selected_tests=None) -> dict:
    """Generate all SVG plots and return paths organised by category.
    selected_tests: set of test section names to include, or None for all.
    """
    # Apply configurable spec-line colour and visibility
    global C_SPEC, _SHOW_SPEC_LINES
    C_SPEC = config.plot.spec_line_color
    _SHOW_SPEC_LINES = config.plot.show_spec_lines
    plots_dir = config.output_path / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    all_plots: dict = {}
    logger.info("Generating pass/fail summary plots...")
    all_plots["pass_fail_summary"] = plot_pass_fail_summary(result, config, plots_dir)
    logger.info("Generating parameter vs spec plots...")
    all_plots["parameter_vs_spec"] = plot_parameter_vs_spec(result, config, plots_dir)
    logger.info("Generating distribution histograms...")
    all_plots["distributions"] = plot_distribution_histograms(result, config, plots_dir)
    logger.info("Generating cross-flow comparison...")
    all_plots["cross_flow"] = plot_cross_flow_comparison(result, config, plots_dir)
    logger.info("Generating Cpk summary...")
    all_plots["cpk_summary"] = plot_cpk_summary(result, config, plots_dir)
    logger.info("Generating per-DUT scatter plots...")
    all_plots["scatter_dut"] = plot_scatter_by_dut(result, config, plots_dir)
    logger.info("Generating per-section corner line charts...")
    all_plots["section_plots"] = generate_section_plots(
        result, config, plots_dir, selected_tests=selected_tests
    )
    total = sum(len(v) for k, v in all_plots.items()
                if k != "section_plots" and isinstance(v, list))
    logger.info(f"Generated {total} SVG plots in {plots_dir}")
    return all_plots
