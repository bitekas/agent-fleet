#!/usr/bin/env python3
"""Mean luma of two regions of a PNG screenshot: the FEED under test, and a
CALIBRATION region known to be black. No image library.

    python3 luma.py shot.png [--feed x0,x1,y0,y1] [--cal x0,x1,y0,y1] [--step N]

Regions are fractions of width/height. Exit 0 and print both numbers. Exit 2
when the PNG is not one this decoder handles (8-bit RGB/RGBA, non-interlaced,
which is what simctl and screencap write) - never a guessed number.

WHY TWO REGIONS. A reader that decodes wrongly - a lossy format conversion on
the way in is enough - can report a known-black navigation bar at 168, the same
value as a light-grey camera feed. A single feed number cannot reveal a broken
reader; a calibration region that must read near black can. So the calibration
region is not optional output, it is what makes the feed number mean anything.

WHY NO PIL. This runs on CI agents and in agent tool shells where nothing but
python3 is promised. A PNG decoder for the one pixel format screenshots use is
sixty lines; a dependency is a second install step per machine.
"""
import struct
import sys
import zlib


def decode(path):
    d = open(path, "rb").read()
    if d[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat, w, h, bpp = 8, b"", 0, 0, 0
    while pos < len(d):
        ln, = struct.unpack_from(">I", d, pos)
        typ, body = d[pos + 4:pos + 8], d[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or interlace != 0 or ctype not in (2, 6):
                raise ValueError(f"unsupported PNG: depth={depth} colour={ctype} interlace={interlace}")
            bpp = 4 if ctype == 6 else 3
        elif typ == b"IDAT":
            idat += body
    raw, stride = zlib.decompress(idat), w * bpp
    out, prev, p = bytearray(), bytearray(stride), 0
    for _ in range(h):
        f, line = raw[p], bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        if f:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                if f == 1: line[i] = (line[i] + a) & 255
                elif f == 2: line[i] = (line[i] + b) & 255
                elif f == 3: line[i] = (line[i] + (a + b) // 2) & 255
                elif f == 4:
                    pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                    line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out += line
        prev = line
    return w, h, bpp, out


def region_luma(img, x0, x1, y0, y1, step=5):
    w, h, bpp, px = img
    tot = n = 0
    for y in range(int(h * y0), int(h * y1), step):
        for x in range(int(w * x0), int(w * x1), step):
            i = (y * w + x) * bpp
            tot += 0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2]
            n += 1
    if n == 0:
        raise ValueError("empty region")
    return tot / n


def parse_region(s):
    parts = [float(v) for v in s.split(",")]
    if len(parts) != 4 or not all(0 <= v <= 1 for v in parts) or parts[0] >= parts[1] or parts[2] >= parts[3]:
        raise ValueError(f"region must be x0,x1,y0,y1 as fractions with x0<x1, y0<y1: {s!r}")
    return parts


def main(argv):
    feed, cal, step, paths = (0.1, 0.9, 0.22, 0.55), (0.3, 0.5, 0.90, 0.97), 5, []
    # A bad region is a NO VERDICT like any other unusable input, not a
    # traceback: a caller reading exit codes must never see a 1 that means
    # "the instrument crashed" next to a 2 that means "could not measure".
    try:
        it = iter(argv)
        for a in it:
            if a == "--feed": feed = parse_region(next(it))
            elif a == "--cal": cal = parse_region(next(it))
            elif a == "--step": step = int(next(it))
            else: paths.append(a)
    except (ValueError, StopIteration) as e:
        print(f"NO VERDICT: bad arguments: {e}"); return 2
    if not paths:
        print(__doc__.strip().splitlines()[0]); return 2
    for p in paths:
        try:
            img = decode(p)
            f, c = region_luma(img, *feed, step=step), region_luma(img, *cal, step=step)
        except (ValueError, OSError, zlib.error, struct.error) as e:
            print(f"{p}: NO VERDICT: {e}"); return 2
        print(f"{p}: feed={f:.1f} cal(known-black)={c:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
