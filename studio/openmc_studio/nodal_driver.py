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
HEIGHT_CM = 1.0                 # thickness of a piece (reflective z faces) for a two-dimensional lattice; a one-layer three-dimensional lattice (what Studio writes) gives its own z pitch


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


def _run_piece(piece: Piece, pitch: float, height: float, materials, settings_kw: dict, workdir: Path):
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
    pz0, pz1 = openmc.ZPlane(-height / 2, boundary_type="reflective"), openmc.ZPlane(height / 2, boundary_type="reflective")
    geometry = openmc.Geometry(openmc.Universe(cells=[openmc.Cell(fill=lattice, region=+px0 & -px1 & +py0 & -py1 & +pz0 & -pz1)]))
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


def two_step(lattice, materials, *, workdir, particles=20000, batches=150, inactive=30, seed=None, threads=None, kernel="sanm", boundaries=None, progress=None) -> TwoStepResult:
    """Run the pieces for `lattice` and solve the core.

    materials   the openmc.Materials the universes use (OPENMC_CROSS_SECTIONS must be set in the environment).
    workdir     where the pieces' run folders go (one per piece); nothing else is written.
    boundaries  the core's outer faces for the solve (nodal.solve_core's names); default vacuum on all four sides. They are NOT read from the OpenMC model: a model with reflective
                sides must say so here, and the result's provenance records what was used.
    """
    nodal.require_openndm()
    say = progress or (lambda m: None)
    pieces, kinds, labels = plan_pieces(lattice)
    _, pitch, height = layer(lattice)
    settings_kw = dict(particles=int(particles), batches=int(batches), inactive=int(inactive), seed=seed, threads=threads)
    workdir = Path(workdir)
    constants, refl_samples = {}, {lab: [] for lab, (u, r) in kinds.items() if r == "reflector"}
    for i, piece in enumerate(pieces):
        say(f"piece {i + 1} of {len(pieces)}: {piece.label}")
        lib = _run_piece(piece, pitch, height, materials, settings_kw, workdir / f"piece_{i}")
        if piece.role == "infinite":
            lab = next(l for l, (u, r) in kinds.items() if u is piece.domains[0])
            constants[lab] = nodal.critical_buckling_fuel(nodal.fine_arrays(lib, piece.domains[0]), np.asarray(lib.energy_groups.group_edges, float))
        else:
            for d in piece.domains:
                lab = next(l for l, (u, r) in kinds.items() if u is d)
                refl_samples[lab].append(nodal.condensed_constants(lib, d))
    for lab, samples in refl_samples.items():
        constants[lab] = mean_constants(samples)
    res = nodal.solve_core(labels, constants, pitch, height, kernel=kernel, boundaries=boundaries, threads=threads or 4)
    prov = dict(schema=nodal.SCHEMA, versions=nodal.versions(), recipe="fuel: infinite lattice, CASMO-25, critical-buckling spectrum correction (k = 1); reflector: strip(s), CASMO-25 condensed by OpenMC "
                "(flux-averaged D); no discontinuity factors; one node per assembly; radial 2D, axial reflective", intermediate_structure=nodal.INTERMEDIATE_NAME,
                settings=settings_kw, pitch_cm=pitch, height_cm=height, kernel=kernel, boundaries=res.boundaries)
    res.provenance.update(prov)
    return TwoStepResult(nodal=res, constants=constants, kinds={lab: {"universe": u.id, "role": r} for lab, (u, r) in kinds.items()},
                         pieces=[(p.label, p.role, p.k, p.k_std, round(p.seconds, 1)) for p in pieces], settings=settings_kw, provenance=prov)


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
    return two_step(lattice, materials, workdir=workdir, **kw)


def result_json(res: TwoStepResult) -> dict:
    """A plain-JSON form of a result (for the headless route and the tab)."""
    n = res.nodal
    return {"ok": True, "k_eff": n.k_eff, "kernel": n.kernel, "converged": n.converged, "layout": n.kinds, "power": np.asarray(n.power).tolist(), "node_size_cm": n.node_size_cm,
            "height_cm": n.height_cm, "boundaries": n.boundaries, "kinds": res.kinds, "constants": {k: {f: np.asarray(v).tolist() for f, v in c.items()} for k, c in res.constants.items()},
            "pieces": [dict(label=l, role=r, k=k, k_std=sd, seconds=sec) for l, r, k, sd, sec in res.pieces], "provenance": res.provenance}


def main(argv=None) -> int:
    import argparse
    import json
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
    ap.add_argument("--reflective", nargs="*", default=[], choices=["x_min", "x_max", "y_min", "y_max"], help="outer faces that are reflective (default: all vacuum)")
    ap.add_argument("--list", action="store_true", help="only list the outermost lattices and exit")
    a = ap.parse_args(argv)
    try:
        if a.list:
            model = load_model(a.model)
            print(json.dumps({"ok": True, "lattices": [{"name": lat.name, "id": lat.id, "shape": list(np.asarray(lat.universes, dtype=object).shape)} for lat in lattices_of(model)]}))
            return 0
        if not a.workdir:
            raise NodalInputError("--workdir is required")
        res = two_step_script(a.model, workdir=a.workdir, lattice_name=a.lattice, particles=a.particles, batches=a.batches, inactive=a.inactive, seed=a.seed, threads=a.threads,
                              kernel=a.kernel, boundaries={f: "reflective" for f in a.reflective} or None)
    except (NodalInputError, nodal.NodalUnavailable) as e:
        print(json.dumps({"ok": False, "error": type(e).__name__, "message": str(e)}))
        return 1
    print(json.dumps(result_json(res)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
