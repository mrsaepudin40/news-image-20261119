#!/usr/bin/env python3
"""The World in One Day -- Thursday 19 November 2026.

A pure-stdlib program that draws one 1024x1024 newspaper front page
summing up the world news of Thursday 19 November 2026: 36 stories
(3 illustrated leads, 8 pictured medium stories, 25 more in brief),
a world map with numbered pins, a four-number stat strip, a DATE CHECK
box and a source footer. No network, no Pillow, deterministic output.

Every headline was re-verified against reports dated 19 November 2026
before it was drawn; three stories that broke on Wednesday 18 November
(EU EUR45bn Ukraine loan, Pew's Muslims-outnumber-Christians projection,
Voyager 1 passing one light-day) are named in the DATE CHECK box as
deliberately left out. Contested claims are attributed in the text.

Layout follows the classic front-page skeleton the day's best entries
share: a big serif masthead with the date and a story/continent count
strip, lead illustrations drawn ABOVE their headlines, a pictured
medium grid, and the map + also-list at the bottom.
"""

import math
import os
import struct
import sys
import zlib

W, H = 1024, 1024

# ---------------------------------------------------------------- palette
CREAM = (246, 239, 220)
PAPER = (251, 247, 234)
NAVY = (16, 41, 78)
NAVY2 = (12, 33, 63)
GOLD = (201, 162, 39)
GOLD2 = (227, 194, 90)
RED = (192, 57, 43)
RED2 = (214, 74, 54)
TEAL = (15, 122, 110)
PURPLE = (107, 79, 161)
ORANGE = (217, 108, 44)
BLUE = (42, 109, 176)
GREEN = (46, 125, 79)
BROWN = (122, 84, 40)
INK = (26, 26, 26)
GREY = (107, 107, 107)
LGREY = (220, 214, 198)
MGREY = (188, 181, 163)
WHITE = (255, 255, 255)
SKY = (174, 205, 226)
SAND = (232, 214, 170)

# ================================================================ TTF font
# A small TrueType reader: cmap (format 12 preferred, format 4 fallback),
# glyf simple + composite outlines, quadratic flattening, 2x supersampled
# scanline rasterisation. Only what a front page needs: Latin-1 text.


def _u16(b, o):
    return struct.unpack_from(">H", b, o)[0]


def _i16(b, o):
    return struct.unpack_from(">h", b, o)[0]


def _u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


class Font:
    def __init__(self, path):
        with open(path, "rb") as f:
            data = f.read()
        self.data = data
        ntab = _u16(data, 4)
        tables = {}
        for i in range(ntab):
            o = 12 + i * 16
            tag = data[o:o + 4].decode("latin-1")
            tables[tag] = (_u32(data, o + 8), _u32(data, o + 12))
        self.tables = tables
        head = tables["head"][0]
        self.upm = _u16(data, head + 18)
        self.loc_fmt = _i16(data, head + 50)
        self.num_glyphs = _u16(data, tables["maxp"][0] + 4)
        hhea = tables["hhea"][0]
        self.ascent = _i16(data, hhea + 4)
        self.descent = _i16(data, hhea + 6)
        self.num_hmetrics = _u16(data, hhea + 34)
        self._cmap = self._read_cmap()
        self._glyph_cache = {}
        self._adv_cache = {}

    def _read_cmap(self):
        data = self.data
        base, _ = self.tables["cmap"]
        n = _u16(data, base + 2)
        best = None
        for i in range(n):
            o = base + 4 + i * 8
            off = _u32(data, o + 4)
            fmt = _u16(data, base + off)
            if fmt == 12:
                return ("12", base + off)
            if fmt == 4 and best is None:
                best = ("4", base + off)
        return best

    def glyph_id(self, ch):
        code = ord(ch)
        kind, off = self._cmap
        data = self.data
        if kind == "12":
            ngroups = _u32(data, off + 12)
            lo, hi = 0, ngroups - 1
            while lo <= hi:
                mid = (lo + hi) // 2
                go = off + 16 + mid * 12
                s = _u32(data, go)
                e = _u32(data, go + 4)
                if code < s:
                    hi = mid - 1
                elif code > e:
                    lo = mid + 1
                else:
                    return _u32(data, go + 8) + (code - s)
            return 0
        seg = _u16(data, off + 6) // 2
        end_base = off + 14
        start_base = end_base + 2 * seg + 2
        delta_base = start_base + 2 * seg
        range_base = delta_base + 2 * seg
        lo, hi = 0, seg - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if code > _u16(data, end_base + 2 * mid):
                lo = mid + 1
            elif code < _u16(data, start_base + 2 * mid):
                hi = mid - 1
            else:
                delta = _i16(data, delta_base + 2 * mid)
                ro = _u16(data, range_base + 2 * mid)
                if ro == 0:
                    return (code + delta) % 65536
                go = range_base + 2 * mid + ro + 2 * (code - _u16(data, start_base + 2 * mid))
                g = _u16(data, go)
                return (g + delta) % 65536 if g else 0
        return 0

    def advance(self, gid):
        if gid in self._adv_cache:
            return self._adv_cache[gid]
        base, _ = self.tables["hmtx"]
        if gid < self.num_hmetrics:
            adv = _u16(self.data, base + gid * 4)
        else:
            adv = _u16(self.data, base + (self.num_hmetrics - 1) * 4)
        self._adv_cache[gid] = adv
        return adv

    def _glyph_offset(self, gid):
        base, _ = self.tables["loca"]
        if self.loc_fmt == 0:
            a = _u16(self.data, base + gid * 2) * 2
            b = _u16(self.data, base + gid * 2 + 2) * 2
        else:
            a = _u32(self.data, base + gid * 4)
            b = _u32(self.data, base + gid * 4 + 4)
        return a, b

    def _read_simple(self, off, contours_out, depth=0):
        """Append flattened contours (lists of (x, y) points) for one glyph."""
        data = self.data
        ncont = _i16(data, off)
        if ncont < 0:
            self._read_composite(off, contours_out, depth)
            return
        if ncont == 0:
            return
        ends = [_u16(data, off + 10 + 2 * i) for i in range(ncont)]
        p = off + 10 + 2 * ncont
        nins = _u16(data, p)
        p += 2 + nins
        npts = ends[-1] + 1
        flags = []
        while len(flags) < npts:
            fl = data[p]
            p += 1
            flags.append(fl)
            if fl & 0x08:
                rep = data[p]
                p += 1
                flags.extend([fl] * rep)
        xs = []
        x = 0
        for fl in flags:
            if fl & 0x02:
                d = data[p]
                p += 1
                x += d if (fl & 0x10) else -d
            elif not (fl & 0x10):
                x += _i16(data, p)
                p += 2
            xs.append(x)
        ys = []
        y = 0
        for fl in flags:
            if fl & 0x04:
                d = data[p]
                p += 1
                y += d if (fl & 0x20) else -d
            elif not (fl & 0x20):
                y += _i16(data, p)
                p += 2
            ys.append(y)
        start = 0
        for end in ends:
            pts = [(xs[i], ys[i], bool(flags[i] & 0x01)) for i in range(start, end + 1)]
            contours_out.append(self._flatten_contour(pts))
            start = end + 1

    def _read_composite(self, off, contours_out, depth):
        if depth > 3:
            return
        data = self.data
        p = off + 10
        while True:
            flags = _u16(data, p)
            comp = _u16(data, p + 2)
            p += 4
            if flags & 0x0001:
                dx = _i16(data, p)
                dy = _i16(data, p + 2)
                p += 4
            else:
                dx = data[p]
                dy = data[p + 1]
                p += 2
            if not (flags & 0x0002):
                # args are point numbers, not offsets
                dx = dy = 0
            sx = sy = 1.0
            m00 = m01 = m10 = m11 = 0.0
            if flags & 0x0008:
                s = _i16(data, p) / 16384.0
                p += 2
                sx = sy = s
                m00 = m11 = s
            elif flags & 0x0040:
                sx = _i16(data, p) / 16384.0
                sy = _i16(data, p + 2) / 16384.0
                p += 4
                m00, m11 = sx, sy
            elif flags & 0x0080:
                m00 = _i16(data, p) / 16384.0
                m01 = _i16(data, p + 2) / 16384.0
                m10 = _i16(data, p + 4) / 16384.0
                m11 = _i16(data, p + 6) / 16384.0
                p += 8
            else:
                m00 = m11 = 1.0
            sub = []
            a, b = self._glyph_offset(comp)
            if b > a:
                self._read_simple(self.tables["glyf"][0] + a, sub, depth + 1)
            for contour in sub:
                contours_out.append([
                    (x * m00 + y * m01 + dx, x * m10 + y * m11 + dy)
                    for (x, y) in contour
                ])
            if not (flags & 0x0020):
                break

    @staticmethod
    def _flatten_contour(pts):
        """Turn on/off-curve points into a polyline (quadratic flattening)."""
        if not pts:
            return []
        # rotate so the contour starts on-curve when possible
        if not pts[0][2]:
            if pts[-1][2]:
                pts = pts[-1:] + pts[:-1]
            else:
                mx = (pts[0][0] + pts[-1][0]) / 2.0
                my = (pts[0][1] + pts[-1][1]) / 2.0
                pts = [(mx, my, True)] + pts
        out = [(pts[0][0], pts[0][1])]
        i = 1
        n = len(pts)
        while i < n:
            x0, y0 = out[-1]
            x1, y1, on1 = pts[i]
            if on1:
                out.append((x1, y1))
                i += 1
            else:
                if i + 1 < n:
                    x2, y2, on2 = pts[i + 1]
                    if on2:
                        ex, ey = x2, y2
                        nxt = i + 2
                    else:
                        ex, ey = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                        nxt = i + 1
                else:
                    ex, ey = pts[0][0], pts[0][1]
                    nxt = n
                # subdivide the quadratic; steps grow with the curve size
                span = max(abs(ex - x0), abs(ey - y0), abs(x1 - x0), abs(y1 - y0))
                steps = max(2, min(16, int(span / 90) + 2))
                for s in range(1, steps + 1):
                    t = s / steps
                    mt = 1 - t
                    out.append((
                        mt * mt * x0 + 2 * mt * t * x1 + t * t * ex,
                        mt * mt * y0 + 2 * mt * t * y1 + t * t * ey,
                    ))
                i = nxt
        return out

    def outline(self, gid):
        if gid in self._glyph_cache:
            return self._glyph_cache[gid]
        a, b = self._glyph_offset(gid)
        contours = []
        if b > a:
            self._read_simple(self.tables["glyf"][0] + a, contours)
        self._glyph_cache[gid] = contours
        return contours

    def text_width(self, s, size):
        scale = size / self.upm
        w = 0.0
        for ch in s:
            w += self.advance(self.glyph_id(ch)) * scale
        return w

    def rasterize(self, gid, size):
        """Return (bitmap, width, height, xoff, yoff): 2x supersampled AA."""
        contours = self.outline(gid)
        if not contours:
            return None
        scale = size / self.upm
        ss = 2
        pts = [[(x * scale * ss, y * scale * ss) for (x, y) in c] for c in contours]
        xs = [x for c in pts for (x, y) in c]
        ys = [y for c in pts for (x, y) in c]
        if not xs:
            return None
        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)
        gw = int(math.ceil(maxx - minx)) + 2
        gh = int(math.ceil(maxy - miny)) + 2
        if gw <= 0 or gh <= 0 or gw > 400 or gh > 400:
            return None
        ox = -minx + 1
        oy = -miny + 1
        buf = bytearray(gw * gh)
        # scanline fill, nonzero winding, at supersampled resolution.
        # Buffer row yy covers font-y [miny-1+yy, miny+yy]: its centre is
        # yc = miny-1+yy+0.5 (the same -miny+1 shift as ox on the x side).
        edges = []
        for c in pts:
            n = len(c)
            for i in range(n):
                x0, y0 = c[i]
                x1, y1 = c[(i + 1) % n]
                if y0 == y1:
                    continue
                edges.append((y0, y1, x0, x1))
        for yy in range(gh):
            yc = yy + 0.5 - oy
            crossings = []
            for (y0, y1, x0, x1) in edges:
                if (y0 <= yc < y1) or (y1 <= yc < y0):
                    t = (yc - y0) / (y1 - y0)
                    crossings.append((x0 + t * (x1 - x0), 1 if y1 > y0 else -1))
            crossings.sort()
            wind = 0
            prev = None
            for (cx, d) in crossings:
                if prev is not None and wind != 0:
                    x0i = max(0, int(math.floor(prev + ox)) if prev + ox >= 0 else 0)
                    x1i = min(gw, int(math.ceil(cx + ox)))
                    for xx in range(x0i, x1i):
                        buf[yy * gw + xx] = 255
                if d > 0:
                    wind += 1
                else:
                    wind -= 1
                prev = cx
        # downsample 2x2 -> 8-bit coverage, output at 1x
        w1 = (gw + 1) // 2
        h1 = (gh + 1) // 2
        out = bytearray(w1 * h1)
        for yy in range(h1):
            for xx in range(w1):
                tot = 0
                cnt = 0
                for dy in (0, 1):
                    for dx in (0, 1):
                        sx, sy = xx * 2 + dx, yy * 2 + dy
                        if sx < gw and sy < gh:
                            tot += buf[sy * gw + sx]
                            cnt += 1
                out[yy * w1 + xx] = tot // max(1, cnt)
        xoff = int(math.floor(minx / ss)) - 1
        yoff = int(math.floor(miny / ss)) - 1
        return (bytes(out), w1, h1, xoff, yoff)


# ================================================================ canvas
class Canvas:
    def __init__(self, w, h, bg):
        self.w = w
        self.h = h
        self.px = bytearray(w * h * 3)
        self.fill_rect(0, 0, w, h, bg)
        self._glyphs = {}

    def set_px(self, x, y, col):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.px[i] = col[0]
            self.px[i + 1] = col[1]
            self.px[i + 2] = col[2]

    def blend_px(self, x, y, col, a):
        if a <= 0 or not (0 <= x < self.w and 0 <= y < self.h):
            return
        if a >= 255:
            self.set_px(x, y, col)
            return
        i = (y * self.w + x) * 3
        self.px[i] = (col[0] * a + self.px[i] * (255 - a)) // 255
        self.px[i + 1] = (col[1] * a + self.px[i + 1] * (255 - a)) // 255
        self.px[i + 2] = (col[2] * a + self.px[i + 2] * (255 - a)) // 255

    def fill_rect(self, x, y, w, h, col):
        x0 = max(0, int(x))
        y0 = max(0, int(y))
        x1 = min(self.w, int(x + w))
        y1 = min(self.h, int(y + h))
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(col) * (x1 - x0)
        for yy in range(y0, y1):
            i = (yy * self.w + x0) * 3
            self.px[i:i + len(row)] = row

    def rect(self, x, y, w, h, col, t=1):
        self.fill_rect(x, y, w, t, col)
        self.fill_rect(x, y + h - t, w, t, col)
        self.fill_rect(x, y, t, h, col)
        self.fill_rect(x + w - t, y, t, h, col)

    def hline(self, x0, x1, y, col, t=1):
        if x1 < x0:
            x0, x1 = x1, x0
        self.fill_rect(x0, y, x1 - x0, t, col)

    def vline(self, x, y0, y1, col, t=1):
        if y1 < y0:
            y0, y1 = y1, y0
        self.fill_rect(x, y0, t, y1 - y0, col)

    def line(self, x0, y0, x1, y1, col, t=1):
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            if t <= 1:
                self.set_px(x0, y0, col)
            else:
                self.fill_rect(x0 - t // 2, y0 - t // 2, t, t, col)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def fill_circle(self, cx, cy, r, col):
        for yy in range(int(cy - r), int(cy + r) + 1):
            dx = int(math.sqrt(max(0, r * r - (yy - cy) ** 2)))
            self.fill_rect(cx - dx, yy, dx * 2 + 1, 1, col)

    def circle(self, cx, cy, r, col, t=1):
        for a in range(360):
            rad = math.radians(a)
            self.fill_rect(int(cx + r * math.cos(rad)) - t // 2,
                           int(cy + r * math.sin(rad)) - t // 2, t, t, col)

    def fill_poly(self, pts, col):
        if len(pts) < 3:
            return
        ys = [p[1] for p in pts]
        for yy in range(int(min(ys)), int(max(ys)) + 1):
            xs = []
            n = len(pts)
            for i in range(n):
                x0, y0 = pts[i]
                x1, y1 = pts[(i + 1) % n]
                if (y0 <= yy < y1) or (y1 <= yy < y0):
                    t = (yy - y0) / (y1 - y0)
                    xs.append(x0 + t * (x1 - x0))
            xs.sort()
            for i in range(0, len(xs) - 1, 2):
                self.fill_rect(int(xs[i]), yy, int(xs[i + 1]) - int(xs[i]) + 1, 1, col)

    def ellipse(self, cx, cy, rx, ry, col):
        for yy in range(int(cy - ry), int(cy + ry) + 1):
            t = (yy - cy) / ry if ry else 0
            if abs(t) > 1:
                continue
            dx = int(rx * math.sqrt(1 - t * t))
            self.fill_rect(cx - dx, yy, dx * 2 + 1, 1, col)

    # ---- text ----
    def _glyph(self, font, ch, size):
        key = (id(font), ch, size)
        g = self._glyphs.get(key)
        if g is None:
            gid = font.glyph_id(ch)
            g = font.rasterize(gid, size) if gid else None
            self._glyphs[key] = g
        return g

    def text_width(self, font, s, size):
        return font.text_width(s, size)

    def draw_text(self, x, y, s, font, size, col, align="left", ls=0.0):
        """Draw text with baseline at y; returns the advance width."""
        if align == "center":
            x -= self.text_width(font, s, size) / 2.0
        elif align == "right":
            x -= self.text_width(font, s, size)
        scale = size / font.upm
        cx = x
        base_y = y
        for ch in s:
            if ch == " ":
                cx += font.advance(font.glyph_id(" ")) * scale + ls
                continue
            g = self._glyph(font, ch, size)
            if g is None:
                cx += font.advance(font.glyph_id(ch)) * scale + ls
                continue
            bmp, gw, gh, xoff, yoff = g
            # Bitmap row 0 is the glyph's BOTTOM (font y grows up); a row
            # covering font-y [yoff+yy, yoff+yy+1] sits on screen at
            # base_y - (yoff+yy+1).
            gx = int(round(cx))
            for yy in range(gh):
                row = yy * gw
                py = int(base_y - yoff - yy - 1)
                if py < 0 or py >= self.h:
                    continue
                for xx in range(gw):
                    a = bmp[row + xx]
                    if a:
                        self.blend_px(gx + xoff + xx, py, col, a)
            cx += font.advance(font.glyph_id(ch)) * scale + ls
        return cx - x

    def wrap(self, font, s, size, maxw):
        words = s.split()
        lines = []
        cur = ""
        for wd in words:
            trial = (cur + " " + wd).strip()
            if self.text_width(font, trial, size) <= maxw or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = wd
        if cur:
            lines.append(cur)
        return lines

    def para(self, x, y, s, font, size, col, maxw, leading=None, align="left"):
        if leading is None:
            leading = int(size * 1.32)
        for ln in self.wrap(font, s, size, maxw):
            self.draw_text(x, y, ln, font, size, col, align=align)
            y += leading
        return y


def write_png(cv, path):
    raw = bytearray()
    stride = cv.w * 3
    for yy in range(cv.h):
        raw.append(0)
        raw += cv.px[yy * stride:(yy + 1) * stride]

    def chunk(tag, data):
        out = struct.pack(">I", len(data)) + tag + data
        out += struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return out

    ihdr = struct.pack(">IIBBBBB", cv.w, cv.h, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", ihdr)
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "wb") as f:
        f.write(png)
    return len(png)

# ================================================================ art
# All illustrations are original flat drawings made of rectangles,
# circles, polygons and lines -- no photos, no copied images.

def _tint(col, f=0.88):
    return tuple(int(255 - (255 - c) * f) for c in col)


def art_icj(cv, x, y, w, h):
    """The Peace Palace and the scales of justice, The Hague."""
    cv.fill_rect(x, y, w, h, SKY)
    cv.fill_circle(x + w - 34, y + 26, 15, GOLD2)
    # courthouse
    bx, bw = x + 26, w - 52
    base_y = y + h - 18
    cv.fill_rect(bx, base_y, bw, 18, SAND)
    cv.fill_rect(bx + 8, base_y - 8, bw - 16, 8, (210, 196, 168))
    cv.fill_rect(bx + 14, base_y - 66, bw - 28, 58, PAPER)
    cv.rect(bx + 14, base_y - 66, bw - 28, 58, MGREY)
    for i in range(4):
        cx0 = bx + 30 + i * ((bw - 60) // 3)
        cv.fill_rect(cx0, base_y - 62, 10, 58, WHITE)
        cv.rect(cx0, base_y - 62, 10, 58, MGREY)
    cv.fill_poly([(bx + 10, base_y - 66), (bx + bw // 2, base_y - 96),
                  (bx + bw - 10, base_y - 66)], NAVY)
    cv.fill_circle(bx + bw // 2, base_y - 78, 7, GOLD2)
    # scales of justice in front
    cx = x + w // 2
    sy = y + h - 34
    cv.fill_rect(cx - 2, sy - 52, 4, 52, GOLD)
    cv.fill_rect(cx - 34, sy - 52, 68, 4, GOLD)
    cv.fill_circle(cx, sy - 54, 4, GOLD)
    for dx in (-34, 34):
        cv.line(cx + dx, sy - 48, cx + dx - 10, sy - 30, GOLD, 2)
        cv.line(cx + dx, sy - 48, cx + dx + 10, sy - 30, GOLD, 2)
        cv.fill_poly([(cx + dx - 12, sy - 30), (cx + dx + 12, sy - 30),
                      (cx + dx, sy - 18)], GOLD2)
    cv.fill_rect(cx - 14, sy, 28, 4, GOLD)


_BOLD_CACHE = [None]


def _bold():
    if _BOLD_CACHE[0] is None:
        here = os.path.dirname(os.path.abspath(__file__))
        _BOLD_CACHE[0] = Font(os.path.join(here,
                                           "LiberationSerif-Bold.ttf"))
    return _BOLD_CACHE[0]


def _star5(cv, cx, cy, r, col):
    pts = []
    for k in range(10):
        ang = -math.pi / 2 + k * math.pi / 5
        rr = r if k % 2 == 0 else r * 0.42
        pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    cv.fill_poly(pts, col)


def art_summit(cv, x, y, w, h):
    """The three leaders, standing before their flags — after the
    reference photo: Trump (US), Xi (China), Putin (Russia)."""
    SKIN = (232, 190, 150)
    NAVY_SUIT = (28, 42, 78)
    DARK = (30, 30, 30)
    # panelled wall, warm brown like the reference backdrop
    cv.fill_rect(x, y, w, h, (133, 96, 62))
    for sx in range(0, w, 52):
        cv.line(x + sx, y, x + sx, y + h, (110, 78, 48), 2)
    centres = [x + w // 6, x + w // 2, x + 5 * w // 6]
    # ---- flags behind each leader ----
    # US flag: stripes + canton
    fx0 = centres[0] - 48
    for s in range(13):
        if s % 2 == 0:
            cv.fill_rect(fx0, y + s * 7, 96, 7, (178, 34, 52))
    cv.fill_rect(fx0, y, 40, 49, (40, 60, 130))
    for dy in range(6, 49, 10):
        for dx in range(5, 40, 9):
            cv.fill_circle(fx0 + dx, y + dy, 2, WHITE)
    # China flag: red + five gold stars
    fx1 = centres[1] - 48
    cv.fill_rect(fx1, y, 96, 92, (222, 32, 32))
    _star5(cv, fx1 + 20, y + 20, 10, (255, 210, 60))
    for (sx, sy) in ((42, 12), (52, 22), (50, 34), (40, 40)):
        _star5(cv, fx1 + sx, y + sy, 4, (255, 210, 60))
    # Russia flag: white / blue / red bands
    fx2 = centres[2] - 48
    cv.fill_rect(fx2, y, 96, 31, WHITE)
    cv.fill_rect(fx2, y + 31, 96, 31, (0, 70, 170))
    cv.fill_rect(fx2, y + 62, 96, 30, (210, 30, 30))
    # ---- three figures ----
    leaders = [
        ("TRUMP", (238, 205, 110), (200, 30, 40),
         [( -25, -6), (-22, -22), (-8, -28), (8, -27), (20, -24),
          (25, -12), (24, -5), (12, -14), (-6, -15), (-18, -12)]),
        ("XI", (22, 22, 22), (40, 90, 180),
         [(-26, -7), (-24, -21), (-10, -27), (10, -27), (24, -21),
          (26, -7), (12, -13), (-12, -13)]),
        ("PUTIN", (198, 182, 148), (140, 30, 40),
         [(-25, -9), (-18, -22), (0, -25), (18, -22), (25, -9),
          (10, -16), (-10, -16)]),
    ]
    for idx, (name, hair_col, tie_col, hair) in enumerate(leaders):
        cx = centres[idx]
        hy = y + 48
        # neck, suit, shirt, tie
        cv.fill_rect(cx - 9, y + 70, 18, 12, SKIN)
        cv.fill_poly([(cx - 44, y + h - 16), (cx - 40, y + 80),
                      (cx + 40, y + 80), (cx + 44, y + h - 16)],
                     NAVY_SUIT)
        cv.fill_poly([(cx - 13, y + 80), (cx + 13, y + 80),
                      (cx, y + 104)], WHITE)
        cv.fill_poly([(cx - 5, y + 82), (cx + 5, y + 82), (cx + 6, y + 98),
                      (cx, y + 110), (cx - 6, y + 98)], tie_col)
        # head, ears, hair, face
        cv.ellipse(cx - 26, hy - 6, 8, 12, SKIN)
        cv.ellipse(cx + 26, hy - 6, 8, 12, SKIN)
        cv.ellipse(cx, hy, 26, 28, SKIN)
        cv.fill_poly([(cx + dx, hy + dy) for (dx, dy) in hair], hair_col)
        cv.fill_circle(cx - 9, hy - 2, 2, DARK)
        cv.fill_circle(cx + 9, hy - 2, 2, DARK)
        cv.line(cx - 13, hy - 9, cx - 5, hy - 10, DARK, 2)
        cv.line(cx + 5, hy - 10, cx + 13, hy - 9, DARK, 2)
        prev = None
        for k in range(11):
            dx = -10 + 2 * k
            py = hy + 12 + (1 - (dx / 10.0) ** 2) * 5
            pt = (cx + dx, int(py))
            if prev is not None:
                cv.line(prev[0], prev[1], pt[0], pt[1], (120, 70, 50), 2)
            prev = pt
    # name band
    cv.fill_rect(x, y + h - 16, w, 16, NAVY)
    for idx, (name, _hc, _tc, _hr) in enumerate(leaders):
        cv.draw_text(centres[idx], y + h - 5, name, _bold(), 10, WHITE,
                     align="center")


def art_market(cv, x, y, w, h):
    """A falling market chart, with one green arrow fighting back."""
    cv.fill_rect(x, y, w, h, PAPER)
    for gy in range(y + 18, y + h - 14, 22):
        cv.hline(x + 10, x + w - 10, gy, LGREY)
    # candlesticks stepping down
    tops = [30, 44, 38, 58, 52, 72, 66, 88, 96]
    for i, t in enumerate(tops):
        cx0 = x + 16 + i * 30
        col = RED2 if i % 2 == 0 else RED
        cv.fill_rect(cx0, y + t, 16, 34, col)
        cv.vline(cx0 + 8, y + t - 8, y + t + 42, col, 2)
    # falling line with arrowhead
    pts = [(x + 14, y + 34), (x + 70, y + 52), (x + 130, y + 48),
           (x + 190, y + 78), (x + 250, y + 92), (x + w - 16, y + 118)]
    for a, b in zip(pts, pts[1:]):
        cv.line(a[0], a[1], b[0], b[1], RED, 3)
    ex, ey = pts[-1]
    cv.fill_poly([(ex, ey), (ex - 14, ey - 7), (ex - 14, ey + 7)], RED)
    # green IPO arrow rising at the right
    gx = x + w - 52
    cv.fill_poly([(gx, y + h - 22), (gx + 12, y + h - 22), (gx + 12, y + 58),
                  (gx + 24, y + 58), (gx + 6, y + 30), (gx - 12, y + 58),
                  (gx, y + 58)], GREEN)


def icon_bridge(cv, x, y, s):
    cv.fill_rect(x, y, s, s, _tint(BLUE))
    cv.fill_rect(x + 6, y + s - 22, s - 12, 5, NAVY)
    for tx in (x + 12, x + s - 22):
        cv.fill_rect(tx, y + 14, 8, s - 32, NAVY)
    cv.line(x + 8, y + s - 22, x + s // 2, y + 16, NAVY, 2)
    cv.line(x + s - 8, y + s - 22, x + s // 2, y + 16, NAVY, 2)
    cv.fill_poly([(x + s // 2 - 9, y + 8), (x + s // 2 + 2, y + 14),
                  (x + s // 2 - 2, y + 20), (x + s // 2 + 9, y + 12),
                  (x + s // 2, y + 22), (x + s // 2 - 8, y + 18)], GOLD2)


def icon_capitol(cv, x, y, s):
    cv.fill_rect(x, y, s, s, _tint(RED2))
    cx = x + s // 2
    cv.ellipse(cx, y + 22, 16, 12, NAVY)
    cv.fill_rect(cx - 16, y + 22, 32, 8, NAVY)
    cv.fill_rect(x + 8, y + 30, s - 16, 6, NAVY)
    for i in range(4):
        cv.fill_rect(x + 12 + i * 12, y + 36, 5, 14, NAVY)
    cv.fill_rect(x + 8, y + 50, s - 16, 5, NAVY)
    cv.vline(cx, y + 6, y + 12, NAVY, 2)


def icon_truck(cv, x, y, s):
    cv.fill_rect(x, y, s, s, _tint(ORANGE))
    cv.fill_rect(x + 8, y + 18, 30, 20, WHITE)
    cv.rect(x + 8, y + 18, 30, 20, ORANGE)
    cv.fill_rect(x + 38, y + 26, 12, 12, WHITE)
    cv.rect(x + 38, y + 26, 12, 12, ORANGE)
    cv.fill_circle(x + 17, y + 42, 5, INK)
    cv.fill_circle(x + 43, y + 42, 5, INK)
    cv.fill_rect(x + 19, y + 23, 8, 3, RED2)
    cv.fill_rect(x + 21, y + 21, 3, 8, RED2)


def icon_ships(cv, x, y, s):
    cv.fill_rect(x, y, s, s, _tint(BLUE))
    cv.fill_poly([(x + 8, y + 30), (x + 28, y + 30), (x + 24, y + 42),
                  (x + 12, y + 42)], NAVY)
    cv.fill_rect(x + 16, y + 18, 3, 12, NAVY)
    cv.fill_poly([(x + 19, y + 18), (x + 19, y + 28), (x + 29, y + 28)], RED2)
    cv.fill_poly([(x + 34, y + 36), (x + 52, y + 36), (x + 48, y + 46),
                  (x + 38, y + 46)], NAVY)
    for wy in (48, 53):
        cv.hline(x + 6, x + s - 6, y + wy, BLUE, 2)


def icon_ice(cv, x, y, s):
    cv.fill_rect(x, y, s, s, _tint(TEAL))
    cv.fill_poly([(x + 8, y + 44), (x + 22, y + 16), (x + 36, y + 44)], WHITE)
    cv.fill_poly([(x + 28, y + 44), (x + 44, y + 22), (x + 54, y + 44)], (210, 230, 240))
    cv.hline(x + 6, x + s - 6, y + 46, BLUE, 2)
    cv.fill_rect(x + 44, y + 8, 2, 16, NAVY)
    cv.fill_rect(x + 46, y + 8, 10, 7, RED2)


def icon_atom(cv, x, y, s):
    cv.fill_rect(x, y, s, s, _tint(PURPLE))
    cx, cy = x + s // 2, y + s // 2
    cv.circle(cx, cy, 16, PURPLE, 2)
    cv.circle(cx, cy, 11, PURPLE, 2)
    cv.fill_circle(cx, cy, 5, RED2)
    for (dx, dy) in ((-14, -10), (14, -10), (0, 15)):
        cv.fill_circle(cx + dx, cy + dy, 3, BLUE)


def icon_shield(cv, x, y, s):
    cv.fill_rect(x, y, s, s, _tint(RED2))
    cx = x + s // 2
    cv.fill_poly([(cx - 15, y + 10), (cx + 15, y + 10), (cx + 15, y + 30),
                  (cx, y + 46), (cx - 15, y + 30)], NAVY)
    cv.fill_poly([(cx, y + 17), (cx + 3, y + 23), (cx + 9, y + 23),
                  (cx + 4, y + 28), (cx + 6, y + 34), (cx, y + 30),
                  (cx - 6, y + 34), (cx - 4, y + 28), (cx - 9, y + 23),
                  (cx - 3, y + 23)], GOLD2)


def icon_parliament(cv, x, y, s):
    cv.fill_rect(x, y, s, s, _tint(TEAL))
    cx = x + s // 2
    cv.ellipse(cx, y + 20, 13, 10, TEAL)
    cv.fill_rect(cx - 13, y + 20, 26, 6, TEAL)
    cv.fill_rect(x + 10, y + 26, s - 20, 5, TEAL)
    for i in range(4):
        cv.fill_rect(x + 13 + i * 11, y + 31, 5, 14, TEAL)
    cv.fill_rect(x + 8, y + 45, s - 16, 5, TEAL)
    cv.fill_rect(x + s - 14, y + 8, 2, 14, NAVY)
    cv.fill_rect(x + s - 12, y + 8, 9, 6, RED2)


ICONS = {"bridge": icon_bridge, "capitol": icon_capitol, "truck": icon_truck,
         "ships": icon_ships, "ice": icon_ice, "atom": icon_atom,
         "shield": icon_shield, "parliament": icon_parliament}

# ================================================================ map
CONTINENTS = [
    # North America
    [(-168, 66), (-140, 70), (-120, 72), (-95, 80), (-80, 73), (-75, 62),
     (-65, 45), (-70, 42), (-75, 35), (-80, 32), (-90, 21), (-97, 16),
     (-105, 20), (-115, 28), (-125, 40), (-125, 49), (-145, 60), (-168, 66)],
    # Greenland
    [(-58, 64), (-45, 60), (-30, 68), (-22, 70), (-30, 76), (-55, 76),
     (-60, 70), (-58, 64)],
    # South America
    [(-80, 10), (-72, 12), (-62, 10), (-52, 5), (-40, -5), (-35, -8),
     (-40, -20), (-48, -28), (-58, -35), (-65, -41), (-70, -50),
     (-73, -53), (-70, -30), (-70, -18), (-77, -12), (-80, 10)],
    # Europe
    [(-10, 36), (-9, 43), (0, 48), (-2, 51), (5, 53), (8, 57), (12, 56),
     (18, 56), (21, 59), (24, 60), (30, 60), (28, 55), (24, 45),
     (28, 40), (23, 36), (19, 40), (12, 44), (3, 43), (-2, 37), (-10, 36)],
    # Africa
    [(-17, 15), (-10, 30), (0, 35), (10, 37), (20, 32), (32, 31),
     (35, 28), (43, 12), (51, 11), (48, 0), (40, -10), (35, -18),
     (28, -26), (20, -35), (16, -28), (12, -18), (9, -1), (4, 6),
     (-8, 5), (-17, 15)],
    # Asia
    [(30, 60), (40, 68), (60, 69), (75, 72), (90, 75), (110, 76),
     (130, 72), (150, 70), (170, 66), (178, 65), (170, 60), (162, 55),
     (156, 50), (142, 45), (140, 38), (135, 33), (127, 30), (122, 28),
     (120, 22), (110, 20), (105, 10), (100, 8), (95, 15), (90, 22),
     (85, 20), (80, 13), (75, 8), (72, 20), (66, 25), (60, 25),
     (55, 26), (50, 29), (48, 30), (44, 29), (40, 36), (35, 36), (30, 60)],
    # Australia
    [(113, -22), (114, -30), (115, -35), (120, -34), (129, -32),
     (132, -32), (137, -35), (140, -38), (145, -38), (150, -37),
     (153, -32), (153, -27), (150, -22), (146, -19), (142, -15),
     (142, -11), (136, -12), (132, -11), (126, -14), (122, -17),
     (118, -20), (113, -22)],
]

# (number, lon, lat)
PINS = [
    (1, 4.5, 52.1), (2, 114.1, 22.5), (3, -74.0, 40.7), (4, 36.5, 45.3),
    (5, 34.5, 31.5), (6, 10.7, 59.9), (7, 12.6, 55.7), (8, 125.8, 39.0),
    (9, -72.3, 18.5), (10, -17.4, 14.7), (11, 106.8, -6.2), (12, 85.5, 19.8),
]


def draw_map(cv, x, y, w, h, font_bold):
    cv.fill_rect(x, y, w, h, (232, 240, 244))
    def px(lon, lat):
        return (x + 6 + (lon + 180) / 360.0 * (w - 12),
                y + 4 + (75 - lat) / 135.0 * (h - 12))
    for poly in CONTINENTS:
        cv.fill_poly([px(lon, lat) for (lon, lat) in poly], (203, 206, 190))
    # Europe's pins sit within a few pixels of each other at this scale,
    # so three of them are nudged outward with a leader line to the true spot.
    NUDGE = {1: (-13, 9), 6: (-11, -13), 7: (13, -7)}
    for (num, lon, lat) in PINS:
        tx, ty = px(lon, lat)
        dx, dy = NUDGE.get(num, (0, 0))
        px0, py0 = int(tx + dx), int(ty + dy)
        if (dx, dy) != (0, 0):
            cv.fill_circle(int(tx), int(ty), 2, RED)
            cv.line(int(tx), int(ty), px0, py0, RED, 1)
        cv.fill_circle(px0, py0, 8, RED)
        cv.circle(px0, py0, 8, WHITE, 1)
        cv.draw_text(px0, py0 + 3, str(num), font_bold, 9, WHITE,
                     align="center")

# ================================================================ content
# 36 stories, all dated Thursday 19 November 2026 and re-verified
# against reports of that day before drawing. Region counts:
# Europe 7, Americas 8, Asia-Pacific 9, Middle East 3, Africa 4,
# Oceania 3, World 2.

REGION_COL = {"EUROPE": BLUE, "AMERICAS": RED2, "ASIA-PACIFIC": TEAL,
              "MIDDLE EAST": ORANGE, "AFRICA": GREEN, "OCEANIA": PURPLE,
              "WORLD": GREY}

STATS = [
    ("-2.02%", "S&P 500 — fifth straight loss", RED),
    ("$81.3bn", "Anthropic IPO, largest ever", TEAL),
    ("9–6", "ICJ: Myanmar guilty of genocide", NAVY),
    ("90 min", "First Trump–Xi–Putin talks", PURPLE),
]

LEADS = [
    {"art": art_summit, "tag": "SHENZHEN · DIPLOMACY",
     "title": "TRUMP, XI AND PUTIN END HISTORIC SUMMIT",
     "deck": "First-ever three-way talks run 90 minutes in Shenzhen; the "
             "leaders denounce nuclear war and APEC adopts the Shenzhen "
             "Outlook on trade, data and AI.",
     "src": "WSJ · USA Today · APEC — 19 Nov 2026"},
    {"art": art_icj, "tag": "THE HAGUE · INTERNATIONAL LAW",
     "title": "WORLD COURT: MYANMAR GUILTY OF GENOCIDE",
     "deck": "The ICJ rules 9–6 that Myanmar committed genocide against "
             "the Rohingya in 2017 — the first state ever held responsible.",
     "src": "Reuters · CNN · Le Monde — 19 Nov 2026"},
    {"art": art_market, "tag": "NEW YORK · MARKETS",
     "title": "WALL STREET SLIDES AS AI BUST BITES",
     "deck": "S&P 500 −2.02%, a fifth straight loss; Nikkei −4.68% — even "
             "as Anthropic's record $81.3bn IPO closes 17% above its price.",
     "src": "Dow Jones · OneTurn — 19 Nov 2026"},
]

MEDIUMS = [
    {"icon": "bridge", "region": "EUROPE", "place": "KERCH",
     "title": "Ukraine hits Kerch Bridge a third time in four days; "
              "Putin vows a harsher reply"},
    {"icon": "capitol", "region": "AMERICAS", "place": "WASHINGTON",
     "title": "Senate rejects Iran war-powers bid, 51–48"},
    {"icon": "truck", "region": "MIDDLE EAST", "place": "GAZA",
     "title": "Aid groups grade Gaza peace plan 4 out of 26; only 49 "
              "trucks a day vs 600"},
    {"icon": "ships", "region": "EUROPE", "place": "LONDON · OSLO",
     "title": "UK and Norway pledge £100m+ for two Ukrainian naval craft"},
    {"icon": "ice", "region": "EUROPE", "place": "COPENHAGEN",
     "title": "Denmark backs US–Greenland security deal, 109–0"},
    {"icon": "atom", "region": "ASIA-PACIFIC", "place": "VIENNA",
     "title": "IAEA: North Korea expanded uranium enrichment"},
    {"icon": "shield", "region": "AMERICAS", "place": "PORT-AU-PRINCE",
     "title": "Haitian police kill 34 gang members in raid to retake corridor"},
    {"icon": "parliament", "region": "ASIA-PACIFIC", "place": "JAKARTA",
     "title": "Indonesia's parliament passes asset-forfeiture bill"},
]

ALSO = [
    "GTA VI out at midnight; NZ first, $79.99",
    "COP31 draft drops fossil fuels, $120bn goal",
    "Cyclone Akvan nears Odisha; 50,000 moved",
    "South Florida floods after slow storm",
    "Migrant boat sinks off Senegal; dozens lost",
    "589m children lived in conflict zones",
    "Tanzania: Lissu convicted of sedition",
    "Ethiopia–Eritrea troops mass near Badme",
    "Iraq orders Kataib Hezbollah out",
    "Pakistan: 22 militants killed in raids",
    "Seoul: Half a million sit entrance exam",
    "Trump pardons Pete Rose posthumously",
    "US in new Supreme Court bid over TPS",
    "US jobless claims unexpectedly rise",
    "Australia jobless rate highest since 2021",
    "Japan inflation quickens; BOJ eyes hike",
    "EU, Mexico to scrap 95% of farm tariffs",
    "Philippines, Chile sign free-trade deal",
    "Serbia elects Cupic speaker, 140 votes",
    "Saudi Arabia warns of storms to 24 Nov",
    "Fiji declares disaster over El Niño",
    "Sánchez admits mistakes in Spain debate",
    "Brent near flat at $89.72; IEA warns",
    "South Africa holds repo rate at 7.25%",
    "Canada eases rules for smaller lenders",
]

DATE_CHECK = ("DATE CHECK — Left out on purpose: the EU's €45bn Ukraine "
              "loan, the Pew projection that Muslims will outnumber "
              "Christians by 2035, and Voyager 1 passing one light-day all "
              "broke on Wednesday 18 November, not Thursday. Every story "
              "on this page is dated Thursday 19 November 2026.")

FOOTER = ("Sources: Reuters, CNN, WSJ, USA Today, AP, UN News, ReliefWeb, "
          "OneTurn, Dow Jones/Morningstar. Original drawings — no photos.")
FOOTER2 = ("Contested claims are attributed. Figures as reported on "
           "Thursday 19 November 2026.")

MAP_KEY_1 = "1 The Hague · 2 Shenzhen · 3 New York · 4 Kerch · 5 Gaza · 6 Oslo"
MAP_KEY_2 = ("7 Copenhagen · 8 Pyongyang · 9 Port-au-Prince · 10 Dakar · "
             "11 Jakarta · 12 Odisha")


# ================================================================ layout
def render():
    here = os.path.dirname(os.path.abspath(__file__))
    reg = Font(os.path.join(here, "LiberationSerif-Regular.ttf"))
    bold = Font(os.path.join(here, "LiberationSerif-Bold.ttf"))
    ital = Font(os.path.join(here, "LiberationSerif-Italic.ttf"))

    cv = Canvas(W, H, CREAM)
    cv.fill_rect(0, 0, W, 10, NAVY)
    cv.fill_rect(0, H - 10, W, 10, NAVY)

    # ---- masthead ----
    cv.draw_text(W // 2, 30, "THE WORLD IN ONE DAY", bold, 13, NAVY,
                 align="center", ls=2.0)
    cv.draw_text(W // 2, 74, "Thursday 19 November 2026", bold, 40, NAVY,
                 align="center")
    cv.hline(26, 998, 82, GOLD, 2)
    cv.fill_rect(26, 88, 972, 24, NAVY)
    cv.draw_text(W // 2, 105,
                 "36 STORIES  ·  EUROPE 7  ·  AMERICAS 8  ·  ASIA-PACIFIC 9  ·  "
                 "MIDDLE EAST 3  ·  AFRICA 4  ·  OCEANIA 3  ·  WORLD 2",
                 bold, 12, WHITE, align="center")

    # ---- numbers strip ----
    for i, (big, label, col) in enumerate(STATS):
        bx = 26 + i * 245
        cv.fill_rect(bx, 120, 237, 52, PAPER)
        cv.rect(bx, 120, 237, 52, MGREY)
        cv.fill_rect(bx, 120, 237, 3, col)
        cv.draw_text(bx + 12, 146, big, bold, 22, col)
        cv.draw_text(bx + 12, 164, label, reg, 10, INK)

    # ---- three leads: summit first and widest ----
    LEAD_WIDTHS = [380, 296, 276]
    lx = 26
    for i, lead in enumerate(LEADS):
        lw = LEAD_WIDTHS[i]
        lead["art"](cv, lx, 182, lw, 134)
        cv.rect(lx, 182, lw, 134, MGREY)
        cv.draw_text(lx, 336, lead["tag"], bold, 10, RED)
        y = 360
        for ln in cv.wrap(bold, lead["title"], 20, lw):
            cv.draw_text(lx, y, ln, bold, 20, NAVY)
            y += 24
        y += 6
        for ln in cv.wrap(reg, lead["deck"], 11.5, lw):
            cv.draw_text(lx, y, ln, reg, 11.5, INK)
            y += 14
        cv.draw_text(lx, y + 11, lead["src"], ital, 9, GREY)
        lx += lw + 10
    cv.hline(26, 998, 470, NAVY, 2)

    # ---- medium grid: 4 x 2 ----
    for idx, med in enumerate(MEDIUMS):
        col, row = idx % 4, idx // 4
        mx = 26 + col * 245
        my = 480 + row * 94
        cv.fill_rect(mx, my, 237, 86, PAPER)
        cv.rect(mx, my, 237, 86, MGREY)
        ICONS[med["icon"]](cv, mx + 8, my + 11, 62)
        tx = mx + 78
        cv.draw_text(tx, my + 20, med["place"], bold, 8.5,
                     REGION_COL[med["region"]])
        cv.draw_text(tx, my + 32, med["region"], bold, 8.5, GREY)
        y = my + 48
        for ln in cv.wrap(bold, med["title"], 11, 151):
            cv.draw_text(tx, y, ln, bold, 11, INK)
            y += 14

    # ---- map + also list ----
    cv.draw_text(26, 692, "WHERE IT HAPPENED", bold, 13, NAVY)
    cv.draw_text(512, 692, "ALSO ON THURSDAY 19 NOVEMBER", bold, 13, NAVY)
    cv.hline(26, 998, 698, NAVY, 1)
    draw_map(cv, 26, 706, 470, 152, bold)
    cv.rect(26, 706, 470, 152, MGREY)
    cv.draw_text(26, 880, MAP_KEY_1, reg, 8.5, GREY)
    cv.draw_text(26, 892, MAP_KEY_2, reg, 8.5, GREY)
    for j, item in enumerate(ALSO):
        col, k = (0, j) if j < 13 else (1, j - 13)
        ax = 512 + col * 246
        ay = 720 + k * 14
        cv.draw_text(ax, ay, "%d." % (j + 1), bold, 10, RED)
        cv.draw_text(ax + 20, ay, item, reg, 10, INK)

    # ---- date check ----
    cv.fill_rect(26, 910, 972, 52, PAPER)
    cv.rect(26, 910, 972, 52, MGREY)
    cv.fill_rect(26, 910, 5, 52, RED)
    y = 930
    for ln in cv.wrap(reg, DATE_CHECK, 11, 940):
        if ln.startswith("DATE CHECK"):
            cv.draw_text(42, y, "DATE CHECK", bold, 11, RED)
            rest = ln[len("DATE CHECK"):]
            cv.draw_text(42 + cv.text_width(bold, "DATE CHECK", 11) + 4, y,
                         rest, reg, 11, INK)
        else:
            cv.draw_text(42, y, ln, reg, 11, INK)
        y += 15

    # ---- footer ----
    cv.draw_text(W // 2, 980, FOOTER, reg, 9, GREY, align="center")
    cv.draw_text(W // 2, 994, FOOTER2, ital, 9, GREY, align="center")
    return cv


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else None
    if out is None:
        out = os.environ.get("OUT")
    if out is None:
        out = "/output/entry.png" if os.path.isdir("/output") else "out/entry.png"
    cv = render()
    n = write_png(cv, out)
    print("wrote %s (%d bytes, %dx%d)" % (out, n, W, H))


if __name__ == "__main__":
    main()
