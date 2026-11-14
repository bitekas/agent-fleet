#!/usr/bin/env python3
"""Tests for luma.py. Pure: generates its own PNGs, so it never depends on a
screenshot that happens to be lying around, and it proves its own teeth: the
one property this instrument exists for - a calibration region that must read
black - is driven RED against a deliberately mis-sized image before it is
trusted."""
import os
import struct
import subprocess
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.realpath(__file__))
LUMA = os.path.join(HERE, "luma.py")
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True  # importing luma writes nothing into the skill tree
import luma  # noqa: E402


def png(w, h, paint, ctype=6, filt=0):
    """Write a PNG whose pixel (x, y) is paint(x, y) -> (r, g, b). Uses one
    filter type for every row so each filter path in the decoder gets a run."""
    bpp = 4 if ctype == 6 else 3
    rows = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            r, g, b = paint(x, y)
            row += bytes((r, g, b, 255)) if ctype == 6 else bytes((r, g, b))
        rows.append(row)
    raw = b""
    prev = bytearray(w * bpp)
    for row in rows:
        enc = bytearray(row)
        if filt == 1:
            for i in range(len(row) - 1, -1, -1):
                enc[i] = (row[i] - (row[i - bpp] if i >= bpp else 0)) & 255
        elif filt == 2:
            for i in range(len(row)):
                enc[i] = (row[i] - prev[i]) & 255
        raw += bytes([filt]) + bytes(enc)
        prev = row
    def chunk(t, b): return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def screen(x, y, w=200, h=400):
    """A synthetic simulator screenshot: light-grey feed in the middle band,
    black chrome at the bottom, white elsewhere."""
    if 0.90 * h <= y < 0.97 * h: return (18, 18, 18)
    if 0.22 * h <= y < 0.55 * h: return (186, 186, 186)
    return (255, 255, 255)


passed = failed = 0
def ok(name): global passed; passed += 1; print(f"  ok   {name}")
def bad(name, why=""): global failed; failed += 1; print(f"  FAIL {name}  {why}")


tmp = tempfile.mkdtemp()
try:
    # 1. every filter type and both colour types decode to the same pixels
    for ctype in (2, 6):
        for filt in (0, 1, 2):
            p = os.path.join(tmp, f"s{ctype}{filt}.png")
            open(p, "wb").write(png(200, 400, screen, ctype, filt))
            img = luma.decode(p)
            f, c = luma.region_luma(img, .1, .9, .22, .55), luma.region_luma(img, .3, .5, .90, .97)
            if abs(f - 186) < 1 and abs(c - 18) < 1: ok(f"decode ctype={ctype} filter={filt}: feed 186, cal 18")
            else: bad(f"decode ctype={ctype} filter={filt}", f"feed={f:.1f} cal={c:.1f}")

    # 2. the CLI prints both numbers and exits 0
    p = os.path.join(tmp, "s60.png")
    r = subprocess.run([sys.executable, LUMA, p], capture_output=True, text=True)
    if r.returncode == 0 and "feed=186.0" in r.stdout and "cal(known-black)=18.0" in r.stdout: ok("cli: both regions printed, exit 0")
    else: bad("cli output", r.stdout + r.stderr)

    # 3. an unsupported PNG is NO VERDICT (exit 2), never a number. Full size, so
    #    both default regions hold pixels: on a tiny image the calibration region
    #    is empty and the refusal would come from "empty region", which proves
    #    nothing about the interlace guard. The reason must name the interlace.
    bad_png = png(200, 400, screen)
    bad_png = bad_png.replace(struct.pack(">IIBBBBB", 200, 400, 8, 6, 0, 0, 0), struct.pack(">IIBBBBB", 200, 400, 8, 6, 0, 0, 1), 1)
    p = os.path.join(tmp, "interlaced.png"); open(p, "wb").write(bad_png)
    r = subprocess.run([sys.executable, LUMA, p], capture_output=True, text=True)
    if r.returncode == 2 and "NO VERDICT" in r.stdout and "interlace=1" in r.stdout: ok("interlaced png -> NO VERDICT naming the interlace, exit 2")
    else: bad("interlaced png should be NO VERDICT naming the interlace", f"rc={r.returncode} {r.stdout}")
    r = subprocess.run([sys.executable, LUMA, os.path.join(tmp, "missing.png")], capture_output=True, text=True)
    if r.returncode == 2: ok("missing file -> exit 2")
    else: bad("missing file should exit 2", str(r.returncode))

    # 4. a malformed region is refused
    r = subprocess.run([sys.executable, LUMA, "--feed", "0.9,0.1,0,1", os.path.join(tmp, "s60.png")], capture_output=True, text=True)
    if r.returncode == 2: ok("inverted region -> exit 2")
    else: bad("inverted region should be refused", str(r.returncode))

    # 5. TEETH: the calibration region catches a misread. A screenshot whose
    #    geometry does not match the regions (chrome not where expected) must
    #    NOT read black in the cal region - the property the instrument exists for.
    p = os.path.join(tmp, "shifted.png")
    open(p, "wb").write(png(200, 400, lambda x, y: screen(x, (y + 100) % 400)))
    c = luma.region_luma(luma.decode(p), .3, .5, .90, .97)
    if c > 100: ok(f"teeth: mis-aligned screenshot reads cal={c:.0f}, not black - the reader would be caught")
    else: bad("teeth: a mis-aligned screenshot passed calibration", f"cal={c:.1f}")
finally:
    for f in os.listdir(tmp): os.unlink(os.path.join(tmp, f))
    os.rmdir(tmp)

print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
