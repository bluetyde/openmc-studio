"""The two-step driver of the nodal package: from an OpenMC core lattice to two-group constants by kind, and a nodal solve (plan P1, the part after the wrapper).

Given the core's `openmc.RectLattice` (one universe per assembly position, 2D) and its materials, it runs the small Monte Carlo pieces that E13 and E15 settled on, and hands
the result to `nodal.solve_core`:

  fuel kind        one run of the assembly universe alone with reflective faces (an infinite lattice), tallied in CASMO-25 with every type including the diffusion
                   coefficient; its fine-group constants are collapsed with the critical-buckling spectrum (`nodal.critical_buckling_fuel`);
  reflector kind   one run per distinct strip taken from the core map: a line through the middle of the core, from an edge inwards (the reflector layers at the edge, then up
                   to three fuel assemblies behind them), reflective at the inner end, vacuum at the outer one; tallied the same way and condensed by OpenMC to two groups.
                   A kind that appears in several strips gets the mean of their constants (E13 did that for the checkerboard).

A kind is a fuel kind when its universe holds a nuclide with Z >= 90 and a reflector kind when it does not. One composition per kind: two positions that share a universe get
the same constants, whatever their neighbours (the found limit: wrapper universes make them separate kinds). Radial two-dimensional only; the axial direction is reflective
in every piece, so axial leakage is not represented. The result carries the recipe and the pieces' k, which are the numbers to look at before trusting the solve.

The core's outer faces are read from the model (`detect_faces`: a plane through the lattice's face with a boundary condition, or what material lies outside it) unless the caller overrides a face; the result records per face what was used and why. Nothing runs at import; a run needs openmc, openndm and nuclear data (OPENMC_CROSS_SECTIONS), and Monte Carlo time: the pieces are small (one assembly and a few of them).
What it was checked against, and what it was not: test/nodal/test_nodal_driver.py and docs/design/nodal-package-plan.md.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import nodal
from .nodal import NodalInputError

FUEL_DEPTH = 3                  # fuel assemblies behind the reflector in a strip (E13)
HEIGHT_CM = 1.0                 # thickness of a piece (reflective z faces) for a two-dimensional lattice; a one-layer three-dimensional lattice (what Studio writes) gives its own z pitch


@dataclass
class Layer:
    """One slab of the model's own material just outside a face of the core lattice, taken into the solve as a ring of nodes (`probe_outside`)."""
    label: str                                   # shared by identical slabs on different sides, so they get one set of constants
    universe: object                             # a universe holding one infinite cell of the material
    width: float                                 # cm
    material: str                                # the material's name, for the messages


@dataclass
class Piece:
    label: str
    role: str                                    # "infinite" or "strip"
    grid: list                                   # [[universe, ...]], one row
    domains: list                                # the universes tallied
    x_bcs: tuple
    widths: list | None = None                   # cm per grid entry when they are not all the lattice pitch (a strip that ends in outside layers)
    k: float = float("nan")
    k_std: float = float("nan")
    seconds: float = 0.0


@dataclass
class TwoStepResult:
    nodal: nodal.NodalResult
    constants: dict                              # kind label -> two-group constants
    kinds: dict                                  # kind label -> {"universe": id, "role": "fuel" | "reflector"}
    pieces: list                                 # (label, role, k, k_std, seconds)
    settings: dict
    faces: dict = field(default_factory=dict)         # per outer face: what was used, from where (model, override, default, assumed) and why
    warnings: list = field(default_factory=list)      # facts about the model that make this method's answer doubtful, in words
    provenance: dict = field(default_factory=dict)


def _is_fissile_nuclide(name: str) -> bool:
    import openmc.data
    try:
        return openmc.data.zam(name)[0] >= 90
    except Exception:
        return False


def is_fuel(universe) -> bool:
    return any(_is_fissile_nuclide(n) for m in universe.get_all_materials().values() for n in m.get_nuclides())


def layer(lattice) -> tuple[np.ndarray, float, float]:
    """(universes as a 2D object array with the top row first, node size, height) of a rectangular lattice with one layer; raises NodalInputError otherwise.
    A two-dimensional lattice gets HEIGHT_CM; a three-dimensional one with a single z layer (Studio's own form) gets its z pitch."""
    import openmc
    if not isinstance(lattice, openmc.RectLattice):
        raise NodalInputError("the nodal driver takes a rectangular lattice (a hexagonal one is not supported)")
    if lattice.outer is not None:
        raise NodalInputError("the lattice has an `outer` universe: positions outside the core must not be a physical region (openndm would treat them as the core's outside); give the reflector as real lattice positions")
    pitch = [float(v) for v in lattice.pitch]
    if abs(pitch[0] - pitch[1]) > 1e-9:
        raise NodalInputError(f"the nodal solver takes square nodes; the lattice pitch is {tuple(pitch)}")
    unis = np.asarray(lattice.universes, dtype=object)
    if lattice.ndim == 2:
        return unis, pitch[0], HEIGHT_CM
    if unis.shape[0] != 1:
        raise NodalInputError(f"the nodal driver takes a lattice with one axial layer; this one has {unis.shape[0]} (axial structure is not represented)")
    return unis[0], pitch[0], pitch[2]


def classify(lattice) -> tuple[dict, list]:
    """(kinds, labels): kinds maps a label to (universe, role); labels is the lattice as rows of labels (top row first). Labels are the universe names, made unique with the id."""
    import openmc
    if not isinstance(lattice, openmc.RectLattice):
        raise NodalInputError("the nodal driver takes a rectangular lattice (a hexagonal one is not supported)")
    unis, pitch, _ = layer(lattice)
    kinds, by_id = {}, {}
    for u in unis.reshape(-1):
        if u.id in by_id:
            continue
        label = f"{(u.name or 'universe')}#{u.id}"
        by_id[u.id] = label
        kinds[label] = (u, "fuel" if is_fuel(u) else "reflector")
    if not any(r == "fuel" for _, r in kinds.values()):
        raise NodalInputError("no assembly in the lattice holds fissile material")
    labels = [[by_id[u.id] for u in row] for row in unis]
    return kinds, labels


def _edge_run(line, kinds, fuel_edge_ok=False):
    """For a line of labels read from one edge inwards: (reflector labels at the edge, fuel labels behind them) or None when the edge is fuel (unless `fuel_edge_ok`: layers of the
    model's own material follow it, so a strip is wanted anyway) or the whole line is reflector."""
    n = 0
    while n < len(line) and kinds[line[n]][1] == "reflector":
        n += 1
    if n == len(line) or (n == 0 and not fuel_edge_ok):
        return None
    fuel = []
    for lab in line[n:n + FUEL_DEPTH]:
        if kinds[lab][1] != "fuel":
            break
        fuel.append(lab)
    return line[:n], fuel


LINE_FACES = ("x_min", "x_max", "y_max", "y_min")      # the face each of the four lines of plan_pieces starts at (left, right, top, bottom)


def plan_pieces(lattice, outside=None) -> tuple[list, dict, list]:
    """The pieces to run, the kinds and the label map. Raises NodalInputError when a reflector kind appears in no strip.
    `outside` maps a face to the list of `Layer`s just outside it (adjacent first); a strip from that edge then ends in those layers instead of in vacuum."""
    outside = outside or {}
    kinds, labels = classify(lattice)
    ny, nx = len(labels), len(labels[0])
    mid_row, mid_col = labels[ny // 2], [row[nx // 2] for row in labels]
    lines = [list(mid_row), list(mid_row[::-1]), list(mid_col), list(mid_col[::-1])]      # each read from an edge inwards
    pieces, seen = [], set()
    for lab, (u, role) in kinds.items():
        if role == "fuel":
            pieces.append(Piece(f"infinite {lab}", "infinite", [[u]], [u], ("reflective", "reflective")))
    for line, face in zip(lines, LINE_FACES):
        layers = list(outside.get(face, ()))
        run = _edge_run(line, kinds, fuel_edge_ok=bool(layers))
        if run is None:
            continue
        refl, fuel = run
        seq = tuple(fuel[::-1]) + tuple(refl[::-1])                   # inner fuel ... outer reflector, the outer end last
        key = seq + tuple(l.label for l in layers)
        if key in seen:
            continue
        seen.add(key)
        grid = [[kinds[lab][0] for lab in seq] + [l.universe for l in layers]]
        domains, ids = [], set()
        for lab in refl:
            if kinds[lab][0].id not in ids:
                ids.add(kinds[lab][0].id)
                domains.append(kinds[lab][0])
        for l in layers:
            if l.universe.id not in ids:
                ids.add(l.universe.id)
                domains.append(l.universe)
        pitch_w = float(lattice.pitch[0])
        widths = [pitch_w] * len(seq) + [l.width for l in layers] if layers else None
        name = " ".join(l.split("#")[0] for l in seq) + ("".join(f" | {l.material} {l.width:g} cm" for l in layers))
        pieces.append(Piece("strip " + name, "strip", grid, domains, ("reflective", "vacuum"), widths))
    covered = {d.id for p in pieces if p.role == "strip" for d in p.domains}
    missing = [lab for lab, (u, role) in kinds.items() if role == "reflector" and u.id not in covered]
    if missing:
        raise NodalInputError(f"no strip through the middle of the core reaches reflector kind(s) {missing}: the driver needs each reflector kind at an edge of the middle row or column")
    return pieces, kinds, labels


def _run_piece(piece: Piece, pitch: float, height: float, materials, settings_kw: dict, workdir: Path):
    import openmc
    import openmc.mgxs
    nx = len(piece.grid[0])
    widths = list(piece.widths) if piece.widths else [pitch] * nx
    x0, y0 = -pitch / 2, -pitch / 2
    x1, y1 = x0 + sum(widths), y0 + pitch
    py0, py1 = openmc.YPlane(y0, boundary_type="reflective"), openmc.YPlane(y1, boundary_type="reflective")
    pz0, pz1 = openmc.ZPlane(-height / 2, boundary_type="reflective"), openmc.ZPlane(height / 2, boundary_type="reflective")
    if piece.widths is None:                      # equal widths: the lattice, as before
        lattice = openmc.RectLattice()
        lattice.universes = piece.grid
        lattice.lower_left, lattice.pitch = (x0, y0), (pitch, pitch)
        px0, px1 = openmc.XPlane(x0, boundary_type=piece.x_bcs[0]), openmc.XPlane(x1, boundary_type=piece.x_bcs[1])
        geometry = openmc.Geometry(openmc.Universe(cells=[openmc.Cell(fill=lattice, region=+px0 & -px1 & +py0 & -py1 & +pz0 & -pz1)]))
    else:                                         # slabs of different widths: one cell per entry, the universe moved to the middle of its slot
        edges = [x0]
        for w in widths:
            edges.append(edges[-1] + w)
        xp = [openmc.XPlane(e) for e in edges]
        xp[0].boundary_type, xp[-1].boundary_type = piece.x_bcs
        cells = []
        for i, u in enumerate(piece.grid[0]):
            c = openmc.Cell(fill=u, region=+xp[i] & -xp[i + 1] & +py0 & -py1 & +pz0 & -pz1)
            c.translation = (0.5 * (edges[i] + edges[i + 1]), 0.0, 0.0)
            cells.append(c)
        geometry = openmc.Geometry(cells)
    st = openmc.Settings()
    st.particles, st.batches, st.inactive = settings_kw["particles"], settings_kw["batches"], settings_kw["inactive"]
    if settings_kw.get("seed"):
        st.seed = int(settings_kw["seed"])
    st.source = openmc.IndependentSource(space=openmc.stats.Box((x0, y0, -height / 2), (x1, y1, height / 2)), constraints={"fissionable": True})
    lib = openmc.mgxs.Library(geometry)
    nodal.configure_library(lib, piece.domains)
    lib.build_library()
    tallies = openmc.Tallies()
    lib.add_to_tallies_file(tallies, merge=True)
    workdir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    sp_path = openmc.Model(geometry, materials, st, tallies).run(output=False, cwd=str(workdir), threads=settings_kw.get("threads"))
    with openmc.StatePoint(sp_path) as sp:
        k = sp.keff
        lib.load_from_statepoint(sp)
    piece.k, piece.k_std, piece.seconds = float(k.nominal_value), float(k.std_dev), time.time() - t0
    return lib


def mean_constants(samples) -> dict:
    """The mean of several two-group constant sets (a reflector kind that appears in more than one strip)."""
    return {f: np.mean([np.asarray(s[f], float) for s in samples], axis=0) for f in nodal.FIELDS}


AXIAL_RATIO = 4.0          # a lattice shorter than this many node widths leaks axially so much that a radial-only answer cannot be close


def model_warnings(pitch: float, height: float, constants: dict) -> list:
    """Plain-words warnings from what is known about the model (not from the answer): the method has no axial leakage and reads no boundary from the model."""
    out = []
    if height < AXIAL_RATIO * pitch:
        out.append(f"The lattice is {height:g} cm tall, {height / pitch:.1f} node widths: axial leakage is large for a core this short and this solve has none (the pieces are axially reflective), "
                   f"so its k is expected to be well above the model's true k, not a small error.")
    return out

# ── the core's outer faces, read from the model ────────────────────────────────────────────────────────────────────────────────────────
FACES = ("x_min", "x_max", "y_min", "y_max")
_FACE_WORDS = {"x_min": "left", "x_max": "right", "y_min": "bottom", "y_max": "top"}


def _core_cell(geometry, lattice):
    """The cell that is filled with the lattice, when it is a cell of the root universe with no rotation; None otherwise."""
    cells = [c for c in geometry.get_all_cells().values() if c.fill is lattice]
    if len(cells) != 1 or cells[0].id not in geometry.root_universe.cells or cells[0].rotation is not None:
        return None
    return cells[0]


def detect_faces(geometry, lattice) -> dict:
    """What the model has at each lateral face of the core lattice: {face: {"type", "position_cm", "detail"}} with type one of
      vacuum | reflective | periodic | white   a plane through the face carries that boundary condition;
      material                                 no boundary condition there: the model goes on (a tank, a reflector block) with the material named in `detail`, or void;
      unknown                                  the lattice is nested, rotated, or the face cannot be placed, so nothing can be said.
    x_min / x_max are the lattice's left and right faces, y_min the bottom and y_max the top (the top row of the map is at y_max)."""
    unis, pitch, height = layer(lattice)
    ny, nx = unis.shape
    cell = _core_cell(geometry, lattice)
    if cell is None:
        return {f: {"type": "unknown", "position_cm": None, "detail": "the lattice is not directly in the root universe (or its cell is rotated), so its faces cannot be placed in the model"} for f in FACES}
    shift = [0.0, 0.0, 0.0] if cell.translation is None else [float(v) for v in cell.translation]
    ll = [float(v) for v in lattice.lower_left]
    pos = {"x_min": ll[0] + shift[0], "x_max": ll[0] + nx * pitch + shift[0], "y_min": ll[1] + shift[1], "y_max": ll[1] + ny * pitch + shift[1]}
    zmid = (ll[2] + height / 2 if len(ll) == 3 else 0.0) + shift[2]
    xmid, ymid = 0.5 * (pos["x_min"] + pos["x_max"]), 0.5 * (pos["y_min"] + pos["y_max"])
    surfaces = list(geometry.get_all_surfaces().values())
    out = {}
    for face, p in pos.items():
        kind = "x-plane" if face.startswith("x") else "y-plane"
        coord = "x0" if face.startswith("x") else "y0"
        tol = 1e-6 * max(1.0, abs(p))
        bcs = sorted({s.boundary_type for s in surfaces if s.type == kind and abs(getattr(s, coord) - p) <= tol and s.boundary_type != "transmission"})
        if len(bcs) > 1:
            raise NodalInputError(f"the {_FACE_WORDS[face]} face of the core lattice (at {p:g} cm) has planes with different boundary conditions: {bcs}")
        if bcs:
            out[face] = {"type": bcs[0], "position_cm": p, "detail": f"a plane at {p:g} cm with boundary condition {bcs[0]}"}
            continue
        eps = 1e-3
        point = {"x_min": (p - eps, ymid, zmid), "x_max": (p + eps, ymid, zmid), "y_min": (xmid, p - eps, zmid), "y_max": (xmid, p + eps, zmid)}[face]
        found = [o for o in geometry.find(point) if hasattr(o, "fill")]
        if not found:
            out[face] = {"type": "unknown", "position_cm": p, "detail": f"nothing is just outside the face at {p:g} cm and no plane with a boundary condition is on it"}
        else:
            fill = found[-1].fill
            name = "void" if fill is None else (getattr(fill, "name", None) or type(fill).__name__)
            out[face] = {"type": "material", "position_cm": p, "detail": f"just outside the face at {p:g} cm the model has {name} (cell {found[-1].name or found[-1].id})"}
    return out


def resolve_faces(detected: dict | None, override: dict | None) -> tuple[dict, dict, list]:
    """(boundaries for the solve, what each face used and why, warnings). An override of a face wins over the model; with `detected` None the model was not read and every face
    not overridden is vacuum, with a warning."""
    override = override or {}
    bad = [f for f in override if f not in FACES]
    if bad:
        raise NodalInputError(f"unknown face(s) {bad}")
    chosen, used, warns = {}, {}, []
    for face in FACES:
        word = _FACE_WORDS[face]
        if face in override:
            chosen[face] = override[face]
            used[face] = {"boundary": override[face], "source": "override", "detail": f"set by the caller: {override[face]}"}
            continue
        if detected is None:
            chosen[face] = "vacuum"
            used[face] = {"boundary": "vacuum", "source": "default", "detail": "the model was not read: vacuum is assumed"}
            warns.append(f"The {word} face is taken as vacuum without looking at the model.")
            continue
        d = detected[face]
        t = d["type"]
        if t in ("vacuum", "reflective"):
            chosen[face] = t
            used[face] = {"boundary": t, "source": "model", "detail": d["detail"]}
        elif t == "material":
            chosen[face] = "vacuum"
            used[face] = {"boundary": "vacuum", "source": "assumed", "detail": d["detail"]}
            warns.append(f"The {word} face: {d['detail']}. OpenMC transports through it; this solve treats the face as vacuum, so material the model has there (a reflector or tank) is not represented.")
        elif t == "unknown":
            chosen[face] = "vacuum"
            used[face] = {"boundary": "vacuum", "source": "assumed", "detail": d["detail"]}
            warns.append(f"The {word} face: {d['detail']}; vacuum is assumed.")
        else:
            raise NodalInputError(f"the {word} face of the core lattice has boundary condition {t!r} in the model, which this solve does not represent; set that face to vacuum or reflective yourself")
    return chosen, used, warns


# ── material outside a face: a tank or reflector the solve can include ──────────────────────────────────────────────────────────────────
MAX_OUTSIDE_CM = 60.0          # a medium that goes on past this is not taken as a slab
STEP_CM = 0.05                 # the probe's step; a layer thinner than this can be missed
MAX_LAYERS = 3
_DIRECTION = {"x_min": (-1.0, 0.0, 0.0), "x_max": (1.0, 0.0, 0.0), "y_min": (0.0, -1.0, 0.0), "y_max": (0.0, 1.0, 0.0)}


def _face_frame(geometry, lattice):
    """(positions, middle of the face along its length, z of the middle, face lengths) of the four lateral faces in the model's coordinates, or None when the lattice cannot be placed."""
    unis, pitch, height = layer(lattice)
    ny, nx = unis.shape
    cell = _core_cell(geometry, lattice)
    if cell is None:
        return None
    shift = [0.0, 0.0, 0.0] if cell.translation is None else [float(v) for v in cell.translation]
    ll = [float(v) for v in lattice.lower_left]
    pos = {"x_min": ll[0] + shift[0], "x_max": ll[0] + nx * pitch + shift[0], "y_min": ll[1] + shift[1], "y_max": ll[1] + ny * pitch + shift[1]}
    zmid = (ll[2] + height / 2 if len(ll) == 3 else 0.0) + shift[2]
    mid = {"x": 0.5 * (pos["y_min"] + pos["y_max"]), "y": 0.5 * (pos["x_min"] + pos["x_max"])}      # along the face: the y of an x face, the x of a y face
    return pos, mid, zmid, {"x": ny * pitch, "y": nx * pitch}


def _walk(geometry, start, direction, max_depth):
    """Walk from `start` along `direction`: ([(cell, s0, s1)], end, s_end). end is "left" when the walk left the geometry (s_end where), "deep" at max_depth. Boundaries are found by bisection."""
    def cell_at(s):
        point = tuple(start[i] + direction[i] * s for i in range(3))
        cells = [o for o in geometry.find(point) if hasattr(o, "fill")]
        return cells[-1] if cells else None
    segs, s0, cur, s = [], 0.0, cell_at(1e-6), 0.0
    if cur is None:
        return [], "left", 0.0
    while s < max_depth:
        nxt = min(s + STEP_CM, max_depth)
        c = cell_at(nxt)
        if (c.id if c is not None else None) != cur.id:
            lo, hi = s, nxt
            for _ in range(40):
                mid = 0.5 * (lo + hi)
                m = cell_at(mid)
                if (m.id if m is not None else None) == cur.id:
                    lo = mid
                else:
                    hi = mid
            b = 0.5 * (lo + hi)
            segs.append((cur, s0, b))
            if c is None:
                return segs, "left", b
            cur, s0 = c, b
        s = nxt
    segs.append((cur, s0, max_depth))
    return segs, "deep", max_depth


def probe_outside(geometry, lattice, face) -> dict:
    """What lies outside one lateral face of the core lattice, as slabs: {"status", "layers", "end_bc", "reason"}.

    status "ok": one to MAX_LAYERS layers of the model's own materials, each as thick as the first one along the normal through the middle of the face, and the same along two other lines
    (a quarter of the face either side of the middle, so a tank that is not uniform along the face is refused); "layers" = [{"material", "name", "thickness", "cell"}] nearest first; "end_bc"
    what bounds the last layer: a plane with a boundary condition there (vacuum or reflective) or, with none, vacuum. status "none": nothing but void or the end of the geometry outside;
    "nonuniform", "unsupported" (a cell filled with a universe or lattice, a white or periodic end, more than MAX_LAYERS layers) and "deep" (a medium past MAX_OUTSIDE_CM) carry a reason and no layers.
    """
    frame = _face_frame(geometry, lattice)
    if frame is None:
        return {"status": "unsupported", "layers": [], "end_bc": None, "reason": "the lattice is not directly in the root universe (or its cell is rotated), so its faces cannot be placed"}
    pos, mid, zmid, length = frame
    axis = face[0]
    runs = []
    for off in (0.0, -length[axis] / 4, length[axis] / 4):
        along = mid[axis] + off
        start = (pos[face], along, zmid) if axis == "x" else (along, pos[face], zmid)
        runs.append(_walk(geometry, start, _DIRECTION[face], MAX_OUTSIDE_CM))
    ref = runs[0]
    for other in runs[1:]:
        same = len(other[0]) == len(ref[0]) and other[1] == ref[1] and all(a[0].id == b[0].id and abs(a[2] - b[2]) < 1e-3 and abs(a[1] - b[1]) < 1e-3 for a, b in zip(other[0], ref[0]))
        if not same:
            sizes = [[round(b - a, 3) for _, a, b in r[0]] for r in runs]
            return {"status": "nonuniform", "layers": [], "end_bc": None, "reason": f"what lies outside is not the same along the face (layer thicknesses on three lines: {sizes})"}
    segs, end, s_end = ref
    layers = []
    void_end = False
    for cell, a, b in segs:
        fill = cell.fill
        if fill is None:
            void_end = True
            break
        if not hasattr(fill, "get_nuclides"):
            return {"status": "unsupported", "layers": [], "end_bc": None, "reason": f"just outside the face, cell {cell.name or cell.id} is filled with a universe or lattice, not a material"}
        layers.append({"material": fill, "name": fill.name or "material", "thickness": b - a, "cell": cell.name or str(cell.id)})
    if end == "deep" and not void_end:
        return {"status": "deep", "layers": [], "end_bc": None, "reason": f"the medium goes on past {MAX_OUTSIDE_CM:g} cm"}
    if not layers:
        return {"status": "none", "layers": [], "end_bc": None, "reason": "nothing but void or the end of the model outside this face"}
    if len(layers) > MAX_LAYERS:
        return {"status": "unsupported", "layers": [], "end_bc": None, "reason": f"{len(layers)} layers outside the face; at most {MAX_LAYERS} are taken"}
    bc = "vacuum"
    where = "the layers end in void" if void_end else "the model ends"
    if not void_end:
        coord = pos[face] + _DIRECTION[face][0 if axis == "x" else 1] * s_end
        kind = "x-plane" if axis == "x" else "y-plane"
        attr = "x0" if axis == "x" else "y0"
        bcs = sorted({sf.boundary_type for sf in geometry.get_all_surfaces().values() if sf.type == kind and abs(getattr(sf, attr) - coord) <= 1e-4 * max(1.0, abs(coord)) and sf.boundary_type != "transmission"})
        if len(bcs) > 1:
            return {"status": "unsupported", "layers": [], "end_bc": None, "reason": f"planes with different boundary conditions {bcs} bound the outside at {coord:g} cm"}
        if bcs:
            bc = bcs[0]
            where = f"a plane at {coord:g} cm with boundary condition {bc}"
        else:
            where = f"the model ends at {coord:g} cm with no plane there that has a boundary condition (vacuum is assumed)"
    if bc not in ("vacuum", "reflective"):
        return {"status": "unsupported", "layers": [], "end_bc": None, "reason": f"the outside ends in a {bc} boundary, which this solve does not represent"}
    return {"status": "ok", "layers": layers, "end_bc": bc, "reason": where}


def describe_layers(probe) -> str:
    return " then ".join(f"{l['name']} {l['thickness']:.3g} cm" for l in probe["layers"])


def make_layers(probes) -> dict:
    """face -> [Layer] for the faces whose probe is ok; slabs of the same material and thickness share one universe and one label."""
    import openmc
    shared, out = {}, {}
    for face, pr in probes.items():
        if pr["status"] != "ok":
            continue
        row = []
        for l in pr["layers"]:
            label = f"{l['name']}#{l['material'].id}@{l['thickness']:.3f}cm"
            if label not in shared:
                shared[label] = Layer(label, openmc.Universe(cells=[openmc.Cell(fill=l["material"])], name=label), float(l["thickness"]), l["name"])
            row.append(shared[label])
        out[face] = row
    return out


def extend_layout(labels, pitch, rings):
    """The core map with the layers around it. rings: face -> [Layer] nearest first. Returns (labels, widths_x left to right, widths_y top to bottom, rows above, columns left).
    A corner node takes the label of the layer of the left or right side next to it (the top or bottom side when that side has none): the same material in a normal tank."""
    left, right = rings.get("x_min", []), rings.get("x_max", [])
    top, bottom = rings.get("y_max", []), rings.get("y_min", [])
    nx, ny = len(labels[0]), len(labels)
    wx = [l.width for l in left[::-1]] + [pitch] * nx + [l.width for l in right]
    wy = [l.width for l in top[::-1]] + [pitch] * ny + [l.width for l in bottom]

    rows = []
    for j in range(len(top) - 1, -1, -1):
        rows.append([left[i].label for i in range(len(left) - 1, -1, -1)] + [top[j].label] * nx + [right[i].label for i in range(len(right))])
    for row in labels:
        rows.append([left[i].label for i in range(len(left) - 1, -1, -1)] + list(row) + [right[i].label for i in range(len(right))])
    for j in range(len(bottom)):
        rows.append([left[i].label for i in range(len(left) - 1, -1, -1)] + [bottom[j].label] * nx + [right[i].label for i in range(len(right))])
    return rows, wx, wy, len(top), len(left)



def read_outside(geometry, lattice, overrides=None):
    """(detected faces, the probe of every face with material outside it, the layers to put in the solve): `detect_faces` with each face whose outside can be taken as slabs rewritten to
    the boundary behind them and a detail naming the layers, and each face whose outside cannot, kept as it is with the reason added. Faces named in `overrides` are not probed."""
    if geometry is None:
        return None, {}, {}
    detected = detect_faces(geometry, lattice)
    probes = {}
    for face in FACES:
        if face not in (overrides or {}) and detected[face]["type"] == "material":
            probes[face] = probe_outside(geometry, lattice, face)
    rings = make_layers(probes)
    for face, pr in probes.items():
        if pr["status"] == "ok":
            detected[face] = {"type": pr["end_bc"], "position_cm": detected[face]["position_cm"],
                              "detail": f"{describe_layers(pr)} outside the face are part of the solve as {len(pr['layers'])} layer(s), taken as uniform along the face; then {pr['reason']}"}
        elif pr["status"] != "none":
            detected[face] = dict(detected[face], detail=f"{detected[face]['detail']} (not taken into the solve: {pr['reason']})")
    return detected, probes, rings


def two_step(lattice, materials, *, workdir, particles=20000, batches=150, inactive=30, seed=None, threads=None, kernel="sanm", boundaries=None, geometry=None, progress=None) -> TwoStepResult:
    """Run the pieces for `lattice` and solve the core.

    materials   the openmc.Materials the universes use (OPENMC_CROSS_SECTIONS must be set in the environment).
    workdir     where the pieces' run folders go (one per piece); nothing else is written.
    boundaries  overrides for the core's outer faces ({'x_min': 'reflective', ...}, nodal.solve_core's names); a face not named is read from the model.
    geometry    the openmc.Geometry the lattice belongs to: the faces are read from it (`detect_faces`). Without it every face not overridden is vacuum, with a warning.
                The result records, per face, what was used and where it came from.
    """
    nodal.require_openndm()
    import openmc
    say = progress or (lambda m: None)
    _, pitch, height = layer(lattice)
    detected, probes, rings = read_outside(geometry, lattice, boundaries)
    pieces, kinds, labels = plan_pieces(lattice, rings)
    materials = openmc.Materials(list(materials) + [l["material"] for pr in probes.values() if pr["status"] == "ok" for l in pr["layers"] if l["material"] not in list(materials)]) if rings else materials
    settings_kw = dict(particles=int(particles), batches=int(batches), inactive=int(inactive), seed=seed, threads=threads)
    workdir = Path(workdir)
    constants, refl_samples = {}, {lab: [] for lab, (u, r) in kinds.items() if r == "reflector"}
    layer_by_uid = {l.universe.id: l for ls in rings.values() for l in ls}
    layer_samples = {l.label: [] for l in layer_by_uid.values()}
    for i, piece in enumerate(pieces):
        say(f"piece {i + 1} of {len(pieces)}: {piece.label}")
        lib = _run_piece(piece, pitch, height, materials, settings_kw, workdir / f"piece_{i}")
        if piece.role == "infinite":
            lab = next(l for l, (u, r) in kinds.items() if u is piece.domains[0])
            constants[lab] = nodal.critical_buckling_fuel(nodal.fine_arrays(lib, piece.domains[0]), np.asarray(lib.energy_groups.group_edges, float))
        else:
            for d in piece.domains:
                if d.id in layer_by_uid:
                    layer_samples[layer_by_uid[d.id].label].append(nodal.condensed_constants(lib, d))
                    continue
                lab = next(l for l, (u, r) in kinds.items() if u is d)
                refl_samples[lab].append(nodal.condensed_constants(lib, d))
    for lab, samples in refl_samples.items():
        constants[lab] = mean_constants(samples)
    for lab, samples in layer_samples.items():
        constants[lab] = mean_constants(samples)
    chosen, faces_used, face_warnings = resolve_faces(detected, boundaries)
    if rings:
        solve_labels, wx, wy, n_top, n_left = extend_layout(labels, pitch, rings)
        res = nodal.solve_core(solve_labels, constants, pitch, height, kernel=kernel, boundaries=chosen, threads=threads or 4, node_widths=(wx, wy))
        res.power = np.asarray(res.power)[n_top:n_top + len(labels), n_left:n_left + len(labels[0])]       # the core's own map; the ring has no fission
        res.kinds = [list(r) for r in labels]
    else:
        res = nodal.solve_core(labels, constants, pitch, height, kernel=kernel, boundaries=chosen, threads=threads or 4)
    prov = dict(schema=nodal.SCHEMA, versions=nodal.versions(), recipe="fuel: infinite lattice, CASMO-25, critical-buckling spectrum correction (k = 1); reflector: strip(s), CASMO-25 condensed by OpenMC "
                "(flux-averaged D); no discontinuity factors; one node per assembly; radial 2D, axial reflective" + ("; the model's own material outside the faces as extra node layers" if rings else ""),
                intermediate_structure=nodal.INTERMEDIATE_NAME,
                settings=settings_kw, pitch_cm=pitch, height_cm=height, kernel=kernel, boundaries=res.boundaries)
    res.provenance.update(prov)
    warnings = model_warnings(pitch, height, constants) + face_warnings
    return TwoStepResult(nodal=res, constants=constants, kinds={lab: {"universe": u.id, "role": r} for lab, (u, r) in kinds.items()},
                         pieces=[(p.label, p.role, p.k, p.k_std, round(p.seconds, 1)) for p in pieces], settings=settings_kw, provenance=prov, warnings=warnings, faces=faces_used)


# ── from a Studio model.py ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def _lattices_inside(universe, out):
    """Collect the lattices below a universe (through its cells' fills, recursively) into `out` (id -> lattice)."""
    import openmc
    for cell in universe.cells.values():
        f = cell.fill
        if isinstance(f, openmc.Lattice):
            if f.id not in out:
                out[f.id] = f
                for u in np.asarray(f.universes, dtype=object).reshape(-1):
                    _lattices_inside(u, out)
        elif isinstance(f, openmc.Universe):
            _lattices_inside(f, out)


def lattices_of(model) -> list:
    """The rectangular lattices of an openmc.Model that no other lattice contains (the core lattices; pin lattices inside assemblies are not), in a stable order."""
    import openmc
    found = dict(model.geometry.get_all_lattices())
    inner = set()
    for lat in found.values():
        below = {}
        for u in np.asarray(lat.universes, dtype=object).reshape(-1):
            _lattices_inside(u, below)
        inner.update(below)
    return [found[i] for i in sorted(found) if i not in inner and isinstance(found[i], openmc.RectLattice)]


def core_lattice(model, name=None):
    """The core lattice of a model: the only outermost rectangular lattice, or the one with this name."""
    outer = lattices_of(model)
    if name is not None:
        hit = [lat for lat in outer if lat.name == name]
        if len(hit) != 1:
            raise NodalInputError(f"no outermost lattice named {name!r}; the model has {[lat.name or lat.id for lat in outer]}")
        return hit[0]
    if len(outer) != 1:
        raise NodalInputError(f"the model has {len(outer)} outermost lattices {[lat.name or lat.id for lat in outer]}; name the core one")
    return outer[0]


def load_model(path):
    """Run a Studio model.py without its `__main__` block and return its `model`. This executes the script, with the trust Studio gives its own generated files."""
    import runpy
    import openmc
    ns = runpy.run_path(str(path), run_name="studio_model")
    model = ns.get("model")
    if not isinstance(model, openmc.Model):
        raise NodalInputError(f"{path} does not define `model` as an openmc.Model")
    return model


def two_step_script(path, *, workdir, lattice_name=None, **kw) -> TwoStepResult:
    """`two_step` on the core lattice of a Studio model.py (the model's own materials)."""
    import openmc
    model = load_model(path)
    lattice = core_lattice(model, lattice_name)
    materials = openmc.Materials(model.geometry.get_all_materials().values())
    return two_step(lattice, materials, workdir=workdir, geometry=model.geometry, **kw)


def result_json(res: TwoStepResult) -> dict:
    """A plain-JSON form of a result (for the headless route and the tab)."""
    n = res.nodal
    return {"ok": True, "k_eff": n.k_eff, "kernel": n.kernel, "converged": n.converged, "layout": n.kinds, "power": np.asarray(n.power).tolist(), "node_size_cm": n.node_size_cm,
            "height_cm": n.height_cm, "boundaries": n.boundaries, "kinds": res.kinds, "constants": {k: {f: np.asarray(v).tolist() for f, v in c.items()} for k, c in res.constants.items()},
            "pieces": [dict(label=l, role=r, k=k, k_std=sd, seconds=sec) for l, r, k, sd, sec in res.pieces], "provenance": res.provenance, "warnings": res.warnings, "faces": res.faces}


def main(argv=None) -> int:
    import argparse
    import json
    import sys
    ap = argparse.ArgumentParser(prog="python -m openmc_studio.nodal_driver", description="Nodal two-step solve of the core lattice of a Studio model.py; prints one JSON line.")
    ap.add_argument("model")
    ap.add_argument("--workdir", default=None, help="where the pieces' run folders go (required unless --list)")
    ap.add_argument("--lattice", default=None, help="name of the core lattice when the model has more than one outermost lattice")
    ap.add_argument("--particles", type=int, default=20000)
    ap.add_argument("--batches", type=int, default=150)
    ap.add_argument("--inactive", type=int, default=30)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--threads", type=int, default=None)
    ap.add_argument("--kernel", default="sanm", choices=["sanm", "nem", "fdm"])
    ap.add_argument("--reflective", nargs="*", default=[], choices=["x_min", "x_max", "y_min", "y_max"], help="outer faces to set reflective, over what the model says")
    ap.add_argument("--vacuum", nargs="*", default=[], choices=["x_min", "x_max", "y_min", "y_max"], help="outer faces to set vacuum, over what the model says")
    ap.add_argument("--faces", action="store_true", help="only print what the model has at the lattice's four outer faces and exit")
    ap.add_argument("--list", action="store_true", help="only list the outermost lattices and exit")
    ap.add_argument("--out", default=None, help="write the JSON result to this file and print a short summary line instead")
    a = ap.parse_args(argv)
    try:
        if a.faces:
            model = load_model(a.model)
            over = {**{f: "vacuum" for f in a.vacuum}, **{f: "reflective" for f in a.reflective}} or None
            det, probes, _ = read_outside(model.geometry, core_lattice(model, a.lattice), over)
            chosen, used, warns = resolve_faces(det, over)
            outside = {f: {"status": pr["status"], "layers": [{"name": l["name"], "thickness": l["thickness"]} for l in pr["layers"]], "end_bc": pr["end_bc"], "reason": pr["reason"]} for f, pr in probes.items()}
            print(json.dumps({"ok": True, "detected": det, "used": used, "warnings": warns, "outside": outside}))
            return 0
        if a.list:
            model = load_model(a.model)
            print(json.dumps({"ok": True, "lattices": [{"name": lat.name, "id": lat.id, "shape": list(np.asarray(lat.universes, dtype=object).shape)} for lat in lattices_of(model)]}))
            return 0
        if not a.workdir:
            raise NodalInputError("--workdir is required")
        res = two_step_script(a.model, workdir=a.workdir, lattice_name=a.lattice, particles=a.particles, batches=a.batches, inactive=a.inactive, seed=a.seed, threads=a.threads,
                              kernel=a.kernel, boundaries={**{f: "vacuum" for f in a.vacuum}, **{f: "reflective" for f in a.reflective}} or None,
                              progress=(lambda m: print(m, file=sys.stderr, flush=True)) if a.out else None)
    except (NodalInputError, nodal.NodalUnavailable) as e:
        print(json.dumps({"ok": False, "error": type(e).__name__, "message": str(e)}))
        return 1
    doc = result_json(res)
    if a.out:
        Path(a.out).write_text(json.dumps(doc), encoding="utf-8", newline="\n")
        print(f"Nodal k = {res.nodal.k_eff:.5f} ({res.nodal.kernel}, {len(res.pieces)} pieces); result written to {a.out}", flush=True)
    else:
        print(json.dumps(doc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
