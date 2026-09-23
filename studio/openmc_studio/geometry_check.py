"""Check a Studio model's geometry for overlaps and gaps before a run.

Two independent looks at the model.py Studio generated, both with OpenMC's own model objects:

1. Points. Random points inside the world are located by hand, level by level, through every
   universe, fill and lattice. At each level a point must be in exactly one cell: in none is a
   gap (a particle there is lost), in more than one is an overlap (OpenMC would silently use
   whichever cell it finds first). This covers the whole world, including places the source
   never sends a particle.
2. Particles (optional). A short transport run with OpenMC's geometry debugging on
   (`openmc -g`), which checks for overlaps at every step of every particle and reports the
   particles it loses. This catches problems exactly at surfaces, which random points miss.

Usage: python geometry_check.py FOLDER OPTIONS_JSON
FOLDER holds model.py. Prints one JSON object on the last line of stdout.
"""
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

MAX_EXAMPLES = 8
MAX_POINTS = 400_000


# ── point location ──

def surface_values(surf, P):
    """f(x, y, z) of an OpenMC surface at points P (3, n), matching Surface.evaluate."""
    x, y, z = P
    try:
        coeffs = surf._get_base_coeffs()
    except (AttributeError, NotImplementedError):  # a torus has no linear or quadric form
        coeffs = ()
    if len(coeffs) == 4:
        a, b, c, d = coeffs
        return a * x + b * y + c * z - d
    if len(coeffs) == 10:
        a, b, c, d, e, f, g, h, j, k = coeffs
        return a * x * x + b * y * y + c * z * z + d * x * y + e * y * z + f * x * z + g * x + h * y + j * z + k
    # Anything else (a torus, say): one point at a time.
    return np.array([surf.evaluate(P[:, i]) for i in range(P.shape[1])], dtype=float)


def region_mask(region, P, cache):
    import openmc
    n = P.shape[1]
    if region is None:
        return np.ones(n, bool)
    if isinstance(region, openmc.Halfspace):
        key = id(region.surface)
        if key not in cache:
            cache[key] = surface_values(region.surface, P)
        v = cache[key]
        return v >= 0 if region.side == "+" else v < 0
    if isinstance(region, openmc.Intersection):
        m = np.ones(n, bool)
        for r in region:
            m &= region_mask(r, P, cache)
        return m
    if isinstance(region, openmc.Union):
        m = np.zeros(n, bool)
        for r in region:
            m |= region_mask(r, P, cache)
        return m
    if isinstance(region, openmc.Complement):
        return ~region_mask(region.node, P, cache)
    raise TypeError(f"unsupported region {type(region).__name__}")


class Finder:
    def __init__(self):
        self.cell_of = None
        self.gaps = []       # (point index, universe id)
        self.overlaps = []   # (point index, [cell ids])

    def walk(self, univ, P, idx):
        """Locate points P (3, n; universe-local coordinates) whose global indices are idx."""
        import openmc
        if not len(idx):
            return
        cache = {}
        cells = list(univ.cells.values())
        masks = [region_mask(c.region, P, cache) for c in cells]
        hits = np.sum(masks, axis=0) if masks else np.zeros(len(idx), int)
        for j in np.flatnonzero(hits == 0):
            self.gaps.append((int(idx[j]), univ.id))
        for j in np.flatnonzero(hits > 1):
            self.overlaps.append((int(idx[j]), [c.id for c, m in zip(cells, masks) if m[j]]))
        one = hits == 1
        for cell, m in zip(cells, masks):
            sel = m & one
            if not sel.any():
                continue
            if cell.fill_type in ("material", "distribmat", "void"):
                self.cell_of[idx[sel]] = cell.id
            elif cell.fill_type == "universe":
                Q = P[:, sel].copy()
                if cell.translation is not None:
                    Q -= np.asarray(cell.translation, float)[:, None]
                if cell.rotation is not None:
                    Q = cell.rotation_matrix @ Q
                self.walk(cell.fill, Q, idx[sel])
            else:  # a lattice: group the points by the universe of their element
                lat, groups = cell.fill, {}
                for j in np.flatnonzero(sel):
                    e, local = lat.find_element(P[:, j])
                    u = lat.get_universe(e) if lat.is_valid_index(e) else lat.outer
                    if u is None:
                        self.gaps.append((int(idx[j]), f"lattice {lat.id}"))
                        continue
                    g = groups.setdefault(u.id, (u, [], []))
                    g[1].append(np.asarray(local, float))
                    g[2].append(idx[j])
                for u, pts, ids in groups.values():
                    self.walk(u, np.array(pts).T, np.array(ids))


def sample_world(world, n, rng):
    shape, R = world.get("shape", "box"), float(world["R"])
    r = 0.999 * R  # stay off the world boundary itself
    if shape == "sphere":
        pts = []
        while sum(len(p) for p in pts) < n:
            q = rng.uniform(-r, r, size=(n, 3))
            pts.append(q[(q ** 2).sum(axis=1) < r * r])
        return np.concatenate(pts)[:n].T
    return rng.uniform(-r, r, size=(3, n))


def check_points(model, world, n, seed):
    rng = np.random.default_rng(seed)
    P = sample_world(world, n, rng)
    f = Finder()
    f.cell_of = np.full(P.shape[1], -1, dtype=np.int64)
    f.walk(model.geometry.root_universe, P, np.arange(P.shape[1]))
    pt = lambda i: [round(float(v), 6) for v in P[:, i]]
    return {
        "points": int(P.shape[1]),
        "gaps": len(f.gaps),
        "overlaps": len(f.overlaps),
        "gap_examples": [{"p": pt(i), "universe": u} for i, u in f.gaps[:MAX_EXAMPLES]],
        "overlap_examples": [{"p": pt(i), "cells": c} for i, c in f.overlaps[:MAX_EXAMPLES]],
        # every distinct pair of overlapping cells, so each one can be named
        "overlap_pairs": sorted({tuple(sorted(c[:2])) for _, c in f.overlaps})[:50],
    }


# ── transport with geometry debugging ──

OVERLAP_RE = re.compile(r"Overlapping cells detected:\s*([\d,\s]+?)\s+on universe\s+(\d+)")
LOST_RE = re.compile(r"(could not be located|was lost|lost particle)", re.I)


def check_transport(model, folder, particles):
    import openmc
    cross = os.environ.get("OPENMC_CROSS_SECTIONS")
    if not cross or not Path(cross).exists():
        return {"ran": False, "reason": "OPENMC_CROSS_SECTIONS is not set, so no particles were run."}
    exe = shutil.which("openmc", path=os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", ""))
    if not exe:
        return {"ran": False, "reason": "The openmc executable was not found next to this Python."}
    work = Path(folder) / "transport"
    work.mkdir(exist_ok=True)
    st = model.settings
    eig = st.run_mode == "eigenvalue"
    st.batches, st.inactive = (3, 1) if eig else (1, 0)
    st.particles = int(particles)
    st.track = []
    st.max_lost_particles = 50
    st.rel_max_lost_particles = 0.5
    st.output = {"summary": False, "tallies": False}
    model.tallies = openmc.Tallies()
    model.export_to_model_xml(str(work / "model.xml"))
    t0 = time.time()
    try:
        r = subprocess.run([exe, "-g"], cwd=work, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return {"ran": False, "reason": "The particle check took over 10 minutes and was stopped."}
    out = (r.stdout or "") + (r.stderr or "")
    ov = OVERLAP_RE.search(out)
    lost_lines = [l.strip() for l in out.splitlines() if LOST_RE.search(l)]
    res = {"ran": True, "particles": int(particles) * int(st.batches), "seconds": round(time.time() - t0, 1),
           "exit_code": r.returncode, "lost": len(lost_lines), "lost_examples": lost_lines[:MAX_EXAMPLES],
           "overlap": None}
    if ov:
        res["overlap"] = {"cells": [int(c) for c in re.findall(r"\d+", ov.group(1))], "universe": int(ov.group(2))}
    if r.returncode and not ov and not lost_lines:
        tail = [l for l in out.splitlines() if l.strip()][-6:]
        res["error"] = "\n".join(tail)
    return res


def main():
    folder, opts = Path(sys.argv[1]), json.loads(sys.argv[2])
    t0 = time.time()
    os.chdir(folder)
    ns = runpy.run_path("model.py", run_name="studio_geometry_check")
    model, ids = ns["model"], ns.get("studio_ids", {})
    out = {"ok": True}
    try:
        out["points"] = check_points(model, opts["world"], min(int(opts.get("points", 100_000)), MAX_POINTS),
                                     int(opts.get("seed", 1)))
    except Exception as exc:  # noqa: BLE001 - reported to the page, not raised
        out["points"] = {"error": f"{type(exc).__name__}: {exc}"}
    if opts.get("particles"):
        try:
            out["transport"] = check_transport(model, folder, int(opts["particles"]))
        except Exception as exc:  # noqa: BLE001
            out["transport"] = {"ran": False, "reason": f"{type(exc).__name__}: {exc}"}
    # Studio's own name for each OpenMC cell id
    out["cells"] = {str(k): v for k, v in (ids.get("cell") or {}).items()}
    out["seconds"] = round(time.time() - t0, 1)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
