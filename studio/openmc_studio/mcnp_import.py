"""Import an MCNP deck that Studio didn't write: geometry and materials, as read-only imported CSG.

openmc_mcnp_adapter (openmc-dev, MIT) reads the deck into an ``openmc.Model``. Studio's imported CSG is a flat list
of cells, each a region tree over a table of surfaces (the format the CAD import writes), so the model is
flattened here: every cell that holds a material (or void) becomes one cell, with the regions of all the cells
above it, the lattice element it sits in, and the translations and rotations of the fills applied. Cells are
grouped into one component per top-level cell and material, each with a preview mesh for the 3D view.

Nothing is guessed. The flattened geometry is checked against OpenMC's own geometry routines on the adapter's
model (``openmc.lib.find_material`` at thousands of points, in a separate process), and the import is refused
if they disagree. What the deck has that this doesn't import (sources, tallies, run settings, and anything the
adapter refuses) is listed in the report. Hexagonal lattices (LAT=2), which the adapter can't read, are read by mcnp_hex.py.

Run as a script by the server:  python -m openmc_studio.mcnp_import <deck> <out.json>
"""
import contextlib
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import warnings
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

try:
    from . import mcnp_hex
except ImportError:  # run as a script: python mcnp_import.py
    import mcnp_hex

MAX_CELLS = 20000          # flattened cells; a lattice of lattices can explode
COMPONENT_CELLS = 1000     # the project format's limit per component; bigger groups are split
PREVIEW_STEPS = (64, 48, 32, 24, 16)  # voxels per axis for the 3D preview, coarser until it fits the budget
PREVIEW_TRIANGLES = 300000             # below the page's CSG_LIMITS (400,000)
CHECK_POINTS = 4000       # over the whole model
CHECK_PER_CELL = 40       # and in each cell's own box
CHECK_MAX = 40000
PALETTE = ["#4a8fd6", "#c8b273", "#888888", "#8fe0c4", "#d67a4a", "#9b7fd4", "#6fbf73", "#e0c48f", "#c85c8e",
           "#5cc8c8", "#b0b060", "#7f8fa6"]


class Refused(Exception):
    """The deck can't be imported faithfully; the message says why, in the user's terms."""


# ── surfaces ─────────────────────────────────────────────────────────────────
def surface_json(s):
    """(type, coeffs) in Studio's imported-CSG vocabulary (index.html CSG_CTORS / csgF)."""
    import openmc
    simple = {openmc.XPlane: ("x-plane", ["x0"]), openmc.YPlane: ("y-plane", ["y0"]), openmc.ZPlane: ("z-plane", ["z0"]),
              openmc.Plane: ("plane", ["a", "b", "c", "d"]), openmc.Sphere: ("sphere", ["x0", "y0", "z0", "r"]),
              openmc.XCylinder: ("x-cylinder", ["y0", "z0", "r"]), openmc.YCylinder: ("y-cylinder", ["x0", "z0", "r"]),
              openmc.ZCylinder: ("z-cylinder", ["x0", "y0", "r"]), openmc.XCone: ("x-cone", ["x0", "y0", "z0", "r2"]),
              openmc.YCone: ("y-cone", ["x0", "y0", "z0", "r2"]), openmc.ZCone: ("z-cone", ["x0", "y0", "z0", "r2"]),
              openmc.Quadric: ("quadric", ["a", "b", "c", "d", "e", "f", "g", "h", "j", "k"])}
    t = simple.get(type(s))
    if t:
        return t[0], {k: float(getattr(s, k)) for k in t[1]}
    if hasattr(s, "_get_base_coeffs") and not isinstance(s, getattr(openmc.surface, "TorusMixin", ())):
        c = [float(x) for x in s._get_base_coeffs()]
        if len(c) == 10:  # a general cylinder or cone: its quadric form
            return "quadric", dict(zip("a b c d e f g h j k".split(), c))
    raise Refused(f"surface {s.id} is a {type(s).__name__}, which Studio's imported geometry can't hold (tori aren't supported).")


def surface_f(t, c, x, y, z):
    """f(x, y, z) for arrays, as index.html csgF (negative = the '-' side)."""
    if t == "plane": return c["a"] * x + c["b"] * y + c["c"] * z - c["d"]
    if t == "x-plane": return x - c["x0"]
    if t == "y-plane": return y - c["y0"]
    if t == "z-plane": return z - c["z0"]
    if t == "sphere": return (x - c["x0"]) ** 2 + (y - c["y0"]) ** 2 + (z - c["z0"]) ** 2 - c["r"] ** 2
    if t == "x-cylinder": return (y - c["y0"]) ** 2 + (z - c["z0"]) ** 2 - c["r"] ** 2
    if t == "y-cylinder": return (x - c["x0"]) ** 2 + (z - c["z0"]) ** 2 - c["r"] ** 2
    if t == "z-cylinder": return (x - c["x0"]) ** 2 + (y - c["y0"]) ** 2 - c["r"] ** 2
    if t == "x-cone": return (y - c["y0"]) ** 2 + (z - c["z0"]) ** 2 - c["r2"] * (x - c["x0"]) ** 2
    if t == "y-cone": return (x - c["x0"]) ** 2 + (z - c["z0"]) ** 2 - c["r2"] * (y - c["y0"]) ** 2
    if t == "z-cone": return (x - c["x0"]) ** 2 + (y - c["y0"]) ** 2 - c["r2"] * (z - c["z0"]) ** 2
    if t == "quadric":
        return (c["a"] * x * x + c["b"] * y * y + c["c"] * z * z + c["d"] * x * y + c["e"] * y * z + c["f"] * x * z
                + c["g"] * x + c["h"] * y + c["j"] * z + c["k"])
    raise ValueError(t)


class Table:
    """Surfaces shared across cells, deduplicated by type and coefficients (to 12 significant digits)."""

    def __init__(self):
        self.by_key, self.rows, self.memo = {}, [], {}

    def id_of(self, s):
        if id(s) in self.memo:
            return self.memo[id(s)]
        t, c = surface_json(s)
        key = (t,) + tuple(float(f"{c[k]:.12g}") for k in sorted(c))
        if key not in self.by_key:
            self.by_key[key] = len(self.rows) + 1  # integer ids, as the project format requires
            self.rows.append({"id": self.by_key[key], "type": t, "coeffs": c})
        self.memo[id(s)] = self.by_key[key]
        return self.by_key[key]


def region_json(r, table):
    import openmc
    if isinstance(r, openmc.Halfspace):
        return {"half": r.side, "s": table.id_of(r.surface)}
    if isinstance(r, (openmc.Intersection, openmc.Union)):
        op = "and" if isinstance(r, openmc.Intersection) else "or"
        return _simplify({"op": op, "args": [region_json(a, table) for a in r]})
    if isinstance(r, openmc.Complement):
        return {"op": "not", "arg": region_json(r.node, table)}
    raise Refused(f"a region of type {type(r).__name__} can't be imported.")


def _simplify(node):
    """Flatten nested and-of-and / or-of-or and drop repeated terms. Flattening a lattice stacks the regions of
    every level above a cell, which repeat the same half-spaces many times over; the meaning is unchanged."""
    args, seen = [], set()
    for a in node["args"]:
        for b in (a["args"] if a.get("op") == node["op"] else [a]):
            key = json.dumps(b, sort_keys=True)
            if key not in seen:
                seen.add(key)
                args.append(b)
    return args[0] if len(args) == 1 else {"op": node["op"], "args": args}


def region_eval(node, surfs, x, y, z, cache):
    if "half" in node:
        s = node["s"]
        if s not in cache:
            sf = surfs[s]
            cache[s] = surface_f(sf["type"], sf["coeffs"], x, y, z)
        return cache[s] < 0 if node["half"] == "-" else cache[s] > 0
    if node["op"] == "and":
        out = np.ones_like(x, dtype=bool)
        for a in node["args"]:
            out &= region_eval(a, surfs, x, y, z, cache)
        return out
    if node["op"] == "or":
        out = np.zeros_like(x, dtype=bool)
        for a in node["args"]:
            out |= region_eval(a, surfs, x, y, z, cache)
        return out
    return ~region_eval(node["arg"], surfs, x, y, z, cache)


# ── flattening ───────────────────────────────────────────────────────────────
def _and(regions):
    import openmc
    regions = [r for r in regions if r is not None]
    if not regions:
        return None
    return regions[0] if len(regions) == 1 else openmc.Intersection(regions)


def _box_region(lo, hi):
    """An axis-aligned box as a region (None for an unbounded side)."""
    import openmc
    parts = []
    for ax, a, b in zip("xyz", lo, hi):
        P = {"x": openmc.XPlane, "y": openmc.YPlane, "z": openmc.ZPlane}[ax]
        if math.isfinite(a):
            parts.append(+P(a))
        if math.isfinite(b):
            parts.append(-P(b))
    return _and(parts)


class Placer:
    """Walk the model from the root universe down, carrying the map from local to global coordinates.

    OpenMC places a filled universe so that a point x of the parent is at y = R (x - t) in the universe
    (cell.translation t, cell.rotation R); lattices place element universes at the element's centre. A region
    written in local coordinates is brought to global ones by applying the inverse maps, innermost first, which
    openmc's Region.rotate / Region.translate do on copies of the surfaces."""

    def __init__(self, table):
        self.table, self.cells, self.names = table, [], {}

    def to_global(self, region, chain):
        """chain: the steps from global coordinates down to this level, outermost first: ('tr', t) means
        y = x - t, ('rot', R) means y = R x. A region written at this level is brought up by undoing them,
        innermost first (translate by t; rotate by R^T)."""
        if region is None:
            return None
        for kind, v in reversed(chain):
            region = region.translate(v) if kind == "tr" else region.rotate(np.asarray(v).T)
        return region

    def place(self, universe, chain, above, top, depth=0):
        import openmc
        if depth > 12:
            raise Refused("universes are nested more than 12 deep.")
        for cell in universe.cells.values():
            reg = self.to_global(cell.region, chain)
            here = above + [reg]
            fill = cell.fill
            if fill is None or isinstance(fill, openmc.Material):
                self.emit(cell, here, fill, top if top is not None else cell)
            elif isinstance(fill, openmc.Universe):
                self.place(fill, chain + self.cell_chain(cell), here, top if top is not None else cell, depth + 1)
            elif isinstance(fill, openmc.RectLattice):
                self.lattice(fill, chain + self.cell_chain(cell), here, top if top is not None else cell, depth)
            elif isinstance(fill, openmc.HexLattice):
                self.hex_lattice(fill, chain + self.cell_chain(cell), here, top if top is not None else cell, depth)
            else:
                raise Refused(f"cell {cell.id} has a fill of type {type(fill).__name__} (distributed materials?), "
                              f"which isn't imported yet.")

    @staticmethod
    def cell_chain(cell):
        """How a cell's fill sits in it, as chain steps: OpenMC moves a point x of the parent to y = R (x - t)."""
        out = []
        if getattr(cell, "translation", None) is not None:
            out.append(("tr", tuple(float(v) for v in cell.translation)))
        if getattr(cell, "rotation", None) is not None:
            out.append(("rot", np.asarray(cell.rotation_matrix, float)))
        return out

    def lattice(self, lat, chain, above, top, depth):
        """Each element of a RectLattice (and the outer universe, repeated beyond the array, as OpenMC does)
        that meets the region above it."""
        glob = _and(above)
        bb = glob.bounding_box if glob is not None else None
        if bb is None or not all(math.isfinite(v) for v in list(bb[0]) + list(bb[1])):
            raise Refused(f"lattice {lat.id} fills an unbounded region, so its elements can't be listed.")
        ll, pitch = np.asarray(lat.lower_left, float), np.asarray(lat.pitch, float)
        nd = len(pitch)
        shape = list(lat.shape)
        # the element range the region's box covers, in the lattice's own coordinates: bring the box's corners in
        corners = np.array([[x, y, z] for x in (bb[0][0], bb[1][0]) for y in (bb[0][1], bb[1][1]) for z in (bb[0][2], bb[1][2])])
        local = self.to_local(corners, chain)
        lo, hi = local.min(axis=0), local.max(axis=0)
        rng = [range(int(math.floor((lo[k] - ll[k]) / pitch[k])), int(math.floor((hi[k] - ll[k]) / pitch[k])) + 1)
               for k in range(nd)]
        count = math.prod(len(r) for r in rng)
        if count + len(self.cells) > MAX_CELLS:
            raise Refused(f"lattice {lat.id} would flatten into more than {MAX_CELLS} cells.")
        for idx in np.ndindex(*[len(r) for r in rng]):
            ijk = tuple(r[i] for r, i in zip(rng, idx))
            inside = all(0 <= ijk[k] < shape[k] for k in range(nd))
            u = lat.get_universe(ijk if nd == 3 else ijk[:2]) if inside else lat.outer
            if u is None:
                continue
            e_lo = [ll[k] + ijk[k] * pitch[k] for k in range(nd)] + [-math.inf] * (3 - nd)
            e_hi = [ll[k] + (ijk[k] + 1) * pitch[k] for k in range(nd)] + [math.inf] * (3 - nd)
            centre = tuple((a + b) / 2 if math.isfinite(a) else 0.0 for a, b in zip(e_lo, e_hi))
            box = self.to_global(_box_region(e_lo, e_hi), chain)
            self.place(u, chain + [("tr", centre)], above + [box], top, depth + 1)

    def hex_lattice(self, lat, chain, above, top, depth):
        """Each element of a HexLattice that meets the region above it. An element's centre is found from the
        lattice's pitch and orientation and its universe is asked from OpenMC (find_element), so OpenMC's own ring
        and index order decides which universe sits where."""
        import openmc
        glob = _and(above)
        bb = glob.bounding_box if glob is not None else None
        if bb is None or not all(math.isfinite(v) for v in list(bb[0]) + list(bb[1])):
            raise Refused(f"lattice {lat.id} fills an unbounded region, so its elements can't be listed.")
        p = float(lat.pitch[0])
        three = len(lat.pitch) == 2
        pz = float(lat.pitch[1]) if three else None
        s3 = math.sqrt(3.0) / 2
        t1, t2 = ((s3 * p, p / 2), (0.0, p)) if lat.orientation == "y" else ((p, 0.0), (p / 2, s3 * p))
        cx, cy = float(lat.center[0]), float(lat.center[1])
        corners = np.array([[x, y, z] for x in (bb[0][0], bb[1][0]) for y in (bb[0][1], bb[1][1]) for z in (bb[0][2], bb[1][2])])
        local = self.to_local(corners, chain)
        lo, hi = local.min(axis=0), local.max(axis=0)
        reach = max(math.hypot(x - cx, y - cy) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]))
        m = int(math.ceil(reach / (s3 * p))) + 1
        nz = (lat.num_axial or len(lat.universes)) if three else 1
        z0 = float(lat.center[2]) - (nz - 1) / 2 * pz if three else 0.0
        klo = khi = 0
        if three:
            if not (math.isfinite(lo[2]) and math.isfinite(hi[2])):
                raise Refused(f"lattice {lat.id} fills a region unbounded in z, so its levels can't be listed.")
            klo = min(0, int(math.floor((lo[2] - (z0 - pz / 2)) / pz + 1e-9)))
            khi = max(nz - 1, int(math.ceil((hi[2] - (z0 - pz / 2)) / pz - 1e-9)) - 1)
        if (2 * m + 1) ** 2 * (khi - klo + 1) > 40 * MAX_CELLS:
            raise Refused(f"lattice {lat.id} would be searched over too many elements.")
        normals = [(math.cos(a), math.sin(a)) for a in (math.radians(30 + 60 * k) for k in range(6))] if lat.orientation == "y"             else [(math.cos(a), math.sin(a)) for a in (math.radians(60 * k) for k in range(6))]
        for k in range(klo, khi + 1):
            for j in range(-m, m + 1):
                for i in range(-m, m + 1):
                    ex, ey = cx + i * t1[0] + j * t2[0], cy + i * t1[1] + j * t2[1]
                    dx, dy = max(lo[0] - ex, 0.0, ex - hi[0]), max(lo[1] - ey, 0.0, ey - hi[1])
                    if math.hypot(dx, dy) > p / math.sqrt(3.0) + 1e-9:
                        continue
                    ez = z0 + k * pz if three else 0.0
                    if three and (ez + pz / 2 <= lo[2] or ez - pz / 2 >= hi[2]):
                        continue
                    idx, _ = lat.find_element((ex, ey, ez))
                    u = lat.get_universe(idx) if lat.is_valid_index(idx) else lat.outer
                    if u is None or getattr(u, "_studio_filler", False):
                        continue
                    faces = [openmc.Plane(a=nx, b=ny, c=0.0, d=nx * ex + ny * ey + p / 2) for nx, ny in normals]
                    parts = [-f for f in faces]
                    if three:
                        parts += [+openmc.ZPlane(ez - pz / 2), -openmc.ZPlane(ez + pz / 2)]
                    box = self.to_global(_and(parts), chain)
                    self.place(u, chain + [("tr", (ex, ey, ez))], above + [box], top, depth + 1)

    @staticmethod
    def to_local(pts, chain):
        """Global points (rows) to this level's coordinates: the chain's steps, outermost first."""
        p = np.asarray(pts, float)
        for kind, v in chain:
            p = p - np.asarray(v) if kind == "tr" else p @ np.asarray(v).T
        return p

    def emit(self, cell, regions, fill, top):
        if len(self.cells) >= MAX_CELLS:
            raise Refused(f"the deck flattens into more than {MAX_CELLS} cells.")
        self.cells.append({"cell": cell, "regions": regions, "material": fill, "top": top})


# ── the import ───────────────────────────────────────────────────────────────
def material_names(text):
    """Names for materials from the comment line right above each M card ('c Water' then 'M1 ...')."""
    names, last = {}, None
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"^[cC](?:\s+(.*))?$", s)
        if m and not re.match(r"^[cC]\s*@studio", s):
            last = (m.group(1) or "").strip() or None
            continue
        mm = re.match(r"^[mM](\d+)(\s|$)", s)
        if mm and last:
            name = re.sub(r"^[-=*\s]*(material\s+\d+\s*[:.-]\s*)?", "", last, flags=re.I)
            name = re.sub(r",?\s*rho\s*=.*$", "", name, flags=re.I).strip(" -=*")
            if name:
                names[int(mm.group(1))] = name[:60]
        if s and not m:
            last = None
    return names



def studio_material(mat, index, names):
    """A Studio material from the deck's. The deck's own fractions and density are kept when Studio can hold them
    (a g/cm3 density with all-weight or all-atom fractions): converting weight fractions to atom fractions here
    would use Python's atomic masses, and OpenMC's run converts back with the nuclear data's, which differ by
    about 1e-4. An atom/b-cm density (Studio stores g/cm3) is converted, and the report says so."""
    sab = ", ".join(n for n, _ in getattr(mat, "_sab", []) or [])
    base = {"mcnp": mat.id, "name": names.get(mat.id) or mat.name or f"Material {mat.id}",
            "color": PALETTE[index % len(PALETTE)], "sab": sab}
    types = {n.percent_type for n in mat.nuclides}
    if mat.density_units == "g/cm3" and len(types) == 1 and not getattr(mat, "_elements", None) and mat.nuclides:
        total = sum(abs(n.percent) for n in mat.nuclides)
        parts = ", ".join(f"{n.name}:{float(f'{abs(n.percent) / total:.12g}')}" for n in mat.nuclides)
        return {**base, "density": float(f"{abs(mat.density):.12g}"), "frac": types.pop(), "comps": parts, "converted": False}
    comps = mat.get_nuclide_atom_densities()
    total = sum(comps.values())
    if not total > 0:
        raise Refused(f"material {mat.id} has no nuclides.")
    parts = ", ".join(f"{n}:{float(f'{v / total:.12g}')}" for n, v in comps.items())
    return {**base, "density": float(f"{mat.get_mass_density():.12g}"), "frac": "ao", "comps": parts, "converted": True}


def preview_mesh(surfs, cells, bounds, key, res):
    """A voxel preview of one component: the faces between its cells and anything else, at up to `res` voxels
    per axis. The slice view and the transport use the exact surfaces; this is only what the 3D view draws."""
    lo, hi = np.array(bounds[:3]), np.array(bounds[3:])
    span = np.maximum(hi - lo, 1e-9)
    n = np.maximum(2, np.minimum(res, np.ceil(span / span.max() * res))).astype(int)
    axes = [lo[k] + (np.arange(n[k]) + 0.5) * span[k] / n[k] for k in range(3)]
    X, Y, Z = np.meshgrid(*axes, indexing="ij")
    inside = np.zeros(X.shape, dtype=bool)
    for c in cells:
        inside |= region_eval(c["region"], surfs, X, Y, Z, {})
    pad = np.pad(inside, 1)
    pos, tri, vid = [], [], {}
    step = span / n

    def vert(i, j, k):
        key_ = (i, j, k)
        if key_ not in vid:
            vid[key_] = len(pos) // 3
            pos.extend(float(v) for v in lo + np.array(key_) * step)
        return vid[key_]
    for ax in range(3):
        a = np.diff(pad.astype(np.int8), axis=ax)
        for sign in (1, -1):
            idx = np.argwhere(a == sign)
            for q in idx:
                g = q - 1
                g[ax] += 1  # the face at the far side of voxel g - e_ax
                u, v = [(ax + 1) % 3, (ax + 2) % 3]
                c0 = list(g)
                c1 = list(g); c1[u] += 1
                c2 = list(g); c2[u] += 1; c2[v] += 1
                c3 = list(g); c3[v] += 1
                ids = [vert(*c) for c in (c0, c1, c2, c3)]
                tri.extend([ids[0], ids[1], ids[2], ids[0], ids[2], ids[3]] if sign < 0 else
                           [ids[0], ids[2], ids[1], ids[0], ids[3], ids[2]])
    return {"conversion": key, "count": len(tri) // 3, "positions_cm": pos, "triangles": tri,
            "note": f"voxel preview {n[0]}x{n[1]}x{n[2]}"}


def check_against_openmc(model, surfs, flat, bounds, boxes=(), n=CHECK_POINTS, per_box=CHECK_PER_CELL):
    """Material at random points: the flattened cells vs OpenMC's own C++ geometry on the adapter's model.
    Points spread over the whole model, plus `per_box` in each cell's own box, so a small cell in a big model is
    checked too (at most CHECK_MAX points)."""
    lo, hi = np.array(bounds[:3]), np.array(bounds[3:])
    rng = np.random.default_rng(12345)
    pts = [lo + (hi - lo) * rng.random((n, 3))]
    boxes = list(boxes)
    if boxes:
        per = max(4, min(per_box, (CHECK_MAX - n) // len(boxes)))
        for b in boxes:
            blo, bhi = np.array(b[:3]), np.array(b[3:])
            pts.append(blo + (bhi - blo) * rng.random((per, 3)))
    pts = np.concatenate(pts)
    n = len(pts)
    X, Y, Z = pts[:, 0], pts[:, 1], pts[:, 2]
    mine = np.full(n, -1, dtype=np.int64)  # material id, 0 void, -1 no cell
    count = np.zeros(n, dtype=np.int64)
    for c in flat:
        m = region_eval(c["region"], surfs, X, Y, Z, {})
        count += m
        mine[m] = c["mat_id"]
    work = tempfile.mkdtemp(prefix="studio-mcnp-check-")
    model_xml = os.path.join(work, "model.xml")
    with contextlib.redirect_stdout(io.StringIO()):
        model.export_to_model_xml(model_xml)
    np.save(os.path.join(work, "pts.npy"), pts)
    probe = os.path.join(work, "probe.py")
    Path(probe).write_text(PROBE)
    r = subprocess.run([sys.executable, probe, model_xml, os.path.join(work, "pts.npy"), os.path.join(work, "out.json")],
                       capture_output=True, text=True, timeout=1800, cwd=work)
    if r.returncode:
        raise Refused("OpenMC couldn't load the converted model to check it: " + (r.stdout + r.stderr).strip()[-400:])
    ref = np.array(json.loads(Path(os.path.join(work, "out.json")).read_text()), dtype=np.int64)
    overlap = int((count > 1).sum())
    considered = ref != -1
    agree = int(((mine == ref) & considered).sum())
    bad = np.flatnonzero((mine != ref) & considered)
    return {"points": int(considered.sum()), "agree": agree, "overlaps": overlap,
            "examples": [{"at": [round(float(v), 4) for v in pts[i]], "imported": int(mine[i]), "openmc": int(ref[i])}
                         for i in bad[:5]]}


PROBE = r'''
import json, os, sys, tempfile, xml.etree.ElementTree as ET
import numpy as np
import openmc.lib
model_xml, pts_file, out = sys.argv[1:4]
root = ET.parse(model_xml).getroot()
for tag in ("settings", "tallies", "plots"):
    for el in root.findall(tag):
        root.remove(el)
root.append(ET.fromstring("<settings><run_mode>fixed source</run_mode><particles>10</particles><batches>1</batches>"
                          "<source><space type='point' parameters='0 0 0'/></source></settings>"))
surfs = root.findall("./geometry/surface")
if surfs and not any(s.get("boundary", "transmission") != "transmission" for s in surfs):
    surfs[0].set("boundary", "vacuum")  # boundary types don't change which cell holds a point
d = tempfile.mkdtemp()
os.chdir(d)
ET.ElementTree(root).write("model.xml")
openmc.lib.init(output=False)
res = []
for p in np.load(pts_file):
    try:
        m = openmc.lib.find_material(tuple(float(x) for x in p))
    except Exception:
        res.append(-1)
        continue
    res.append(0 if m is None else int(m.id))
openmc.lib.finalize()
json.dump(res, open(out, "w"))
'''


def import_deck(path):
    import openmc
    from openmc_mcnp_adapter import mcnp_to_model
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    notes = []
    openmc.reset_auto_ids()
    try:
        with warnings.catch_warnings(record=True) as w, contextlib.redirect_stdout(io.StringIO()):
            warnings.simplefilter("always")
            model, hex_cells = mcnp_hex.read_deck(path, mcnp_to_model)
        notes += sorted({str(x.message)[:200] for x in w})
        if hex_cells:
            notes.append("Hexagonal lattice (LAT=2) in cell " + ", ".join(str(c) for c in hex_cells)
                         + ": read by Studio itself (the converter can't), in the manual's index order.")
    except mcnp_hex.Unsupported as e:
        raise Refused(f"a hexagonal lattice can't be imported: {e}.")
    except NotImplementedError as e:
        raise Refused(f"the converter doesn't support this yet: {e}.")
    except Exception as e:  # noqa: BLE001
        raise Refused(f"the deck couldn't be read ({type(e).__name__}: {str(e)[:300]}).")
    geom = model.geometry
    # importance-0 cells mark the outside world in MCNP; Studio has its own world boundary
    imp0 = {int(m.group(1)) for m in re.finditer(r"(?im)^\s*(\d+)\b[^\n]*\bimp:[a-z,|]+\s*=?\s*0(?:\.0*)?\b", text)}
    if not geom.root_universe.cells:
        raise Refused("the deck has no cells at the top level: every cell is in a universe (U=) that no cell fills.")
    table = Table()
    placer = Placer(table)
    placer.place(geom.root_universe, [], [], None)
    names = material_names(text)
    mats = {}
    for i, m in enumerate(sorted({c["material"].id: c["material"] for c in placer.cells if c["material"] is not None}.values(),
                                 key=lambda m: m.id)):
        mats[m.id] = studio_material(m, i, names)
    # every placed cell once (a lattice places the same cell many times, so they're kept apart by position here,
    # not by cell number), with its box; zero-volume placements (an element that only touches its parent along a
    # face) are dropped
    flat, voids, skipped, empty = [], [], [], 0
    for c in placer.cells:
        cell, top = c["cell"], c["top"]
        if top.id in imp0 or cell.id in imp0:
            skipped.append(cell.id)
            continue
        region = _and(c["regions"])
        if region is None:
            raise Refused(f"cell {cell.id} fills all of space, which Studio's world can't hold.")
        box = None
        try:
            bb = region.bounding_box
            if all(math.isfinite(v) for v in list(bb[0]) + list(bb[1])):
                box = [float(v) for v in list(bb[0]) + list(bb[1])]
        except Exception:  # noqa: BLE001
            box = None
        if box is not None and any(box[i + 3] - box[i] <= 1e-9 for i in range(3)):
            empty += 1
            continue
        row = {"id": cell.id, "top": top.id, "name": cell.name or f"Cell {cell.id}", "box": box,
               "mat_id": c["material"].id if c["material"] is not None else 0, "region": region_json(region, table)}
        # void: Studio's world is void wherever no part or imported cell is, so void cells aren't imported (the
        # check still counts them, as void)
        (voids if c["material"] is None else flat).append(row)
    if not flat:
        raise Refused("the deck has no cell with a material once the outside (importance 0) cells are set aside.")
    unbounded = sorted({c["id"] for c in flat if c["box"] is None})
    if unbounded:
        raise Refused(f"cells {unbounded[:6]} extend to infinity; give the deck an outside cell with importance 0 so "
                      f"Studio knows where the model ends.")
    boxes = [c["box"] for c in flat + voids if c["box"] is not None]
    bounds = [float(min(b[i] for b in boxes)) for i in range(3)] + [float(max(b[i + 3] for b in boxes)) for i in range(3)]
    surfs = {r["id"]: r for r in table.rows}
    check = check_against_openmc(model, surfs, flat + voids, bounds, boxes=boxes)
    if check["agree"] < check["points"] or check["overlaps"]:
        raise Refused(f"the flattened geometry doesn't match OpenMC's reading of the deck at "
                      f"{check['points'] - check['agree']} of {check['points']} points ({check['overlaps']} overlapping); "
                      f"e.g. {check['examples'][:2]}. Nothing was imported.")
    void_cells = sorted({c["id"] for c in voids})
    # components: one per top-level cell and material (split in chunks of COMPONENT_CELLS)
    comps, counts = {}, {}
    for c in flat:
        base = (c["top"], c["mat_id"])
        counts[base] = counts.get(base, 0) + 1
        key = base + ((counts[base] - 1) // COMPONENT_CELLS,)
        k = comps.setdefault(key, {"cells": [], "bounds": None})
        k["cells"].append(c)
        b = c["box"]
        k["bounds"] = b if k["bounds"] is None else [min(k["bounds"][i], b[i]) for i in range(3)] + \
            [max(k["bounds"][i + 3], b[i + 3]) for i in range(3)]
    components = []
    res_i = 0
    while True:  # the preview mesh, coarser until the whole import fits the 3D budget
        meshes = {key: preview_mesh(surfs, k["cells"], k["bounds"], f"{sha}|cell{key[0]}-m{key[1]}-{key[2]}", PREVIEW_STEPS[res_i])
                  for key, k in comps.items()}
        if sum(m["count"] for m in meshes.values()) <= PREVIEW_TRIANGLES or res_i == len(PREVIEW_STEPS) - 1:
            break
        res_i += 1
    parts = {}
    for key in comps:
        parts[key[:2]] = parts.get(key[:2], 0) + 1
    for (top, mid, chunk), k in comps.items():
        used = set()
        for c in k["cells"]:
            _used(c["region"], used)
        name = f"Cell {top} · {mats[mid]['name']}" + (f" ({chunk + 1}/{parts[(top, mid)]})" if parts[(top, mid)] > 1 else "")
        key = f"cell{top}-m{mid}-{chunk}"
        components.append({"key": key, "name": name, "bounds_cm": k["bounds"],
                           "surfaces": [surfs[s] for s in sorted(used)],
                           "cells": [{"name": c["name"], "region": c["region"], "mcnp_cell": c["id"],
                                      "material_mcnp": mid} for c in k["cells"]],
                           "display": meshes[(top, mid, chunk)]})
    from openmc_studio import mcnp_cards_in
    cards = mcnp_cards_in.parse(text)
    import openmc_mcnp_adapter as oma
    return {"ok": True, "source_sha256": sha, "adapter": "openmc_mcnp_adapter",
            "versions": {"openmc": openmc.__version__, "openmc_mcnp_adapter": getattr(oma, "__version__", None)},
            "materials": list(mats.values()), "components": components, "bounds_cm": bounds,
            "cells": len(flat), "outside_cells": sorted(set(skipped)), "void_cells": len(void_cells),
            "empty_placements": empty, "check": check,
            "sources": cards["sources"], "tallies": cards["tallies"], "run_settings": cards["settings"],
            "not_imported": cards["refused"], "import_notes": cards["notes"], "notes": notes}


def _used(node, out):
    if "half" in node:
        out.add(node["s"])
    elif node["op"] == "not":
        _used(node["arg"], out)
    else:
        for a in node["args"]:
            _used(a, out)


def main(argv=None):
    deck, out = (argv or sys.argv[1:])[:2]
    try:
        rep = import_deck(deck)
    except Refused as e:
        rep = {"ok": False, "error": str(e)}
    Path(out).write_text(json.dumps(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
