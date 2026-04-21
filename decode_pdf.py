"""
Properly decode CID-font PDF text using ToUnicode CMaps.
Works fully with stdlib - no external packages needed.
"""
import sys, re, zlib

def decompress(data):
    for wbits in (15, -15, 47):
        try:
            return zlib.decompress(data, wbits)
        except Exception:
            pass
    return data

def parse_cmap(cmap_bytes):
    """Parse a ToUnicode CMap stream, return dict {hex_code -> unicode_char}."""
    mapping = {}
    text = cmap_bytes.decode("latin-1", errors="replace")
    # beginbfchar ... endbfchar  (single code mappings)
    for block in re.finditer(r"beginbfchar(.*?)endbfchar", text, re.DOTALL):
        for m in re.finditer(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block.group(1)):
            src = m.group(1).upper()
            dst_bytes = bytes.fromhex(m.group(2))
            try:
                dst = dst_bytes.decode("utf-16-be")
            except Exception:
                dst = dst_bytes.decode("latin-1", errors="replace")
            mapping[src] = dst
    # beginbfrange ... endbfrange  (range mappings)
    for block in re.finditer(r"beginbfrange(.*?)endbfrange", text, re.DOTALL):
        for m in re.finditer(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block.group(1)):
            start = int(m.group(1), 16)
            end   = int(m.group(2), 16)
            base  = int(m.group(3), 16)
            width = len(m.group(1))
            for i in range(end - start + 1):
                src = f"{start+i:0{width}X}"
                try:
                    dst = chr(base + i)
                except Exception:
                    dst = "?"
                mapping[src] = dst
    return mapping

def decode_hex_string(hex_str, cmaps):
    """Decode a hex string <XXYY...> using available CID CMaps, 2 bytes at a time."""
    result = []
    hex_str = hex_str.upper().replace(" ", "")
    i = 0
    while i < len(hex_str):
        # try 4-char (2-byte) code first, then 2-char (1-byte)
        for width in (4, 2):
            chunk = hex_str[i:i+width]
            if len(chunk) < width:
                break
            for cmap in cmaps:
                if chunk in cmap:
                    result.append(cmap[chunk])
                    i += width
                    break
            else:
                continue
            break
        else:
            result.append("?")
            i += 2
    return "".join(result)

def extract_content(raw, stream_idx, cmaps_by_font):
    """Extract all text from a content stream using font CMaps."""
    streams = list(re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.DOTALL))
    if stream_idx >= len(streams):
        return ""
    data = streams[stream_idx].group(1)
    pre = raw[max(0, streams[stream_idx].start()-800):streams[stream_idx].start()]
    if b"FlateDecode" in pre:
        data = decompress(data)

    text = data.decode("latin-1", errors="replace")
    lines = []
    current_font = None
    y_pos = 0.0
    x_pos = 0.0

    # Track font changes: /F1 12 Tf
    # Track position: x y Td / x y TD / matrix Tm
    # Text: <hex> Tj  or [<hex> ...] TJ  or (str) Tj

    for line in text.split('\n'):
        line = line.strip()
        # Font selection
        mf = re.match(r"/(\w+)\s+[\d.]+\s+Tf", line)
        if mf:
            current_font = mf.group(1)
            continue
        # Position
        mp = re.match(r"([-\d.]+)\s+([-\d.]+)\s+T[dD]", line)
        if mp:
            x_pos = float(mp.group(1))
            y_pos = float(mp.group(2))

    # Now extract text with font context
    current_font = None
    # Parse token by token
    tokens = re.split(r'(\s+)', text)
    full = text

    results = []  # (y_approx, x_approx, text)
    # Use regex to find BT...ET blocks
    for bt_block in re.finditer(r'BT(.*?)ET', full, re.DOTALL):
        block = bt_block.group(1)
        cur_font = None
        cur_x = 0.0
        cur_y = 0.0

        # Font
        for mf in re.finditer(r'/(F\d+)\s+[\d.]+\s+Tf', block):
            cur_font = mf.group(1)

        # Collect all text ops in order with positions
        ops = []
        # Td/TD
        for m in re.finditer(r'([-\d.]+)\s+([-\d.]+)\s+T[dD]', block):
            cur_x += float(m.group(1))
            cur_y += float(m.group(2))
        # Tm (absolute)
        for m in re.finditer(r'([-\d.]+\s+){4}([-\d.]+)\s+([-\d.]+)\s+Tm', block):
            pass  # approximate

        # Hex strings: <...> Tj
        for m in re.finditer(r'<([0-9A-Fa-f\s]+)>\s*Tj', block):
            hex_s = m.group(1).replace(" ","")
            cmaps = list(cmaps_by_font.get(cur_font, {None: {}}).values()) if cur_font else []
            if not cmaps and cmaps_by_font:
                cmaps = [list(v.values())[0] for v in cmaps_by_font.values() if v]
            decoded = decode_hex_string(hex_s, cmaps) if cmaps else hex_s
            ops.append(decoded)

        # Array TJ: [<hex> num <hex> ...] TJ
        for m in re.finditer(r'\[([^\]]+)\]\s*TJ', block):
            inner = m.group(1)
            parts = []
            for hm in re.finditer(r'<([0-9A-Fa-f\s]+)>', inner):
                hex_s = hm.group(1).replace(" ","")
                cmaps = list(cmaps_by_font.get(cur_font, {None: {}}).values()) if cur_font else []
                if not cmaps and cmaps_by_font:
                    cmaps = [list(v.values())[0] for v in cmaps_by_font.values() if v]
                decoded = decode_hex_string(hex_s, cmaps) if cmaps else hex_s
                parts.append(decoded)
            if parts:
                ops.append("".join(parts))

        # Literal strings: (text) Tj
        for m in re.finditer(r'\(([^)]*)\)\s*Tj', block):
            ops.append(m.group(1))

        if ops:
            results.append((cur_y, cur_x, " ".join(ops)))

    # Sort by y descending (top of page first), then x
    results.sort(key=lambda r: -r[0])
    return "\n".join(t for _, _, t in results if t.strip())


def main(pdf_path):
    with open(pdf_path, "rb") as f:
        raw = f.read()

    streams = list(re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.DOTALL))
    print(f"File: {pdf_path}  |  Size: {len(raw):,} bytes  |  Streams: {len(streams)}")

    # --- Step 1: Find all ToUnicode streams and font names ---
    # Object refs: /ToUnicode X 0 R  near font dicts
    obj_offsets = {}
    for m in re.finditer(rb"(\d+)\s+0\s+obj", raw):
        obj_offsets[int(m.group(1))] = m.start()

    # Find font objects and their ToUnicode refs
    font_to_cmap = {}  # font_name -> cmap_dict
    # Find all font resource dicts:  /F1 11 0 R  /F2 19 0 R etc.
    for page_res in re.finditer(rb"/(F\d+)\s+(\d+)\s+0\s+R", raw):
        fname = page_res.group(1).decode()
        fobj  = int(page_res.group(2))
        # Find ToUnicode ref in this font object
        fobj_offset = obj_offsets.get(fobj, -1)
        if fobj_offset < 0:
            continue
        fobj_text = raw[fobj_offset:fobj_offset+2000]
        tu = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", fobj_text)
        if not tu:
            continue
        tu_obj = int(tu.group(1))
        tu_offset = obj_offsets.get(tu_obj, -1)
        if tu_offset < 0:
            continue
        # Get the stream for this ToUnicode object
        seg = raw[tu_offset:tu_offset+50000]
        sm = re.search(rb"stream\r?\n(.*?)\r?\nendstream", seg, re.DOTALL)
        if not sm:
            continue
        cmap_data = sm.group(1)
        pre = raw[max(0, tu_offset):tu_offset+500]
        if b"FlateDecode" in pre:
            cmap_data = decompress(cmap_data)
        cmap = parse_cmap(cmap_data)
        if fname not in font_to_cmap:
            font_to_cmap[fname] = {}
        font_to_cmap[fname][tu_obj] = cmap
        sample = list(cmap.items())[:3]
        print(f"  Font {fname} CMap ({len(cmap)} entries): {sample}")

    if not font_to_cmap:
        print("No ToUnicode CMaps found — trying direct decode of all streams...")

    # --- Step 2: Find page content streams ---
    # Pages: /Contents [ X 0 R ]
    page_num = 0
    for pm in re.finditer(rb"/Contents\s*\[\s*([\d\s0R]+)\]", raw):
        page_num += 1
        ref_nums = re.findall(rb"(\d+)\s+0\s+R", pm.group(1))
        print(f"\n{'='*60}")
        print(f"PAGE {page_num}")
        print('='*60)
        for ref in ref_nums:
            obj_n = int(ref)
            off = obj_offsets.get(obj_n, -1)
            if off < 0:
                continue
            seg = raw[off:off+200000]
            sm = re.search(rb"stream\r?\n(.*?)\r?\nendstream", seg, re.DOTALL)
            if not sm:
                continue
            cdata = sm.group(1)
            pre2 = seg[:500]
            if b"FlateDecode" in pre2:
                cdata = decompress(cdata)

            page_text = cdata.decode("latin-1", errors="replace")
            # Extract BT...ET blocks
            bt_texts = []
            for bt in re.finditer(r'BT(.*?)ET', page_text, re.DOTALL):
                block = bt.group(1)
                cur_font = None
                mf = re.findall(r'/(F\d+)\s+[\d.]+\s+Tf', block)
                if mf:
                    cur_font = mf[-1]
                cmaps = []
                if cur_font and cur_font in font_to_cmap:
                    cmaps = list(font_to_cmap[cur_font].values())
                elif font_to_cmap:
                    # fallback: try all known cmaps
                    cmaps = [c for fc in font_to_cmap.values() for c in fc.values()]

                parts = []
                for op_m in re.finditer(r'(<[0-9A-Fa-f\s]+>|\([^)]*\))\s*T[jJ]|\[([^\]]+)\]\s*TJ', block):
                    full_op = op_m.group(0)
                    # hex Tj
                    hm = re.match(r'<([0-9A-Fa-f\s]+)>\s*Tj', full_op)
                    if hm:
                        parts.append(decode_hex_string(hm.group(1).replace(" ",""), cmaps))
                        continue
                    # literal Tj
                    lm = re.match(r'\(([^)]*)\)\s*Tj', full_op)
                    if lm:
                        parts.append(lm.group(1))
                        continue
                    # TJ array
                    am = re.match(r'\[([^\]]+)\]\s*TJ', full_op)
                    if am:
                        inner = am.group(1)
                        cell = []
                        for hx in re.finditer(r'<([0-9A-Fa-f\s]+)>', inner):
                            cell.append(decode_hex_string(hx.group(1).replace(" ",""), cmaps))
                        for lx in re.finditer(r'\(([^)]*)\)', inner):
                            cell.append(lx.group(1))
                        parts.append("".join(cell))
                if parts:
                    bt_texts.append(" ".join(p for p in parts if p.strip()))

            if bt_texts:
                for t in bt_texts:
                    if t.strip():
                        print(t)
            else:
                # Fallback: raw printables
                for m in re.finditer(rb"[ -~]{4,}", cdata):
                    s = m.group(0).decode("ascii", errors="replace").strip()
                    if s and not re.match(r'^[\s/\\<>()]*$', s):
                        print(s)

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "IO_SPEC.pdf"
    main(path)
