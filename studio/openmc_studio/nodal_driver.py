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

Nothing runs at import; a run needs openmc, openndm and nuclear data (OPENMC_CROSS_SECTIONS), and Monte Carlo time: the pieces are small (one assembly and a few of them).
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
HEIGHT_CM = 1.0                 # the pieces are one centimetre thick with reflective z faces (2D)


@dataclass
class Piece:
    label: str
    role: str                                    # "infinite" or "strip"
    grid: list                                   # [[universe, ...]], one row
    domains: list                                # the universes tallied
    x_bcs: tuple
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
    provenance: dict = field(default_factory=dict)


def _is_fissile_nuclide(name: str) -> bool:
    import openmc.data
    try:
        return openmc.data.zam(name)[0] >= 90
    except Exception:
        return False


def is_fuel(universe) -> bool:
    return any(_is_fissile_nuclide(n) for m in universe.get_all_materials().values() for n in m.get_nuclides())


def classify(lattice) -> tuple[dict, list]:
    """(kinds, labels): kinds maps a label to (universe, role); labels is the lattice as rows of labels (top row first). Labels are the universe names, made unique with the id."""
    import openmc
    if not isinstance(lattice, openmc.RectLattice):
        raise NodalInputError("the nodal driver takes a rectangular lattice (a hexagonal one is not supported)")
    if lattice.ndim != 2:
        raise NodalInputError("the nodal driver takes a two-dimensional lattice (one universe per assembly, no axial layers)")
    if lattice.outer is not None:
        raise NodalInputError("the lattice has an `outer` universe: positions outside the core must not be a physical region (openndm would treat them as the core's outside); give the reflector as real lattice positions")
    if abs(lattice.pitch[0] - lattice.pitch[1]) > 1e-9:
        raise NodalInputError(f"the nodal solver takes square nodes; the lattice pitch is {tuple(lattice.pitch)}")
    unis = np.asarray(lattice.universes, dtype=object)
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


def _edge_run(line, kinds):
    """For a line of labels read from one edge inwards: (reflector labels at the edge, fuel labels behind them) or None when the edge is fuel."""
    n = 0
    while n < len(line) and kinds[line[n]][1] == "reflector":
        n += 1
    if n == 0 or n == len(line):
        return None
    fuel = []
    for lab in line[n:n + FUEL_DEPTH]:
        if kinds[lab][1] != "fuel":
            break
        fuel.append(lab)
    return line[:n], fuel


def plan_pieces(lattice) -> tuple[list, dict, list]:
    """The pieces to run, the kinds and the label map. Raises NodalInputError when a reflector kind appears in no strip."""
    kinds, labels = classify(lattice)
    ny, nx = len(labels), len(labels[0])
    mid_row, mid_col = labels[ny // 2], [row[nx // 2] for row in labels]
    lines = [list(mid_row), list(mid_row[::-1]), list(mid_col), list(mid_col[::-1])]      # each read from an edge inwards
    pieces, seen = [], set()
    for lab, (u, role) in kinds.items():
        if role == "fuel":
            pieces.append(Piece(f"infinite {lab}", "infinite", [[u]], [u], ("reflective", "reflective")))
    for line in lines:
        run = _edge_run(line, kinds)
        if run is None:
            continue
        refl, fuel = run
        seq = tuple(fuel[::-1]) + tuple(refl[::-1])                   # inner fuel ... outer reflector, the outer end last
        if seq in seen:
            continue
        seen.add(seq)
        grid = [[kinds[lab][0] for lab in seq]]
        domains, ids = [], set()
        for lab in refl:
            if kinds[lab][0].id not in ids:
                ids.add(kinds[lab][0].id)
                domains.append(kinds[lab][0])
        pieces.append(Piece("strip " + " ".join(l.split("#")[0] for l in seq), "strip", grid, domains, ("reflective", "vacuum")))
    covered = {d.id for p in pieces if p.role == "strip" for d in p.domains}
    missing = [lab for lab, (u, role) in kinds.items() if role == "reflector" and u.id not in covered]
    if missing:
        raise NodalInputError(f"no strip through the middle of the core reaches reflector kind(s) {missing}: the driver needs each reflector kind at an edge of the middle row or column")
    return pieces, kinds, labels


def _run_piece(piece: Piece, pitch: float, materials, settings_kw: dict, workdir: Path):
    import openmc
    import openmc.mgxs
    ny, nx = 1, len(piece.grid[0])
    lattice = openmc.RectLattice()
    lattice.universes = piece.grid
    x0, y0 = -pitch / 2, -pitch / 2
    x1, y1 = x0 + nx * pitch, y0 + pitch
    lattice.lower_left, lattice.pitch = (x0, y0), (pitch, pitch)
    px0, px1 = openmc.XPlane(x0, boundary_type=piece.x_bcs[0]), openmc.XPlane(x1, boundary_type=piece.x_bcs[1])
    py0, py1 = openmc.YPlane(y0, boundary_type="reflective"), openmc.YPlane(y1, boundary_type="reflective")
    pz0, pz1 = openmc.ZPlane(-HEIGHT_CM / 2, boundary_type="reflective"), openmc.ZPlane(HEIGHT_CM / 2, boundary_type="reflective")
    geometry = openmc.Geometry(openmc.Universe(cells=[openmc.Cell(fill=lattice, region=+px0 & -px1 & +py0 & -py1 & +pz0 & -pz1)]))
    st = openmc.Settings()
    st.particles, st.batches, st.inactive = settings_kw["particles"], settings_kw["batches"], settings_kw["inactive"]
    if settings_kw.get("seed"):
        st.seed = int(settings_kw["seed"])
    st.source = openmc.IndependentSource(space=openmc.stats.Box((x0, y0, -HEIGHT_CM / 2), (x1, y1, HEIGHT_CM / 2)), constraints={"fissionable": True})
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


def two_step(lattice, materials, *, workdir, particles=20000, batches=150, inactive=30, seed=None, threads=None, kernel="sanm", progress=None) -> TwoStepResult:
    """Run the pieces for `lattice` and solve the core.

    materials   the openmc.Materials the universes use (OPENMC_CROSS_SECTIONS must be set in the environment).
    workdir     where the pieces' run folders go (one per piece); nothing else is written.
    """
    nodal.require_openndm()
    say = progress or (lambda m: None)
    pieces, kinds, labels = plan_pieces(lattice)
    pitch = float(lattice.pitch[0])
    settings_kw = dict(particles=int(particles), batches=int(batches), inactive=int(inactive), seed=seed, threads=threads)
    workdir = Path(workdir)
    constants, refl_samples = {}, {lab: [] for lab, (u, r) in kinds.items() if r == "reflector"}
    for i, piece in enumerate(pieces):
        say(f"piece {i + 1} of {len(pieces)}: {piece.label}")
        lib = _run_piece(piece, pitch, materials, settings_kw, workdir / f"piece_{i}")
        if piece.role == "infinite":
            lab = next(l for l, (u, r) in kinds.items() if u is piece.domains[0])
            constants[lab] = nodal.critical_buckling_fuel(nodal.fine_arrays(lib, piece.domains[0]), np.asarray(lib.energy_groups.group_edges, float))
        else:
            for d in piece.domains:
                lab = next(l for l, (u, r) in kinds.items() if u is d)
                refl_samples[lab].append(nodal.condensed_constants(lib, d))
    for lab, samples in refl_samples.items():
        constants[lab] = mean_constants(samples)
    res = nodal.solve_core(labels, constants, pitch, HEIGHT_CM, kernel=kernel, threads=threads or 4)
    prov = dict(schema=nodal.SCHEMA, versions=nodal.versions(), recipe="fuel: infinite lattice, CASMO-25, critical-buckling spectrum correction (k = 1); reflector: strip(s), CASMO-25 condensed by OpenMC "
                "(flux-averaged D); no discontinuity factors; one node per assembly; radial 2D, axial reflective", intermediate_structure=nodal.INTERMEDIATE_NAME,
                settings=settings_kw, pitch_cm=pitch, kernel=kernel)
    res.provenance.update(prov)
    return TwoStepResult(nodal=res, constants=constants, kinds={lab: {"universe": u.id, "role": r} for lab, (u, r) in kinds.items()},
                         pieces=[(p.label, p.role, p.k, p.k_std, round(p.seconds, 1)) for p in pieces], settings=settings_kw, provenance=prov)
