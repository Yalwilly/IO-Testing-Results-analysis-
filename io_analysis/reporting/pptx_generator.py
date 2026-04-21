"""
PowerPoint (.pptx) report generator for IO Testing Results Analysis.
Uses Python standard library only (zipfile + xml) — no python-pptx required.

Slide deck structure:
  Slide 1  — Title slide
  Slide 2  — Executive Summary (pass/fail cards + overall stats)
  Slide 3  — Parameter Pass/Fail overview table (all params)
  Slide N… — One slide per active test section with:
               • Section title
               • Stats mini-table (mean / std / min / max / pass%)
               • Embedded SVG chart images (PNG converted via SVG→EMF-fallback,
                 or embedded as SVG within an image placeholder using OOXML)
  Last     — Appendix: per-flow DUT counts
"""

import io
import logging
import math
import re
import textwrap
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from io_analysis.config import Config
from io_analysis.data.models import AnalysisResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# EMU helpers  (1 inch = 914400 EMU, 1 pt = 12700 EMU)
# Slide size: 10 in × 7.5 in (widescreen 13.33 × 7.5 also common)
# ---------------------------------------------------------------------------
_W  = 9144000   # slide width  (10 in)
_H  = 6858000   # slide height (7.5 in)
_M  = 457200    # margin       (0.5 in)
_TH = 685800    # title area height (0.75 in)
_PT = 12700     # 1 point in EMU

# Colours (hex without #)
_C_DARK   = "2C3E50"
_C_ACCENT = "2980B9"
_C_PASS   = "27AE60"
_C_FAIL   = "E74C3C"
_C_WARN   = "E67E22"
_C_LIGHT  = "ECF0F1"
_C_WHITE  = "FFFFFF"
_C_GRAY   = "95A5A6"


# ---------------------------------------------------------------------------
# Low-level XML helpers
# ---------------------------------------------------------------------------

_NSMAP = {
    "a":   "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p":   "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r":   "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "dc":  "http://purl.org/dc/elements/1.1/",
    "cp":  "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "ep":  "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
    "ct":  "http://schemas.openxmlformats.org/package/2006/content-types",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
}

for _pfx, _uri in _NSMAP.items():
    ET.register_namespace(_pfx, _uri)


def _x(tag: str, attrib: Optional[dict] = None, text: Optional[str] = None,
        children: Optional[list] = None) -> ET.Element:
    """Create an XML element, resolving 'prefix:localname' tags."""
    if ":" in tag:
        pfx, local = tag.split(":", 1)
        ns = _NSMAP[pfx]
        full = f"{{{ns}}}{local}"
    else:
        full = tag
    el = ET.Element(full, attrib or {})
    if text is not None:
        el.text = str(text)
    for child in (children or []):
        el.append(child)
    return el


def _toxml(el: ET.Element) -> bytes:
    return ET.tostring(el, encoding="UTF-8", xml_declaration=True)


def _sp(x, y, w, h) -> dict:
    """Positional dict for xfrm helpers."""
    return {"x": x, "y": y, "w": w, "h": h}


# ---------------------------------------------------------------------------
# DrawingML shape builders
# ---------------------------------------------------------------------------

def _solidFill(hex_color: str) -> ET.Element:
    return _x("a:solidFill", children=[
        _x("a:srgbClr", {"val": hex_color})
    ])


def _ln(w_pt=1, hex_color="CCCCCC") -> ET.Element:
    return _x("a:ln", {"w": str(int(w_pt * 12700))}, children=[
        _solidFill(hex_color)
    ])


def _txBody(paras: list[ET.Element],
            anchor: str = "ctr",
            wrap: str = "square",
            inset: int = 91440) -> ET.Element:
    return _x("p:txBody", children=[
        _x("a:bodyPr", {
            "anchor": anchor, "wrap": wrap,
            "lIns": str(inset), "rIns": str(inset),
            "tIns": str(inset // 2), "bIns": str(inset // 2),
        }),
        _x("a:lstStyle"),
        *paras,
    ])


def _para(text: str, size_pt: int = 14, bold: bool = False,
          color: str = _C_DARK, align: str = "l",
          italic: bool = False) -> ET.Element:
    rPr = _x("a:rPr", {
        "lang": "en-US", "sz": str(size_pt * 100),
        "b": "1" if bold else "0",
        "i": "1" if italic else "0",
        "dirty": "0",
    }, children=[_solidFill(color)])
    r = _x("a:r", children=[rPr, _x("a:t", text=text)])
    pPr = _x("a:pPr", {"algn": align})
    return _x("a:p", children=[pPr, r])


def _rect_sp(sp_id: int, name: str,
             x, y, w, h,
             fill_color: str = _C_WHITE,
             line_color: Optional[str] = _C_LIGHT,
             line_pt: float = 0.75,
             text_paras: Optional[list] = None,
             rx: int = 0) -> ET.Element:
    """Generic filled rectangle / text box shape."""
    spPr_children = [
        _x("a:xfrm", children=[
            _x("a:off",  {"x": str(x), "y": str(y)}),
            _x("a:ext",  {"cx": str(w), "cy": str(h)}),
        ]),
        _x("a:prstGeom", {"prst": "roundRect" if rx else "rect"},
           children=[_x("a:avLst", children=[
               _x("a:gd", {"name": "adj", "fmla": f"val {rx}"})
           ] if rx else [])]),
        _solidFill(fill_color),
    ]
    if line_color:
        spPr_children.append(_ln(line_pt, line_color))
    else:
        spPr_children.append(_x("a:ln", children=[_x("a:noFill")]))

    nvSpPr = _x("p:nvSpPr", children=[
        _x("p:cNvPr", {"id": str(sp_id), "name": name}),
        _x("p:cNvSpPr"),
        _x("p:nvPr"),
    ])
    spPr = _x("p:spPr", children=spPr_children)
    children = [nvSpPr, spPr]
    if text_paras is not None:
        children.append(_txBody(text_paras))
    return _x("p:sp", children=children)


def _title_sp(sp_id: int, x, y, w, h, title: str, size_pt=24) -> ET.Element:
    return _rect_sp(
        sp_id, "Title", x, y, w, h,
        fill_color=_C_DARK,
        line_color=None,
        text_paras=[_para(title, size_pt=size_pt, bold=True,
                          color=_C_WHITE, align="l")],
    )


def _card(sp_id: int, x, y, w, h,
          label: str, value: str,
          fill: str = _C_ACCENT, val_size=28) -> ET.Element:
    return _rect_sp(
        sp_id, label, x, y, w, h,
        fill_color=fill,
        line_color=None,
        rx=36000,
        text_paras=[
            _para(value, size_pt=val_size, bold=True, color=_C_WHITE, align="ctr"),
            _para(label,  size_pt=9,       bold=False, color=_C_WHITE, align="ctr"),
        ],
    )


def _pic_sp(sp_id: int, name: str, rel_id: str,
            x, y, w, h) -> ET.Element:
    """Correct OOXML p:pic shape — placed directly in spTree.

    Using p: namespace for nvPicPr/blipFill/spPr (presentationml, not pic:).
    A p:graphicFrame is NOT used for pictures; that is only for tables/charts.
    """
    _P = _NSMAP["p"]
    el = ET.Element(f"{{{_P}}}pic")
    el.append(_x("p:nvPicPr", children=[
        _x("p:cNvPr", {"id": str(sp_id), "name": name}),
        _x("p:cNvPicPr"),
        _x("p:nvPr"),
    ]))
    el.append(_x("p:blipFill", children=[
        _x("a:blip", {
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed": rel_id,
        }),
        _x("a:stretch", children=[_x("a:fillRect")]),
    ]))
    el.append(_x("p:spPr", children=[
        _x("a:xfrm", children=[
            _x("a:off", {"x": str(x), "y": str(y)}),
            _x("a:ext", {"cx": str(w), "cy": str(h)}),
        ]),
        _x("a:prstGeom", {"prst": "rect"}, children=[_x("a:avLst")]),
        _x("a:ln", children=[_x("a:noFill")]),
    ]))
    return el


# ---------------------------------------------------------------------------
# Table builder
# ---------------------------------------------------------------------------

def _tbl_cell(text: str, w: int,
              bold=False, color=_C_DARK, fill=_C_WHITE,
              size_pt=9, align="l") -> ET.Element:
    tc = _x("a:tc", children=[
        _txBody([_para(text, size_pt=size_pt, bold=bold,
                       color=color, align=align)], inset=45720),
        _x("a:tcPr", children=[
            _solidFill(fill),
            _ln(0.5, "CCCCCC"),
        ]),
    ])
    return tc


def _tbl_row(cells: list[ET.Element], h: int) -> ET.Element:
    return _x("a:tr", {"h": str(h)}, children=cells)


def _table_sp(sp_id: int, x, y, w, h,
              headers: List[str],
              rows: List[List[str]],
              col_widths: Optional[List[int]] = None) -> ET.Element:
    n_cols = len(headers)
    if col_widths is None:
        cw = w // n_cols
        col_widths = [cw] * n_cols
        col_widths[-1] = w - sum(col_widths[:-1])

    row_h = 310000  # ~0.34 in per row
    hdr_h = 370000

    tblPr  = _x("a:tblPr", {"firstRow": "1", "bandRow": "1"},
                children=[_solidFill(_C_WHITE)])
    tblGrid = _x("a:tblGrid", children=[
        _x("a:gridCol", {"w": str(cw)}) for cw in col_widths
    ])

    hdr_cells = [_tbl_cell(h_txt, col_widths[i],
                            bold=True, color=_C_WHITE, fill=_C_DARK,
                            size_pt=9, align="ctr")
                 for i, h_txt in enumerate(headers)]
    tbl_rows = [_tbl_row(hdr_cells, hdr_h)]

    for ri, row_data in enumerate(rows):
        fill = "F4F6F7" if ri % 2 == 0 else _C_WHITE
        cells = []
        for ci, cell_txt in enumerate(row_data):
            cell_fill = fill
            cell_color = _C_DARK
            cell_bold = False
            if ci == len(row_data) - 1:  # Status column heuristic
                ltxt = cell_txt.lower()
                if ltxt in ("pass", "all pass"):
                    cell_fill = "D5F5E3"; cell_color = "1A7A3D"; cell_bold = True
                elif ltxt in ("fail", "all fail"):
                    cell_fill = "FADBD8"; cell_color = "A93226"; cell_bold = True
                elif "marginal" in ltxt:
                    cell_fill = "FDEACD"; cell_color = "B7460E"; cell_bold = True
            cells.append(_tbl_cell(cell_txt, col_widths[ci],
                                    bold=cell_bold, color=cell_color,
                                    fill=cell_fill, size_pt=8))
        tbl_rows.append(_tbl_row(cells, row_h))

    tbl = _x("a:tbl", children=[tblPr, tblGrid, *tbl_rows])

    nvGF = _x("p:nvGraphicFramePr", children=[
        _x("p:cNvPr", {"id": str(sp_id), "name": f"Table{sp_id}"}),
        _x("p:cNvGraphicFramePr", children=[
            _x("a:graphicFrameLocks", {"noGrp": "1"})
        ]),
        _x("p:nvPr"),
    ])
    xfrm = _x("p:xfrm", children=[
        _x("a:off",  {"x": str(x), "y": str(y)}),
        _x("a:ext",  {"cx": str(w), "cy": str(h)}),
    ])
    graphic = ET.Element(
        "{http://schemas.openxmlformats.org/drawingml/2006/main}graphic"
    )
    gd = ET.SubElement(
        graphic,
        "{http://schemas.openxmlformats.org/drawingml/2006/main}graphicData",
        {"uri": "http://schemas.openxmlformats.org/drawingml/2006/table"},
    )
    gd.append(tbl)
    return _x("p:graphicFrame", children=[nvGF, xfrm, graphic])


# ---------------------------------------------------------------------------
# Slide builder
# ---------------------------------------------------------------------------

class _SlideBuilder:
    def __init__(self, slide_num: int, slide_layout_rel: str = "rId1"):
        self._num = slide_num
        self._layout_rel = slide_layout_rel
        self._shapes: list[ET.Element] = []
        self._rels: list[tuple] = []   # (rel_id, type, target, target_mode)
        self._next_id = 10
        self._next_rid = 2  # rId1 = layout

    def _new_id(self) -> int:
        v = self._next_id
        self._next_id += 1
        return v

    def _new_rid(self) -> str:
        v = f"rId{self._next_rid}"
        self._next_rid += 1
        return v

    def add_shape(self, shape: ET.Element):
        self._shapes.append(shape)

    def add_image_rel(self, target: str) -> str:
        rid = self._new_rid()
        self._rels.append((
            rid,
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
            target,
            "Internal",
        ))
        return rid

    def add_title(self, text: str, subtitle: str = ""):
        self.add_shape(_title_sp(
            self._new_id(), _M, _M // 2,
            _W - 2 * _M, _TH, text, size_pt=22,
        ))
        if subtitle:
            self.add_shape(_rect_sp(
                self._new_id(), "Sub", _M, _M // 2 + _TH + 20000,
                _W - 2 * _M, 300000,
                fill_color=_C_DARK, line_color=None,
                text_paras=[_para(subtitle, 11, color=_C_GRAY, align="l")],
            ))

    def add_card(self, x, y, w, h, label, value, fill=_C_ACCENT):
        self.add_shape(_card(self._new_id(), x, y, w, h, label, value, fill))

    def add_text_box(self, x, y, w, h, paras, fill=_C_WHITE, line=_C_LIGHT):
        self.add_shape(_rect_sp(
            self._new_id(), "TxtBox", x, y, w, h,
            fill_color=fill, line_color=line,
            text_paras=paras,
        ))

    def add_table(self, x, y, w, h, headers, rows, col_widths=None):
        self.add_shape(_table_sp(
            self._new_id(), x, y, w, h, headers, rows, col_widths
        ))

    def add_svg(self, svg_path: Path, x, y, w, h):
        """Embed an SVG file as a p:pic shape (Office 2016+ renders SVG natively)."""
        target = f"../media/{svg_path.name}"
        rid = self.add_image_rel(target)
        pic = _pic_sp(self._new_id(), svg_path.stem, rid, x, y, w, h)
        self.add_shape(pic)

    def build_xml(self) -> bytes:
        spTree = _x("p:spTree", children=[
            _x("p:nvGrpSpPr", children=[
                _x("p:cNvPr", {"id": "1", "name": ""}),
                _x("p:cNvGrpSpPr"),
                _x("p:nvPr"),
            ]),
            _x("p:grpSpPr", children=[
                _x("a:xfrm", children=[
                    _x("a:off",  {"x": "0", "y": "0"}),
                    _x("a:ext",  {"cx": "0", "cy": "0"}),
                    _x("a:chOff", {"x": "0", "y": "0"}),
                    _x("a:chExt", {"cx": "0", "cy": "0"}),
                ])
            ]),
            *self._shapes,
        ])
        cSld = _x("p:cSld", children=[
            _x("p:bg", children=[
                _x("p:bgPr", children=[
                    _solidFill(_C_WHITE),
                ])
            ]),
            spTree,
        ])
        sld = _x("p:sld", {
            "xmlns:a": _NSMAP["a"],
            "xmlns:p": _NSMAP["p"],
            "xmlns:r": _NSMAP["r"],
        }, children=[
            cSld,
            _x("p:clrMapOvr", children=[_x("a:masterClrMapping")]),
        ])
        return ET.tostring(sld, encoding="UTF-8", xml_declaration=True)

    def build_rels_xml(self) -> bytes:
        root = ET.Element(
            "Relationships",
            {"xmlns": "http://schemas.openxmlformats.org/package/2006/relationships"}
        )
        # Layout relationship (always rId1)
        ET.SubElement(root, "Relationship", {
            "Id": "rId1",
            "Type": ("http://schemas.openxmlformats.org/officeDocument/2006/"
                     "relationships/slideLayout"),
            "Target": self._layout_rel,
        })
        for rid, rtype, target, mode in self._rels:
            attrib = {"Id": rid, "Type": rtype, "Target": target}
            if mode == "External":
                attrib["TargetMode"] = "External"
            ET.SubElement(root, "Relationship", attrib)
        return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


# ---------------------------------------------------------------------------
# Full PPTX package builder
# ---------------------------------------------------------------------------

class _PptxBuilder:
    def __init__(self):
        self._slides: list[_SlideBuilder] = []
        self._media: dict[str, bytes] = {}  # name → bytes

    def new_slide(self) -> _SlideBuilder:
        sb = _SlideBuilder(len(self._slides) + 1)
        self._slides.append(sb)
        return sb

    def add_media(self, name: str, data: bytes):
        self._media[name] = data

    @staticmethod
    def _content_types_xml(n_slides: int) -> bytes:
        root = ET.Element(
            "Types",
            {"xmlns": "http://schemas.openxmlformats.org/package/2006/content-types"}
        )
        # Defaults
        for ext, ct in [
            ("rels",  "application/vnd.openxmlformats-package.relationships+xml"),
            ("xml",   "application/xml"),
            ("svg",   "image/svg+xml"),
            ("png",   "image/png"),
        ]:
            ET.SubElement(root, "Default", {"Extension": ext, "ContentType": ct})
        # Parts
        parts = [
            ("/ppt/presentation.xml",
             "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"),
            ("/ppt/slideLayouts/slideLayout1.xml",
             "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"),
            ("/ppt/slideMasters/slideMaster1.xml",
             "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"),
            ("/ppt/theme/theme1.xml",
             "application/vnd.openxmlformats-officedocument.theme+xml"),
            ("/docProps/core.xml",
             "application/vnd.openxmlformats-package.core-properties+xml"),
            ("/docProps/app.xml",
             "application/vnd.openxmlformats-officedocument.extended-properties+xml"),
        ]
        for i in range(1, n_slides + 1):
            parts.append((
                f"/ppt/slides/slide{i}.xml",
                "application/vnd.openxmlformats-officedocument.presentationml.slide+xml",
            ))
        for part, ct in parts:
            ET.SubElement(root, "Override", {"PartName": part, "ContentType": ct})
        return ET.tostring(root, encoding="UTF-8", xml_declaration=True)

    @staticmethod
    def _root_rels_xml() -> bytes:
        root = ET.Element(
            "Relationships",
            {"xmlns": "http://schemas.openxmlformats.org/package/2006/relationships"}
        )
        for rid, rtype, target in [
            ("rId1",
             "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
             "ppt/presentation.xml"),
            ("rId2",
             "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties",
             "docProps/core.xml"),
            ("rId3",
             "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties",
             "docProps/app.xml"),
        ]:
            ET.SubElement(root, "Relationship",
                          {"Id": rid, "Type": rtype, "Target": target})
        return ET.tostring(root, encoding="UTF-8", xml_declaration=True)

    @staticmethod
    def _presentation_xml(n_slides: int) -> bytes:
        sldIdLst = _x("p:sldIdLst", children=[
            _x("p:sldId", {"id": str(256 + i),
                            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id": f"rId{i+1}"})
            for i in range(n_slides)
        ])
        prs = _x("p:presentation", {
            "xmlns:a": _NSMAP["a"],
            "xmlns:p": _NSMAP["p"],
            "xmlns:r": _NSMAP["r"],
            "saveSubsetFonts": "1",
        }, children=[
            _x("p:sldMasterIdLst", children=[
                _x("p:sldMasterId", {
                    "id": "2147483648",
                    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id": "rId100",
                })
            ]),
            sldIdLst,
            _x("p:sldSz", {"cx": str(_W), "cy": str(_H), "type": "screen4x3"}),
            _x("p:notesSz", {"cx": "6858000", "cy": "9144000"}),
        ])
        return ET.tostring(prs, encoding="UTF-8", xml_declaration=True)

    @staticmethod
    def _presentation_rels_xml(n_slides: int) -> bytes:
        root = ET.Element(
            "Relationships",
            {"xmlns": "http://schemas.openxmlformats.org/package/2006/relationships"}
        )
        for i in range(n_slides):
            ET.SubElement(root, "Relationship", {
                "Id": f"rId{i+1}",
                "Type": ("http://schemas.openxmlformats.org/officeDocument/2006/"
                         "relationships/slide"),
                "Target": f"slides/slide{i+1}.xml",
            })
        ET.SubElement(root, "Relationship", {
            "Id": "rId100",
            "Type": ("http://schemas.openxmlformats.org/officeDocument/2006/"
                     "relationships/slideMaster"),
            "Target": "slideMasters/slideMaster1.xml",
        })
        ET.SubElement(root, "Relationship", {
            "Id": "rId101",
            "Type": ("http://schemas.openxmlformats.org/officeDocument/2006/"
                     "relationships/theme"),
            "Target": "theme/theme1.xml",
        })
        return ET.tostring(root, encoding="UTF-8", xml_declaration=True)

    @staticmethod
    def _theme_xml() -> bytes:
        """Minimal theme XML."""
        return b"""<?xml version='1.0' encoding='UTF-8'?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="IOTheme">
  <a:themeElements>
    <a:clrScheme name="IO"><a:dk1><a:srgbClr val="2C3E50"/></a:dk1>
      <a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>
      <a:dk2><a:srgbClr val="2980B9"/></a:dk2>
      <a:lt2><a:srgbClr val="ECF0F1"/></a:lt2>
      <a:accent1><a:srgbClr val="3498DB"/></a:accent1>
      <a:accent2><a:srgbClr val="E74C3C"/></a:accent2>
      <a:accent3><a:srgbClr val="2ECC71"/></a:accent3>
      <a:accent4><a:srgbClr val="E67E22"/></a:accent4>
      <a:accent5><a:srgbClr val="9B59B6"/></a:accent5>
      <a:accent6><a:srgbClr val="1ABC9C"/></a:accent6>
      <a:hlink><a:srgbClr val="2980B9"/></a:hlink>
      <a:folHlink><a:srgbClr val="8E44AD"/></a:folHlink>
    </a:clrScheme>
    <a:fontScheme name="IO">
      <a:majorFont><a:latin typeface="Arial"/></a:majorFont>
      <a:minorFont><a:latin typeface="Arial"/></a:minorFont>
    </a:fontScheme>
    <a:fmtScheme name="IO">
      <a:fillStyleLst>
        <a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>
        <a:solidFill><a:srgbClr val="ECF0F1"/></a:solidFill>
        <a:solidFill><a:srgbClr val="2C3E50"/></a:solidFill>
      </a:fillStyleLst>
      <a:lnStyleLst>
        <a:ln w="6350"><a:solidFill><a:srgbClr val="95A5A6"/></a:solidFill></a:ln>
        <a:ln w="12700"><a:solidFill><a:srgbClr val="2C3E50"/></a:solidFill></a:ln>
        <a:ln w="19050"><a:solidFill><a:srgbClr val="2C3E50"/></a:solidFill></a:ln>
      </a:lnStyleLst>
      <a:effectStyleLst>
        <a:effectStyle><a:effectLst/></a:effectStyle>
        <a:effectStyle><a:effectLst/></a:effectStyle>
        <a:effectStyle><a:effectLst/></a:effectStyle>
      </a:effectStyleLst>
      <a:bgFillStyleLst>
        <a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>
        <a:solidFill><a:srgbClr val="ECF0F1"/></a:solidFill>
        <a:solidFill><a:srgbClr val="2C3E50"/></a:solidFill>
      </a:bgFillStyleLst>
    </a:fmtScheme>
  </a:themeElements>
</a:theme>"""

    @staticmethod
    def _slide_master_xml() -> bytes:
        return b"""<?xml version='1.0' encoding='UTF-8'?>
<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
             xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:cSld><p:spTree>
    <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
    <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>
      <a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
  </p:spTree></p:cSld>
  <p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1"
    accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5"
    accent6="accent6" hlink="hlink" folHlink="folHlink"/>
  <p:sldLayoutIdLst>
    <p:sldLayoutId id="2147483649"
      r:id="rId1"/>
  </p:sldLayoutIdLst>
</p:sldMaster>"""

    @staticmethod
    def _slide_master_rels_xml() -> bytes:
        return b"""<?xml version='1.0' encoding='UTF-8'?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout"
    Target="../slideLayouts/slideLayout1.xml"/>
  <Relationship Id="rId2"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme"
    Target="../theme/theme1.xml"/>
</Relationships>"""

    @staticmethod
    def _slide_layout_xml() -> bytes:
        return b"""<?xml version='1.0' encoding='UTF-8'?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
             xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
             type="blank" preserve="1">
  <p:cSld name="Blank"><p:spTree>
    <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
    <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>
      <a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
  </p:spTree></p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>"""

    @staticmethod
    def _slide_layout_rels_xml() -> bytes:
        return b"""<?xml version='1.0' encoding='UTF-8'?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster"
    Target="../slideMasters/slideMaster1.xml"/>
</Relationships>"""

    @staticmethod
    def _core_xml(title: str, author: str) -> bytes:
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        return f"""<?xml version='1.0' encoding='UTF-8'?>
<cp:coreProperties
  xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
  xmlns:dc="http://purl.org/dc/elements/1.1/"
  xmlns:dcterms="http://purl.org/dc/terms/"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>{title}</dc:title>
  <dc:creator>{author}</dc:creator>
  <cp:lastModifiedBy>{author}</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>
</cp:coreProperties>""".encode("utf-8")

    @staticmethod
    def _app_xml() -> bytes:
        return b"""<?xml version='1.0' encoding='UTF-8'?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
  <Application>IO Testing Results Analysis</Application>
</Properties>"""

    def save(self, path: Path, title="IO Report", author="IO Analysis Tool"):
        n = len(self._slides)
        with zipfile.ZipFile(str(path), "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml",     self._content_types_xml(n))
            zf.writestr("_rels/.rels",              self._root_rels_xml())
            zf.writestr("ppt/presentation.xml",     self._presentation_xml(n))
            zf.writestr("ppt/_rels/presentation.xml.rels",
                        self._presentation_rels_xml(n))
            zf.writestr("ppt/theme/theme1.xml",     self._theme_xml())
            zf.writestr("ppt/slideMasters/slideMaster1.xml",
                        self._slide_master_xml())
            zf.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels",
                        self._slide_master_rels_xml())
            zf.writestr("ppt/slideLayouts/slideLayout1.xml",
                        self._slide_layout_xml())
            zf.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels",
                        self._slide_layout_rels_xml())
            zf.writestr("docProps/core.xml",  self._core_xml(title, author))
            zf.writestr("docProps/app.xml",   self._app_xml())

            for i, sb in enumerate(self._slides, 1):
                zf.writestr(f"ppt/slides/slide{i}.xml",       sb.build_xml())
                zf.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", sb.build_rels_xml())

            for name, data in self._media.items():
                zf.writestr(f"ppt/media/{name}", data)


# ---------------------------------------------------------------------------
# High-level slide generators
# ---------------------------------------------------------------------------

def _slide_title(pptx: _PptxBuilder, title: str, subtitle: str,
                 date_str: str, author: str):
    """Slide 1 — Title."""
    sb = pptx.new_slide()

    # Dark banner fills entire slide
    sb.add_shape(_rect_sp(
        10, "Bg", 0, 0, _W, _H,
        fill_color=_C_DARK, line_color=None,
    ))
    # Accent bar left
    sb.add_shape(_rect_sp(
        11, "Bar", 0, 0, 180000, _H,
        fill_color=_C_ACCENT, line_color=None,
    ))
    # Title text
    sb.add_text_box(
        220000, _H // 2 - 700000, _W - 440000, 550000,
        [_para(title, 32, bold=True, color=_C_WHITE, align="l")],
        fill=_C_DARK, line=None,
    )
    # Subtitle
    sb.add_text_box(
        220000, _H // 2 - 120000, _W - 440000, 350000,
        [_para(subtitle, 16, color=_C_GRAY, align="l")],
        fill=_C_DARK, line=None,
    )
    # Date / author
    sb.add_text_box(
        220000, _H - 600000, _W - 440000, 300000,
        [_para(f"{date_str}   |   {author}", 10, color=_C_GRAY, align="l")],
        fill=_C_DARK, line=None,
    )


def _slide_summary(pptx: _PptxBuilder, result: AnalysisResult,
                   selected_tests: set):
    """Slide 2 — Executive summary cards + top-10 failing params."""
    sb = pptx.new_slide()
    sb.add_title("Executive Summary",
                 f"Tests: {', '.join(sorted(selected_tests))}")

    summary = result.overall_summary
    pass_rate = summary.get("overall_pass_rate", 0)
    n_duts = max(
        (len(fd.dut_ids) for fd in result.flow_data.values()),
        default=0,
    )

    # Cards
    card_data = [
        ("Pass Rate",    f"{pass_rate:.1f}%",
         _C_PASS if pass_rate >= 99 else (_C_WARN if pass_rate >= 95 else _C_FAIL)),
        ("Measurements", str(summary.get("total_measurements", 0)), _C_ACCENT),
        ("Pass",         str(summary.get("total_pass", 0)), _C_PASS),
        ("Fail",         str(summary.get("total_fail", 0)),
         _C_FAIL if summary.get("total_fail", 0) > 0 else _C_GRAY),
        ("Parameters",   str(summary.get("total_parameters", 0)), _C_ACCENT),
        ("DUTs",         str(n_duts), _C_ACCENT),
    ]
    card_w = 1350000
    card_h = 700000
    total_card_w = len(card_data) * (card_w + 60000) - 60000
    cx = (_W - total_card_w) // 2
    cy = _TH + _M + 300000
    for lbl, val, fill in card_data:
        sb.add_card(cx, cy, card_w, card_h, lbl, val, fill)
        cx += card_w + 60000

    # Failing params table
    fails = [
        (f"{flow}/{param}", f"{s.pass_rate:.1f}%",
         f"{s.minimum:.3g}", f"{s.maximum:.3g}", s.unit, s.status)
        for (flow, param), s in sorted(result.parameter_stats.items())
        if s.fail_count > 0
    ]
    ty = cy + card_h + _M
    th = _H - ty - _M
    if fails:
        sb.add_shape(_rect_sp(
            sb._new_id(), "FailHdr",
            _M, ty - 350000, _W - 2 * _M, 320000,
            fill_color=_C_DARK, line_color=None,
            text_paras=[_para("Parameters with Failures", 13, bold=True,
                              color=_C_WHITE)],
        ))
        cw_total = _W - 2 * _M
        cws = [int(cw_total * r) for r in [0.38, 0.12, 0.12, 0.12, 0.10, 0.16]]
        cws[-1] = cw_total - sum(cws[:-1])
        sb.add_table(
            _M, ty, cw_total, th,
            ["Parameter", "Pass%", "Min", "Max", "Unit", "Status"],
            fails[:12],
            col_widths=cws,
        )
    else:
        sb.add_text_box(
            _M, ty, _W - 2 * _M, th,
            [_para("✓  All parameters passed across all flows and conditions.",
                   16, bold=True, color=_C_PASS, align="ctr")],
            fill="EBF7EF", line=_C_PASS,
        )


def _slide_section(pptx: _PptxBuilder, result: AnalysisResult,
                   test_name: str, section_plots: dict,
                   plots_dir: Path):
    """One slide per test section — stats table + up to 2 charts."""
    from io_analysis.plotting.plotter import REPORT_IOS, SECTION_MEASUREMENTS

    sb = pptx.new_slide()
    clean = test_name.replace("/", " / ")
    sb.add_title(clean)

    # Collect stats rows for REPORT_IOS
    meas_list = SECTION_MEASUREMENTS.get(test_name, [])
    stat_rows = []
    for meas in meas_list:
        for io in REPORT_IOS:
            param = f"{io}_{meas}"
            for flow, s in [
                (fl, result.parameter_stats[(fl, param)])
                for fl in result.all_flows
                if (fl, param) in result.parameter_stats
            ]:
                stat_rows.append([
                    io, meas, s.unit,
                    f"{s.mean:.3g}", f"{s.std:.3g}",
                    f"{s.minimum:.3g}", f"{s.maximum:.3g}",
                    f"{s.pass_rate:.1f}%", s.status,
                ])

    # Collect chart SVG paths for this section
    sec_charts = section_plots.get(test_name, {})
    chart_paths = [p for p in sec_charts.values() if p and p.exists()]

    # Layout: table top, charts bottom (or side by side)
    content_y = _TH + _M + 100000
    content_h  = _H - content_y - _M

    if chart_paths:
        tbl_h = int(content_h * 0.40)
        chart_y = content_y + tbl_h + 80000
        chart_h = _H - chart_y - _M
    else:
        tbl_h = content_h

    if stat_rows:
        cw_total = _W - 2 * _M
        cws = [int(cw_total * r) for r in [0.13, 0.18, 0.07, 0.10, 0.09,
                                            0.10, 0.10, 0.11, 0.12]]
        cws[-1] = cw_total - sum(cws[:-1])
        sb.add_table(
            _M, content_y, cw_total, tbl_h,
            ["IO", "Measurement", "Unit", "Mean", "Std Dev",
             "Min", "Max", "Pass%", "Status"],
            stat_rows,
            col_widths=cws,
        )
    else:
        sb.add_text_box(
            _M, content_y, _W - 2 * _M, tbl_h,
            [_para("No data available for this test section.",
                   12, color=_C_GRAY, align="ctr", italic=True)],
            fill="F8F9FA", line=_C_LIGHT,
        )

    # Embed charts
    if chart_paths:
        n_charts = min(len(chart_paths), 2)
        gap = 80000
        chart_w = (_W - 2 * _M - (n_charts - 1) * gap) // n_charts
        cx = _M
        for svg_path in chart_paths[:n_charts]:
            pptx.add_media(svg_path.name, svg_path.read_bytes())
            sb.add_svg(svg_path, cx, chart_y, chart_w, chart_h)
            cx += chart_w + gap


def _slide_param_overview(pptx: _PptxBuilder, result: AnalysisResult,
                           selected_tests: set):
    """Slide — full parameter pass/fail overview table."""
    from io_analysis.plotting.plotter import REPORT_IOS, TEST_SECTION_ORDER

    param_test_map = {}
    for fd in result.flow_data.values():
        for row in fd.rows:
            p, t = row.get("Parameter"), row.get("Test_Name")
            if p and t and p not in param_test_map:
                param_test_map[p] = t

    sb = pptx.new_slide()
    sb.add_title("Parameter Overview — All Results")

    rows = []
    for test_name in TEST_SECTION_ORDER:
        if test_name not in selected_tests:
            continue
        for io in REPORT_IOS:
            for (flow, param), s in sorted(result.parameter_stats.items()):
                if not param.startswith(io + "_"):
                    continue
                if param_test_map.get(param) != test_name:
                    continue
                meas = param[len(io) + 1:]
                rows.append([
                    test_name[:18], io, meas, flow,
                    f"{s.pass_rate:.1f}%",
                    f"{s.cpk:.2f}" if s.cpk else "—",
                    s.status,
                ])

    if not rows:
        return

    cw_total = _W - 2 * _M
    cws = [int(cw_total * r) for r in [0.19, 0.13, 0.16, 0.12, 0.11, 0.10, 0.19]]
    cws[-1] = cw_total - sum(cws[:-1])
    content_y = _TH + _M + 100000
    content_h  = _H - content_y - _M

    sb.add_table(
        _M, content_y, cw_total, content_h,
        ["Test Section", "IO", "Measurement", "Flow",
         "Pass%", "Cpk", "Status"],
        rows[:25],
        col_widths=cws,
    )
    if len(rows) > 25:
        sb.add_text_box(
            _M, _H - _M - 200000, _W - 2 * _M, 200000,
            [_para(f"(showing 25 of {len(rows)} parameters — see HTML report for full list)",
                   8, color=_C_GRAY, italic=True)],
            fill=_C_WHITE, line=None,
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_pptx_report(result: AnalysisResult, plot_paths: dict,
                          config: Config,
                          selected_tests: Optional[set] = None) -> Path:
    """
    Generate a PowerPoint report and save it next to the HTML report.
    Returns the path to the saved .pptx file.
    """
    from io_analysis.plotting.plotter import TEST_SECTION_ORDER

    active_tests = (selected_tests if selected_tests is not None
                    else set(TEST_SECTION_ORDER))
    plots_dir = config.output_path / "plots"
    section_plots = plot_paths.get("section_plots", {})

    title  = config.report.title
    author = getattr(config.report, "author", "IO Analysis Tool")
    date_s = datetime.now().strftime("%Y-%m-%d %H:%M")

    pptx = _PptxBuilder()

    _slide_title(pptx, title,
                 f"Intel IO Electrical Validation  |  {date_s}",
                 date_s, author)
    _slide_summary(pptx, result, active_tests)
    _slide_param_overview(pptx, result, active_tests)

    for test_name in TEST_SECTION_ORDER:
        if test_name not in active_tests:
            continue
        _slide_section(pptx, result, test_name, section_plots, plots_dir)

    out_path = config.output_path / "IO_Validation_Report.pptx"
    pptx.save(out_path, title=title, author=author)
    logger.info(f"PPTX report saved: {out_path}")
    return out_path
