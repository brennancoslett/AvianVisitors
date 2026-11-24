#!/usr/bin/env python3
"""Precompute how the browser shapes bird names in Caveat, for render_labels.py.

The label engine sizes every name from Chrome's canvas measureText, which
shapes each word with HarfBuzz - Caveat swaps in contextual alternates (ss01,
ss02) as a handwriting would - and rounds each glyph's advance to a whole
pixel at the 100 px it measures at. Pillow can shape but doesn't expose the
glyphs, and a HarfBuzz binding may not exist for the frame's Pi, so this
writes the result for every word of every English BirdNET name to
label_metrics.json:

    words[word] = [width at weight 600 in px at 100 px (Chrome's rounding),
                   [[text, stylistic set or "", advance at weight 400 in font units], ...]]

Run on any machine with uharfbuzz after changing the font or the name list:

    pip install uharfbuzz && python3 build_label_metrics.py
"""
import json
import math
import os

import uharfbuzz as hb
from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, "..", "avian", "frontend", "fonts", "Caveat.ttf")
NAMES = os.path.join(HERE, "..", "model", "l18n", "labels_en.json")
OUT = os.path.join(HERE, "label_metrics.json")


def shaper(weight, scale):
    font = hb.Font(hb.Face(hb.Blob.from_file_path(FONT)))
    font.scale = (scale, scale)
    font.set_variations({"wght": weight})
    return font


def shape(font, text):
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, {})
    return buf.glyph_infos, buf.glyph_positions


def main():
    upem = TTFont(FONT)["head"].unitsPerEm
    measure = shaper(600, 100 * 64)      # 100 px in 26.6 fixed point, like the canvas
    draw = shaper(400, upem)
    with open(NAMES, encoding="utf-8") as f:
        names = json.load(f).values()
    words = sorted({w for name in names for w in name.split(" ") if w})
    table = {}
    for word in words:
        _, pos = shape(measure, word)
        w600 = sum(math.floor(p.x_advance / 64 + 0.5) for p in pos)
        infos, pos = shape(draw, word)
        clusters = [i.cluster for i in infos]
        glyphs = []
        for k, (info, p) in enumerate(zip(infos, pos)):
            end = min([c for c in clusters if c > info.cluster], default=len(word))
            name = draw.glyph_to_string(info.codepoint)
            feat = name.rsplit(".", 1)[1] if "." in name and name.rsplit(".", 1)[1].startswith("ss") else ""
            glyphs.append([word[info.cluster:end], feat, p.x_advance])
        table[word] = [w600, glyphs]
    _, sp600 = shape(measure, " ")
    _, sp400 = shape(draw, " ")
    data = {"font": "Caveat.ttf", "upem": upem,
            "space600": sum(math.floor(p.x_advance / 64 + 0.5) for p in sp600),
            "space400": sum(p.x_advance for p in sp400), "words": table}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {len(table)} words to {OUT} ({os.path.getsize(OUT) // 1024} KB)")


if __name__ == "__main__":
    main()
