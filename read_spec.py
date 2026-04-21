"""Deep-scan a PDF for any readable text content regardless of encoding."""
import sys, re, zlib

def try_decompress(data):
    for wbits in (15, -15, 47):
        try:
            return zlib.decompress(data, wbits)
        except Exception:
            pass
    return data

def decode_bytes(b):
    for enc in ("utf-8", "latin-1", "utf-16-le", "utf-16-be", "cp1252"):
        try:
            return b.decode(enc)
        except Exception:
            pass
    return b.decode("latin-1", errors="replace")

def extract_all_strings(path):
    with open(path, "rb") as f:
        raw = f.read()

    print(f"File size: {len(raw):,} bytes")

    # --- 1. All PDF streams (with decompression) ---
    streams = list(re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.DOTALL))
    print(f"PDF streams found: {len(streams)}")

    all_texts = []
    for i, m in enumerate(streams):
        content = m.group(1)
        pre = raw[max(0, m.start()-600):m.start()]
        if b"FlateDecode" in pre or b"/Fl " in pre:
            content = try_decompress(content)
        chunk = []
        for tm in re.finditer(rb'\(([^)]{1,200})\)\s*T[jJm]', content):
            s = decode_bytes(tm.group(1)).strip()
            if s:
                chunk.append(s)
        for tm in re.finditer(rb'\[([^\]]{1,500})\]\s*TJ', content):
            for sm in re.finditer(rb'\(([^)]{1,200})\)', tm.group(1)):
                s = decode_bytes(sm.group(1)).strip()
                if s:
                    chunk.append(s)
        for bt in re.finditer(rb'BT(.*?)ET', content, re.DOTALL):
            for sm in re.finditer(rb'\(([^)]{1,200})\)', bt.group(1)):
                s = decode_bytes(sm.group(1)).strip()
                if s and s not in chunk:
                    chunk.append(s)
        if chunk:
            print(f"\n--- Stream {i+1} TEXT ---")
            print(" | ".join(chunk))
            all_texts.extend(chunk)

    # --- 2. Raw printable ASCII strings ---
    print("\n--- RAW PRINTABLE STRINGS (>=6 chars, filtered) ---")
    seen = set()
    skip_kw = ("endobj","xref","startxref","Creator","Producer","ModDate",
               "CreationDate","Type","Subtype","Filter","Length","Width",
               "Height","BitsPerComponent","ColorSpace","FunctionType",
               "Domain","Range","Encode","Decode","MediaBox","CropBox",
               "Rotate","Pages","Catalog","Font","ProcSet","XObject",
               "DeviceGray","DeviceRGB","JBIG2Decode","CCITTFaxDecode",
               "DCTDecode","JavaScript","Annot","Action","URI","endstream")
    for m in re.finditer(rb"[ -~\t]{6,}", raw):
        s = m.group(0).decode("ascii", errors="replace").strip()
        if s in seen:
            continue
        seen.add(s)
        if re.search(r'[A-Za-z]{2,}.*\d|\d.*[A-Za-z]|\d+\.\d+', s):
            if not any(k in s for k in skip_kw):
                print(s)

    if not all_texts:
        print("\n[No text layer — PDF is image-based/scanned]")

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "IO_SPEC.pdf"
    extract_all_strings(path)
