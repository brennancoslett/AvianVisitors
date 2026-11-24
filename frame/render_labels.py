"""Bird names for render_local.py: a Python port of the frontend's label engine.

apt.js writes each bird's name along a run of the bird's own outline (a back,
a belly line, a wing's leading edge), carrying it on past the run where the
name is longer than the edge, breaking it over two lines where that sits
closer, and falling back to a line drawn tangent to the silhouette. The
packer then reserves the lettering's footprint. This module ports that
engine function for function - outline(), pickEdge(), planLabel() and their
helpers - with the frame's capture-time settings, so render_local.py names
birds where the browser does. Comments here are brief; the reasoning behind
every constant is in apt.js next to the original.

Text is measured in Caveat at weight 600, as the page's canvas measures it,
and drawn at 400, the weight the frame's capture CSS sets.
"""
from __future__ import annotations

import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont, features

HERE = os.path.dirname(os.path.abspath(__file__))
HAND = os.path.join(HERE, "..", "avian", "frontend", "fonts", "Caveat.ttf")

LABEL_GAP = 3
LABEL_NEAR = 2
LABEL_MIN_PX = 11          # shoot.py rewrites apt.js's 9 to the frame's label_min_px
LABEL_MAX_PX = 21
LABEL_ASC = 0.80
LABEL_DESC = 0.25
LABEL_INK = 0.0025
LABEL_BOW = 0.06
LABEL_DEG = 55
LABEL_EXT = 3.0
LABEL_RUN = 1.25
LABEL_TAN = 30
LABEL_REACH = 1.15
LABEL_ADHERE = 0.9
LABEL_LEAN = 0.5
LABEL_BEND = 0.5
LABEL_ATT = 4
LABEL_HOLD = 0.4
LABEL_LEAD = 1.05
LABEL_EVEN = 0.40
LABEL_KEEP = 0.94
LABEL_SNUG = 0.85
LABEL_ROOM = 0.25
LABEL_BESIDE = 2.0
LABEL_LIFT = [0, 0.02, 0.06, 0.18, 0.45]
LABEL_SEAT = 0.35
LABEL_LEDGE = 0.36
LABEL_CURL = 68
LABEL_CHUNK = 4


def jround(x):
    """JavaScript Math.round: halves go up, not to even."""
    return math.floor(x + 0.5)


def hypot(x, y):
    return math.hypot(x, y)


# --- text metrics ---------------------------------------------------------------
_em_cache = {}
_fonts = {}


def _hand(px, weight):
    key = (px, weight)
    if key not in _fonts:
        engine = ImageFont.Layout.RAQM if features.check("raqm") else ImageFont.Layout.BASIC
        f = ImageFont.truetype(HAND, px, layout_engine=engine)
        f.set_variation_by_axes([weight])
        _fonts[key] = f
    return _fonts[key]


_metrics = None


def _table():
    global _metrics
    if _metrics is None:
        import json
        path = os.path.join(HERE, "label_metrics.json")
        try:
            with open(path, encoding="utf-8") as f:
                _metrics = json.load(f)
        except OSError:
            _metrics = {"words": {}, "space600": None, "space400": None, "upem": 1000}
    return _metrics


def _hb(weight, scale):
    """A live HarfBuzz font when uharfbuzz is installed, else None."""
    key = ("hb", weight, scale)
    if os.environ.get("AVIAN_NO_HARFBUZZ"):   # exercise the precomputed table, as on a Pi
        return None
    if key not in _fonts:
        try:
            import uharfbuzz as hb
            f = hb.Font(hb.Face(hb.Blob.from_file_path(HAND)))
            f.scale = (scale, scale)
            f.set_variations({"wght": weight})
            _fonts[key] = f
        except Exception:
            _fonts[key] = None
    return _fonts[key]


def _hb_shape(font, text):
    import uharfbuzz as hb
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, {})
    return buf.glyph_infos, buf.glyph_positions


def _word600(word):
    """Chrome's width of one word at 600 / 100 px: shaped, each glyph rounded."""
    hb = _hb(600, 100 * 64)
    if hb is not None:
        return sum(math.floor(p.x_advance / 64 + 0.5) for p in _hb_shape(hb, word)[1])
    hit = _table()["words"].get(word)
    if hit:
        return hit[0]
    f = _hand(100, 600)   # unknown word, no HarfBuzz: unshaped, so a little off
    return sum(math.floor(f.getlength(ch) + 0.5) for ch in word)


def text_em(s):
    """canvas measureText('600 100px Hand') / 100: words shaped separately."""
    if s not in _em_cache:
        words = s.split(" ")
        space = _table().get("space600") or _word600(" ")
        _em_cache[s] = (sum(_word600(w) for w in words if w) + space * (len(words) - 1)) / 100
    return _em_cache[s]


def _glyphs400(text):
    """[(chars, stylistic set, advance in em)] for drawing at weight 400."""
    out = []
    upem = _table().get("upem") or 1000
    hb = _hb(400, upem)
    for wi, word in enumerate(text.split(" ")):
        if wi:
            sp = _table().get("space400")
            out.append((" ", "", (sp if sp is not None else _hand(1000, 400).getlength(" ")) / upem))
        if not word:
            continue
        if hb is not None:
            infos, pos = _hb_shape(hb, word)
            clusters = [i.cluster for i in infos]
            for info, p in zip(infos, pos):
                end = min([c for c in clusters if c > info.cluster], default=len(word))
                name = hb.glyph_to_string(info.codepoint)
                tail = name.rsplit(".", 1)[1] if "." in name else ""
                out.append((word[info.cluster:end], tail if tail.startswith("ss") else "", p.x_advance / upem))
            continue
        hit = _table()["words"].get(word)
        if hit:
            out.extend((ch, feat, adv / upem) for ch, feat, adv in hit[1])
        else:
            f = _hand(1000, 400)
            out.extend((ch, "", f.getlength(ch) / 1000) for ch in word)
    return out


# --- outline ----------------------------------------------------------------------
class Outline:
    def __init__(self, pts, w, h, grid, cells):
        self.pts, self.w, self.h, self.grid, self.cells = pts, w, h, grid, cells

    def at(self, x, y):
        if x < 0 or y < 0 or x >= self.w or y >= self.h:
            return 0
        return int(self.grid[y, x])

    def at_many(self, xs, ys):
        """Vectorised at() for integer arrays."""
        ok = (xs >= 0) & (ys >= 0) & (xs < self.w) & (ys < self.h)
        out = np.zeros(xs.shape, dtype=bool)
        out[ok] = self.grid[ys[ok], xs[ok]]
        return out


_outline_cache = {}


def outline(slug, mask):
    """Moore boundary walk of the silhouette, resampled every 1.2 cells and
    lightly smoothed. Cached per slug (it is in mask space)."""
    if slug in _outline_cache:
        return _outline_cache[slug]
    w, h, g = mask.w, mask.h, mask.bits
    at = lambda x, y: 0 if (x < 0 or y < 0 or x >= w or y >= h) else g[y, x]  # noqa: E731
    ys, xs = np.nonzero(g)
    if not len(ys):
        _outline_cache[slug] = False
        return False
    sy0 = int(ys.min())
    sx = int(xs[ys == sy0].min())
    sy = sy0
    NB = [(-1, 0), (-1, -1), (0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1)]
    idx = {d: k for k, d in enumerate(NB)}
    pts = [(sx, sy)]
    bx, by, cx, cy, guard = sx, sy, sx - 1, sy, 0
    while guard < 20000:
        guard += 1
        k0 = idx.get((cx - bx, cy - by), 0)
        found = False
        for t in range(1, 9):
            j = (k0 + t) % 8
            nx, ny = bx + NB[j][0], by + NB[j][1]
            if at(nx, ny):
                cx, cy = bx + NB[(j + 7) % 8][0], by + NB[(j + 7) % 8][1]
                bx, by, found = nx, ny, True
                break
        if not found:
            break
        if bx == sx and by == sy and len(pts) > 2:
            break
        pts.append((bx, by))
    if len(pts) < 20:
        _outline_cache[slug] = False
        return False
    rs, acc = [pts[0]], 0.0
    for i in range(1, len(pts)):
        acc += hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
        if acc >= 1.2:
            rs.append(pts[i])
            acc = 0.0
    n = len(rs)
    sm = []
    for i in range(n):
        ax = ay = 0
        for d in range(-2, 3):
            q = rs[(i + d + n) % n]
            ax += q[0]
            ay += q[1]
        sm.append((ax / 5, ay / 5))
    cells = np.argwhere(g)[:, ::-1]   # (x, y) rows in row-major order, like apt.js
    out = Outline(sm, w, h, g.astype(bool), cells)
    _outline_cache[slug] = out
    return out


# --- run scoring --------------------------------------------------------------
def edge_quality(cover, straight, tilt):
    s = (straight - 0.85) / 0.12
    s = 0 if s < 0 else 1 if s > 1 else s
    lv = 1 - (1 - LABEL_LEAN) * tilt / LABEL_DEG
    if lv < 0:
        lv = 0
    return (1 if cover > 1 else cover) * s * lv


def ink_depth(out, W, H, p, tx, ty, cap):
    nx, ny = ty, -tx
    for s in (1, -1):
        if not out.at(jround((p[0] + nx * s * 1.5) / W * out.w), jround((p[1] + ny * s * 1.5) / H * out.h)):
            continue
        miss = 0
        d = 1.5
        while d <= cap:
            if out.at(jround((p[0] + nx * s * d) / W * out.w), jround((p[1] + ny * s * d) / H * out.h)):
                miss = 0
            else:
                miss += 1
                if miss > 4:
                    break
            d += 0.5
        return d - miss * 0.5
    return 0


def pick_edge(out, W, H, name_em, fit_em, max_px, min_px):  # noqa: C901 - mirrors apt.js pickEdge()
    P = [(q[0] / out.w * W, q[1] / out.h * H) for q in out.pts]
    n = len(P)
    seg = [hypot(P[(i + 1) % n][0] - P[i][0], P[(i + 1) % n][1] - P[i][1]) for i in range(n)]
    hoop = 0.0
    for v in seg:
        hoop += v
    half = max(3, 0.45 * max_px) / 2 / (hoop / n)
    arm = max(1, min(jround(n / 4), jround(half)))
    lean = []
    for i in range(n):
        q0, q1 = P[(i - arm + n) % n], P[(i + arm) % n]
        lv = abs(math.atan2(q1[1] - q0[1], q1[0] - q0[0]) * 180 / math.pi)
        lean.append(180 - lv if lv > 90 else lv)
    slack, min_run = 2 * LABEL_EXT, LABEL_RUN * min_px
    slot = max(1, jround(n * 0.025))
    pot = {}
    limit = n * 0.62
    for i in range(n):
        ln, tilt = 0.0, lean[i]
        L = 0
        while L < limit:
            ln += seg[(i + L) % n]
            if lean[(i + L) % n] > tilt:
                tilt = lean[(i + L) % n]
            if tilt >= LABEL_DEG:
                break
            if L < 3:
                L += 1
                continue
            a0, a1 = P[i], P[(i + L) % n]
            cx, cy = a1[0] - a0[0], a1[1] - a0[1]
            chord = hypot(cx, cy)
            if chord < ln * 0.5:
                break
            if chord < ln * 0.85 or ln < min_run:
                L += 1
                continue
            px = max_px if fit_em <= slack else min(max_px, math.floor(ln / (fit_em - slack)))
            if px < LABEL_MIN_PX:
                L += 1
                continue
            cover = ln / (name_em * px)
            q = edge_quality(cover, chord / ln, tilt)
            if q <= 0:
                L += 1
                continue
            g = int(i / slot)
            if g in pot and q <= pot[g]["q"]:
                L += 1
                continue
            bow = 0.0
            for k in (1, 2, 3):
                m = P[(i + jround(L * k / 4)) % n]
                t = ((m[0] - a0[0]) * cx + (m[1] - a0[1]) * cy) / (chord * chord)
                d = hypot(m[0] - a0[0] - cx * t, m[1] - a0[1] - cy * t) / chord
                if d > bow:
                    bow = d
            if bow > LABEL_BOW:
                L += 1
                continue
            bend = 1 - (1 - LABEL_BEND) * bow / LABEL_BOW
            pot[g] = {"q": q, "i": i, "L": L, "len": ln, "deg": tilt, "cover": cover,
                      "shape": bend * edge_quality(1, 1, tilt)}
            L += 1
    lst = [pot[k] for k in sorted(pot)]

    def wrap(v):
        return ((v % n) + n) % n

    def follow(i0, L0, ceil, cap):
        a, b, ln, fwd, back = i0, i0 + L0, 0.0, 0.0, 0.0
        for k in range(L0 + 1):
            ln += seg[wrap(i0 + k)]
        while ln < cap:
            ok_f, ok_b = lean[wrap(b + 1)] <= ceil, lean[wrap(a - 1)] <= ceil
            if not ok_f and not ok_b:
                break
            if ok_f and (not ok_b or fwd <= back):
                s = seg[wrap(b)]
                b += 1
                fwd += s
            else:
                a -= 1
                s = seg[wrap(a)]
                back += s
            ln += s
        return {"pts": [P[wrap(k)] for k in range(a, b + 1)], "len": ln}

    lst.sort(key=lambda c: -c["q"])
    lst = lst[:16]
    for c in lst:
        c["run"] = [P[(c["i"] + m) % n] for m in range(c["L"] + 1)]
        c["ledge"] = follow(c["i"], c["L"], LABEL_DEG, name_em * max_px)["len"]
        c["grow"] = (lambda c: lambda cap, ceil: follow(c["i"], c["L"], ceil, cap))(c)
    dep, cap, deep = {}, (W if W > H else H), 0

    def dep_at(idx):
        if idx not in dep:
            a, b = P[(idx - 1 + n) % n], P[(idx + 1) % n]
            dx, dy = b[0] - a[0], b[1] - a[1]
            dL = hypot(dx, dy) or 1
            dep[idx] = ink_depth(out, W, H, P[idx], dx / dL, dy / dL, cap)
        return dep[idx]

    for c in lst:
        ds = sorted(dep_at((c["i"] + m) % n) for m in range(c["L"] + 1))
        c["seat"] = ds[len(ds) >> 1]
        if c["seat"] > deep:
            deep = c["seat"]
    for c in lst:
        sit = c["seat"] / (LABEL_SEAT * deep) if deep > 0 else 1
        c["shape"] *= 1 if sit > 1 else sit
    return lst


# --- geometry of a set line --------------------------------------------------------
def band_ink(out, pts, px, W, H):
    res = max(out.w / W, out.h / H)
    rows = max(11, math.ceil((LABEL_ASC + LABEL_DESC) * px * res) + 1)
    step = min(1, 1 / (2 * res))
    e = np.array([-LABEL_DESC + (LABEL_ASC + LABEL_DESC) * r / (rows - 1) for r in range(rows)])
    hits = []
    for i in range(1, len(pts)):
        ax, ay = pts[i - 1]
        dx, dy = pts[i][0] - ax, pts[i][1] - ay
        d = hypot(dx, dy)
        if d < 1e-6:
            continue
        ux, uy = dx / d, dy / d
        cnt = max(1, jround(d / step))
        j = np.arange(cnt, dtype=np.float64)
        qx = (ax + dx * j / cnt)[:, None]
        qy = (ay + dy * j / cnt)[:, None]
        X = np.floor((qx + uy * e * px) / W * out.w + 0.5).astype(np.int64)
        Y = np.floor((qy - ux * e * px) / H * out.h + 0.5).astype(np.int64)
        hits.extend((out.at_many(X, Y).sum(axis=1) / rows).tolist())
    if not hits:
        return 1
    win = max(2, jround(px * 0.45 / step))
    if len(hits) <= win:
        s = 0.0
        for v in hits:
            s += v
        return s / len(hits)
    s, worst = 0.0, 0.0
    for i, v in enumerate(hits):
        s += v
        if i >= win:
            s -= hits[i - win]
        if i >= win - 1 and s / win > worst:
            worst = s / win
        if worst > LABEL_INK:
            return worst
    return worst


def hug_share(out, pts, px, W, H, reach_em):
    reach = px * reach_em + LABEL_NEAR
    dvals = []
    d = 0
    while d <= reach:
        dvals.append(d)
        d += 2
    D = np.array(dvals, dtype=np.float64)[None, :]
    near = alln = 0
    for i in range(1, len(pts)):
        ax, ay = pts[i - 1]
        dx, dy = pts[i][0] - ax, pts[i][1] - ay
        L = hypot(dx, dy)
        if L < 1e-6:
            continue
        nx, ny = -dy / L, dx / L
        cnt = max(1, jround(L))
        j = np.arange(cnt, dtype=np.float64)
        x = (ax + dx * j / cnt)[:, None]
        y = (ay + dy * j / cnt)[:, None]
        alln += cnt
        a = out.at_many(np.floor((x + nx * D) / W * out.w + 0.5).astype(np.int64),
                        np.floor((y + ny * D) / H * out.h + 0.5).astype(np.int64))
        b = out.at_many(np.floor((x - nx * D) / W * out.w + 0.5).astype(np.int64),
                        np.floor((y - ny * D) / H * out.h + 0.5).astype(np.int64))
        near += int((a | b).any(axis=1).sum())
    return near / alln if alln else 0


def offset_run(run, out, W, H, px, lift):
    n = len(run)
    nx, ny, plus, minus, down = [], [], 0, 0, 0
    arc = 0.0
    for i in range(1, n):
        arc += hypot(run[i][0] - run[i - 1][0], run[i][1] - run[i - 1][1])
    win = max(2, jround(px * 0.6 * (n - 1) / (arc or 1)))
    for i in range(n):
        a, b = run[max(0, i - win)], run[min(n - 1, i + win)]
        vx, vy = -(b[1] - a[1]), (b[0] - a[0])
        L = hypot(vx, vy) or 1
        nx.append(vx / L)
        ny.append(vy / L)
        for d in (1, 2, 3):
            probe = d * px * 0.35
            if out.at(jround((run[i][0] + vx / L * probe) / W * out.w), jround((run[i][1] + vy / L * probe) / H * out.h)):
                plus += 1
            if out.at(jround((run[i][0] - vx / L * probe) / W * out.w), jround((run[i][1] - vy / L * probe) / H * out.h)):
                minus += 1
    side = 1 if plus <= minus else -1
    lean = 0.0
    for i in range(n):
        if ny[i] * side > down:
            down = ny[i] * side
        lean += ny[i] * side
    gap = LABEL_NEAR + px * (LABEL_DESC + (LABEL_ASC - LABEL_DESC) * down + (lift or 0))
    pts = [(run[i][0] + nx[i] * side * gap, run[i][1] + ny[i] * side * gap) for i in range(n)]
    return {"pts": pts, "under": lean > 0}


def arc_len(pts):
    total = 0.0
    for i in range(1, len(pts)):
        total += hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
    return total


def nudge(frm, toward, d):
    dx, dy = frm[0] - toward[0], frm[1] - toward[1]
    L = hypot(dx, dy) or 1
    return (frm[0] + dx / L * d, frm[1] + dy / L * d)


def centred_span(pts, want, toward=None):
    seg, total = [], 0.0
    for i in range(1, len(pts)):
        d = hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
        seg.append(d)
        total += d
    if total <= 0:
        return pts

    def on(t):
        if t <= 0:
            return pts[0]
        acc = 0.0
        for k in range(len(seg)):
            if acc + seg[k] >= t:
                f = (t - acc) / seg[k]
                return (pts[k][0] + (pts[k + 1][0] - pts[k][0]) * f, pts[k][1] + (pts[k + 1][1] - pts[k][1]) * f)
            acc += seg[k]
        return pts[-1]

    head, tail = pts[0], pts[-1]
    cx, cy = tail[0] - head[0], tail[1] - head[1]
    cL = hypot(cx, cy) or 1

    def at(t):
        if t < 0:
            return (head[0] + cx / cL * t, head[1] + cy / cL * t)
        if t > total:
            return (tail[0] + cx / cL * (t - total), tail[1] + cy / cL * (t - total))
        return on(t)

    mid, half = total / 2, want / 2
    if toward and want > total:
        slack = (want - total) / 2
        u = ((toward[0] - head[0]) * cx + (toward[1] - head[1]) * cy) / (cL * cL) * total
        mid = max(mid - slack, min(mid + slack, u))
    steps = max(2, jround(want / 6))
    outp = [at(mid - half + want * i / steps) for i in range(steps + 1)]
    pad = (want - arc_len(outp)) / 2
    if pad > 0 and len(outp) > 1:
        outp[0] = nudge(outp[0], outp[1], pad)
        outp[-1] = nudge(outp[-1], outp[-2], pad)
    return outp


def stack(base, away, d, want):
    n = len(base)
    nx, ny = [], []
    for i in range(1, n):
        dx, dy = base[i][0] - base[i - 1][0], base[i][1] - base[i - 1][1]
        L = hypot(dx, dy) or 1
        nx.append(dy / L * away)
        ny.append(-dx / L * away)
    outp = []
    for i in range(n):
        j = i - 1 if i else 0
        k = i if i < n - 1 else n - 2
        mx, my = nx[j] + nx[k], ny[j] + ny[k]
        L = hypot(mx, my) or 1
        mx /= L
        my /= L
        m = mx * nx[j] + my * ny[j]
        if m < 0.5:
            m = 0.5
        outp.append((base[i][0] + mx * d / m, base[i][1] + my * d / m))
    pad = (want - arc_len(outp)) / 2
    if pad > 0 and n > 1:
        outp[0] = nudge(outp[0], outp[1], pad)
        outp[n - 1] = nudge(outp[n - 1], outp[n - 2], pad)
    return outp


def baseline_ok(pts, ceil=None):
    ax, ay = pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1]
    aL = hypot(ax, ay) or 1
    was = None
    if not ceil:
        ceil = LABEL_DEG
    for i in range(1, len(pts)):
        dx, dy = pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]
        if (dx * ax + dy * ay) / aL <= 0:
            return False
        d = math.atan2(dy, dx) * 180 / math.pi
        if was is not None and abs(d - was) >= LABEL_DEG:
            return False
        was = d
        if d > 90:
            d = 180 - d
        elif d < -90:
            d = -180 - d
        if abs(d) >= ceil:
            return False
    return True


def tangent_span(out, W, H, px, want):
    cells = out.cells
    sx, sy = W / out.w, H / out.h
    cxs, cys = cells[:, 0].astype(np.float64), cells[:, 1].astype(np.float64)
    cx = float(cxs.sum()) / len(cells) * sx
    cy = float(cys.sum()) / len(cells) * sy
    best = None
    for k in range(-LABEL_TAN, LABEL_TAN + 1, 5):
        th = k * math.pi / 180
        ux, uy = math.cos(th), math.sin(th)
        nx, ny = uy, -ux
        dd = cxs * sx * nx + cys * sy * ny
        hi, lo = float(dd.max()), float(dd.min())
        half = abs(nx) * sx / 2 + abs(ny) * sy / 2
        t = cx * ux + cy * uy
        for s in (0, 1):
            c = hi + half + LABEL_NEAR + LABEL_DESC * px if s else lo - half - LABEL_NEAR - LABEL_ASC * px
            pts = [(c * nx + (t - want / 2) * ux, c * ny + (t - want / 2) * uy),
                   (c * nx + (t + want / 2) * ux, c * ny + (t + want / 2) * uy)]
            score = hug_share(out, pts, px, W, H, 1.3) / (1 + abs(k) / LABEL_TAN)
            if not best or score > best["score"]:
                best = {"score": score, "deg": abs(k), "pts": pts}
    return best


def hug_rows(out, rows, px, W, H, reach_em):
    near = alln = 0.0
    for r in rows:
        L = arc_len(r["pts"])
        near += hug_share(out, r["pts"], px, W, H, reach_em) * L
        alln += L
    return near / alln if alln else 0


def break_name(name):
    lays = [{"rows": [name], "em": text_em(name)}]
    best = None
    for i in range(1, len(name) - 1):
        if name[i] != " ":
            continue
        a, b = name[:i], name[i + 1:]
        ea, eb = text_em(a), text_em(b)
        even = ea / eb if ea < eb else eb / ea
        if even < LABEL_EVEN:
            continue
        if not best or even > best["even"]:
            best = {"even": even, "rows": [a, b], "em": ea if ea > eb else eb}
    if best:
        lays.append({"rows": best["rows"], "em": best["em"]})
    return lays


def label_bounds(rows, px):
    x0 = y0 = math.inf
    x1 = y1 = -math.inf
    for r in rows:
        pts = r["pts"]
        b = sweep_box(pts, 0, len(pts) - 1, px, gap=False)
        x0, y0, x1, y1 = min(x0, b[0]), min(y0, b[1]), max(x1, b[2]), max(y1, b[3])
    return {"dx0": x0 - LABEL_GAP, "dx1": x1 + LABEL_GAP, "dy0": y0 - LABEL_GAP, "dy1": y1 + LABEL_GAP}


def sweep_box(pts, start, end, px, gap=True):
    x0 = y0 = math.inf
    x1 = y1 = -math.inf
    for i in range(start, end + 1):
        j = i - 1 if i else 1
        dx, dy = pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]
        if i == 0:
            dx, dy = -dx, -dy
        L = hypot(dx, dy) or 1
        nx, ny = dy / L, -dx / L
        for e in (-LABEL_DESC, LABEL_ASC):
            bx, by = pts[i][0] + nx * e * px, pts[i][1] + ny * e * px
            if bx < x0:
                x0 = bx
            if bx > x1:
                x1 = bx
            if by < y0:
                y0 = by
            if by > y1:
                y1 = by
    if not gap:
        return (x0, y0, x1, y1)
    return {"dx0": x0 - LABEL_GAP, "dx1": x1 + LABEL_GAP, "dy0": y0 - LABEL_GAP, "dy1": y1 + LABEL_GAP}


def label_cells(rows, px):
    cells = []
    for r in rows:
        pts = r["pts"]
        n = len(pts)
        if n == 0:
            continue
        if n == 1:
            cells.append(sweep_box(pts, 0, 0, px))
            continue
        for start in range(0, n - 1, LABEL_CHUNK):
            cells.append(sweep_box(pts, start, min(n - 1, start + LABEL_CHUNK), px))
    return cells


# --- planner --------------------------------------------------------------------
def plan_label(out, name, W, H, max_px):  # noqa: C901 - mirrors apt.js planLabel()
    lays = break_name(name)
    name_em = lays[0]["em"]
    floor_px = max(LABEL_MIN_PX, max_px - 4)
    cands = pick_edge(out, W, H, name_em, lays[-1]["em"], max_px, floor_px)
    mid = (W / 2, H / 2)
    slack = 2 * LABEL_EXT

    def spill(rows, px):
        b = label_bounds(rows, px)
        return max(-b["dx0"], -b["dy0"], b["dx1"] - W, b["dy1"] - H)

    def lost(rows, px):
        b = label_bounds(rows, px)
        ox = max(0, min(b["dx1"], W) - max(b["dx0"], 0))
        oy = max(0, min(b["dy1"], H) - max(b["dy0"], 0))
        return ((b["dx1"] - b["dx0"]) * (b["dy1"] - b["dy0"]) - ox * oy) / (W * H)

    def set_(c, px, lay, ceil=None):
        n = len(lay["rows"])
        want, wide = [], 0
        if not ceil:
            ceil = LABEL_DEG
        for r in range(n):
            want.append(text_em(lay["rows"][r]) * px + 4)
            if want[r] > want[wide]:
                wide = r
        ranks = [0] * n
        for lift in LABEL_LIFT:
            off = offset_run(c["run"], out, W, H, px, lift)
            for r in range(n):
                ranks[r] = r if off["under"] else n - 1 - r
            p = (offset_run(c["run"], out, W, H, px, lift + ranks[wide] * LABEL_LEAD)["pts"]
                 if ranks[wide] else off["pts"])
            if p[-1][0] < p[0][0]:
                p = p[::-1]
            arc = arc_len(p)
            away = -1 if off["under"] else 1

            def spread(base):
                rows = []
                for r2 in range(n):
                    d = (ranks[r2] - ranks[wide]) * LABEL_LEAD * px
                    core = base if r2 == wide else centred_span(base, want[r2])
                    rows.append({"pts": stack(core, away, d, want[r2]) if d else core, "text": lay["rows"][r2]})
                return rows

            tries = [spread(centred_span(p, want[wide]))]
            if want[wide] > arc:
                alt = spread(centred_span(p, want[wide], mid))
                if spill(alt, px) < spill(tries[0], px):
                    tries.insert(0, alt)
                else:
                    tries.append(alt)
            for rows in tries:
                good = True
                for r in range(n):
                    if not baseline_ok(rows[r]["pts"], ceil):
                        good = False
                        break
                    if band_ink(out, rows[r]["pts"], px, W, H) > LABEL_INK:
                        good = False
                        break
                    if hug_share(out, centred_span(rows[r]["pts"], min(want[r], arc)), px, W, H,
                                 1.3 + lift + ranks[r] * LABEL_LEAD) < LABEL_ADHERE:
                        good = False
                        break
                if good:
                    return {"rows": rows, "att": hug_rows(out, rows, px, W, H, LABEL_BESIDE), "lost": lost(rows, px)}
        return None

    def merit(c, lay, got):
        hold = LABEL_HOLD + (1 - LABEL_HOLD) * (1 if c["cover"] > 1 else c["cover"])
        return (c["shape"] * hold * math.pow(got["att"], LABEL_ATT) / (1 + got["lost"])
                * (LABEL_KEEP if len(lay["rows"]) > 1 else 1))

    def planned(c, lay, px, got):
        return {"px": px, "rows": got["rows"], "q": c["q"], "deg": c["deg"], "att": got["att"],
                "lost": got["lost"], "merit": merit(c, lay, got), "cand": c, "lay": lay}

    def fits(c, lay, px, broken):
        if c["len"] < LABEL_RUN * px:
            return False
        if broken and name_em * px <= W:
            return False
        return not (lay["em"] > slack and c["len"] < (lay["em"] - slack) * px)

    def hug(p):
        if not p or not p.get("cand") or not p["cand"].get("grow"):
            return p
        wide = 0
        for r in range(len(p["lay"]["rows"])):
            if text_em(p["lay"]["rows"][r]) > text_em(p["lay"]["rows"][wide]):
                wide = r
        want = text_em(p["lay"]["rows"][wide]) * p["px"] + 4
        if p["cand"]["ledge"] >= LABEL_LEDGE * want:
            return p
        ceil = LABEL_DEG
        while True:
            ceil += 1
            grown = p["cand"]["grow"](want, ceil)
            if not (grown["len"] < want and ceil < LABEL_CURL):
                break
        got = set_({"run": grown["pts"]}, p["px"], p["lay"], ceil)
        if (not got or got["att"] < p["att"]) and ceil < LABEL_CURL:
            ceil = LABEL_CURL
            got = set_({"run": p["cand"]["grow"](want, ceil)["pts"]}, p["px"], p["lay"], ceil)
        if not got or got["att"] < p["att"]:
            return p
        p["rows"], p["att"], p["lost"] = got["rows"], got["att"], got["lost"]
        return p

    def done(p):
        return p is not None and p["att"] >= LABEL_SNUG and p["lost"] <= LABEL_ROOM

    def bound(c):
        return c["shape"] * (LABEL_HOLD + (1 - LABEL_HOLD) * (1 if c["cover"] > 1 else c["cover"]))

    order = sorted(range(len(cands)), key=lambda k: -bound(cands[k]))
    for px in range(max_px, floor_px - 1, -1):
        best = None
        for c in cands:
            c["plain"] = False
        for c in cands:
            if not fits(c, lays[0], px, False):
                continue
            c["plain"] = True
            rode = set_(c, px, lays[0])
            if rode:
                best = planned(c, lays[0], px, rode)
                break
        if done(best):
            return hug(best)
        floor = min(LABEL_SNUG, best["att"]) if best else 0
        for k in order:
            if done(best):
                break
            c = cands[k]
            if best and bound(c) <= best["merit"]:
                break
            for j, lay in enumerate(lays):
                if not j and c["plain"]:
                    continue
                if not fits(c, lay, px, j > 0):
                    continue
                rode = set_(c, px, lay)
                if not rode or rode["att"] < floor:
                    continue
                if not best or merit(c, lay, rode) > best["merit"]:
                    best = planned(c, lay, px, rode)
        if best:
            return hug(best)
    tan_px = max(LABEL_MIN_PX, min(max_px, math.floor(LABEL_REACH * W / name_em)))
    tan = tangent_span(out, W, H, tan_px, name_em * tan_px + 4)
    return {"px": tan_px, "rows": [{"pts": tan["pts"], "text": name}], "q": 0, "deg": tan["deg"]} if tan else None


def label_cap(W, H):
    return jround(min(LABEL_MAX_PX, math.sqrt(W * H) * 0.16))


def assign_labels(tiles):
    """apt.js assignLabels(): plan every tile's name at its current size."""
    for t in tiles:
        t["labelBox"] = t["labelRows"] = t["labelCells"] = None
        t["labelPx"] = 0
        name = t["data"].get("com") or t["data"].get("sci")
        if not name:
            continue
        out = outline(t["slug"], t["mask"])
        if not out:
            continue
        max_px = max(LABEL_MIN_PX, label_cap(t["fullW"], t["fullH"]))
        plan = plan_label(out, name, t["fullW"], t["fullH"], max_px)
        if not plan:
            continue
        t["labelPx"] = plan["px"]
        t["labelRows"] = plan["rows"]
        t["labelBox"] = label_bounds(plan["rows"], plan["px"])
        t["labelCells"] = label_cells(plan["rows"], plan["px"])


# --- drawing ----------------------------------------------------------------------
def draw_labels(overlay, tiles, origin, dsf, color=(0, 0, 0)):
    """Set each name on its path the way SVG textPath does with
    startOffset=50% and text-anchor=middle: every glyph stands on the path at
    its own midpoint, turned to the local tangent; a glyph whose midpoint
    falls off either end of the path is not drawn."""
    ox, oy = origin
    for t in tiles:
        if not t.get("labelRows"):
            continue
        size = t["labelPx"] * dsf
        font = _hand(size, 400)
        for row in t["labelRows"]:
            pts = [((ox + t["x"] + p[0]) * dsf, (oy + t["y"] + p[1]) * dsf) for p in row["pts"]]
            _text_on_path(overlay, row["text"], pts, font, size, color)


def _text_on_path(overlay, text, pts, font, size, color):
    seg = [hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1)]
    total = sum(seg)
    if total <= 0:
        return
    glyphs = _glyphs400(text)
    advance = sum(g[2] for g in glyphs) * size
    pen = total / 2 - advance / 2
    box = int(size * 2.2)
    for chars, feat, adv_em in glyphs:
        adv = adv_em * size
        mid = pen + adv / 2
        pen += adv
        if chars == " " or mid < 0 or mid > total:
            continue
        acc, k = 0.0, 0
        while k < len(seg) - 1 and acc + seg[k] < mid:
            acc += seg[k]
            k += 1
        f = (mid - acc) / seg[k] if seg[k] else 0
        x = pts[k][0] + (pts[k + 1][0] - pts[k][0]) * f
        y = pts[k][1] + (pts[k + 1][1] - pts[k][1]) * f
        ang = math.degrees(math.atan2(pts[k + 1][1] - pts[k][1], pts[k + 1][0] - pts[k][0]))
        glyph = Image.new("RGBA", (box, box), (0, 0, 0, 0))
        kw = {"features": [feat]} if feat and features.check("raqm") else {}
        ImageDraw.Draw(glyph).text((box / 2, box / 2), chars, font=font, fill=(*color, 255), anchor="ms", **kw)
        glyph = glyph.rotate(-ang, resample=Image.Resampling.BICUBIC, center=(box / 2, box / 2))
        overlay.alpha_composite(glyph, (int(round(x - box / 2)), int(round(y - box / 2))))
