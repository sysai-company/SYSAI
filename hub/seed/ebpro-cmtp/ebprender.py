"""A window of an EasyBuilder Pro project drawn as a PNG, the way the panel shows it as far as the project tells:
background, shapes, the pictures of the first state (PNG, BMP and baseline JPEG), labels in the project's fonts
(TrueType fonts of the system), EasyBuilder's own library shapes as plain buttons, fields and lamps. Pure Python,
no packages."""
import math
import struct
import zlib

import ttf

FONT = 1.35     # px of a font per EasyBuilder point (as the canvas of the window app)
LINE = 1.36
FIELD = {'NumericInput', 'NumericDisplay', 'ASCII', 'SetWord?', 'ASCII?'}
LAMP = {'BitLamp', 'WordLamp?', 'MultiState?'}


def _hex(c, default=(0, 0, 0)):
    try:
        c = str(c)
        return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
    except (TypeError, ValueError, IndexError):
        return default


class Canvas:
    def __init__(self, w: int, h: int, bg=(0, 0, 0)):
        self.w, self.h = w, h
        self.px = bytearray(bytes(bg) * (w * h))

    def fill(self, l, t, r, b, rgb, alpha: float = 1.0) -> None:
        """Fill pixels l..r, t..b (inclusive)."""
        l, t, r, b = max(0, int(l)), max(0, int(t)), min(self.w - 1, int(r)), min(self.h - 1, int(b))
        if l > r or t > b:
            return
        n = r - l + 1
        if alpha >= 1:
            row = bytes(rgb) * n
            for y in range(t, b + 1):
                i = 3 * (y * self.w + l)
                self.px[i:i + 3 * n] = row
            return
        a, ia = alpha, 1 - alpha
        for y in range(t, b + 1):
            i = 3 * (y * self.w + l)
            seg = self.px[i:i + 3 * n]
            self.px[i:i + 3 * n] = bytes(int(seg[k] * ia + rgb[k % 3] * a) for k in range(3 * n))

    def frame(self, l, t, r, b, rgb, width=1) -> None:
        width = max(1, int(width))
        self.fill(l, t, r, t + width - 1, rgb)
        self.fill(l, b - width + 1, r, b, rgb)
        self.fill(l, t, l + width - 1, b, rgb)
        self.fill(r - width + 1, t, r, b, rgb)

    def gradient(self, l, t, r, b, top, bottom) -> None:
        h = max(1, int(b) - int(t))
        for y in range(int(t), int(b) + 1):
            k = (y - int(t)) / h
            self.fill(l, y, r, y, tuple(int(top[i] + (bottom[i] - top[i]) * k) for i in range(3)))

    def line(self, x0, y0, x1, y1, rgb, width=1) -> None:
        width = max(1, int(width))
        n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        h = width // 2
        if x0 == x1 or y0 == y1:
            self.fill(min(x0, x1) - h, min(y0, y1) - h, max(x0, x1) - h + width - 1, max(y0, y1) - h + width - 1, rgb)
            return
        for k in range(n):
            x = x0 + (x1 - x0) * k / max(1, n - 1)
            y = y0 + (y1 - y0) * k / max(1, n - 1)
            self.fill(x - h, y - h, x - h + width - 1, y - h + width - 1, rgb)

    def ellipse(self, l, t, r, b, rgb, edge=None) -> None:
        cx, cy = (l + r) / 2, (t + b) / 2
        rx, ry = max(0.5, (r - l) / 2), max(0.5, (b - t) / 2)
        for y in range(max(0, int(t)), min(self.h - 1, int(b)) + 1):
            dy = (y - cy) / ry
            if abs(dy) > 1:
                continue
            dx = rx * (1 - dy * dy) ** 0.5
            self.fill(cx - dx, y, cx + dx, y, rgb)
            if edge:
                self.fill(cx - dx, y, cx - dx, y, edge)
                self.fill(cx + dx, y, cx + dx, y, edge)
        if edge:
            self.fill(cx - rx * 0.4, t, cx + rx * 0.4, t, edge)
            self.fill(cx - rx * 0.4, b, cx + rx * 0.4, b, edge)

    def image(self, img, l, t, r, b) -> None:
        """Draw an RGBA image (w, h, bytes) stretched over l..r, t..b."""
        iw, ih, data = img
        tw, th = int(r) - int(l) + 1, int(b) - int(t) + 1
        if tw <= 0 or th <= 0 or iw <= 0 or ih <= 0:
            return
        xs = [min(iw - 1, int((x + 0.5) * iw / tw)) for x in range(tw)]
        for y in range(th):
            py = int(t) + y
            if not 0 <= py < self.h:
                continue
            sy = min(ih - 1, int((y + 0.5) * ih / th))
            src = memoryview(data)[4 * iw * sy:4 * iw * (sy + 1)]
            base = 3 * (py * self.w)
            for x in range(tw):
                px = int(l) + x
                if not 0 <= px < self.w:
                    continue
                q = 4 * xs[x]
                a = src[q + 3]
                if a == 0:
                    continue
                i = base + 3 * px
                if a == 255:
                    self.px[i:i + 3] = src[q:q + 3]
                else:
                    for c in range(3):
                        self.px[i + c] = (src[q + c] * a + self.px[i + c] * (255 - a)) // 255

    def mask(self, m, x0, y0, rgb, clip=None) -> None:
        """Paint colour rgb through an alpha mask (w, h, bytes) with its top-left at x0, y0."""
        w, h, a = m
        cl, ct, cr, cb = clip or (0, 0, self.w - 1, self.h - 1)
        cl, ct, cr, cb = max(0, cl), max(0, ct), min(self.w - 1, cr), min(self.h - 1, cb)
        x0, y0 = int(round(x0)), int(round(y0))
        for y in range(h):
            py = y0 + y
            if not ct <= py <= cb:
                continue
            row = a[y * w:(y + 1) * w]
            if not any(row):
                continue
            base = 3 * py * self.w
            for x, v in enumerate(row):
                if not v:
                    continue
                px = x0 + x
                if not cl <= px <= cr:
                    continue
                i = base + 3 * px
                for c in range(3):
                    self.px[i + c] = (rgb[c] * v + self.px[i + c] * (255 - v)) // 255

    def png(self) -> bytes:
        raw = b''.join(b'\x00' + bytes(self.px[3 * y * self.w:3 * (y + 1) * self.w]) for y in range(self.h))
        return png_bytes(self.w, self.h, raw, 2)


def png_bytes(w, h, raw, ctype) -> bytes:
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, ctype, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


# -- pictures --------------------------------------------------------------------------------------------------------
def decode_png(data: bytes):
    """(w, h, RGBA bytes) of a PNG (8-bit and lower, not interlaced); ValueError otherwise."""
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('not a PNG')
    p, idat, pal, trns = 8, [], None, None
    w = h = depth = ctype = inter = None
    while p + 8 <= len(data):
        n, kind = struct.unpack_from('>I4s', data, p)
        body = data[p + 8:p + 8 + n]
        if kind == b'IHDR':
            w, h, depth, ctype, _, _, inter = struct.unpack('>IIBBBBB', body)
        elif kind == b'PLTE':
            pal = body
        elif kind == b'tRNS':
            trns = body
        elif kind == b'IDAT':
            idat.append(body)
        elif kind == b'IEND':
            break
        p += 12 + n
    if not w or inter or depth == 16 or w * h > 16_000_000:
        raise ValueError('this PNG is not supported')
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    bpp = max(1, ch * depth // 8)
    stride = (w * ch * depth + 7) // 8
    raw = zlib.decompress(b''.join(idat))
    out = bytearray()
    prev = bytearray(stride)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        if f == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif f == 2:
            line = bytearray((a + b) & 255 for a, b in zip(line, prev))
        elif f == 3:
            for i in range(stride):
                line[i] = (line[i] + ((line[i - bpp] if i >= bpp else 0) + prev[i]) // 2) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = line
        if depth < 8:
            per = 8 // depth
            vals = [(line[x // per] >> (8 - depth * (x % per + 1))) & ((1 << depth) - 1) for x in range(w)]
            if ctype == 0:
                k = 255 // ((1 << depth) - 1)
                vals = [v * k for v in vals]
        else:
            vals = line
        if ctype == 6:
            out += vals
        elif ctype == 2:
            key = struct.unpack('>HHH', trns) if trns and len(trns) == 6 else None
            for x in range(w):
                rgb = vals[3 * x:3 * x + 3]
                out += bytes(rgb) + (b'\x00' if key and tuple(rgb) == key else b'\xff')
        elif ctype == 3:
            for v in vals:
                out += (pal[3 * v:3 * v + 3] if pal and 3 * v + 3 <= len(pal) else b'\x00\x00\x00') + \
                    bytes([trns[v] if trns and v < len(trns) else 255])
        elif ctype == 0:
            for v in vals:
                out += bytes([v, v, v, 255])
        else:
            for x in range(w):
                v = vals[2 * x]
                out += bytes([v, v, v, vals[2 * x + 1]])
    return w, h, bytes(out)


def decode_bmp(data: bytes, transparent=None):
    """(w, h, RGBA bytes) of an uncompressed Windows bitmap; the transparent colour gets alpha 0."""
    if data[:2] != b'BM' or len(data) < 54:
        raise ValueError('not a bitmap')
    off, = struct.unpack_from('<I', data, 10)
    hsize, w, h, _, bits, comp = struct.unpack_from('<IiiHHI', data, 14)
    if comp not in (0, 3) or bits not in (1, 4, 8, 24, 32) or not 0 < w <= 10000 or not 0 < abs(h) <= 10000:
        raise ValueError('this bitmap is not supported')
    pal = []
    if bits <= 8:
        n = struct.unpack_from('<I', data, 46)[0] or 1 << bits
        p = 14 + hsize
        pal = [bytes((data[p + 4 * i + 2], data[p + 4 * i + 1], data[p + 4 * i])) for i in range(n)]
    key = bytes(_hex(transparent)) if transparent else None
    stride = (bits * w + 31) // 32 * 4
    out = bytearray()
    for y in range(abs(h)):
        src = off + (abs(h) - 1 - y if h > 0 else y) * stride
        for x in range(w):
            if bits >= 24:
                q = src + x * (bits // 8)
                rgb = bytes((data[q + 2], data[q + 1], data[q]))
            else:
                v = (data[src + x * bits // 8] >> (8 - bits - x * bits % 8)) & ((1 << bits) - 1)
                rgb = pal[v] if v < len(pal) else b'\x00\x00\x00'
            out += rgb + (b'\x00' if rgb == key else b'\xff')
    return w, abs(h), bytes(out)


# -- JPEG: the pictures of a mnemonic are often JPEG, and a grey box is not the mnemonic ---------------------------
_ZIGZAG = (0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5,
           12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21, 28,
           35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51,
           58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63)
_COS = tuple(tuple((0.35355339059327373 if u == 0 else 0.5) * math.cos((2 * x + 1) * u * math.pi / 16)
                   for x in range(8)) for u in range(8))


def _huff_table(counts, syms):
    """(length, code) → symbol, the canonical code of a DHT segment."""
    codes, code, k = {}, 0, 0
    for length in range(1, 17):
        for _ in range(counts[length - 1]):
            codes[(length, code)] = syms[k]
            k += 1
            code += 1
        code <<= 1
    return codes


class _Bits:
    """The entropy-coded stream: 0xFF00 is a stuffed 0xFF, a restart marker ends the run."""

    def __init__(self, data, pos):
        self.d, self.p, self.b, self.n = data, pos, 0, 0

    def bit(self):
        if self.n == 0:
            if self.p >= len(self.d):
                return 0
            c = self.d[self.p]
            if c == 0xFF:
                nxt = self.d[self.p + 1] if self.p + 1 < len(self.d) else 0
                if nxt == 0x00:
                    self.p += 2
                elif 0xD0 <= nxt <= 0xD7:
                    self.p += 2
                    return 0
                else:
                    self.p += 1
                    return 0
            else:
                self.p += 1
            self.b, self.n = c, 8
        self.n -= 1
        return (self.b >> self.n) & 1

    def bits(self, k):
        v = 0
        for _ in range(k):
            v = (v << 1) | self.bit()
        return v

    def huff(self, table):
        code = 0
        for length in range(1, 17):
            code = (code << 1) | self.bit()
            v = table.get((length, code))
            if v is not None:
                return v
        raise ValueError('bad huffman code')

    def align_restart(self):
        self.n = 0
        while self.p + 1 < len(self.d):
            if self.d[self.p] == 0xFF and 0xD0 <= self.d[self.p + 1] <= 0xD7:
                self.p += 2
                return
            self.p += 1


def _extend(v, k):
    return v - (1 << k) + 1 if k and v < (1 << (k - 1)) else v


def _idct(coef):
    """The 8×8 inverse DCT, separable, level-shifted to 0..255."""
    tmp = [0.0] * 64
    for v in range(8):
        row = coef[v * 8:(v + 1) * 8]
        for x in range(8):
            s = 0.0
            for u in range(8):
                if row[u]:
                    s += _COS[u][x] * row[u]
            tmp[v * 8 + x] = s
    out = [0] * 64
    for x in range(8):
        for y in range(8):
            s = 0.0
            for v in range(8):
                t = tmp[v * 8 + x]
                if t:
                    s += _COS[v][y] * t
            p = int(s + 128.5)
            out[y * 8 + x] = 0 if p < 0 else (255 if p > 255 else p)
    return out


def _block(bits, c, qt, huff):
    dct = [0] * 64
    t = bits.huff(huff[(0, c['dc'])])
    c['pred'] += _extend(bits.bits(t), t) if t else 0
    dct[0] = c['pred'] * qt[c['tq']][0]
    k = 1
    while k < 64:
        rs = bits.huff(huff[(1, c['ac'])])
        r, s = rs >> 4, rs & 15
        if s == 0:
            if r != 15:
                break
            k += 16
            continue
        k += r
        if k > 63:
            break
        dct[_ZIGZAG[k]] = _extend(bits.bits(s), s) * qt[c['tq']][k]
        k += 1
    return _idct(dct)


def _upsample(plane, pw, ph, W, H, ch, cv, hmax, vmax):
    """A component plane at full window size; subsampled chroma is interpolated, not replicated."""
    if ch == hmax and cv == vmax:
        return [plane[y * pw + x] for y in range(H) for x in range(W)]
    out = [0] * (W * H)
    for y in range(H):
        fy = (y + 0.5) * cv / vmax - 0.5
        y0 = int(math.floor(fy))
        ty = fy - y0
        y0 = 0 if y0 < 0 else (ph - 1 if y0 > ph - 1 else y0)
        y1 = 0 if y0 + 1 < 0 else (ph - 1 if y0 + 1 > ph - 1 else y0 + 1)
        for x in range(W):
            fx = (x + 0.5) * ch / hmax - 0.5
            x0 = int(math.floor(fx))
            tx = fx - x0
            x0 = 0 if x0 < 0 else (pw - 1 if x0 > pw - 1 else x0)
            x1 = 0 if x0 + 1 < 0 else (pw - 1 if x0 + 1 > pw - 1 else x0 + 1)
            a, b = plane[y0 * pw + x0], plane[y0 * pw + x1]
            c, d = plane[y1 * pw + x0], plane[y1 * pw + x1]
            top = a + (b - a) * tx
            out[y * W + x] = top + (c + (d - c) * tx - top) * ty
    return out


def _jpeg_scan(data, pos, frame, scomps, qt, huff, restart):
    comps = frame['comps']
    byid = {c['id']: c for c in comps}
    for sc in scomps:
        c = byid[sc['id']]
        c['dc'], c['ac'], c['pred'] = sc['dc'], sc['ac'], 0
    hmax = max(c['h'] for c in comps)
    vmax = max(c['v'] for c in comps)
    mcux = (frame['w'] + 8 * hmax - 1) // (8 * hmax)
    mcuy = (frame['h'] + 8 * vmax - 1) // (8 * vmax)
    for c in comps:
        c['pw'] = mcux * c['h'] * 8
        c['plane'] = [0] * (c['pw'] * mcuy * c['v'] * 8)
    bits = _Bits(data, pos)
    for m in range(mcux * mcuy):
        if restart and m and m % restart == 0:
            bits.align_restart()
            for c in comps:
                c['pred'] = 0
        for c in comps:
            for by in range(c['v']):
                for bx in range(c['h']):
                    blk = _block(bits, c, qt, huff)
                    x0 = ((m % mcux) * c['h'] + bx) * 8
                    y0 = ((m // mcux) * c['v'] + by) * 8
                    for y in range(8):
                        base = (y0 + y) * c['pw'] + x0
                        c['plane'][base:base + 8] = blk[y * 8:(y + 1) * 8]
    W, H = frame['w'], frame['h']
    full = [_upsample(c['plane'], c['pw'], mcuy * c['v'] * 8, W, H, c['h'], c['v'], hmax, vmax)
            for c in comps]
    out = bytearray(W * H * 4)
    if len(full) == 1:
        for i in range(W * H):
            v = full[0][i]
            v = 0 if v < 0 else (255 if v > 255 else int(v))
            q = 4 * i
            out[q] = out[q + 1] = out[q + 2] = v
            out[q + 3] = 255
        return W, H, bytes(out)
    yp, cbp, crp = full[0], full[1], full[2]
    for i in range(W * H):
        Y, cb, cr = yp[i], cbp[i] - 128, crp[i] - 128
        r = Y + 1.402 * cr
        g = Y - 0.344136 * cb - 0.714136 * cr
        b = Y + 1.772 * cb
        q = 4 * i
        out[q] = 0 if r < 0 else (255 if r > 255 else int(r))
        out[q + 1] = 0 if g < 0 else (255 if g > 255 else int(g))
        out[q + 2] = 0 if b < 0 else (255 if b > 255 else int(b))
        out[q + 3] = 255
    return W, H, bytes(out)


def decode_jpeg(data: bytes):
    """(w, h, RGBA) of a baseline JPEG; None for progressive, arithmetic or anything else not handled here."""
    if data[:2] != b'\xff\xd8':
        return None
    qt, huff, frame, restart, i, n = {}, {}, None, 0, 2, len(data)
    while i < n:
        if data[i] != 0xFF:
            i += 1
            continue
        while i < n and data[i] == 0xFF:
            i += 1
        if i >= n:
            break
        m = data[i]
        i += 1
        if m in (0xD8, 0xD9, 0x01) or 0xD0 <= m <= 0xD7:
            continue
        if i + 2 > n:
            break
        ln = struct.unpack_from('>H', data, i)[0]
        seg = data[i + 2:i + ln]
        i += ln
        if m == 0xDB:
            k = 0
            while k < len(seg):
                pq, tq = seg[k] >> 4, seg[k] & 15
                k += 1
                if pq == 0:
                    qt[tq] = list(seg[k:k + 64])
                    k += 64
                else:
                    qt[tq] = [struct.unpack_from('>H', seg, k + 2 * j)[0] for j in range(64)]
                    k += 128
        elif m == 0xC4:
            k = 0
            while k < len(seg):
                tc, th = seg[k] >> 4, seg[k] & 15
                k += 1
                counts = list(seg[k:k + 16])
                k += 16
                total = sum(counts)
                huff[(tc, th)] = _huff_table(counts, list(seg[k:k + total]))
                k += total
        elif m in (0xC0, 0xC1):
            h, w = struct.unpack_from('>HH', seg, 1)
            comps = [{'id': seg[6 + 3 * c], 'h': seg[7 + 3 * c] >> 4, 'v': seg[7 + 3 * c] & 15,
                      'tq': seg[8 + 3 * c]} for c in range(seg[5])]
            frame = {'w': w, 'h': h, 'comps': comps}
        elif m in (0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            return None
        elif m == 0xDD:
            restart = struct.unpack_from('>H', seg, 0)[0]
        elif m == 0xDA:
            if frame is None:
                return None
            scomps = [{'id': seg[1 + 2 * c], 'dc': seg[2 + 2 * c] >> 4, 'ac': seg[2 + 2 * c] & 15}
                      for c in range(seg[0])]
            try:
                return _jpeg_scan(data, i, frame, scomps, qt, huff, restart)
            except (ValueError, IndexError, KeyError, struct.error):
                return None
    return None


def picture(p, guid: str, transparent=None):
    """(w, h, RGBA) of a library picture, None if it cannot be decoded here (progressive JPEG, GIF)."""
    lib, _ = p._library()
    try:
        o, n = lib[bytes.fromhex(guid)]
    except (KeyError, ValueError):
        return None
    data = p.payload[o:o + n]
    try:
        if data[:2] == b'BM':
            return decode_bmp(data, transparent)
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            return decode_png(data)
        if data[:3] == b'\xff\xd8\xff':
            return decode_jpeg(data)
    except (ValueError, IndexError, KeyError, struct.error, zlib.error):
        return None
    return None


# -- labels --------------------------------------------------------------------------------------------------------
def _font(name):
    bold = 'bold' in str(name or '').lower()
    return ttf.find(str(name or '').replace('Bold', '').replace('bold', '').strip() or 'Droid Sans Fallback', bold)


def _draw_text(cv, lab, box, whole, scale, clip):
    text = str(lab.get('text') or '')
    if not text.strip():
        return
    f = _font(lab.get('font'))
    px = max(1.0, float(lab.get('size') or 12) * FONT * scale)
    rgb = _hex(lab.get('color'))
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    lh = px * LINE
    l, t, r, _ = box
    if f is None:       # no fonts at all: grey bars where the text is
        for k, line in enumerate(lines):
            w = len(line) * px * 0.55
            x = l if whole else lab['x'] * scale
            cv.fill(x, t + k * lh + px * 0.3, x + w, t + k * lh + px * 0.9, rgb, 0.5)
        return
    widths = [f.width(line, px) for line in lines]
    block = (r - l + 1) if whole else max(widths or [0])
    x0 = l if whole else lab['x'] * scale
    y0 = t if whole else lab['y'] * scale
    asc, desc = f.ascent * px / f.upm, -f.descent * px / f.upm
    align = lab.get('align') or 'left'
    for k, line in enumerate(lines):
        if not line.strip():
            continue
        w, h, base, a = f.render(line, px)
        shift = {'center': (block - widths[k]) / 2, 'right': block - widths[k]}.get(align, 0)
        top = y0 + k * lh + (lh - (asc + desc)) / 2 + asc - base
        cv.mask((w, h, a), x0 + shift - 1, top, rgb, clip)
        if getattr(f, 'fake_bold', False):
            cv.mask((w, h, a), x0 + shift, top, rgb, clip)


def _light(c) -> bool:
    r, g, b = _hex(c)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.62


def render(p, window, scale: float = 1.0, marks: bool = False, states=None) -> bytes:
    """PNG bytes of the window (scale 0.1-2). marks — the index of every object in a corner, to name them."""
    sc = p.scene(window)
    if states is None:
        states = {}
    if not isinstance(states, dict):
        raise ValueError('states must map object indices to state indices')
    chosen = {}
    for key, state in states.items():
        if not isinstance(key, str) or not key.isascii() or not key.isdigit() or str(int(key)) != key:
            raise ValueError('state object index must be a canonical nonnegative integer string')
        index = int(key)
        if index >= len(sc['objects']) or not isinstance(state, int) or isinstance(state, bool) or state < 0:
            raise ValueError('invalid object or state index')
        pics = sc['objects'][index].get('picture') or []
        if state >= len(pics):
            raise ValueError(f'object #{index} has no picture state {state}')
        chosen[index] = state
    W, H = sc['window']['width'], sc['window']['height']
    scale = max(0.1, min(2.0, float(scale or 1)))
    cw, ch = max(1, int(W * scale)), max(1, int(H * scale))
    cv = Canvas(cw, ch, _hex(sc['window']['background'], (0, 0, 0)))
    pics = {}
    for o in sc['objects']:
        if o['kind'] == 'Window' or not o.get('bbox'):
            continue
        l, t, r, b = (v * scale for v in o['bbox'])
        if r < 0 or b < 0 or l >= cw or t >= ch:
            continue
        kind = o['kind']
        if kind == 'Line':
            cv.line(int(l), int(t), int(r), int(b), _hex(o.get('frame') or o.get('fill')),
                    max(1, int((o.get('frame_width') or 1) * scale)))
        elif kind in ('Rect', 'Text') or kind.startswith('draw_'):
            if o.get('fill'):
                cv.fill(l, t, r, b, _hex(o['fill']))
            if kind != 'Text' and o.get('frame') and (o.get('frame_width') or 0) > 0:
                cv.frame(l, t, r, b, _hex(o['frame']), max(1, int(o['frame_width'] * scale)))
        state = chosen.get(o['index'], o.get('state') or 0)
        pic = (o.get('picture') or [None])[state]
        labels = o.get('labels') or []
        if o['index'] in chosen and len(labels) > 1:
            lab = labels[state] if state < len(labels) and str(labels[state].get('text') or '') else None
        else:
            lab = next((x for x in labels if str(x.get('text') or '') != ''), None)
        if pic:
            key = pic['image'] + (pic['transparent'] or '')
            if key not in pics:
                pics[key] = picture(p, pic['image'], pic['transparent'])
            if pics[key]:
                cv.image(pics[key], l, t, r, b)
            else:   # a picture this renderer does not decode (progressive JPEG, GIF): a light box
                cv.fill(l, t, r, b, (128, 128, 128), 0.35)
                cv.frame(l, t, r, b, (200, 200, 200), 1)
        elif not o.get('shape') and kind != 'Line' and kind not in ('Rect', 'Text') and not kind.startswith('draw_') \
                and (o.get('fill') or o.get('frame')):     # a widget without a picture / shape: a plain box
            if o.get('fill'):
                cv.fill(l, t, r, b, _hex(o['fill']))
            if o.get('frame'):
                cv.frame(l, t, r, b, _hex(o['frame']), max(1, int((o.get('frame_width') or 1) * scale)))
        elif o.get('shape'):
            if kind in FIELD:
                cv.fill(l, t, r, b, (255, 255, 255))
                cv.frame(l, t, r, b, (112, 112, 112), 1)
            elif kind in LAMP and not lab and 0.6 < (r - l + 1) / max(1, b - t + 1) < 1.6:
                cv.ellipse(l, t, r, b, (190, 190, 190), (85, 85, 85))
            elif kind in LAMP:      # a lamp with a text or a long one: a plate, not a round lamp
                cv.gradient(l, t, r, b, (246, 246, 246), (222, 222, 222))
                cv.frame(l, t, r, b, (138, 138, 138), 1)
            elif lab and _light(lab.get('color')):
                cv.gradient(l, t, r, b, (93, 110, 128), (46, 58, 71))
                cv.frame(l, t, r, b, (28, 36, 44), 1)
            else:
                cv.gradient(l, t, r, b, (251, 251, 251), (210, 210, 210))
                cv.frame(l, t, r, b, (111, 111, 111), 1)
        if lab:
            whole = kind == 'Text'
            _draw_text(cv, lab, (l, t, r, b), whole, scale, (0, 0, cw - 1, ch - 1))
    if marks:
        f = ttf.find('Arial') or ttf.find('')
        for o in sc['objects']:
            if o['kind'] == 'Window' or not o.get('bbox'):
                continue
            l, t = o['bbox'][0] * scale, o['bbox'][1] * scale
            s = str(o['index'])
            if f:
                w, h, base, a = f.render(s, 11)
                cv.fill(l, t, l + w, t + 12, (200, 30, 30))
                cv.mask((w, h, a), l, t + 9 - base, (255, 255, 255))
    return cv.png()
