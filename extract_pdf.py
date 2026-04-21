"""Extract JPEG/PNG images embedded in PDF and save them."""
import sys, re, zlib, os

def try_decompress(data):
    for wbits in (15, -15, 47):
        try:
            return zlib.decompress(data, wbits)
        except Exception:
            pass
    return None

def extract_images(path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    with open(path, "rb") as f:
        raw = f.read()

    # Also try to decode CID/hex text from content streams
    streams = list(re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.DOTALL))
    print(f"Total streams: {len(streams)}")

    img_count = 0
    txt_count = 0

    for i, m in enumerate(streams):
        data = m.group(1)
        pre = raw[max(0,m.start()-800):m.start()]

        # JPEG images
        if b"DCTDecode" in pre or data[:2] == b'\xff\xd8':
            fn = os.path.join(out_dir, f"image_{i+1}.jpg")
            with open(fn, "wb") as f2:
                f2.write(data)
            print(f"Saved JPEG: {fn} ({len(data):,} bytes)")
            img_count += 1
            continue

        # JBIG2 / CCITT images
        if b"JBIG2Decode" in pre or b"CCITTFaxDecode" in pre:
            fn = os.path.join(out_dir, f"image_{i+1}.bin")
            with open(fn, "wb") as f2:
                f2.write(data)
            print(f"Saved binary image: {fn}")
            img_count += 1
            continue

        # Deflate streams — try text extraction
        if b"FlateDecode" in pre:
            dec = try_decompress(data)
            if dec is None:
                continue
            # CID hex text: <XXXX> Tj or [(..)] TJ
            texts = []
            for hm in re.finditer(rb'<([0-9A-Fa-f]+)>\s*T[jJ]', dec):
                hex_str = hm.group(1)
                # decode as UTF-16BE pairs
                try:
                    chars = bytes.fromhex(hex_str.decode()).decode('utf-16-be', errors='replace')
                    texts.append(chars)
                except Exception:
                    texts.append(hex_str.decode(errors='replace'))
            # Also standard (text) Tj
            for tm in re.finditer(rb'\(([^)]{1,300})\)\s*T[jJ]', dec):
                try:
                    texts.append(tm.group(1).decode('latin-1'))
                except Exception:
                    pass
            # Array TJ
            for tm in re.finditer(rb'\[([^\]]{1,600})\]\s*TJ', dec):
                inner = tm.group(1)
                for sm in re.finditer(rb'<([0-9A-Fa-f]+)>', inner):
                    try:
                        chars = bytes.fromhex(sm.group(1).decode()).decode('utf-16-be', errors='replace')
                        texts.append(chars)
                    except Exception:
                        pass
                for sm in re.finditer(rb'\(([^)]{1,200})\)', inner):
                    try:
                        texts.append(sm.group(1).decode('latin-1'))
                    except Exception:
                        pass
            if texts:
                txt_count += 1
                joined = " ".join(t for t in texts if t.strip())
                print(f"\n=== Stream {i+1} TEXT ===")
                print(joined)
            else:
                # dump raw decoded for inspection
                printable = re.findall(rb'[ -~]{3,}', dec)
                if printable:
                    print(f"\n=== Stream {i+1} PRINTABLE ===")
                    for p in printable:
                        s = p.decode('latin-1').strip()
                        if s:
                            print(s)

    print(f"\nDone. Images: {img_count}, Text streams: {txt_count}")

if __name__ == "__main__":
    pdf = sys.argv[1] if len(sys.argv) > 1 else "IO_SPEC.pdf"
    out = sys.argv[2] if len(sys.argv) > 2 else "spec_pages"
    extract_images(pdf, out)
