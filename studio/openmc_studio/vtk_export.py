"""Write a finished run's mesh tallies and particle tracks as legacy VTK files for ParaView.

OpenMC's own writers (RegularMesh.write_data_to_vtk, Tracks.write_to_vtk) need the `vtk` Python
package, which Studio's environment doesn't have. The legacy VTK format is simple enough to write
directly: an ASCII header, then big-endian binary arrays.

- A regular mesh tally becomes STRUCTURED_POINTS, a cylindrical one a STRUCTURED_GRID whose points are
  the (r, phi, z) grid turned into x, y, z. Each score gets <score>_mean, <score>_std_dev and
  <score>_rel_err cell arrays, summed over every other filter except energy; with an energy filter,
  each energy bin also gets its own <score>_mean_E<i> array. Values are per source particle and per
  cm^3 (divided by the voxel volume), like OpenMC's writer with volume_normalization=True.
- tracks.h5 becomes POLYDATA: one polyline per particle track, with energy_eV, track_id and particle
  (0 neutron, 1 photon, 2 electron, 3 positron) as point data.

Usage: export_run(run_dir, out_dir, stl={name: bytes}) -> manifest dict
"""
import glob
import json
import math
import os
import re
import struct
from pathlib import Path

import numpy as np

PARTICLE_CODES = {"neutron": 0, "photon": 1, "electron": 2, "positron": 3}


def _safe(name):
    """An ASCII file or array name: legacy VTK headers are ASCII, and so is every name ParaView lists."""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(name)).strip("_") or "tally"


def _num(values):
    """Numbers for a header line: plain Python floats (NumPy 2's repr, np.float64(...), is not VTK)."""
    return " ".join(repr(float(v)) for v in values)


def _header(title, dataset):
    title = title[:250].encode("ascii", "replace").decode("ascii")  # a tally named "Dose uSv/h" with a micro sign
    return (f"# vtk DataFile Version 3.0\n{title}\nBINARY\nDATASET {dataset}\n").encode("ascii")


def _array_block(name, values, kind="double"):
    dt = {"double": ">f8", "float": ">f4", "int": ">i4"}[kind]
    data = np.ascontiguousarray(np.asarray(values).ravel(), dtype=dt).tobytes()
    return f"SCALARS {name} {kind} 1\nLOOKUP_TABLE default\n".encode("ascii") + data + b"\n"


def _mesh_arrays(t, openmc, mesh_f, dims, label=None):
    """{array name: values in VTK cell order (x or r fastest)}, per source particle, not yet per volume."""
    shape = [f.num_bins for f in t.filters]
    k = t.filters.index(mesh_f)
    efilt = next((i for i, f in enumerate(t.filters) if isinstance(f, openmc.EnergyFilter)), None)
    n = int(np.prod(dims))
    # where each MeshFilter bin goes in the grid (bins are 1-based (i, j, k); x or r varies fastest)
    idx = np.array([(b[0] - 1) + dims[0] * ((b[1] - 1) + dims[1] * (b[2] - 1)) for b in mesh_f.bins])
    mean = t.mean.reshape(shape + list(t.mean.shape[1:]))   # filters..., nuclides, scores
    var = (t.std_dev ** 2).reshape(shape + list(t.std_dev.shape[1:]))
    out = {}
    for s, score in enumerate(t.scores):
        m_s, v_s = mean[..., s], var[..., s]  # filters..., nuclides
        keep = [k] + ([efilt] if efilt is not None else [])
        drop = tuple(i for i in range(len(shape) + 1) if i not in keep)  # other filters and nuclides
        m_k, v_k = m_s.sum(axis=drop), v_s.sum(axis=drop)            # (mesh[, energy]) in filter order
        if efilt is not None and efilt < k:
            m_k, v_k = m_k.T, v_k.T                                     # -> (mesh, energy)
        if efilt is None:
            m_k, v_k = m_k[:, None], v_k[:, None]
        tot_m, tot_v = m_k.sum(axis=1), v_k.sum(axis=1)
        grid = lambda a: _place(a, idx, n)
        name = label or _safe(score)
        out[f"{name}_mean"] = grid(tot_m)
        out[f"{name}_std_dev"] = grid(np.sqrt(tot_v))
        with np.errstate(divide="ignore", invalid="ignore"):
            out[f"{name}_rel_err"] = grid(np.where(tot_m > 0, np.sqrt(tot_v) / tot_m, 0.0))
        if efilt is not None:
            for e in range(m_k.shape[1]):
                out[f"{name}_mean_E{e}"] = grid(m_k[:, e])
    return out


def _place(a, idx, n):
    g = np.zeros(n)
    g[idx] = a
    return g


def _write_regular(path, t, m, arrays, scale=1.0):
    dims = [int(d) for d in m.dimension] + [1] * (3 - len(m.dimension))
    lo = np.array(m.lower_left, float)
    hi = np.array(m.upper_right, float)
    step = (hi - lo) / np.array(dims)
    vol = float(np.prod(step))
    body = _header(f"OpenMC Studio mesh tally {t.name} (per source particle, per cm^3)", "STRUCTURED_POINTS")
    body += (f"DIMENSIONS {dims[0] + 1} {dims[1] + 1} {dims[2] + 1}\n"
             f"ORIGIN {_num(lo)}\nSPACING {_num(step)}\n"
             f"CELL_DATA {int(np.prod(dims))}\n").encode("ascii")
    for name, vals in arrays.items():
        body += _array_block(name, vals if name.endswith("_rel_err") else vals / vol * scale)
    Path(path).write_bytes(body)
    return {"cells": int(np.prod(dims)), "type": "STRUCTURED_POINTS"}


def _write_cylindrical(path, t, m, arrays, scale=1.0):
    r, phi, z = (np.asarray(g, float) for g in (m.r_grid, m.phi_grid, m.z_grid))
    ox, oy, oz = (float(v) for v in getattr(m, "origin", (0.0, 0.0, 0.0)))
    nr, nphi, nz = len(r) - 1, len(phi) - 1, len(z) - 1
    # A cell is drawn as a hexahedron, so a bin spanning a wide angle (a whole ring, with one angular bin) would
    # collapse to a sliver. Each angular bin is drawn as `sub` segments of at most 11.25 degrees, all carrying
    # the bin's value; the bin structure is unchanged.
    sub = max(1, int(math.ceil(float(np.max(np.diff(phi))) / (2 * math.pi / 32) - 1e-9)))
    phi_f = np.concatenate([np.linspace(phi[j], phi[j + 1], sub, endpoint=False) for j in range(nphi)] + [phi[-1:]])
    # points with r varying fastest, then phi, then z (VTK structured-grid order)
    zz, pp, rr = np.meshgrid(z, phi_f, r, indexing="ij")
    pts = np.stack([ox + rr * np.cos(pp), oy + rr * np.sin(pp), oz + zz], axis=-1).reshape(-1, 3)
    vols = (0.5 * (r[1:] ** 2 - r[:-1] ** 2)[None, None, :] * np.diff(phi)[None, :, None]
            * np.diff(z)[:, None, None]).ravel()
    grid = lambda v: np.repeat(np.asarray(v).reshape(nz, nphi, nr), sub, axis=1).ravel()  # bin -> its segments
    body = _header(f"OpenMC Studio mesh tally {t.name} (per source particle, per cm^3)", "STRUCTURED_GRID")
    body += f"DIMENSIONS {nr + 1} {nphi * sub + 1} {nz + 1}\nPOINTS {len(pts)} double\n".encode("ascii")
    body += np.ascontiguousarray(pts, dtype=">f8").tobytes() + b"\n"
    body += f"CELL_DATA {nr * nphi * sub * nz}\n".encode("ascii")
    for name, vals in arrays.items():
        body += _array_block(name, grid(vals if name.endswith("_rel_err") else vals / vols * scale))
    Path(path).write_bytes(body)
    return {"cells": nr * nphi * sub * nz, "bins": nr * nphi * nz, "segments_per_bin": sub, "type": "STRUCTURED_GRID"}


def _write_tracks(path, tracks):
    pts, energy, tid, ptype, lines = [], [], [], [], []
    n = 0
    for i, tr in enumerate(tracks):
        for pt in tr.particle_tracks:
            st = pt.states
            if len(st) < 2:
                continue
            code = PARTICLE_CODES.get(str(pt.particle).split(".")[-1].lower(), -1)
            pts.append(np.column_stack([st["r"]["x"], st["r"]["y"], st["r"]["z"]]))
            energy.append(np.asarray(st["E"], float))
            tid.append(np.full(len(st), i, int))
            ptype.append(np.full(len(st), code, int))
            lines.append(np.arange(n, n + len(st)))
            n += len(st)
    if not lines:
        return None
    P = np.concatenate(pts)
    body = _header("OpenMC Studio particle tracks", "POLYDATA")
    body += f"POINTS {n} double\n".encode("ascii") + np.ascontiguousarray(P, ">f8").tobytes() + b"\n"
    conn = np.concatenate([np.concatenate([[len(l)], l]) for l in lines])
    body += f"LINES {len(lines)} {len(conn)}\n".encode("ascii") + np.ascontiguousarray(conn, ">i4").tobytes() + b"\n"
    body += f"POINT_DATA {n}\n".encode("ascii")
    body += _array_block("energy_eV", np.concatenate(energy))
    body += _array_block("track_id", np.concatenate(tid), "int")
    body += _array_block("particle", np.concatenate(ptype), "int")
    Path(path).write_bytes(body)
    return {"points": n, "lines": len(lines), "type": "POLYDATA"}


README = """OpenMC Studio results for ParaView (or VisIt)

Run: {run}
{files}
Units
- Mesh tallies: per source particle, per cm^3 of voxel. For flux that is fluence per source particle
  (particle-cm per cm^3 = 1/cm^2). <score>_rel_err is the relative error (0.05 = 5%); voxels with no
  score have 0. <score>_mean_E<i> is energy bin i on its own, lowest energy first.
- Dose maps (a "[neutron dose]" or "[photon dose]" file per particle): effective dose per voxel, in Sv/h
  (<particle>_dose_Sv_per_h_*, from the source rate set in Studio) or pSv per source particle
  (<particle>_dose_pSv_*). Add the particles with ParaView's Calculator for the total.
- Lengths are in cm.
- tracks.vtk: energy_eV at each point; particle 0 = neutron, 1 = photon, 2 = electron, 3 = positron.
- geometry_*.stl: one file per material, from Studio's STL export. Each part is its whole shape: where
  parts overlap, the model gives the space to the part higher in Studio's list, so a surface drawn inside
  another part here is not a boundary in the simulation.{stl_note}

Open in ParaView
1. File > Open, select all the files, OK, then Apply.
2. Select a mesh tally and colour it by flux_mean (or another array) in the toolbar.
3. For flux, turn on a log scale: Edit colour map > "Use log scale when mapping data to colors".
4. Filters > Slice or Threshold (on flux_rel_err, say below 0.1) to look inside.
"""


def export_run(run_dir, out_dir, stl=None, stl_note=""):
    import openmc

    run_dir, out = Path(run_dir), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = []
    try:
        dose_info = json.loads((run_dir / "dose.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        dose_info = {}
    dose = dose_info.get("tallies", {})
    sps = sorted(glob.glob(str(run_dir / "statepoint.*.h5")), key=lambda p: int(os.path.basename(p).split(".")[1]))
    if sps:
        with openmc.StatePoint(sps[-1]) as sp:
            used = set()
            for t in sp.tallies.values():
                mf = next((f for f in t.filters if isinstance(f, openmc.MeshFilter)), None)
                if mf is None:
                    continue
                m = mf.mesh
                is_cyl = isinstance(m, getattr(openmc, "CylindricalMesh", ()))
                if not (is_cyl or isinstance(m, openmc.RegularMesh)):
                    continue
                dims = [int(d) for d in m.dimension] + [1] * (3 - len(m.dimension))
                base = _safe(t.name)
                name = base
                i = 2
                while name in used:
                    name, i = f"{base}_{i}", i + 1
                used.add(name)
                d = dose.get(str(t.id))
                if d:  # a dose map: flux x ICRP coefficient per voxel volume = pSv per source particle
                    rate = dose_info.get("source_rate")
                    label = f"{d['particle']}_dose_" + ("Sv_per_h" if rate else "pSv")
                    scale = rate * 3600e-12 if rate else 1.0
                else:
                    label, scale = None, 1.0
                arrays = _mesh_arrays(t, openmc, mf, dims, label)
                info = (_write_cylindrical if is_cyl else _write_regular)(out / f"{name}.vtk", t, m, arrays, scale)
                if d:
                    info["dose"] = label
                files.append({"file": f"{name}.vtk", "tally": t.name, "arrays": list(arrays), **info})
    tpath = run_dir / "tracks.h5"
    if tpath.exists():
        info = _write_tracks(out / "tracks.vtk", openmc.Tracks(str(tpath)))
        if info:
            files.append({"file": "tracks.vtk", **info})
    for fname, data in (stl or {}).items():
        safe = _safe(Path(fname).stem) + ".stl"
        (out / safe).write_bytes(data)
        files.append({"file": safe, "type": "STL"})
    listing = "".join(f"- {f['file']}" + (f" (mesh tally \"{f['tally']}\", {f['cells']:,} voxels)" if "tally" in f else "")
                      + "\n" for f in files)
    (out / "README.txt").write_text(README.format(run=run_dir.name, files=listing or "- (no mesh tallies or tracks)\n",
                                                  stl_note=stl_note), encoding="utf-8")
    manifest = {"run": run_dir.name, "files": files}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
