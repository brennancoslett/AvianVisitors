"""render_local.py must place birds and their names exactly where the browser frontend does.

The expected rectangles were measured from the real page (apt.js in headless
Chromium, shoot.py's BirdWeather settings, every bird perched)."""
import json
import os
import unittest

import render_local

SPECIES = [
    {"sci": "Passer domesticus", "com": "House Sparrow", "n": 4556},
    {"sci": "Poecile atricapillus", "com": "Black-capped Chickadee", "n": 1126},
    {"sci": "Cyanocitta cristata", "com": "Blue Jay", "n": 1046},
    {"sci": "Haemorhous mexicanus", "com": "House Finch", "n": 508},
    {"sci": "Bombycilla cedrorum", "com": "Cedar Waxwing", "n": 429},
    {"sci": "Sitta canadensis", "com": "Red-breasted Nuthatch", "n": 369},
    {"sci": "Dryobates pubescens", "com": "Downy Woodpecker", "n": 345},
    {"sci": "Branta canadensis", "com": "Canada Goose", "n": 332},
    {"sci": "Dryobates villosus", "com": "Hairy Woodpecker", "n": 322},
    {"sci": "Sitta carolinensis", "com": "White-breasted Nuthatch", "n": 199},
]

# sci, left, top, width, height (collage-local CSS px), from the browser.
BROWSER = [
    ["Passer domesticus", 152.45, 87.98, 232.26, 189.54],
    ["Poecile atricapillus", 195.31, 233.37, 121.9, 89.25],
    ["Cyanocitta cristata", 253.86, 259.3, 88.61, 114.07],
    ["Haemorhous mexicanus", 294.42, 87.53, 71.81, 68.35],
    ["Bombycilla cedrorum", 145.38, 168.0, 64.67, 64.09],
    ["Sitta canadensis", 219.57, 64.47, 77.2, 46.18],
    ["Dryobates pubescens", 151.83, 229.9, 37.72, 88.38],
    ["Branta canadensis", 349.09, 160.15, 54.68, 58.66],
    ["Dryobates villosus", 362.4, 110.37, 44.22, 70.35],
    ["Sitta carolinensis", 307.53, 30.63, 37.29, 51.56],
]

# Same birds with names, in the tall box: sci, left, top, width, height, then each
# name line as text, px, first and last path point, point count (browser SVG, 0.1 px).
BROWSER_NAMES = [
    ["Passer domesticus", 99.55, 132.36, 221.59, 180.84, [["House Sparrow", 21, [64.6, -1.7, 154.9, 62.3], 20]]],
    ["Poecile atricapillus", 98.79, 302.36, 116.31, 85.15, [["Black-capped", 16, [7.6, -9.1, 81.9, 0.3], 14], ["Chickadee", 16, [17.1, 7.9, 73.2, 16.8], 11]]],
    ["Cyanocitta cristata", 204.4, 308.85, 84.54, 108.83, [["Blue Jay", 15, [11.1, 50.7, 42.0, 18.7], 8]]],
    ["Haemorhous mexicanus", 279.9, 197.69, 68.52, 65.21, [["House Finch", 11, [26.2, 5.2, 62.1, 39.5], 9]]],
    ["Bombycilla cedrorum", 264.35, 120.04, 61.7, 61.15, [["Cedar Waxwing", 11, [25.2, -6.1, 66.8, 39.5], 11]]],
    ["Sitta canadensis", 196.99, 84.09, 73.66, 44.06, [["Red-breasted", 11, [15.2, -15.7, 67.0, -6.7], 10], ["Nuthatch", 11, [19.2, -4.4, 61.8, 5.5], 8]]],
    ["Dryobates pubescens", 73.89, 203.57, 35.99, 84.32, [["Downy", 11, [-2.9, -9.1, 24.9, -17.1], 6], ["Woodpecker", 11, [-9.4, 4.8, 36.7, -8.5], 9]]],
    ["Branta canadensis", 116.58, 58.8, 52.17, 55.97, [["Canada Goose", 11, [17.6, 6.2, 64.6, 36.3], 10]]],
    ["Dryobates villosus", 67.45, 80.11, 42.19, 67.12, [["Hairy", 11, [1.1, -13.1, 26.1, -17.0], 5], ["Woodpecker", 11, [-8.2, -0.2, 39.2, -7.3], 9]]],
    ["Sitta carolinensis", 153.4, 379.38, 35.58, 49.2, [["White-breasted Nuthatch", 11, [-32.9, 54.6, 68.9, 63.5], 2]]],
]


class RenderLocalLayoutTests(unittest.TestCase):
    def test_layout_matches_browser(self):
        dims = json.load(open(os.path.join(render_local.FRONTEND, "dims.json")))
        masks = json.load(open(os.path.join(render_local.FRONTEND, "masks.json")))
        tiles = render_local.layout(render_local.floor_counts(SPECIES), dims, masks, rng=lambda: 0.99)
        got = {t["data"]["sci"]: t for t in tiles}
        self.assertEqual(sorted(got), sorted(r[0] for r in BROWSER))
        for sci, left, top, w, h in BROWSER:
            t = got[sci]
            for name, mine, theirs in (("x", t["x"], left), ("y", t["y"], top),
                                       ("w", t["fullW"], w), ("h", t["fullH"], h)):
                self.assertAlmostEqual(mine, theirs, delta=0.01, msg=f"{sci} {name}")

    def test_names_match_browser(self):
        os.environ["AVIAN_NO_HARFBUZZ"] = "1"   # the precomputed widths, as on a Pi
        dims = json.load(open(os.path.join(render_local.FRONTEND, "dims.json")))
        masks = json.load(open(os.path.join(render_local.FRONTEND, "masks.json")))
        _, _, W, H = render_local.BOXES["tall"]["collage"]
        tiles = render_local.layout(render_local.floor_counts(SPECIES), dims, masks, rng=lambda: 0.99,
                                    W=W, H=H, names=True)
        got = {t["data"]["sci"]: t for t in tiles}
        for sci, left, top, w, h, labels in BROWSER_NAMES:
            t = got[sci]
            for name, mine, theirs in (("x", t["x"], left), ("y", t["y"], top),
                                       ("w", t["fullW"], w), ("h", t["fullH"], h)):
                self.assertAlmostEqual(mine, theirs, delta=0.01, msg=f"{sci} {name}")
            self.assertEqual([r["text"] for r in t["labelRows"]], [lab[0] for lab in labels], sci)
            for row, (text, px, ends, count) in zip(t["labelRows"], labels):
                self.assertEqual(t["labelPx"], px, sci)
                self.assertEqual(len(row["pts"]), count, f"{sci} {text}")
                first, last = row["pts"][0], row["pts"][-1]
                for mine, theirs in zip((first[0], first[1], last[0], last[1]), ends):
                    self.assertAlmostEqual(mine, theirs, delta=0.06, msg=f"{sci} {text}")

    def test_empty_list_renders_the_nest(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "frame.png")
            render_local.render(out, [], box="classic")
            from PIL import Image
            with Image.open(out) as im:
                self.assertEqual(im.size, (1200, 1600))


if __name__ == "__main__":
    unittest.main()
