"""
PMIC DC2DC Validation — SVG Plot Generator.
Generates one SVG file per (test_type, regulator, vout_target) combination.
All drawing reuses the SVG primitives from io_analysis.plotting.plotter.
"""

import logging
from pathlib import Path

from io_analysis.plotting.plotter import SVG, _esc, _ys, _linspace, _save, _pct_range

logger = logging.getLogger(__name__)

# ── Colour palette ─────────────────────────────────────────────────────────
PALETTE = [
    "#3498db", "#e67e22", "#2ecc71", "#9b59b6", "#1abc9c",
    "#e74c3c", "#f39c12", "#2980b9", "#16a085", "#8e44ad",
    "#c0392b", "#27ae60", "#d35400", "#7f8c8d", "#2c3e50",
]

REG_LABELS = {
    "DC2DC_ANA": "Analog DC2DC",
    "DC2DC_DIG": "Digital DC2DC",
}

# ── Helpers ────────────────────────────────────────────────────────────────

def _color(idx: int) -> str:
    return PALETTE[idx % len(PALETTE)]


def _safe_attr(s) -> str:
    return str(s).replace('"', "").replace("'", "").replace(" ", "_")


def _fmt_current(iout_str: str) -> str:
    """Format an IoutSMU value as a human-readable current string."""
    try:
        v = float(iout_str)
        if v < 0.001:
            return f"{v*1e6:.0f}µA"
        if v < 1.0:
            return f"{v*1000:.0f}mA"
        return f"{v:.1f}A"
    except Exception:
        return str(iout_str)


def _f(s, default=None):
    """Safely parse float; filter sentinel big values."""
    try:
        v = float(str(s).strip())
        if v != v or abs(v) > 1e15:     # NaN or sentinel
            return default
        return v
    except (ValueError, TypeError):
        return default


def _filter_outliers(pts, iqr_factor=2.5):
    """
    Remove Y-axis outliers from a list of (x, y) tuples using the IQR method.
    Points with Y outside [Q1 - iqr_factor*IQR,  Q3 + iqr_factor*IQR] are dropped.
    Returns the cleaned list (or the original if fewer than 4 points).
    """
    if len(pts) < 4:
        return pts
    ys = sorted(p[1] for p in pts)
    n  = len(ys)
    q1 = ys[n // 4]
    q3 = ys[(3 * n) // 4]
    iqr = q3 - q1
    if iqr == 0:
        return pts          # all identical — nothing to remove
    lo = q1 - iqr_factor * iqr
    hi = q3 + iqr_factor * iqr
    return [(x, y) for x, y in pts if lo <= y <= hi]


def _xs(v, x_min, x_max, pl, pr):
    if x_max == x_min:
        return (pl + pr) / 2.0
    return pl + (v - x_min) / (x_max - x_min) * (pr - pl)


def _grid_line(svg, x0, y0, x1, y1):
    svg.line(x0, y0, x1, y1, stroke="#e8e8e8", sw=0.7, dash="4,3")


def _y_axis(svg, y_min, y_max, pl, pr, pt, pb, n=6, fmt=".3g", tick_step=None):
    import math as _math
    svg.line(pl, pt, pl, pb)
    if tick_step is not None:
        start = _math.floor(y_min / tick_step) * tick_step
        ticks, v = [], start
        while v <= y_max + 1e-9:
            ticks.append(round(v, 10))
            v += tick_step
    else:
        ticks = _linspace(y_min, y_max, n)
    for tick in ticks:
        y = _ys(tick, y_min, y_max, pt, pb)
        svg.line(pl - 5, y, pl, y)
        _grid_line(svg, pl, y, pr, y)
        svg.text(pl - 8, y + 4, format(tick, fmt), fs=9, anchor="end", fill="#888")


def _x_axis(svg, x_min, x_max, pl, pr, pt, pb, n=8, fmt=".3g", tick_step=None):
    import math as _math
    svg.line(pl, pb, pr, pb)
    if tick_step is not None:
        start = _math.ceil(x_min / tick_step) * tick_step
        ticks, v = [], start
        while v <= x_max + 1e-9:
            ticks.append(round(v, 10))
            v += tick_step
    else:
        ticks = _linspace(x_min, x_max, n)
    for tick in ticks:
        x = _xs(tick, x_min, x_max, pl, pr)
        svg.line(x, pb, x, pb + 5)
        _grid_line(svg, x, pt, x, pb)
        svg.text(x, pb + 16, format(tick, fmt), fs=9, anchor="middle", fill="#888")


def _axis_labels(svg, x_lbl, y_lbl, pl, pr, pt, pb, h):
    mid_y = (pt + pb) / 2
    svg.text(16, mid_y, y_lbl, fs=11, fill="#555", anchor="middle",
             transform=f"rotate(-90,16,{mid_y:.1f})")
    svg.text((pl + pr) / 2, h - 10, x_lbl, fs=11, anchor="middle", fill="#555")


def _add_cursor_layer(svg, x_min, x_max, y_min, y_max, pl, pr, pt, pb):
    """Embed a transparent hit-rect + crosshair + tooltip into an SVG.
    The JS in the HTML report reads data-* attrs to convert pixel→data coords."""
    w = int(svg.w)
    h = int(svg.h)
    # Transparent overlay that catches mouse events
    svg.parts.append(
        f'<rect class="cursor-overlay"'
        f' x="{pl:.1f}" y="{pt:.1f}"'
        f' width="{pr - pl:.1f}" height="{pb - pt:.1f}"'
        f' fill="transparent" style="cursor:default"'
        f' data-xmin="{x_min:.8g}" data-xmax="{x_max:.8g}"'
        f' data-ymin="{y_min:.8g}" data-ymax="{y_max:.8g}"'
        f' data-pl="{pl:.1f}" data-pr="{pr:.1f}"'
        f' data-pt="{pt:.1f}" data-pb="{pb:.1f}"/>'
    )
    # Crosshair + tooltip group (hidden until JS activates it)
    svg.parts.append(
        f'<g class="cursor-layer" style="pointer-events:none;display:none">'
        f'<line class="cur-v" x1="0" y1="{pt:.1f}" x2="0" y2="{pb:.1f}"'
        f' stroke="#e74c3c" stroke-width="1.2" stroke-dasharray="5,3"/>'
        f'<line class="cur-h" x1="{pl:.1f}" y1="0" x2="{pr:.1f}" y2="0"'
        f' stroke="#e74c3c" stroke-width="1.2" stroke-dasharray="5,3"/>'
        f'<rect class="cur-tip-bg" x="0" y="0" width="170" height="48"'
        f' rx="4" fill="#1a252f" stroke="#34495e" stroke-width="1" opacity="0.92"/>'
        f'<text class="cur-tip-s" x="0" y="0" font-size="8"'
        f' font-family="Arial,sans-serif" fill="#f1c40f"/>'
        f'<text class="cur-tip-x" x="0" y="0" font-size="9"'
        f' font-family="Arial,sans-serif" fill="#ecf0f1"/>'
        f'<text class="cur-tip-y" x="0" y="0" font-size="9"'
        f' font-family="Arial,sans-serif" fill="#2ecc71"/>'
        f'</g>'
    )


def _multi_line_chart(title, x_lbl, y_lbl, series_list,
                      out_path, w=1400, h=520,
                      y_tick_step=None, y_range=None,
                      x_tick_step=None, x_fmt=".3g"):
    """
    Multi-series connected-dot line chart.
    series_list: list of {label, x, y, color, data_attrs:{...}}
    data_attrs keys become SVG data-* attributes on each <g class="series">.
    y_tick_step: draw Y ticks at multiples of this value (e.g. 5 for 0,5,10,…)
    y_range: (min, max) tuple to fix the Y axis range (overrides auto-range)
    x_tick_step: draw X ticks at multiples of this value (e.g. 0.05 for 50mA steps)
    x_fmt: format string for X tick labels
    """
    ML, MT, MB, MR_LEG = 78, 68, 80, 300
    # Auto-grow height so all legend entries fit (17px each, starts at pt+8=76)
    _min_h = MT + 8 + len(series_list) * 17 + MB + 20
    h = max(h, _min_h)
    pl, pr, pt, pb = ML, w - MR_LEG, MT, h - MB

    all_x = [v for s in series_list for v in s.get("x", []) if v is not None]
    all_y = [v for s in series_list for v in s.get("y", []) if v is not None]
    if not all_x:
        return None

    x_min, x_max = min(all_x), max(all_x)
    y_min, y_max = min(all_y), max(all_y)
    xpad = (x_max - x_min) * 0.05 or 0.05
    ypad = (y_max - y_min) * 0.08 or 0.5
    x_min -= xpad; x_max += xpad
    y_min -= ypad; y_max += ypad
    if y_range is not None:
        if y_range[0] is not None:
            y_min = y_range[0]
        if y_range[1] is not None:
            y_max = y_range[1]

    svg = SVG(w, h)
    svg.title(title)
    _y_axis(svg, y_min, y_max, pl, pr, pt, pb, tick_step=y_tick_step)
    _x_axis(svg, x_min, x_max, pl, pr, pt, pb, tick_step=x_tick_step, fmt=x_fmt)
    _axis_labels(svg, x_lbl, y_lbl, pl, pr, pt, pb, h)

    for i, s in enumerate(series_list):
        pts = sorted((xi, yi) for xi, yi in zip(s.get("x", []), s.get("y", []))
                     if xi is not None and yi is not None)
        if not pts:
            continue
        color = s.get("color", _color(i))
        is_ref = s.get("ref", False)
        da = s.get("data_attrs", {})
        da_str = " ".join(f'data-{k}="{_esc(str(v))}"' for k, v in da.items())
        g_class = 'series pmic-series ref-overlay' if is_ref else 'series pmic-series'
        lbl_esc = _esc(str(s.get("label", "")))
        svg.parts.append(f'<g class="{g_class}" data-label="{lbl_esc}" data-color="{_esc(color)}" {da_str}>')
        if len(pts) > 1:
            d = ("M " + " L ".join(
                f"{_xs(px, x_min, x_max, pl, pr):.1f},{_ys(py, y_min, y_max, pt, pb):.1f}"
                for px, py in pts))
            dash = ' stroke-dasharray="7,4"' if is_ref else ''
            svg.parts.append(
                f'<path d="{d}" fill="none" stroke="{color}" '
                f'stroke-width="2.2" stroke-linejoin="round" opacity="0.9"{dash}/>')
        for px, py in pts:
            cx = _xs(px, x_min, x_max, pl, pr)
            cy = _ys(py, y_min, y_max, pt, pb)
            if is_ref:
                svg.circle(cx, cy, 5.5, fill="none", stroke=color)
            else:
                svg.circle(cx, cy, 4, fill=color, stroke="white")
        svg.parts.append("</g>")

    # legend
    lx, ly = w - MR_LEG + 16, pt + 8
    for i, s in enumerate(series_list):
        color = s.get("color", _color(i))
        is_ref = s.get("ref", False)
        da = s.get("data_attrs", {})
        da_str = " ".join(f'data-{k}="{_esc(str(v))}"' for k, v in da.items())
        g_class = 'legend-item ref-overlay' if is_ref else 'legend-item'
        svg.parts.append(f'<g class="{g_class}" {da_str}>')
        svg.rect(lx, ly - 7, 22, 4, fill=color)
        if is_ref:
            svg.circle(lx + 11, ly - 5, 4, fill="none", stroke=color)
        else:
            svg.circle(lx + 11, ly - 5, 4, fill=color)
        lbl = str(s.get("label", ""))[:44]
        svg.text(lx + 28, ly, lbl, fs=9, fill="#333")
        svg.parts.append("</g>")
        ly += 17
        if ly > h - 20:
            break

    _add_cursor_layer(svg, x_min, x_max, y_min, y_max, pl, pr, pt, pb)
    return _save(svg, out_path)


def _scatter_chart(title, x_lbl, y_lbl, series_list, out_path,
                   w=1400, h=520, dot_r=5):
    """Scatter chart (no connecting lines).  Same interface as _multi_line_chart."""
    ML, MT, MB, MR_LEG = 78, 68, 80, 300
    _min_h = MT + 8 + len(series_list) * 16 + MB + 20
    h = max(h, _min_h)
    pl, pr, pt, pb = ML, w - MR_LEG, MT, h - MB

    all_x = [v for s in series_list for v in s.get("x", []) if v is not None]
    all_y = [v for s in series_list for v in s.get("y", []) if v is not None]
    if not all_x:
        return None

    x_min, x_max = min(all_x), max(all_x)
    y_min, y_max = min(all_y), max(all_y)
    xpad = (x_max - x_min) * 0.05 or 0.05
    ypad = (y_max - y_min) * 0.10 or 0.5
    x_min -= xpad; x_max += xpad
    y_min -= ypad; y_max += ypad

    svg = SVG(w, h)
    svg.title(title)
    _y_axis(svg, y_min, y_max, pl, pr, pt, pb)
    _x_axis(svg, x_min, x_max, pl, pr, pt, pb)
    _axis_labels(svg, x_lbl, y_lbl, pl, pr, pt, pb, h)

    for i, s in enumerate(series_list):
        pts = [(xi, yi) for xi, yi in zip(s.get("x", []), s.get("y", []))
               if xi is not None and yi is not None]
        if not pts:
            continue
        color = s.get("color", _color(i))
        is_ref = s.get("ref", False)
        da = s.get("data_attrs", {})
        da_str = " ".join(f'data-{k}="{_esc(str(v))}"' for k, v in da.items())
        g_class = 'series pmic-series ref-overlay' if is_ref else 'series pmic-series'
        lbl_esc = _esc(str(s.get("label", "")))
        svg.parts.append(f'<g class="{g_class}" data-label="{lbl_esc}" data-color="{_esc(color)}" {da_str}>')
        for px, py in pts:
            cx = _xs(px, x_min, x_max, pl, pr)
            cy = _ys(py, y_min, y_max, pt, pb)
            if is_ref:
                svg.circle(cx, cy, dot_r + 1.5, fill="none", stroke=color)
            else:
                svg.circle(cx, cy, dot_r, fill=color, stroke="white")
        svg.parts.append("</g>")

    # legend
    lx, ly = w - MR_LEG + 16, pt + 8
    for i, s in enumerate(series_list):
        color = s.get("color", _color(i))
        is_ref = s.get("ref", False)
        da = s.get("data_attrs", {})
        da_str = " ".join(f'data-{k}="{_esc(str(v))}"' for k, v in da.items())
        g_class = 'legend-item ref-overlay' if is_ref else 'legend-item'
        svg.parts.append(f'<g class="{g_class}" {da_str}>')
        if is_ref:
            svg.circle(lx + 6, ly - 5, 6, fill="none", stroke=color)
        else:
            svg.circle(lx + 6, ly - 5, 5, fill=color)
        lbl = str(s.get("label", ""))[:44]
        svg.text(lx + 18, ly, lbl, fs=9, fill="#333")
        svg.parts.append("</g>")
        ly += 16
        if ly > h - 20:
            break

    _add_cursor_layer(svg, x_min, x_max, y_min, y_max, pl, pr, pt, pb)
    return _save(svg, out_path)


def _cat_dot_chart(title, categories, y_lbl, series_list, out_path,
                   w=1400, h=560, y_tick_step=None, y_range=None):
    """
    Categorical x-axis chart with dots + connecting lines.
    categories: ordered list of str labels for x axis.
    series_list: [{label, values:{cat→y}, color, data_attrs}]
    y_tick_step: fixed y-tick interval (e.g. 5 for 0,5,10,…)
    y_range: (min, max) — either value may be None to keep auto.
    """
    ML, MT, MB, MR_LEG = 78, 68, 80, 300
    _min_h = MT + 8 + len(series_list) * 17 + MB + 20
    h = max(h, _min_h)
    pl, pr, pt, pb = ML, w - MR_LEG, MT, h - MB

    all_y = [v for s in series_list for v in s.get("values", {}).values() if v is not None]
    if not all_y:
        return None

    y_min, y_max = min(all_y), max(all_y)
    ypad = (y_max - y_min) * 0.10 or 0.5
    y_min -= ypad; y_max += ypad
    if y_range is not None:
        if y_range[0] is not None: y_min = y_range[0]
        if y_range[1] is not None: y_max = y_range[1]

    svg = SVG(w, h)
    svg.title(title)
    _y_axis(svg, y_min, y_max, pl, pr, pt, pb, tick_step=y_tick_step)
    svg.line(pl, pb, pr, pb)

    # x-axis category labels
    n = len(categories)
    cat_xs = {cat: pl + (ci + 1) * (pr - pl) / (n + 1)
              for ci, cat in enumerate(categories)}
    for cat, cx in cat_xs.items():
        svg.line(cx, pb, cx, pb + 5)
        _grid_line(svg, cx, pt, cx, pb)
        svg.text(cx, pb + 16, cat, fs=10, anchor="middle", fill="#888")

    svg.text(16, (pt + pb) / 2, y_lbl, fs=11, fill="#555", anchor="middle",
             transform=f"rotate(-90,16,{(pt+pb)/2:.1f})")
    svg.text((pl + pr) / 2, h - 10, "Vin Setpoint [V]", fs=11,
             anchor="middle", fill="#555")

    n_series = len(series_list)
    for i, s in enumerate(series_list):
        color = s.get("color", _color(i))
        is_ref = s.get("ref", False)
        vals  = s.get("values", {})
        da    = s.get("data_attrs", {})
        da_str = " ".join(f'data-{k}="{_esc(str(v))}"' for k, v in da.items())
        jitter = (i - n_series / 2 + 0.5) * 5
        g_class = 'series pmic-series ref-overlay' if is_ref else 'series pmic-series'
        svg.parts.append(f'<g class="{g_class}" {da_str}>')

        # connecting line first (drawn under dots)
        line_pts = [(cat_xs[c] + jitter, _ys(vals[c], y_min, y_max, pt, pb))
                    for c in categories if vals.get(c) is not None]
        if len(line_pts) > 1:
            d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in line_pts)
            svg.parts.append(
                f'<path d="{d}" fill="none" stroke="{color}" '
                f'stroke-width="1.8" stroke-dasharray="5,3" opacity="0.6"/>')

        # dots on top
        for cat in categories:
            yv = vals.get(cat)
            if yv is None:
                continue
            cx = cat_xs[cat] + jitter
            cy = _ys(yv, y_min, y_max, pt, pb)
            if is_ref:
                svg.circle(cx, cy, 7.5, fill="none", stroke=color)
            else:
                svg.circle(cx, cy, 6, fill=color, stroke="white")
        svg.parts.append("</g>")

    # legend
    lx, ly = w - MR_LEG + 16, pt + 8
    for i, s in enumerate(series_list):
        color = s.get("color", _color(i))
        is_ref = s.get("ref", False)
        da    = s.get("data_attrs", {})
        da_str = " ".join(f'data-{k}="{_esc(str(v))}"' for k, v in da.items())
        g_class = 'legend-item ref-overlay' if is_ref else 'legend-item'
        svg.parts.append(f'<g class="{g_class}" {da_str}>')
        svg.rect(lx, ly - 7, 18, 4, fill=color)
        if is_ref:
            svg.circle(lx + 9, ly - 5, 6, fill="none", stroke=color)
        else:
            svg.circle(lx + 9, ly - 5, 5, fill=color)
        svg.text(lx + 24, ly, str(s.get("label", ""))[:44], fs=9, fill="#333")
        svg.parts.append("</g>")
        ly += 17
        if ly > h - 20:
            break

    # Cursor overlay — X range uses pixel coords directly (categorical axis);
    # Y range is the real data range so the tooltip Y value is meaningful.
    _add_cursor_layer(svg, pl, pr, y_min, y_max, pl, pr, pt, pb)
    return _save(svg, out_path)


# ── Reference series helpers ──────────────────────────────────────────────


def _ref_xy_series(ref_data, test_type, outer_key, outer_dims,
                   inner_dims, x_cols, y_col, ref_label, start_idx,
                   data_attr_fn, label_fn, extra_filter=None):
    """
    Build ref series dicts (xy-chart) from ref_data rows.
    Returns list of series dicts with "ref": True already set.
    outer_key : tuple of values for the outer group (reg, vout, mode, ...)
    x_cols    : list of candidate column names for x (first non-None wins)
    extra_filter: optional callable(row)->bool applied per row
    """
    rows = ref_data.get_rows(test_type) if ref_data is not None else []
    if not rows:
        return [], start_idx
    grp = _group_rows(rows, outer_dims)
    sec_rows = grp.get(outer_key, [])
    if not sec_rows:
        return [], start_idx
    series = []
    idx = start_idx
    inner = _group_rows(sec_rows, inner_dims)
    for key, s_rows in sorted(inner.items()):
        if extra_filter and not all(extra_filter(r) for r in s_rows):
            s_rows = [r for r in s_rows if extra_filter(r)]
        pts = []
        for r in s_rows:
            x = None
            for xc in x_cols:
                x = _f(r.get(xc))
                if x is not None:
                    break
            y = _f(r.get(y_col))
            if x is not None and y is not None and abs(y) < 1e15:
                pts.append((x, y))
        if not pts:
            continue
        pts = _filter_outliers(sorted(pts))
        if not pts:
            continue
        xs, ys = zip(*pts)
        series.append({
            "label":      f"[{ref_label}] " + label_fn(key),
            "x":          list(xs),
            "y":          list(ys),
            "color":      _color(idx),
            "ref":        True,
            "data_attrs": data_attr_fn(key),
        })
        idx += 1
    return series, idx


def _ref_cat_series(ref_data, test_type, outer_key, outer_dims,
                    inner_dims, val_fn, ref_label, start_idx,
                    data_attr_fn, label_fn, extra_filter=None):
    """
    Build ref series dicts (categorical chart) from ref_data rows.
    val_fn(s_rows, cat_key) -> {vin_str: float} dict
    """
    rows = ref_data.get_rows(test_type) if ref_data is not None else []
    if not rows:
        return [], start_idx
    grp = _group_rows(rows, outer_dims)
    sec_rows = grp.get(outer_key, [])
    if not sec_rows:
        return [], start_idx
    series = []
    idx = start_idx
    inner = _group_rows(sec_rows, inner_dims)
    for key, s_rows in sorted(inner.items()):
        if extra_filter and not all(extra_filter(r) for r in s_rows):
            s_rows = [r for r in s_rows if extra_filter(r)]
        vals = val_fn(s_rows, key)
        if not vals:
            continue
        series.append({
            "label":      f"[{ref_label}] " + label_fn(key),
            "values":     vals,
            "color":      _color(idx),
            "ref":        True,
            "data_attrs": data_attr_fn(key),
        })
        idx += 1
    return series, idx


# ── Series builder helpers ─────────────────────────────────────────────────

def _build_series_key(row, dims: list) -> tuple:
    return tuple(row.get(d, "") for d in dims)


def _group_rows(rows: list, key_dims: list) -> dict:
    """Group rows by tuple of values across key_dims."""
    groups: dict = {}
    for row in rows:
        k = _build_series_key(row, key_dims)
        groups.setdefault(k, []).append(row)
    return groups


# ══════════════════════════════════════════════════════════════════════════
# 1. Static Load Regulation  →  Iout vs Efficiency
# ══════════════════════════════════════════════════════════════════════════

def plot_static_load(data, output_dir: Path, ref_data=None, ref_label='REF') -> dict:
    """
    One plot per (regulator, vout_target, efficiency_mode).
    Series within each plot = (Vin setpoint, chip_id, temperature).
    """
    plots: dict = {}
    rows_all = data.get_rows("Static_Load")
    if not rows_all:
        logger.info("No Static_Load rows")
        return plots

    def _pairs(rows, x_col, y_col):
        pts = []
        for r in rows:
            x = _f(r.get(x_col))
            y = _f(r.get(y_col))
            if x is not None and y is not None:
                pts.append((x, y))
        return pts

    # One plot per (regulator, vout, mode)
    sec_groups = _group_rows(rows_all, ["Regulator Name", "Vout", "DCDC Efficiency Mode"])
    for (reg, vout, mode), sec_rows in sorted(sec_groups.items()):
        series_list = []
        idx = 0
        # Series = (Vin, chip, temp)
        inner = _group_rows(sec_rows, ["Vin", "_chip_id", "Temperature"])
        for (vin, chip, temp), s_rows in sorted(inner.items()):
            pts = _pairs(s_rows, "Iout [A]", "Efficiency [Pout/Pin %]")
            if not pts:
                pts = _pairs(s_rows, "IoutSMU", "Efficiency [Pout/Pin %]")
            if not pts:
                continue
            pts = _filter_outliers(sorted(pts))
            if not pts:
                continue
            xs, ys = zip(*pts)
            series_list.append({
                "label":  f"Vin={vin}V | Chip {chip} | T={temp}°C",
                "x": list(xs), "y": list(ys),
                "color": _color(idx),
                "data_attrs": {"mode": mode, "chip": chip,
                               "temp": temp, "vin": _safe_attr(vin),
                               "reg": _safe_attr(reg)},
            })
            idx += 1

        # ── Reference efficiency series ────────────────────────────────
        if ref_data is not None:
            def _lbl_load(k): return f"Vin={k[0]}V | Ch{k[1]} | T={k[2]}°C"
            def _da_load(k):  return {"mode": mode, "chip": k[1], "temp": k[2],
                                      "vin": _safe_attr(k[0]), "reg": _safe_attr(reg)}
            refs, idx = _ref_xy_series(
                ref_data, "Static_Load", (reg, vout, mode),
                ["Regulator Name", "Vout", "DCDC Efficiency Mode"],
                ["Vin", "_chip_id", "Temperature"],
                ["Iout [A]", "IoutSMU"], "Efficiency [Pout/Pin %]",
                ref_label, idx, _da_load, _lbl_load)
            series_list.extend(refs)

        if not series_list:
            continue
        reg_label = REG_LABELS.get(reg, reg)
        mode_safe = _safe_attr(mode)
        # PWM (full) has wider current ranges → 100 mA steps; PWM_L and others use 50 mA
        is_pwm_full = mode.upper() == "PWM"
        x_step = 0.1 if is_pwm_full else 0.05
        x_fmt  = ".1f" if is_pwm_full else ".2f"

        # ── Plot A: Efficiency vs Iout ──────────────────────────────────
        fname = f"pmic_static_load_{_safe_attr(reg)}_vout{_safe_attr(vout)}_{mode_safe}.svg"
        p = _multi_line_chart(
            f"Static Load Regulation — {reg_label}  Vout={vout}V  [{mode}]  — Efficiency",
            "Output Current  Iout [A]", "Efficiency [%]",
            series_list, output_dir / fname,
            y_tick_step=5, y_range=(0, 100),
            x_tick_step=x_step, x_fmt=x_fmt)
        if p:
            plots.setdefault(reg, []).append(p)
            logger.info("Saved: %s", p.name)

        # ── Plot B: Vout [V] vs Iout (load regulation curve) ───────────
        vout_series = []
        vidx = 0
        for (vin, chip, temp), s_rows in sorted(inner.items()):
            pts = []
            for r in s_rows:
                x = _f(r.get("Iout [A]")) or _f(r.get("IoutSMU"))
                y = _f(r.get("Vout [V]"))
                if x is not None and y is not None:
                    pts.append((x, y))
            if not pts:
                continue
            pts = _filter_outliers(sorted(pts))
            if not pts:
                continue
            xs, ys = zip(*pts)
            vout_series.append({
                "label": f"Vin={vin}V | Chip {chip} | T={temp}°C",
                "x": list(xs), "y": list(ys),
                "color": _color(vidx),
                "data_attrs": {"mode": mode, "chip": chip,
                               "temp": temp, "vin": _safe_attr(vin),
                               "reg": _safe_attr(reg)},
            })
            vidx += 1
        if vout_series and ref_data is not None:
            def _da_vl(k): return {"mode": mode, "chip": k[1], "temp": k[2],
                                   "vin": _safe_attr(k[0]), "reg": _safe_attr(reg)}
            def _lbl_vl(k): return f"Vin={k[0]}V | Ch{k[1]} | T={k[2]}°C"
            refs_v, vidx = _ref_xy_series(
                ref_data, "Static_Load", (reg, vout, mode),
                ["Regulator Name", "Vout", "DCDC Efficiency Mode"],
                ["Vin", "_chip_id", "Temperature"],
                ["Iout [A]", "IoutSMU"], "Vout [V]",
                ref_label, vidx, _da_vl, _lbl_vl)
            vout_series.extend(refs_v)
        if vout_series:
            vfname = f"pmic_static_load_vreg_{_safe_attr(reg)}_vout{_safe_attr(vout)}_{mode_safe}.svg"
            pv = _multi_line_chart(
                f"Static Load Regulation — {reg_label}  Vout={vout}V  [{mode}]  — Vout vs Iout",
                "Output Current  Iout [A]", "Output Voltage  Vout [V]",
                vout_series, output_dir / vfname,
                x_tick_step=x_step, x_fmt=x_fmt)
            if pv:
                plots.setdefault(reg, []).append(pv)
                logger.info("Saved: %s", pv.name)

    return plots


# ══════════════════════════════════════════════════════════════════════════
# 2. Static Line Regulation  →  Vin vs Vout
# ══════════════════════════════════════════════════════════════════════════

def plot_static_line(data, output_dir: Path, ref_data=None, ref_label='REF') -> dict:
    """
    One plot per (regulator, vout_target, efficiency_mode).
    Series within each plot = (chip_id, temperature).
    """
    plots: dict = {}
    rows_all = data.get_rows("Static_Line")
    if not rows_all:
        return plots

    # One plot per (regulator, vout, mode, iout_level)
    sec_groups = _group_rows(rows_all, ["Regulator Name", "Vout", "DCDC Efficiency Mode", "IoutSMU"])
    for (reg, vout, mode, iout), sec_rows in sorted(sec_groups.items()):
        series_list = []
        idx = 0
        inner = _group_rows(sec_rows, ["_chip_id", "Temperature"])
        for (chip, temp), s_rows in sorted(inner.items()):
            pts = []
            for r in s_rows:
                x = _f(r.get("Vin [V]"))
                y = _f(r.get("Vout [V]"))
                if x is not None and y is not None:
                    pts.append((x, y))
            if not pts:
                continue
            pts = _filter_outliers(sorted(pts))
            if not pts:
                continue
            xs, ys = zip(*pts)
            series_list.append({
                "label": f"Chip {chip} | T={temp}°C",
                "x": list(xs), "y": list(ys),
                "color": _color(idx),
                "data_attrs": {"mode": mode, "chip": chip,
                               "temp": temp, "reg": _safe_attr(reg)},
            })
            idx += 1

        # ── Reference series ───────────────────────────────────────────────
        if ref_data is not None:
            def _da_line(k):  return {"mode": mode, "chip": k[0], "temp": k[1],
                                      "reg": _safe_attr(reg)}
            def _lbl_line(k): return f"Chip {k[0]} | T={k[1]}°C"
            refs, idx = _ref_xy_series(
                ref_data, "Static_Line", (reg, vout, mode, iout),
                ["Regulator Name", "Vout", "DCDC Efficiency Mode", "IoutSMU"],
                ["_chip_id", "Temperature"],
                ["Vin [V]"], "Vout [V]",
                ref_label, idx, _da_line, _lbl_line)
            series_list.extend(refs)

        if not series_list:
            continue
        reg_label = REG_LABELS.get(reg, reg)
        mode_safe = _safe_attr(mode)
        iout_lbl  = _fmt_current(iout)
        iout_safe = _safe_attr(iout)
        fname = (f"pmic_static_line_{_safe_attr(reg)}_vout{_safe_attr(vout)}"
                 f"_{mode_safe}_iout{iout_safe}.svg")
        p = _multi_line_chart(
            f"Static Line Regulation — {reg_label}  Vout={vout}V  [{mode}]  Iload={iout_lbl}",
            "Input Voltage  Vin [V]", "Output Voltage  Vout [V]",
            series_list, output_dir / fname)
        if p:
            plots.setdefault(reg, []).append(p)

    return plots


# ══════════════════════════════════════════════════════════════════════════
# 3. Quiescence — returns table-ready data (no SVG)
# ══════════════════════════════════════════════════════════════════════════

def build_quiescence_table(data, ref_data=None, ref_label='REF') -> dict:
    """
    Returns {regulator: [row_dict, ...]} where each row_dict has keys:
      temp, vin, mode, chip, iin_disable, iin_enable, delta, status
    Caller renders as HTML table.
    """
    result: dict = {}
    rows_all = data.get_rows("Quiescence", ok_only=False)
    for row in rows_all:
        reg  = row.get("Regulator Name", "").strip()
        temp = row.get("Temperature", "").strip()
        vin  = row.get("Vin", "").strip()
        # also check Vin [V] measured if setpoint missing
        if not vin:
            vin = row.get("Vin [V]", "").strip()
        mode   = row.get("DCDC Efficiency Mode", "").strip()
        chip   = row.get("_chip_id", "")
        dis    = _f(row.get("IinDisable [A]"))
        en     = _f(row.get("IinEnable [A]"))
        delta  = _f(row.get("Delta [A]"))
        status = row.get("Exec Status", "").strip().upper()
        result.setdefault(reg, []).append({
            "temp": temp, "vin": vin, "mode": mode, "chip": chip,
            "iin_disable": dis, "iin_enable": en,
            "delta": delta, "status": status,
        })
    # ── Reference quiescence rows ─────────────────────────────────────────
    if ref_data is not None:
        for row in (ref_data.get_rows("Quiescence", ok_only=False) or []):
            reg  = row.get("Regulator Name", "").strip()
            temp = row.get("Temperature", "").strip()
            vin  = row.get("Vin", "").strip() or row.get("Vin [V]", "").strip()
            mode = row.get("DCDC Efficiency Mode", "").strip()
            chip = f"[{ref_label}] " + str(row.get("_chip_id", ""))
            dis    = _f(row.get("IinDisable [A]"))
            en     = _f(row.get("IinEnable [A]"))
            delta  = _f(row.get("Delta [A]"))
            status = row.get("Exec Status", "").strip().upper()
            result.setdefault(reg, []).append({
                "temp": temp, "vin": vin, "mode": mode, "chip": chip,
                "iin_disable": dis, "iin_enable": en,
                "delta": delta, "status": status,
                "is_ref": True,
            })
    return result


# ══════════════════════════════════════════════════════════════════════════
# 4. Power On  →  Vin vs RiseTime scatter
# ══════════════════════════════════════════════════════════════════════════

def plot_power_on(data, output_dir: Path, ref_data=None, ref_label='REF') -> dict:
    """Vin [V] vs RiseTime [uS], series = (vout_target, mode, chip, temp)"""
    plots: dict = {}
    rows_all = data.get_rows("PowerOn")
    if not rows_all:
        return plots

    reg_groups = _group_rows(rows_all, ["Regulator Name"])
    for (reg,), reg_rows in sorted(reg_groups.items()):
        series_list = []
        idx = 0
        inner = _group_rows(reg_rows, ["Vout", "DCDC Efficiency Mode", "_chip_id", "Temperature"])
        for (vout, mode, chip, temp), s_rows in sorted(inner.items()):
            pts = []
            for r in s_rows:
                x = _f(r.get("Vin [V]"))
                y = _f(r.get("RiseTime [uS]"))
                if x is not None and y is not None and y < 1e10:
                    pts.append((x, y))
            if not pts:
                continue
            pts = _filter_outliers(sorted(pts))
            if not pts:
                continue
            xs, ys = zip(*pts)
            series_list.append({
                "label": f"Vout={vout}V {mode} Chip {chip} T={temp}°C",
                "x": list(xs), "y": list(ys),
                "color": _color(idx),
                "data_attrs": {"mode": mode, "chip": chip, "temp": temp,
                               "reg": _safe_attr(reg)},
            })
            idx += 1

        # ── Reference series ───────────────────────────────────────────────
        if ref_data is not None:
            def _da_pon(k):  return {"mode": k[1], "chip": k[2], "temp": k[3],
                                     "reg": _safe_attr(reg)}
            def _lbl_pon(k): return f"Vout={k[0]}V {k[1]} Ch{k[2]} T={k[3]}°C"
            refs, idx = _ref_xy_series(
                ref_data, "PowerOn", (reg,),
                ["Regulator Name"],
                ["Vout", "DCDC Efficiency Mode", "_chip_id", "Temperature"],
                ["Vin [V]"], "RiseTime [uS]",
                ref_label, idx, _da_pon, _lbl_pon,
                extra_filter=lambda r: (_f(r.get("RiseTime [uS]")) or 0) < 1e10)
            series_list.extend(refs)

        if not series_list:
            continue
        reg_label = REG_LABELS.get(reg, reg)
        fname = f"pmic_poweron_{_safe_attr(reg)}.svg"
        p = _scatter_chart(
            f"Power On — Slew Rate  vs  Vin — {reg_label}",
            "Input Voltage  Vin [V]", "Rise Time [µs]",
            series_list, output_dir / fname)
        if p:
            plots.setdefault(reg, []).append(p)

    return plots


# ══════════════════════════════════════════════════════════════════════════
# 5. Transient Response  →  Load step vs Vout p2p
# ══════════════════════════════════════════════════════════════════════════

def plot_transient(data, output_dir: Path, ref_data=None, ref_label='REF') -> dict:
    """
    Separate plots per (reg, vout, mode, load_high, load_low).
    Two charts per group:
      Plot A: Overshoot  [mV] = (Vout Max - Vout_setpoint) * 1000
      Plot B: Undershoot [mV] = (Vout_setpoint - Vout Min)  * 1000
    X-axis: 3 discrete Vin setpoints as evenly-spaced categories.
    Series within each plot = (chip, temp, slope direction).
    """
    plots: dict = {}
    rows_all = data.get_rows("Transient")
    if not rows_all:
        return plots

    # Sorted Vin category labels (strings) used across all plots
    _vin_set = {r.get("Vin", "").strip() for r in rows_all if r.get("Vin", "").strip()}
    if ref_data is not None:
        for r in (ref_data.get_rows("Transient") or []):
            v = r.get("Vin", "").strip()
            if v: _vin_set.add(v)
    all_vins = sorted(
        _vin_set,
        key=lambda v: float(v) if v.replace(".", "").lstrip("-").isdigit() else 0
    )

    outer_dims = ["Regulator Name", "Vout", "DCDC Efficiency Mode",
                  "Load step current high", "Load step current low"]
    outer_groups = _group_rows(rows_all, outer_dims)

    for (reg, vout, mode, load_high, load_low), grp_rows in sorted(outer_groups.items()):
        reg_label = REG_LABELS.get(reg, reg)
        mode_safe = _safe_attr(mode)
        lh_lbl    = _fmt_current(load_high)
        ll_lbl    = _fmt_current(load_low)
        step_lbl  = f"{ll_lbl}→{lh_lbl}"
        lh_safe   = _safe_attr(load_high)
        ll_safe   = _safe_attr(load_low)

        for plot_tag, y_col, y_lbl, slope_filter, agg_fn, init_val in [
            # Step-down (load removed, slope "N") → plot Vout Max
            ("overshoot",  "Vout Max", "Vout Max [V]", "N", max, -1e9),
            # Step-up   (load applied, slope "P") → plot Vout Min
            ("undershoot", "Vout Min", "Vout Min [V]", "P", min,  1e9),
        ]:
            series_list = []
            idx = 0
            inner = _group_rows(grp_rows, ["_chip_id", "Temperature", "Slope"])
            for (chip, temp, slope), s_rows in sorted(inner.items()):
                # Only use the relevant slope direction for each metric
                if slope.strip().upper() != slope_filter:
                    continue
                dir_lbl = "step↓" if slope_filter == "N" else "step↑"
                values  = {}   # vin_str → V
                for r in s_rows:
                    vin_s  = r.get("Vin", "").strip()
                    meas   = _f(r.get(y_col))
                    if not vin_s or meas is None:
                        continue
                    # keep worst-case: max for Vout Max, min for Vout Min
                    values[vin_s] = agg_fn(values.get(vin_s, init_val), meas)
                if not values:
                    continue
                series_list.append({
                    "label": f"Ch{chip} | T={temp}°C | {dir_lbl}",
                    "values": values,
                    "color": _color(idx),
                    "data_attrs": {"mode": mode, "chip": chip,
                                   "temp": temp, "reg": _safe_attr(reg)},
                })
                idx += 1

            # ── Reference series ─────────────────────────────────────────
            if ref_data is not None:
                ref_tr = ref_data.get_rows("Transient") or []
                if ref_tr:
                    outer_key_tr = (reg, vout, mode, load_high, load_low)
                    ref_grp_tr = _group_rows(ref_tr, outer_dims)
                    ref_grp_rows = ref_grp_tr.get(outer_key_tr, [])
                    if ref_grp_rows:
                        ref_inner_tr = _group_rows(ref_grp_rows,
                                                   ["_chip_id", "Temperature", "Slope"])
                        for (chip_r, temp_r, slope_r), rr in sorted(ref_inner_tr.items()):
                            if slope_r.strip().upper() != slope_filter:
                                continue
                            dir_lbl_r = "step↓" if slope_filter == "N" else "step↑"
                            vals_r = {}
                            for r in rr:
                                vin_s_r  = r.get("Vin", "").strip()
                                meas_r   = _f(r.get(y_col))
                                if not vin_s_r or meas_r is None:
                                    continue
                                vals_r[vin_s_r] = agg_fn(vals_r.get(vin_s_r, init_val), meas_r)
                            if vals_r:
                                series_list.append({
                                    "label":  f"[{ref_label}] Ch{chip_r} | T={temp_r}°C | {dir_lbl_r}",
                                    "values": vals_r,
                                    "color":  _color(idx),
                                    "ref":    True,
                                    "data_attrs": {"mode": mode, "chip": chip_r,
                                                   "temp": temp_r, "reg": _safe_attr(reg)},
                                })
                                idx += 1

            if not series_list:
                continue

            title = (f"Transient — {reg_label}  Vout={vout}V  [{mode}]  "
                     f"Load {step_lbl}  — {plot_tag.capitalize()}")
            fname = (f"pmic_transient_{plot_tag}_{_safe_attr(reg)}"
                     f"_vout{_safe_attr(vout)}_{mode_safe}"
                     f"_lh{lh_safe}_ll{ll_safe}.svg")
            p = _cat_dot_chart(
                title, all_vins, y_lbl,
                series_list, output_dir / fname,
                y_tick_step=None, y_range=(None, None))
            if p:
                plots.setdefault(reg, []).append(p)
                logger.info("Saved: %s", p.name)

    return plots


# ══════════════════════════════════════════════════════════════════════════
# 6. Voltage Transitions  →  Vout Max / Vout Min vs Mode+Vin+Temp
# ══════════════════════════════════════════════════════════════════════════

def plot_voltage_transitions(data, output_dir: Path, ref_data=None, ref_label='REF') -> dict:
    """
    Per (regulator, vout_target) generates:
      Plot A: Vout Max & Vout Min vs (Vin, Iload) categories — series = (chip, temp, mode)
      Plot B: Rise Time [µs]   — Slope=P rows
      Plot C: Fall Time [µs]   — Slope=N rows
    X-axis categories: "Vin=xV / I=yA"
    Legend includes Power Mode.
    """

    # ── Case-insensitive column lookup helper ──────────────────────────────
    def _col_val(row, *candidates):
        rl = {k.lower().strip(): v for k, v in row.items()}
        for c in candidates:
            v = rl.get(c.lower().strip())
            if v is not None:
                return _f(v)
        return None

    def _iload(row):
        """Get load current from row, trying common column names."""
        return (_col_val(row, "Iout [A]") or
                _col_val(row, "IoutSMU") or
                _col_val(row, "Iout[A]") or
                _col_val(row, "Load current [A]"))

    def _cat_label(vin, iload):
        if iload is not None:
            return f"Vin={vin}V / I={_fmt_current(str(iload))}"
        return f"Vin={vin}V"

    plots: dict = {}
    rows_all = data.get_rows("VoltageTransitions")
    if not rows_all:
        return plots

    def _build_plots(reg_rows, reg, vout, ref_rows_for_reg, reg_label):
        """Build all plots for one (reg, vout) group."""
        local_plots = []

        # ── Collect all category labels (Vin + Iload) ─────────────────────
        cats_set: set = set()
        for r in reg_rows:
            vin   = r.get("Vin", "").strip()
            iload = _iload(r)
            cats_set.add(_cat_label(vin, iload))
        categories = sorted(cats_set)

        # ═══ Plot A: Vout Max + Vout Min ══════════════════════════════════
        series_list = []
        idx = 0
        inner = _group_rows(reg_rows, ["_chip_id", "Temperature", "DCDC Efficiency Mode"])
        for (chip, temp, mode), s_rows in sorted(inner.items()):
            for metric, col in [("Max V", "Vout Max "), ("Min V", "Vout Min ")]:
                vals_dict: dict = {}
                for r in s_rows:
                    vin   = r.get("Vin", "").strip()
                    iload = _iload(r)
                    cat   = _cat_label(vin, iload)
                    v = _f(r.get(col)) if col in r else _f(r.get(col.strip()))
                    if v is None:
                        v = _col_val(r, col, col.strip())
                    if v is not None and abs(v) < 1e10:
                        if metric == "Max V":
                            vals_dict[cat] = max(vals_dict.get(cat, -1e9), v)
                        else:
                            vals_dict[cat] = min(vals_dict.get(cat, 1e9), v)
                if not vals_dict:
                    continue
                series_list.append({
                    "label": f"{metric} | Ch{chip} | T={temp}°C | {mode}",
                    "values": vals_dict,
                    "color": _color(idx),
                    "data_attrs": {"chip": chip, "temp": temp, "mode": mode,
                                   "reg": _safe_attr(reg)},
                })
                idx += 1

        # ref for Plot A
        if ref_rows_for_reg:
            ref_inner = _group_rows(ref_rows_for_reg,
                                    ["_chip_id", "Temperature", "DCDC Efficiency Mode"])
            for (chip_r, temp_r, mode_r), rr in sorted(ref_inner.items()):
                for metric_r, col_r in [("Max V", "Vout Max "), ("Min V", "Vout Min ")]:
                    vd = {}
                    for r in rr:
                        vin_r   = r.get("Vin", "").strip()
                        iload_r = _iload(r)
                        cat_r   = _cat_label(vin_r, iload_r)
                        vr = _col_val(r, col_r, col_r.strip())
                        if vr is not None and abs(vr) < 1e10:
                            if metric_r == "Max V":
                                vd[cat_r] = max(vd.get(cat_r, -1e9), vr)
                            else:
                                vd[cat_r] = min(vd.get(cat_r, 1e9), vr)
                    if vd:
                        series_list.append({
                            "label":  f"[{ref_label}] {metric_r} | Ch{chip_r} | T={temp_r}°C | {mode_r}",
                            "values": vd,
                            "color":  _color(idx),
                            "ref":    True,
                            "data_attrs": {"chip": chip_r, "temp": temp_r, "mode": mode_r,
                                           "reg": _safe_attr(reg)},
                        })
                        idx += 1

        if series_list:
            fname = f"pmic_vtrans_{_safe_attr(reg)}_vout{_safe_attr(vout)}.svg"
            p = _cat_dot_chart(
                f"Voltage Transitions — {reg_label}  Vout={vout}V",
                categories, "Voltage [V]",
                series_list, output_dir / fname)
            if p:
                local_plots.append(p)

        # ═══ Plots B & C: Rise / Fall Time ════════════════════════════════
        for time_tag, slope_filter, time_lbl, col_candidates in [
            ("risetime", "P",
             "Rise Time [µs]",
             ["RiseTime [uS]", "Rise Time [uS]", "RiseTime [us]",
              "Rise Time [us]", "Rise Time[uS]"]),
            ("falltime", "N",
             "Fall Time [µs]",
             ["Measured Fall Time [uS]", "Measured Fall Time [us]",
              "Fall Time [uS]", "Fall Time [us]",
              "Measured Fall Time [pSec]", "Fall Time [pSec]"]),
        ]:
            t_series: list = []
            tidx = 0
            inner2 = _group_rows(reg_rows, ["_chip_id", "Temperature", "DCDC Efficiency Mode"])
            for (chip, temp, mode), s_rows in sorted(inner2.items()):
                acc: dict = {}
                for r in s_rows:
                    if r.get("Slope", "").strip().upper() != slope_filter:
                        continue
                    vin   = r.get("Vin", "").strip()
                    iload = _iload(r)
                    cat   = _cat_label(vin, iload)
                    v = _col_val(r, *col_candidates)
                    if v is not None and abs(v) < 1e15:
                        acc.setdefault(cat, []).append(v)
                vals_avg = {cat: sum(vs) / len(vs) for cat, vs in acc.items()}
                if not vals_avg:
                    continue
                t_series.append({
                    "label": f"Ch{chip} | T={temp}°C | {mode}",
                    "values": vals_avg,
                    "color": _color(tidx),
                    "data_attrs": {"chip": chip, "temp": temp, "mode": mode,
                                   "reg": _safe_attr(reg)},
                })
                tidx += 1

            # ref for rise/fall
            if ref_rows_for_reg:
                ref_inner2 = _group_rows(ref_rows_for_reg,
                                         ["_chip_id", "Temperature", "DCDC Efficiency Mode"])
                for (chip_r, temp_r, mode_r), rr in sorted(ref_inner2.items()):
                    acc2: dict = {}
                    for r in rr:
                        if r.get("Slope", "").strip().upper() != slope_filter:
                            continue
                        vin_r   = r.get("Vin", "").strip()
                        iload_r = _iload(r)
                        cat_r   = _cat_label(vin_r, iload_r)
                        v = _col_val(r, *col_candidates)
                        if v is not None and abs(v) < 1e15:
                            acc2.setdefault(cat_r, []).append(v)
                    vd2_avg = {cat: sum(vs) / len(vs) for cat, vs in acc2.items()}
                    if vd2_avg:
                        t_series.append({
                            "label":  f"[{ref_label}] Ch{chip_r} | T={temp_r}°C | {mode_r}",
                            "values": vd2_avg,
                            "color":  _color(tidx),
                            "ref":    True,
                            "data_attrs": {"chip": chip_r, "temp": temp_r, "mode": mode_r,
                                           "reg": _safe_attr(reg)},
                        })
                        tidx += 1

            if not t_series:
                continue
            edge_title = "Rising Edge" if slope_filter == "P" else "Falling Edge"
            t_fname = (f"pmic_vtrans_{time_tag}_{_safe_attr(reg)}"
                       f"_vout{_safe_attr(vout)}.svg")
            sp = _cat_dot_chart(
                f"Voltage Transitions — {reg_label}  Vout={vout}V  — {edge_title} Time",
                categories, time_lbl,
                t_series, output_dir / t_fname)
            if sp:
                local_plots.append(sp)

        return local_plots

    # ── Top-level: group and dispatch ──────────────────────────────────────
    reg_groups = _group_rows(rows_all, ["Regulator Name", "Vout"])

    # Pre-load ref rows if available
    ref_by_reg: dict = {}
    if ref_data is not None:
        ref_vt = ref_data.get_rows("VoltageTransitions") or []
        if ref_vt:
            ref_grp = _group_rows(ref_vt, ["Regulator Name", "Vout"])
            ref_by_reg = ref_grp

    for (reg, vout), reg_rows in sorted(reg_groups.items()):
        reg_label = REG_LABELS.get(reg, reg)
        ref_rows_for_reg = ref_by_reg.get((reg, vout), [])
        for p in _build_plots(reg_rows, reg, vout, ref_rows_for_reg, reg_label):
            plots.setdefault(reg, []).append(p)
            logger.info("Saved: %s", p.name)

    return plots


# ══════════════════════════════════════════════════════════════════════════
# 7. Auto Mode Transitions  →  Iout vs Efficiency  AND  Iout vs Vout Min
# ══════════════════════════════════════════════════════════════════════════

def plot_automode(data, output_dir: Path, ref_data=None, ref_label='REF') -> dict:
    """
    Two plots per (regulator, vout_target):
      Plot A: Iout [A] vs Efficiency [%]
      Plot B: Iout [A] vs Vout Min
    """
    plots: dict = {}
    rows_all = data.get_rows("AutoMode")
    if not rows_all:
        return plots

    sec_groups = _group_rows(rows_all, ["Regulator Name", "Vout"])
    for (reg, vout), sec_rows in sorted(sec_groups.items()):
        reg_label = REG_LABELS.get(reg, reg)

        for plot_tag, y_col, y_lbl in [
            ("eff",  "Efficiency [Pout/Pin %]", "Efficiency [%]"),
            ("vmin", "Vout Min ",               "Vout Minimum [V]"),
            ("vmax", "Vout Max ",               "Vout Maximum [V]"),
        ]:
            series_list = []
            idx = 0
            inner = _group_rows(sec_rows, ["Vin", "_chip_id", "Temperature"])
            for (vin, chip, temp), s_rows in sorted(inner.items()):
                pts = []
                for r in s_rows:
                    # Iout: prefer IoutSMU (float) then Iout [A]
                    x = _f(r.get("Iout [A]"))
                    if x is None:
                        x = _f(r.get("IoutSMU"))
                    y_raw = r.get(y_col, "")
                    if not y_raw.strip():
                        y_raw = r.get(y_col.strip(), "")
                    y = _f(y_raw)
                    if x is not None and y is not None and abs(y) < 1e10:
                        pts.append((x, y))
                if not pts:
                    continue
                pts = _filter_outliers(sorted(pts))
                if not pts:
                    continue
                xs, ys = zip(*pts)
                series_list.append({
                    "label": f"Vin={vin}V | Chip {chip} | T={temp}°C",
                    "x": list(xs), "y": list(ys),
                    "color": _color(idx),
                    "data_attrs": {"chip": chip, "temp": temp,
                                   "vin": _safe_attr(vin), "reg": _safe_attr(reg)},
                })
                idx += 1

            # ── Reference series ─────────────────────────────────────────
            if ref_data is not None:
                def _da_am(k):  return {"chip": k[1], "temp": k[2],
                                        "vin": _safe_attr(k[0]), "reg": _safe_attr(reg)}
                def _lbl_am(k): return f"Vin={k[0]}V | Ch{k[1]} | T={k[2]}°C"
                y_col_am = y_col if not y_col.endswith(" ") else y_col
                refs_am, idx = _ref_xy_series(
                    ref_data, "AutoMode", (reg, vout),
                    ["Regulator Name", "Vout"],
                    ["Vin", "_chip_id", "Temperature"],
                    ["Iout [A]", "IoutSMU"], y_col_am,
                    ref_label, idx, _da_am, _lbl_am)
                series_list.extend(refs_am)

            if not series_list:
                continue
            x_lbl = "Output Current  Iout [A]"
            title  = (f"Auto Mode — {reg_label}  Vout={vout}V  — "
                      + ("Efficiency" if plot_tag == "eff"
                         else "Min Output Voltage" if plot_tag == "vmin"
                         else "Max Output Voltage"))
            fname  = f"pmic_automode_{plot_tag}_{_safe_attr(reg)}_vout{_safe_attr(vout)}.svg"
            extra = {"y_tick_step": 5, "y_range": (0, 100)} if plot_tag == "eff" else {}
            p = _multi_line_chart(title, x_lbl, y_lbl,
                                  series_list, output_dir / fname, **extra)
            if p:
                plots.setdefault(reg, []).append(p)

    return plots


# ══════════════════════════════════════════════════════════════════════════
# Master entry point
# ══════════════════════════════════════════════════════════════════════════

def generate_all_pmic_plots(data, output_dir: Path,
                            ref_data=None, ref_label="REF") -> dict:
    """
    Generate all PMIC plots. Returns:
    {
      'Static_Load':        {reg: [Path, ...]},
      'Static_Line':        {reg: [Path, ...]},
      'Quiescence':         None (table only),
      'PowerOn':            {reg: [Path, ...]},
      'Transient':          {reg: [Path, ...]},
      'VoltageTransitions': {reg: [Path, ...]},
      'AutoMode':           {reg: [Path, ...]},
    }
    ref_data: optional second PMICData object whose series are overlaid (dashed/hollow)
    ref_label: label prefix used on reference series (e.g. "REF", "WW04", ...)
    """
    pdir = output_dir / "pmic_plots"
    pdir.mkdir(parents=True, exist_ok=True)

    kw = dict(ref_data=ref_data, ref_label=ref_label)
    results = {
        "Static_Load":        plot_static_load(data, pdir, **kw),
        "Static_Line":        plot_static_line(data, pdir, **kw),
        "Quiescence":         build_quiescence_table(data, **kw),
        "PowerOn":            plot_power_on(data, pdir, **kw),
        "Transient":          plot_transient(data, pdir, **kw),
        "VoltageTransitions": plot_voltage_transitions(data, pdir, **kw),
        "AutoMode":           plot_automode(data, pdir, **kw),
    }
    if ref_data is not None:
        logger.info("PMIC plots with reference overlay generated in %s", pdir)
    else:
        logger.info("PMIC plots generated in %s", pdir)
    return results
