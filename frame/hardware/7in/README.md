# 7.3" frame backing

A 3D-printed back for the [Inky Impression 7.3"](https://www.adafruit.com/product/6471) in an ordinary 5x7" picture frame: the 7.3" counterpart of `../BirdPicBacking`. It replaces the frame's cardboard back. Four corner pads press the display against the mat, fins hold it where the screen lines up with the mat, the Pi sits in the pocket, and a captured keyhole hangs the frame.

`backing_7in.py` is the source (CadQuery). `backing_7in.stl` / `.3mf` / `.step` are generated from it with the default parameters, which assume:

| Parameter | Default | Check on your frame |
|---|---|---|
| `RABBET_W` x `RABBET_H` | 127.5 x 178.3 mm | the opening on the back the cardboard sits in |
| `RABBET_DEPTH` | 9.5 mm | back face of the moulding down to the glass |
| `LIP` | 8 mm | must be no wider than the moulding's back face |
| `GLASS_T`, `MAT_T` | 2.0, 1.4 mm | glass and mat thickness |
| `FPC_SIDE` | `"left"` | which long edge the display's ribbon wraps round, seen from the back with the Pi at the bottom |
| `BOARD_T`, `PI_GAP` | 3.0, 11.0 mm | display thickness (glass to PCB back) and header stack: estimates, measure once the parts arrive |

Any 5x7 frame works if its rabbet is at least glass + mat + 3 mm deep and its moulding's back face is at least 8 mm wide. A deep frame or shadow box isn't needed: the plate sticks out about 15 mm behind the frame.

## Regenerate

```bash
pip install cadquery
python3 backing_7in.py --check   # prints the plate size and checks it clears the display, mat, Pi and header
```

## Print

- 143.5 x 194.3 x 15.2 mm with the defaults; it needs a bed at least that big (it doesn't fit a 180 mm bed).
- The STL/3MF are already oriented: back face on the bed, pocket up, no supports.
- PLA or PETG, 0.2 mm layers, 3 walls, 15% infill.

## Assemble

1. Take the cardboard back out of the frame and pull or bend away its tabs.
2. Mount the Pi (3 A+ or Zero 2 W) on the display's header with the included standoffs.
3. Put the glass, then the mat, into the frame face down. Lay the display on the mat, screen down, with the **Pi toward the bottom of the frame** and the display **pushed against the rabbet wall on its ribbon-cable side**.
4. Plug in the micro-USB cable and lead it out through the notch in the bottom rim.
5. Press the backing on (the "TOP" label goes at the top) and fix it with four short wood screws (#4 x 1/2" or M3 x 12) through the rim into the moulding.
6. Hang it from a screw in the wall: the head goes in the round hole and slides up into the keyhole.

If the picture is upside down, set `rotate = 270` in `~/.birdframe/config.toml`.
