#!/usr/bin/env python3
"""Draw the collage without a browser, for a Pi that can't run one (Pi Zero W).

shoot.py renders the collage by screenshotting the real frontend in headless
Chromium, which needs a 64-bit Pi. This module ports the part of the
frontend that decides the picture - apt.js renderCollage() and maskPack(),
with the tunables shoot.py rewrites at capture time - to Python, and paints
the result with the same capture_art compositor shoot.py uses. Given the
same species and poses it places every tile where the browser does; the
title is set with Pillow in Liberation Serif, the face Chromium uses for it
on a Pi.

Bird names come from render_labels.py, a port of the frontend's label
engine. Not ported: the mic-mirroring mode.

    python3 render_local.py --zip 58501 --out frame.png
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import capture_art

HERE = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(HERE, "..", "avian", "frontend")
ILLUSTRATIONS = os.path.join(HERE, "..", "avian", "assets", "illustrations")
RAW_ILLUSTRATIONS = ("https://raw.githubusercontent.com/Twarner491/AvianVisitors/"
                     "avian-visitors/avian/assets/illustrations/")

# Page geometry, measured from the frontend in headless Chromium at shoot.py's
# BirdWeather settings (2x, mat 0.04, 17/39 px titles). "classic" is shoot.py's
# 600x800 page with the collage at 52vh, a wide box. "tall" is a 440 px page
# with the collage at 64vh: a box shaped like the 7.3" frame's window, so the
# cluster fills it instead of being scaled down to its width.
BOXES = {
    "classic": {"vw": 600, "collage": (24.0, 234.5, 552, 404), "eyebrow_top": 152.5, "headline_top": 175.5},
    "tall": {"vw": 440, "collage": (17.0, 186.5, 406, 500), "eyebrow_top": 104.5, "headline_top": 127.5},
}
VW, VH, DSF = 600, 800, 2
COLLAGE_X, COLLAGE_Y, COLLAGE_W, COLLAGE_H = BOXES["classic"]["collage"]
PAPER = (252, 252, 251)
EYEBROW = {"top": 152.5 + 1.5, "box": 17.0, "line": 20.74, "px": 17, "spacing": 1.02, "color": (74, 63, 49)}
HEADLINE = {"top": 175.5, "box": 39.0, "line": 39.0, "px": 39, "spacing": 2.34, "color": (26, 22, 18)}
EMPTY = {"px": 18, "spacing": 2.16, "line": 25.2, "color": (36, 36, 36), "gap": 28}
SHADOW = {"color": [26, 22, 18, round(0.10 * 255)], "offset": [0, 2 * DSF], "blur": 6 * DSF}

# apt.js constants, with shoot.py's BirdWeather capture-time rewrites.
GRID_STRIDE = 4
FLY_PROB = 0.15
X_BIAS, Y_BIAS, PAD = 1.0, 1.2, 1
COUNT_EXP = 1.0
SMALL_FLOOR = 0.04


def jsum(values):
    """Left-to-right float addition, as JavaScript's reduce does. Python 3.12+
    sum() compensates rounding, which changes the last bit - and the packer has
    comparisons between mathematically equal values that the last bit decides."""
    acc = 0.0
    for v in values:
        acc += v
    return acc


def slugify(sci):
    import re
    return re.sub(r"[^a-z0-9]+", "-", sci.lower()).strip("-")


def tuning(n):
    return {
        "budget": 0.46 if n <= 4 else 0.40 if n <= 12 else 0.34 if n <= 24 else 0.28,
        "min_area": 0.0100 if n <= 8 else 0.0075 if n <= 20 else 0.0055,
    }


class Mask:
    """A silhouette as horizontal runs of set cells: the union of the runs'
    grid ranges equals the union of the per-cell ranges apt.js tests, so
    collisions come out identical with far fewer rectangles."""

    def __init__(self, rec):
        self.w, self.h = int(rec["w"]), int(rec["h"])
        raw = np.frombuffer(base64.b64decode(rec["bits"]), dtype=np.uint8)
        bits = np.unpackbits(raw)[: self.w * self.h].reshape(self.h, self.w)
        self.bits = bits
        runs = []
        for y in range(self.h):
            row = np.concatenate(([0], bits[y], [0])).astype(np.int8)
            d = np.diff(row)
            for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):
                runs.append((a, b, y))          # cells a..b-1 in row y
        r = np.array(runs, dtype=np.float64).reshape(-1, 3)
        self.xa, self.xb, self.y = r[:, 0], r[:, 1], r[:, 2]   # xb is exclusive (= last + 1)


class Packer:
    """apt.js maskPack(): spiral each tile outward from the centre, largest
    first, keeping the free position nearest the cluster's centre of mass."""

    def __init__(self, W, H):
        self.W, self.H = W, H
        self.GW = math.ceil(W / GRID_STRIDE) + 2
        self.GH = math.ceil(H / GRID_STRIDE) + 2

    def _ranges(self, t, tx, ty):
        """Grid ranges of every run for tile positions tx, ty (arrays, one per
        candidate): x0, y0, x1, y1 shaped (candidates, runs)."""
        m = t["mask"]
        sx, sy = t["fullW"] / m.w, t["fullH"] / m.h
        tx = np.asarray(tx, dtype=np.float64)[:, None]
        ty = np.asarray(ty, dtype=np.float64)[:, None]
        x0 = np.trunc((tx + m.xa * sx) / GRID_STRIDE)
        x1 = np.trunc((tx + m.xb * sx) / GRID_STRIDE)
        y0 = np.trunc((ty + m.y * sy) / GRID_STRIDE)
        y1 = np.trunc((ty + (m.y + 1) * sy) / GRID_STRIDE)
        x0, y0 = np.maximum(x0, 0), np.maximum(y0, 0)
        x1, y1 = np.minimum(x1, self.GW - 1), np.minimum(y1, self.GH - 1)
        return x0.astype(np.int64), y0.astype(np.int64), x1.astype(np.int64), y1.astype(np.int64)

    def _label_ranges(self, t, tx, ty):
        """Grid ranges of the label's sub-boxes (apt.js boxRange), same shape as _ranges."""
        lc = t.get("labelCells")
        tx = np.asarray(tx, dtype=np.float64)[:, None]
        ty = np.asarray(ty, dtype=np.float64)[:, None]
        b = np.array([[c["dx0"], c["dy0"], c["dx1"], c["dy1"]] for c in lc], dtype=np.float64)
        x0 = np.maximum(np.trunc((tx + b[:, 0]) / GRID_STRIDE), 0)
        y0 = np.maximum(np.trunc((ty + b[:, 1]) / GRID_STRIDE), 0)
        x1 = np.minimum(np.trunc((tx + b[:, 2]) / GRID_STRIDE), self.GW - 1)
        y1 = np.minimum(np.trunc((ty + b[:, 3]) / GRID_STRIDE), self.GH - 1)
        return x0.astype(np.int64), y0.astype(np.int64), x1.astype(np.int64), y1.astype(np.int64)

    def _hit(self, x0, y0, x1, y1):
        S = self.sat
        ok = (x1 >= x0) & (y1 >= y0)
        x1c, y1c = np.maximum(x1, x0 - 1), np.maximum(y1, y0 - 1)
        s = S[y1c + 1, x1c + 1] - S[y0, x1c + 1] - S[y1c + 1, x0] + S[y0, x0]
        return ((s > 0) & ok).any(axis=1)

    def _collides(self, t, tx, ty):
        hit = self._hit(*self._ranges(t, tx, ty))
        if t.get("labelCells"):
            hit |= self._hit(*self._label_ranges(t, tx, ty))
        return hit

    def _fill(self, x0, y0, x1, y1, pad):
        for a, b, c, d in zip(x0, y0, x1, y1):
            ya, yb = max(b - pad, 0), min(d + pad, self.GH - 1)
            xa, xb = max(a - pad, 0), min(c + pad, self.GW - 1)
            if yb >= ya and xb >= xa:
                self.grid[ya:yb + 1, xa:xb + 1] = 1

    def _stamp(self, t, tx, ty):
        self._fill(*(a[0] for a in self._ranges(t, [tx], [ty])), PAD)
        if t.get("labelCells"):   # lighter dilation around the lettering (COLLAGE_LABEL_PAD)
            self._fill(*(a[0] for a in self._label_ranges(t, [tx], [ty])), min(PAD, 1))
        self.sat = np.zeros((self.GH + 1, self.GW + 1), dtype=np.int32)
        self.sat[1:, 1:] = self.grid.cumsum(0).cumsum(1)

    def pack(self, tiles):
        W, H = self.W, self.H
        self.grid = np.zeros((self.GH, self.GW), dtype=np.uint8)
        self.sat = np.zeros((self.GH + 1, self.GW + 1), dtype=np.int32)
        cx, cy = W / 2, H / 2
        tiles.sort(key=lambda t: -(t["fullW"] * t["fullH"]))   # stable, like Array.sort
        seed = 0x9E3779B9

        def rand():
            nonlocal seed
            seed = (seed * 16807) % 2147483647
            return seed / 2147483647

        placed = []
        for i, t in enumerate(tiles):
            if i == 0:
                t["x"], t["y"] = cx - t["fullW"] / 2, cy - t["fullH"] / 2
                self._stamp(t, t["x"], t["y"])
                placed.append(t)
                continue
            area = [p["fullW"] * p["fullH"] for p in placed]
            comW = jsum(area)
            comX = jsum((p["x"] + p["fullW"] / 2) * a for p, a in zip(placed, area)) / comW
            comY = jsum((p["y"] + p["fullH"] / 2) * a for p, a in zip(placed, area)) / comW
            best, best_cost = None, math.inf
            step = max(GRID_STRIDE, min(t["fullW"], t["fullH"]) * 0.05)
            max_r = max(W, H)
            found = -1
            phase = rand() * math.pi * 2
            r = 0.0
            while r <= max_r:
                if found >= 0 and r > found + step * 2:
                    break
                samples = max(36, math.floor(r / 1.6))
                k = np.arange(samples)
                theta = phase + (k / samples) * math.pi * 2
                px = cx + r * X_BIAS * np.cos(theta) - t["fullW"] / 2
                py = cy + r * Y_BIAS * np.sin(theta) - t["fullH"] / 2
                on = ~((px < 0) | (py < 0) | (px + t["fullW"] > W) | (py + t["fullH"] > H))
                lb = t.get("labelBox")
                if lb:
                    on &= ~((px + lb["dx0"] < 0) | (py + lb["dy0"] < 0) | (px + lb["dx1"] > W) | (py + lb["dy1"] > H))
                idx = np.flatnonzero(on)
                if idx.size:
                    hit = self._collides(t, px[idx], py[idx])
                    for j in idx[~hit]:   # rand() only for free spots, in ring order
                        dx = px[j] + t["fullW"] / 2 - comX
                        dy = py[j] + t["fullH"] / 2 - comY
                        cost = math.hypot(dx / X_BIAS, dy / Y_BIAS) + rand() * step * 0.5
                        if cost < best_cost:
                            best_cost, best = cost, (float(px[j]), float(py[j]))
                if best and found < 0:
                    found = r
                r += step
            if best:
                t["x"], t["y"] = best
                self._stamp(t, *best)
            else:
                t["x"] = t["y"] = -99999.0
            placed.append(t)
        return placed


def _tiles(species, dims, masks, rng, count_exp):
    """Step 1 of renderCollage(): a tile per drawable bird, with its pose,
    silhouette, aspect and count-weighted score."""
    cache, tiles = {}, []
    for s in species:
        base = slugify(s["sci"])
        has_flight = (base + "-2") in dims
        pose = 2 if (has_flight and rng() < FLY_PROB) else 1
        slug = base + "-2" if pose == 2 else base
        if slug not in masks and pose == 2:
            pose, slug = 1, base
        if slug not in masks:
            continue
        d = dims.get(slug)
        try:
            n = float(s.get("n") or 1)
        except (TypeError, ValueError):
            n = 1.0
        if not n or math.isnan(n):
            n = 1.0
        tiles.append({"mask": cache.setdefault(slug, Mask(masks[slug])), "data": s, "pose": pose,
                      "slug": slug, "ar": d[0] / d[1] if d else 1.4, "score": max(1.0, n) ** count_exp})
    return tiles


def _size(tiles, budget, min_area):
    """Steps 2-3: share the area budget by score, floor rare birds, squeeze
    the overflow out of the larger tiles, then width/height from aspect."""
    total = jsum(t["score"] for t in tiles) or 1
    for t in tiles:
        t["area"] = max(min_area, budget * t["score"] / total)
    sum_a = jsum(t["area"] for t in tiles)
    if sum_a > budget:
        fixed = jsum(t["area"] for t in tiles if t["area"] <= min_area + 1e-9)
        flex = sum_a - fixed
        shrink = min(1, max(0, budget - fixed) / flex) if flex > 0 else 1
        for t in tiles:
            if t["area"] > min_area + 1e-9:
                t["area"] *= shrink
    for t in tiles:
        t["fullW"] = math.sqrt(t["area"] * t["ar"])
        t["fullH"] = t["fullW"] / t["ar"]


def _extent(t):
    """A tile's footprint including any label run past its box (clusterBounds)."""
    b = t.get("labelBox")
    return (t["x"] + (min(0, b["dx0"]) if b else 0),
            t["x"] + t["fullW"] + (max(0, b["dx1"] - t["fullW"]) if b else 0),
            t["y"] + (min(0, b["dy0"]) if b else 0),
            t["y"] + t["fullH"] + (max(0, b["dy1"] - t["fullH"]) if b else 0))


def _bounds(arr):
    live = [_extent(t) for t in arr if t["x"] >= -1000]
    if not live:
        return math.inf, -math.inf, math.inf, -math.inf
    return (min(e[0] for e in live), max(e[1] for e in live),
            min(e[2] for e in live), max(e[3] for e in live))


def _pack_to_fit(tiles, W, H, names=False):
    """Pack, then shrink and repack (at most 10 times) until every bird is on
    the canvas, and centre the cluster. With names, every pack re-plans the
    labels at the tiles' current size first, as apt.js does."""
    packer = Packer(W, H)
    label = (lambda: None) if not names else (lambda: _labels().assign_labels(tiles))
    label()
    placed = packer.pack(tiles)
    L, R, Tp, B = _bounds(placed)
    for _ in range(10):
        missing = any(t["x"] < -1000 for t in placed)
        overflow = L < 0 or Tp < 0 or R > W or B > H
        if not missing and not overflow:
            break
        scale = 0.93
        if overflow:
            sx = (W * 0.96) / max(R - L, W * 0.96)
            sy = (H * 0.94) / max(B - Tp, H * 0.94)
            scale = min(scale, sx, sy)
        for t in tiles:
            t["fullW"] *= scale
            t["fullH"] *= scale
        label()
        placed = packer.pack(tiles)
        L, R, Tp, B = _bounds(placed)
    dx, dy = W / 2 - (L + R) / 2, H / 2 - (Tp + B) / 2
    if abs(dx) > 1 or abs(dy) > 1:
        for t in placed:
            if t["x"] > -1000:
                t["x"] += dx
                t["y"] += dy
    return [t for t in placed if t["x"] > -1000]


def _labels():
    import render_labels
    return render_labels


def layout(species, dims, masks, rng=random.random, W=COLLAGE_W, H=COLLAGE_H, count_exp=COUNT_EXP, names=False):
    """apt.js renderCollage() up to the tile rectangles. Returns placed tiles
    with x, y, fullW, fullH (collage-local CSS px), slug and pose."""
    T = tuning(len(species))
    tiles = _tiles(species, dims, masks, rng, count_exp)
    if not tiles:
        return []
    _size(tiles, W * H * T["budget"], W * H * T["min_area"])
    return _pack_to_fit(tiles, W, H, names)


# --- type ---------------------------------------------------------------------
def _mono_file():
    """Chromium's default monospace is fontconfig's: DejaVu Sans Mono on a Pi."""
    names = ["DejaVuSansMono-Bold.ttf", "NotoSansMono-Bold.ttf", "LiberationMono-Bold.ttf"]
    if shutil.which("fc-match"):
        try:
            path = subprocess.run(["fc-match", "-f", "%{file}", "monospace:bold"],
                                  capture_output=True, text=True, timeout=10).stdout
            if os.path.isfile(path):
                return path
        except (OSError, subprocess.SubprocessError):
            pass
    for root in ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/TTF", "/usr/share/fonts/noto",
                 "/usr/share/fonts/truetype/noto", "/usr/share/fonts/truetype/liberation",
                 "/usr/share/fonts/liberation"):
        for name in names:
            if os.path.isfile(os.path.join(root, name)):
                return os.path.join(root, name)
    return None


def _font_file(style):
    """The face Chromium draws the titles in. Its default serif on Linux is
    "Times New Roman", which fontconfig maps to Liberation Serif (installed
    with the frame's browser packages, and by install.sh for local render).
    None means synthesise this style from the regular face."""
    names = {"regular": ["LiberationSerif-Regular.ttf", "Tinos-Regular.ttf", "DejaVuSerif.ttf"],
             "bold": ["LiberationSerif-Bold.ttf", "Tinos-Bold.ttf", "DejaVuSerif-Bold.ttf"],
             "italic": ["LiberationSerif-Italic.ttf", "Tinos-Italic.ttf", "DejaVuSerif-Italic.ttf"]}[style]
    if shutil.which("fc-match"):
        pattern = "Times New Roman" + {"regular": "", "bold": ":bold", "italic": ":italic"}[style]
        try:
            path = subprocess.run(["fc-match", "-f", "%{file}", pattern],
                                  capture_output=True, text=True, timeout=10).stdout
            if os.path.isfile(path) and os.path.basename(path) in names:
                return path
        except (OSError, subprocess.SubprocessError):
            pass
    for name in names:
        for root in ("/usr/share/fonts/truetype/liberation", "/usr/share/fonts/truetype/liberation2",
                     "/usr/share/fonts/liberation", "/usr/share/fonts/TTF",
                     "/usr/share/fonts/truetype/croscore", "/usr/share/fonts/truetype/dejavu"):
            path = os.path.join(root, name)
            if os.path.isfile(path):
                return path
    return None


def _font(style, px):
    path = _mono_file() if style == "mono" else _font_file(style)
    if path is None and style != "regular":
        path = _font_file("regular")
    if path is None:
        raise RuntimeError("no serif font found; install fonts-liberation")
    from PIL import features
    # Kern like the browser's HarfBuzz when Pillow can (libraqm0 on a Pi).
    engine = ImageFont.Layout.RAQM if features.check("raqm") else ImageFont.Layout.BASIC
    return (ImageFont.truetype(path, px, layout_engine=engine),
            style == "italic" and _font_file("italic") is None)


def _draw_line(overlay, text, spec, top, *, style, center_x=VW / 2):
    """One CSS line box: centred, letter-spaced, baseline placed the way a
    browser centres the font's ascent+descent in the line height."""
    px = spec["px"] * DSF
    font, oblique = _font(style, px)
    ascent, descent = font.getmetrics()
    spacing = spec["spacing"] * DSF
    # Pen position of each glyph, including its kern against the previous one.
    pen = [font.getlength(text[:i + 1]) - font.getlength(text[i]) for i in range(len(text))]
    total = font.getlength(text) + spacing * len(text)
    baseline = (top * DSF + (spec["line"] * DSF - (ascent + descent)) / 2
                + (spec["box"] - spec["line"]) * DSF / 2 + ascent)
    x0 = center_x * DSF - total / 2
    layer = Image.new("RGBA", overlay.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for i, ch in enumerate(text):
        draw.text((x0 + pen[i] + spacing * i, baseline), ch, font=font,
                  fill=(*spec["color"], 255), anchor="ls")
    if oblique:  # no italic face: slant like a browser's synthetic oblique (~14 deg)
        k = math.tan(math.radians(14))
        layer = layer.transform(layer.size, Image.Transform.AFFINE,
                                (1, k, -k * baseline, 0, 1, 0), Image.Resampling.BICUBIC)
    overlay.alpha_composite(layer)


# --- assets -------------------------------------------------------------------
def _read_json(path):
    with open(path) as f:
        return json.load(f)


def _cutout(slug, pose, sci, resolver, cache_dir):
    if resolver is not None:
        found = resolver(sci, "perched" if pose == 1 else "flight")
        if found is None:
            raise RuntimeError(f"{slug} is not in the active bundle")
        return open(found, "rb").read()
    local = os.path.join(ILLUSTRATIONS, slug + ".png")
    if os.path.isfile(local):
        return open(local, "rb").read()
    cached = os.path.join(cache_dir, slug + ".png")
    if not os.path.isfile(cached):
        os.makedirs(cache_dir, exist_ok=True)
        req = urllib.request.Request(RAW_ILLUSTRATIONS + slug + ".png",
                                     headers={"User-Agent": "AvianVisitors-frame/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read(capture_art.MAX_ASSET_BYTES + 1)
        capture_art.decode_capture_image(body).close()   # validate before caching
        with tempfile.NamedTemporaryFile(dir=cache_dir, delete=False) as f:
            f.write(body)
        os.replace(f.name, cached)
    return open(cached, "rb").read()


def floor_counts(species, floor_frac=SMALL_FLOOR):
    """shoot.py's API handler: lift the rarest counts so they draw a little larger."""
    sp = [dict(s) for s in species]
    if sp and floor_frac > 0:
        floor = max((s.get("n") or 1) for s in sp) * floor_frac
        for s in sp:
            if (s.get("n") or 1) < floor:
                s["n"] = max(1, round(floor))
    return sp


def render(out, species, *, title="Avian Visitors", subtitle="Heard Today", rng=random.random,
           names=False, box="tall", cutout_resolver=None, dims_path=None, masks_path=None,
           empty_text="no recent detections", cache_dir=None, log=None):
    """Write the capture shoot_birdweather() would (2x, 800 CSS px tall), without a browser."""
    t0 = time.monotonic()
    geo = BOXES[box]
    vw = geo["vw"]
    cx0, cy0, cw, ch = geo["collage"]
    dims = _read_json(dims_path or os.path.join(FRONTEND, "dims.json"))
    masks = _read_json(masks_path or os.path.join(FRONTEND, "masks.json"))
    cache_dir = cache_dir or os.path.expanduser("~/.birdframe/cutouts")
    tiles = layout(floor_counts(species), dims, masks, rng=rng, W=cw, H=ch, names=names)
    t_layout = time.monotonic() - t0

    size = (vw * DSF, VH * DSF)
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    if title:
        _draw_line(overlay, title, EYEBROW, geo["eyebrow_top"] + 1.5, style="italic", center_x=vw / 2)
    if subtitle:
        _draw_line(overlay, subtitle.upper(), HEADLINE, geo["headline_top"], style="bold", center_x=vw / 2)
    images = []
    if tiles:
        for t in tiles:
            body = _cutout(t["slug"], t["pose"], t["data"]["sci"], cutout_resolver, cache_dir)
            with capture_art.decode_capture_image(body) as im:
                natural = list(im.size)
            images.append({"body": body, "natural": natural, "fit": "contain", "position": [0.5, 0.5],
                           "rect": [(cx0 + t["x"]) * DSF, (cy0 + t["y"]) * DSF,
                                    t["fullW"] * DSF, t["fullH"] * DSF],
                           "shadow": SHADOW})
        if names:
            _labels().draw_labels(overlay, tiles, (cx0, cy0), DSF)
    else:  # the empty nest with its status line, centred in the collage box
        with open(os.path.join(FRONTEND, "nest.webp"), "rb") as f:
            body = f.read()
        with capture_art.decode_capture_image(body) as im:
            natural = list(im.size)
        nw = min(cw * 0.78, 470)
        nh = nw * natural[1] / natural[0]
        text_h = EMPTY["line"] if empty_text else 0
        top = cy0 + (ch - (nh + (EMPTY["gap"] + text_h if empty_text else 0))) / 2
        images.append({"body": body, "natural": natural, "fit": "contain", "position": [0.5, 0.5],
                       "rect": [(vw - nw) / 2 * DSF, top * DSF, nw * DSF, nh * DSF], "shadow": None})
        if empty_text:
            spec = {**EMPTY, "box": text_h}
            _draw_line(overlay, empty_text, spec, top + nh + EMPTY["gap"] - 2, style="mono",  # -2: measured
                       center_x=vw / 2)
    png = capture_art.compose_capture(overlay, images, size, PAPER)
    tmp = out + ".tmp"
    with open(tmp, "wb") as f:
        f.write(png)
    os.replace(tmp, out)
    if log:
        log(f"local render: {len(tiles)} birds{' with names' if names else ''}, "
            f"layout {t_layout:.1f}s, total {time.monotonic() - t0:.1f}s")
    return tiles


def render_birdweather(out, species, *, title=None, subtitle=None, bird_names=False, capture=None,
                       cutout_resolver=None, dims_path=None, masks_path=None, bundle_assets=None,
                       timeout_ms=None, box="tall", **_look):
    """Drop-in for shoot.shoot_birdweather() on a Pi without a browser."""
    if species is None:
        raise RuntimeError("render_birdweather needs a species list")
    render(out, species, title="Avian Visitors" if title is None else title,
           subtitle="Heard Today" if subtitle is None else subtitle, names=bool(bird_names), box=box,
           cutout_resolver=cutout_resolver, dims_path=dims_path, masks_path=masks_path,
           log=lambda m: print(m, file=sys.stderr))
    if capture is not None:
        capture["species"] = [dict(s) for s in species]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    loc = ap.add_mutually_exclusive_group(required=True)
    loc.add_argument("--zip")
    loc.add_argument("--station-id")
    loc.add_argument("--species-json", help="render this [{sci, com, n}] list instead of fetching")
    ap.add_argument("--country", default="us")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", default="frame.png")
    ap.add_argument("--perched", action="store_true", help="never use flight poses (for comparisons)")
    ap.add_argument("--names", action="store_true", help="write each bird's name along it")
    ap.add_argument("--box", choices=sorted(BOXES), default="tall")
    a = ap.parse_args()
    if a.species_json:
        species = _read_json(a.species_json)
    else:
        import birdweather
        species = (birdweather.species_for_station(a.station_id, days=a.days) if a.station_id
                   else birdweather.species_for_zip(a.zip, country=a.country, days=a.days))
    render(a.out, species, rng=(lambda: 0.99) if a.perched else random.random, names=a.names, box=a.box, log=print)
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
