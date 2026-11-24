#!/usr/bin/env python3
"""Parametric 3D-printed backing for the 7.3" Inky Impression in a 5x7" frame.

The 7.3" counterpart of BirdPicBacking: a plate that replaces the frame's
cardboard back. Its rim sits on the back of the frame moulding, four corner
pads reach into the rabbet and press the display against the mat, and an
open pocket houses the Pi mounted on the back of the display.

Additions over the 13.3" backing:
- Locating fins hold the board against the rabbet wall on its ribbon-cable
  (FPC) side. The 7.3" screen is 2.9 mm off-centre on its board (16.5 mm
  border on the FPC edge, ~10.7 mm opposite); a 5x7 rabbet has ~2.1 mm of
  slack per side, so pushing the board to the FPC side puts the screen within
  ~0.8 mm (4 px) of centre.
- A captured keyhole: the wall screw's head slides into a closed pocket.
- Four counterbored screw holes in the rim fix the plate to the moulding.

Measure your frame and update the PARAMETERS block, then:

    pip install cadquery
    python3 backing_7in.py            # writes backing_7in.{step,stl,3mf}
    python3 backing_7in.py --check    # also checks clearances against a model of the stack

Coordinates: viewed from the BACK of the hanging frame. X right, Y up, Z=0 is
the back face of the frame moulding, +Z away from the frame (toward the wall).
The exported STL/3MF is flipped to print orientation: plate back on the bed,
pocket and pads facing up, no supports needed.
"""
from __future__ import annotations

import argparse
import os

import cadquery as cq

# ---------------------------------------------------------------- PARAMETERS
# Frame. Measure the opening on the back of the frame that the cardboard back
# sits in (the rabbet), and how deep it is from the back face of the moulding
# down to the glass.
RABBET_W = 127.5        # rabbet width (5" = 127.0) plus a little clearance
RABBET_H = 178.3        # rabbet height (7" = 177.8) plus a little clearance
RABBET_DEPTH = 9.5      # back face of moulding down to the glass
LIP = 8.0               # how far the rim overlaps the moulding; <= moulding back width

# What sits in the rabbet in front of the display board.
GLASS_T = 2.0           # glass (or acrylic) thickness
MAT_T = 1.4             # mat board thickness

# Inky Impression 7.3" (PIM773), from Pimoroni's dimension drawing.
BOARD_W, BOARD_H = 123.2, 174.2   # portrait
BOARD_T = 3.0           # front of glass to back of PCB, without components
FPC_SIDE = "left"       # long edge the ribbon wraps round, seen from the BACK: "left" or "right"

# Pi mounted on the back of the board, component side facing the display.
# gap = Inky PCB back to Pi PCB top: 8.5 mm female header + 2.5 mm male header
# body = 11 mm; a full-size Pi needs Pimoroni's included extension header
# (+8.5 mm) so its ~16 mm USB/Ethernet ports clear the display.
PI_MODEL = "zero2"      # "zero2" (also the original Zero W), "3a+", "4" or "5"
PI_MODELS = {           # (width, length) portrait mm, gap, PCB, underside parts, port block height
    "zero2": dict(size=(30, 65), gap=11.0, t=1.0, under=1.5, ports=0.0),
    "3a+": dict(size=(56, 65), gap=11.0, t=1.4, under=2.0, ports=7.0),
    "4": dict(size=(56, 85), gap=19.5, t=1.4, under=2.0, ports=16.0),
    "5": dict(size=(56, 85), gap=19.5, t=1.4, under=2.0, ports=16.0),
}
PI = PI_MODELS[PI_MODEL]
PI_GAP, PI_T, PI_UNDER = PI["gap"], PI["t"], PI["under"]
CLEARANCE = 1.5         # air gap kept between the Pi and the plate floor

# Plate details.
FLOOR_T = 2.4           # back wall thickness
PAD = 10.0              # corner pad size (presses the board's corner, clear of parts)
FIN_DEPTH = 2.5         # fins run this far alongside the board edge (< BOARD_T)
FIT = 0.4               # total side-to-side play left for the board
CORNER_R = 4.0          # plate corner radius
CABLE_W, CABLE_H = 12.0, 7.0   # USB cable notch in the bottom rim
CABLE_X = 0.0           # notch centre, mm from the plate centre (+ = right, seen from back)
SCREW_D, SCREW_HEAD_D, SCREW_FLOOR = 3.4, 7.0, 4.0   # rim screws (#4 / M3 wood screws)
KEYHOLE_FROM_TOP = 28.0  # keyhole centre below the top of the rabbet
KEY_HEAD_D, KEY_SHANK_D, KEY_TRAVEL = 9.5, 4.6, 12.0   # wall-screw head, shank, slide length
KEY_HEAD_T = 3.5        # head pocket depth
LABEL = "TOP"

# ------------------------------------------------------------------- DERIVED
PAD_DEPTH = RABBET_DEPTH - GLASS_T - MAT_T - BOARD_T   # rim face to board back
STACK = PI_GAP + PI_T + PI_UNDER + CLEARANCE           # board back to plate floor
POCKET = STACK - PAD_DEPTH                             # pocket depth behind Z=0
T = POCKET + FLOOR_T                                   # plate thickness
W, H = RABBET_W + 2 * LIP, RABBET_H + 2 * LIP
SLACK_X = RABBET_W - BOARD_W - FIT                     # board is pushed to the FPC side
SLACK_Y = (RABBET_H - BOARD_H - FIT) / 2               # centred top to bottom
FPC_SIGN = -1 if FPC_SIDE == "left" else 1


def set_pi(model):
    """Switch Pi model and recompute everything derived from it."""
    global PI_MODEL, PI, PI_GAP, PI_T, PI_UNDER, STACK, POCKET, T
    PI_MODEL, PI = model, PI_MODELS[model]
    PI_GAP, PI_T, PI_UNDER = PI["gap"], PI["t"], PI["under"]
    STACK = PI_GAP + PI_T + PI_UNDER + CLEARANCE
    POCKET = STACK - PAD_DEPTH
    T = POCKET + FLOOR_T


def check_params():
    if FPC_SIDE not in ("left", "right"):
        raise SystemExit('FPC_SIDE must be "left" or "right"')
    if PAD_DEPTH < 0:
        raise SystemExit(
            f"the display stack is {-PAD_DEPTH:.1f} mm proud of the rabbet; "
            "this design needs RABBET_DEPTH >= glass + mat + board")
    if SLACK_X < 0 or SLACK_Y < 0:
        raise SystemExit("the board does not fit the rabbet; check RABBET_W/H")
    if FIN_DEPTH >= BOARD_T:
        raise SystemExit("FIN_DEPTH must be less than BOARD_T so fins never touch the mat")


def backing():
    # Solid plate, then the pocket from the frame side.
    plate = (cq.Workplane("XY").rect(W, H).extrude(T)
             .edges("|Z").fillet(CORNER_R)
             .faces(">Z").edges().chamfer(1.2))
    plate = plate.cut(cq.Workplane("XY").rect(RABBET_W, RABBET_H).extrude(POCKET))

    # Corner columns: from the floor, through the pocket, into the rabbet down
    # to the board's back face.
    cols = cq.Workplane("XY")
    for sx in (-1, 1):
        for sy in (-1, 1):
            cx = sx * (RABBET_W / 2 - PAD / 2)
            cy = sy * (RABBET_H / 2 - PAD / 2)
            cols = cols.union(cq.Workplane("XY").box(PAD, PAD, POCKET + PAD_DEPTH, centered=(True, True, False))
                              .translate((cx, cy, -PAD_DEPTH)))
    plate = plate.union(cols)

    # Locating fins, hanging off the pads alongside the board edge.
    fins = cq.Workplane("XY")
    z0 = -PAD_DEPTH - FIN_DEPTH
    if SLACK_X > 0.6:   # long side opposite the FPC fills all the side play
        fx = -FPC_SIGN * (RABBET_W / 2 - SLACK_X / 2)
        for sy in (-1, 1):
            fins = fins.union(cq.Workplane("XY").box(SLACK_X, PAD, FIN_DEPTH + 0.01, centered=(True, True, False))
                              .translate((fx, sy * (RABBET_H / 2 - PAD / 2), z0)))
    if SLACK_Y > 0.6:   # both short ends, kept to the corners (older boards have side buttons mid-edge)
        for sx in (-1, 1):
            for sy in (-1, 1):
                fins = fins.union(cq.Workplane("XY").box(PAD, SLACK_Y, FIN_DEPTH + 0.01, centered=(True, True, False))
                                  .translate((sx * (RABBET_W / 2 - PAD / 2), sy * (RABBET_H / 2 - SLACK_Y / 2), z0)))
    plate = plate.union(fins)

    # Cable notch through the bottom rim, open to the frame side.
    plate = plate.cut(cq.Workplane("XY").box(CABLE_W, LIP + 2, CABLE_H, centered=(True, True, False))
                      .translate((CABLE_X, -(RABBET_H / 2 + LIP / 2), -0.01)))

    # Rim screws: two along each long side (the bottom rim carries the cable
    # notch), counterbored from the back so a short screw reaches the moulding.
    for x, y in ((sx * (W / 2 - LIP / 2), sy * H / 4) for sx in (-1, 1) for sy in (-1, 1)):
        plate = plate.cut(cq.Workplane("XY").circle(SCREW_D / 2).extrude(T + 1).translate((x, y, -0.5)))
        plate = plate.cut(cq.Workplane("XY").circle(SCREW_HEAD_D / 2).extrude(T).translate((x, y, SCREW_FLOOR)))

    # Captured keyhole: boss on the inside of the floor with a head pocket.
    ky = RABBET_H / 2 - KEYHOLE_FROM_TOP
    y_entry = ky - KEY_TRAVEL / 2
    boss_h = KEY_HEAD_T + 1.6
    plate = plate.union(cq.Workplane("XY").box(KEY_HEAD_D + 7, KEY_TRAVEL + KEY_HEAD_D + 7, boss_h, centered=(True, True, False))
                        .edges("|Z").fillet(2).translate((0, ky, POCKET - boss_h)))
    head_slot = (cq.Workplane("XY").center(0, ky)
                 .slot2D(KEY_TRAVEL + KEY_HEAD_D, KEY_HEAD_D, angle=90).extrude(KEY_HEAD_T)
                 .translate((0, 0, POCKET - KEY_HEAD_T)))
    shank_slot = (cq.Workplane("XY").center(0, ky)
                  .slot2D(KEY_TRAVEL + KEY_SHANK_D, KEY_SHANK_D, angle=90).extrude(T + 1)
                  .translate((0, 0, POCKET - 0.5)))
    entry = cq.Workplane("XY").circle(KEY_HEAD_D / 2).extrude(T + 1).translate((0, y_entry, POCKET - KEY_HEAD_T))
    plate = plate.cut(head_slot).cut(shank_slot).cut(entry)

    # "TOP" on the outside so the board goes in the right way up.
    if LABEL:
        plate = plate.cut(cq.Workplane("XY").workplane(offset=T - 0.6)
                          .center(0, RABBET_H / 2 - 8).text(LABEL, 7, 1, kind="bold", halign="center", valign="center"))
    return plate


def pi_parts(bx, z_board_back):
    """Pi, header and port block, placed per Pimoroni's drawing: the Pi's
    header-side mounting holes sit 96 mm from the FPC edge, the port end points
    down, and the top holes are 85 mm up, so every model hangs in the lower half."""
    away = -FPC_SIGN
    w, length = PI["size"]
    # Header-side edge 99.5 mm from the FPC edge; the board extends back toward the FPC.
    pi_x = bx + FPC_SIGN * BOARD_W / 2 + away * (99.5 - w / 2)
    top = -BOARD_H / 2 + 88.2                      # top edge of every Pi footprint
    pi_y = top - length / 2
    z_pi = z_board_back + PI_GAP

    def box(bw, bh, t, x, y, z):
        return cq.Workplane("XY").box(bw, bh, t, centered=(True, True, False)).translate((x, y, z))

    parts = {
        "pi": box(w, length, PI_T + PI_UNDER, pi_x, pi_y, z_pi),
        "header": box(5.1, 51, PI_GAP, bx + away * (96 - BOARD_W / 2), top - 3.5 - 29, z_board_back),
    }
    if PI["ports"]:
        # USB / Ethernet block at the bottom end, facing the display, overhanging 2 mm.
        parts["ports"] = box(w - 2, 21, PI["ports"], pi_x, top - length - 2 + 10.5, z_pi - PI["ports"])
    return parts, (pi_x, pi_y, z_pi)


def stack_model():
    """The parts the plate must clear, for --check."""
    bx = FPC_SIGN * (RABBET_W - BOARD_W) / 2          # board pushed against the FPC-side wall
    z_board_back = -PAD_DEPTH
    board = cq.Workplane("XY").box(BOARD_W, BOARD_H, BOARD_T, centered=(True, True, False)) \
        .translate((bx, 0, z_board_back - BOARD_T))
    mat = cq.Workplane("XY").box(RABBET_W, RABBET_H, MAT_T, centered=(True, True, False)) \
        .translate((0, 0, z_board_back - BOARD_T - MAT_T))
    parts, _ = pi_parts(bx, z_board_back)
    if PI["ports"] and PI["ports"] >= PI_GAP:
        raise SystemExit(f"Pi {PI_MODEL} ports ({PI['ports']} mm) do not clear the display at a {PI_GAP} mm gap")
    return {"board": board, "mat": mat, **parts}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="check clearances against the display stack")
    ap.add_argument("--pi", choices=sorted(PI_MODELS), help="override PI_MODEL")
    ap.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)))
    a = ap.parse_args()
    if a.pi and a.pi != PI_MODEL:
        set_pi(a.pi)
    check_params()
    plate = backing()
    print(f"Pi {PI_MODEL}: plate {W:.1f} x {H:.1f} x {T:.1f} mm; pads reach {PAD_DEPTH:.1f} mm into the rabbet; "
          f"pocket {POCKET:.1f} mm deep; side fins {SLACK_X:.2f} mm, end fins {SLACK_Y:.2f} mm")
    if a.check:
        ok = True
        for name, part in stack_model().items():
            v = plate.intersect(part).val().Volume() if plate.intersect(part).vals() else 0.0
            print(f"  {name:7s} overlap {v:.3f} mm^3")
            ok &= v < 1e-3
        pi_bottom = -PAD_DEPTH + PI_GAP + PI_T + PI_UNDER
        print(f"  Pi underside to floor: {POCKET - pi_bottom:.2f} mm "
              f"(keyhole boss sits {RABBET_H / 2 - KEYHOLE_FROM_TOP:.0f} mm above centre, Pi stays in the lower half)")
        if not ok:
            raise SystemExit("clearance check FAILED")
        print("clearance check passed")
    base = os.path.join(a.out, "backing_7in" + ("" if PI_MODEL == "zero2" else f"_pi{PI_MODEL}"))
    cq.exporters.export(plate, base + ".step")
    printable = plate.rotate((0, 0, 0), (1, 0, 0), 180).translate((0, 0, T))
    cq.exporters.export(printable, base + ".stl", tolerance=0.05, angularTolerance=0.1)
    try:
        cq.exporters.export(printable, base + ".3mf", tolerance=0.05, angularTolerance=0.1)
    except Exception as e:  # older CadQuery without 3MF support
        print(f"3mf export skipped: {e}")
    print(f"wrote {base}.step/.stl/.3mf")


if __name__ == "__main__":
    main()
