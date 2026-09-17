"""NE 403 graphite pile (UT) as an OpenMC Studio project.

    python make_project.py            writes graphite-pile.openmc-studio.json next to this script

Open the .json in Studio with Export ▸ Open project. Studio then shows the pile, writes model.py
and model.mcnp, and can run it.

Geometry, from the NE 403 pre-lab "Neutron diffusion length measurement using the Graphite Pile":
- Upper, apertured block: 8 ft wide (x) × 8 ft deep (y) × 8 ft tall (z).
- Solid graphite base below it: 2 ft tall, same width and depth. Whole pile: 8 × 8 × 10 ft.
- Diamond apertures: squares with 2 in sides turned 45° (a diamond seen from the front), running the
  full 8 ft depth (along y). 12 columns × 11 rows on an 8 in pitch, as in Figure 1: columns 4 in
  from the side faces, top row 4 in below the top, bottom row 12 in above the base.
- Source drawer: 0.75 in × 8 in × 0.75 in, long side along y (parallel to the apertures), centered
  under the middle of the pile, about 1 ft above the bottom.

Coordinates: origin at the center of the whole pile; x across the front face, y into the pile (the
front face is y = -4 ft), z up. Units are cm, as Studio stores them.

Assumptions to check against your course files:
- PuBe spectrum: Studio has no tabulated source spectrum yet, so the source is a Maxwell spectrum
  with T = 2.8 MeV (mean energy 4.2 MeV, close to PuBe's). Replace it with the course's starter
  SDEF in model.mcnp, or change the energy in Studio, for a real comparison.
- Graphite: PNNL-15870 #63 "Carbon, Graphite (Reactor Grade)", 1.7 g/cm³ with 1 ppm boron, and the
  c_Graphite thermal scattering table. Apertures and the drawer are dry air (PNNL #4).
- The room around the pile is left out (vacuum boundary 1 ft past the sides).
- Tallies are Studio mesh tallies, 1 in (2.54 cm) bins, through the measurement channel
  (the 7th column from the left, which is 4 in right of center; the 3rd row from the bottom)
  and at the 40 in "indicated depth". The He-3 (n,alpha) response isn't included yet.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIBRARY = HERE.parent.parent / "studio" / "openmc_studio" / "static" / "materials.jsonl"
IN = 2.54  # cm per inch
FT = 12 * IN

WIDTH = DEPTH = 8 * FT              # x, y
HEIGHT = 10 * FT                    # z: 2 ft base + 8 ft apertured block
Z_BOTTOM = -HEIGHT / 2
PITCH = 8 * IN
SIDE = 2 * IN                       # aperture square side
COLS, ROWS = 12, 11
COL_X = [(-44 + 8 * k) * IN for k in range(COLS)]              # 4 in from each side face
ROW_Z = [Z_BOTTOM + 3 * FT + k * PITCH for k in range(ROWS)]   # bottom row 12 in above the 2 ft base
SOURCE_Z = Z_BOTTOM + 1 * FT
CHANNEL_X = COL_X[6]                # 7th column from the left: +4 in
CHANNEL_Z = ROW_Z[2]                # 3rd row from the bottom
DEPTH_40 = -DEPTH / 2 + 40 * IN     # "indicated depth of 40 inches" from the front face

r = lambda v: round(v, 6)


def library_material(num, mid, color, sab=""):
    for line in LIBRARY.read_text(encoding="utf-8").splitlines():
        o = json.loads(line)
        if o.get("num") == num:
            return {"id": mid, "name": o["name"], "color": color, "density": o["density"], "frac": "wo",
                    "comps": o["comps"], "sab": sab, "ref": f"PNNL #{num}"}
    raise SystemExit(f"PNNL #{num} is not in {LIBRARY}")


def box(pid, name, x, y, z, sx, sy, sz, material, ry=0, group=None):
    p = {"id": pid, "name": name, "shape": "box", "x": r(x), "y": r(y), "z": r(z), "r": 10, "h": 20, "axis": "z",
         "sx": r(sx), "sy": r(sy), "sz": r(sz), "rx": 0, "ry": ry, "rz": 0, "material": material}
    if group:
        p["group"] = group
    return p


def mesh(tid, name, n, lo, hi):
    return {"id": tid, "name": name, "kind": "mesh", "cells": [], "scores": ["flux"], "ebins": "",
            "nx": n[0], "ny": n[1], "nz": n[2], "lx": r(lo[0]), "ly": r(lo[1]), "lz": r(lo[2]),
            "ux": r(hi[0]), "uy": r(hi[1]), "uz": r(hi[2])}


def main():
    graphite = library_material(63, "m_graphite", "#5d636b", sab="c_Graphite")
    air = library_material(4, "m_air", "#8fb8cf")

    parts = []
    # Apertures first: parts higher in the Explorer win where shapes overlap, so the air channels
    # are cut out of the graphite block listed after them.
    for i, z in enumerate(reversed(ROW_Z)):          # top row first, like reading the front view
        row = ROWS - i
        for c, x in enumerate(COL_X):
            parts.append(box(f"ap_r{row}_c{c + 1}", f"Aperture row {row} col {c + 1}", x, 0, z,
                             SIDE, DEPTH, SIDE, air["id"], ry=45, group="g_apertures"))
    parts.append(box("drawer", "Source drawer", 0, 0, SOURCE_Z, 0.75 * IN, 8 * IN, 0.75 * IN, air["id"]))
    parts.append(box("pile", "Graphite pile", 0, 0, 0, WIDTH, DEPTH, HEIGHT, graphite["id"]))

    half = 0.75 * IN / 2
    source = {"id": "s_pube", "name": "PuBe source (Maxwell approx.)", "particle": "neutron", "strength": 1,
              "space": "box", "x": 0, "y": 0, "z": r(SOURCE_Z), "rin": 0, "r": 5, "h": 10,
              "x0": r(-half), "x1": r(half), "y0": r(-4 * IN), "y1": r(4 * IN), "z0": r(SOURCE_Z - half), "z1": r(SOURCE_Z + half),
              "angle": "isotropic", "u": 0, "v": 0, "w": 1,
              "energy": "maxwell", "lines": "4.2:1", "wa": 0.988, "wb": 2.249, "theta": 2.8, "emin": 0.1, "emax": 11}

    t = 0.5 * IN  # half width of a 1 in measurement bin
    tallies = [
        mesh("t_x", "Flux across (x), channel row 3, 40 in deep", (96, 1, 1),
             (-WIDTH / 2, DEPTH_40 - t, CHANNEL_Z - t), (WIDTH / 2, DEPTH_40 + t, CHANNEL_Z + t)),
        mesh("t_y", "Flux in depth (y), channel col 7 row 3", (1, 96, 1),
             (CHANNEL_X - t, -DEPTH / 2, CHANNEL_Z - t), (CHANNEL_X + t, DEPTH / 2, CHANNEL_Z + t)),
        mesh("t_z", "Flux up (z), channel col 7, 40 in deep", (1, 1, 120),
             (CHANNEL_X - t, DEPTH_40 - t, Z_BOTTOM), (CHANNEL_X + t, DEPTH_40 + t, -Z_BOTTOM)),
        mesh("t_map", "Flux map (XZ) at 40 in deep", (96, 1, 120),
             (-WIDTH / 2, DEPTH_40 - t, Z_BOTTOM), (WIDTH / 2, DEPTH_40 + t, -Z_BOTTOM)),
    ]

    aperture_center = [0, 0, r((ROW_Z[0] + ROW_Z[-1]) / 2)]
    project = {
        "materials": [graphite, air],
        "parts": parts,
        "groups": [{"id": "g_apertures", "name": "Apertures", "x": aperture_center[0], "y": aperture_center[1], "z": aperture_center[2]}],
        "sources": [source],
        "tallies": tallies,
        "settings": {"name": "NE403 graphite pile", "runMode": "fixed source", "particles": 20000, "batches": 10,
                     "inactive": 0, "seed": 12345, "maxTracks": 20, "track": "", "photon": False,
                     "worldShape": "box", "worldR": r(HEIGHT / 2 + 1 * FT), "worldBC": "vacuum", "worldFill": "void"},
    }
    out = HERE / "graphite-pile.openmc-studio.json"
    out.write_text(json.dumps(project, indent=1), encoding="utf-8")
    print(f"Wrote {out}: {len(parts)} parts ({COLS * ROWS} apertures), {len(tallies)} tallies.")


if __name__ == "__main__":
    main()
