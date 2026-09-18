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
  Modeled as an array group ("Apertures (12×11 array)") with nested row groups for easy collapsing
  and lattice export.
- Source drawer: 0.75 in × 8 in × 0.75 in, long side along y (parallel to the apertures), centered
  under the middle of the pile, about 1 ft above the bottom.

Coordinates: origin at the center of the whole pile; x across the front face, y into the pile (the
front face is y = -4 ft), z up. Units are cm, as Studio stores them.

Pre-lab measurement positions:
- Measurement channel: 7th column from left (+4 in right of center), 3rd row from bottom (Row 3).
- 10 measurements along the depth of channel (y) in 8-inch increments.
- Transverse measurements across the front face (x) through row 3 at 40 in depth.
- Vertical measurements up the height (z) through column 7 at 40 in depth.
- He-3 proportional counter detector response tallies for MT 103 He-3(n,p)T (5316 b at 0.0253 eV).
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


def mesh(tid, name, n, lo, hi, detector="none", response_mat="", response_score="(n,p)"):
    m = {"id": tid, "name": name, "kind": "mesh", "cells": [], "scores": ["flux"], "ebins": "",
         "nx": n[0], "ny": n[1], "nz": n[2], "lx": r(lo[0]), "ly": r(lo[1]), "lz": r(lo[2]),
         "ux": r(hi[0]), "uy": r(hi[1]), "uz": r(hi[2])}
    if detector != "none":
        m["detector"] = detector
        m["responseMat"] = response_mat
        m["responseScore"] = response_score
        m["responseScale"] = "macro"
    return m


def main():
    graphite = library_material(63, "m_graphite", "#5d636b", sab="c_Graphite")
    air = library_material(4, "m_air", "#8fb8cf")
    he3 = {
        "id": "m_he3",
        "name": "He-3 detector gas (4 atm)",
        "color": "#8fe0c4",
        "density": 0.000502,
        "frac": "ao",
        "comps": "He3:1",
        "sab": "",
        "ref": "Ideal gas, 4 atm, 20 °C",
    }

    aperture_center = [0, 0, r((ROW_Z[0] + ROW_Z[-1]) / 2)]
    groups = [
        {
            "id": "g_apertures",
            "name": "Apertures (12×11 array)",
            "parent": None,
            "x": aperture_center[0],
            "y": aperture_center[1],
            "z": aperture_center[2],
            "lattice": {
                "nx": COLS,
                "ny": 1,
                "nz": ROWS,
                "dx": r(PITCH),
                "dy": r(DEPTH),
                "dz": r(PITCH),
                "fill": graphite["id"],
                "asLattice": True,
            },
        }
    ]

    parts = []
    # Apertures arranged by row (top to bottom): each row is a nested sub-group under g_apertures.
    # Parts higher in the Explorer win where shapes overlap, so the air channels are cut out
    # of the solid graphite block listed after them.
    for i, z in enumerate(reversed(ROW_Z)):          # top row first, like reading the front view
        row = ROWS - i
        row_gid = f"g_row_{row}"
        is_meas_row = (row == 3)
        row_name = f"Row {row} (z = {round((z - Z_BOTTOM)/IN, 1)} in)" + (" [Measurement]" if is_meas_row else "")
        groups.append({
            "id": row_gid,
            "name": row_name,
            "parent": "g_apertures",
            "x": 0,
            "y": 0,
            "z": r(z),
        })
        for c, x in enumerate(COL_X):
            col = c + 1
            is_meas_channel = (is_meas_row and col == 7)
            part_name = f"Aperture r{row} c{col}" + (" (Channel Col 7, 40 in deep)" if is_meas_channel else "")
            parts.append(box(f"ap_r{row}_c{col}", part_name, x, 0, z,
                             SIDE, DEPTH, SIDE, air["id"], ry=45, group=row_gid))

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
        mesh("t_he3_x", "He-3 response across (x), row 3, 40 in deep", (96, 1, 1),
             (-WIDTH / 2, DEPTH_40 - t, CHANNEL_Z - t), (WIDTH / 2, DEPTH_40 + t, CHANNEL_Z + t),
             detector="he3", response_mat="m_he3", response_score="(n,p)"),
        mesh("t_he3_y", "He-3 response in depth (y), col 7 row 3", (1, 96, 1),
             (CHANNEL_X - t, -DEPTH / 2, CHANNEL_Z - t), (CHANNEL_X + t, DEPTH / 2, CHANNEL_Z + t),
             detector="he3", response_mat="m_he3", response_score="(n,p)"),
        mesh("t_he3_z", "He-3 response up (z), col 7, 40 in deep", (1, 1, 120),
             (CHANNEL_X - t, DEPTH_40 - t, Z_BOTTOM), (CHANNEL_X + t, DEPTH_40 + t, -Z_BOTTOM),
             detector="he3", response_mat="m_he3", response_score="(n,p)"),
        mesh("t_map", "Flux map (XZ) at 40 in deep", (96, 1, 120),
             (-WIDTH / 2, DEPTH_40 - t, Z_BOTTOM), (WIDTH / 2, DEPTH_40 + t, -Z_BOTTOM)),
    ]

    project = {
        "materials": [graphite, air, he3],
        "parts": parts,
        "groups": groups,
        "sources": [source],
        "tallies": tallies,
        "settings": {"name": "NE403 graphite pile", "runMode": "fixed source", "particles": 2000, "batches": 5,
                     "inactive": 0, "seed": 12345, "maxTracks": 20, "track": "", "photon": False,
                     "worldShape": "box", "worldR": r(HEIGHT / 2 + 1 * FT), "worldBC": "vacuum", "worldFill": "void"},
    }
    out = HERE / "graphite-pile.openmc-studio.json"
    out.write_text(json.dumps(project, indent=1), encoding="utf-8")
    print(f"Wrote {out}: {len(parts)} parts ({COLS * ROWS} apertures across {len(groups)} groups), {len(tallies)} tallies.")


if __name__ == "__main__":
    main()
