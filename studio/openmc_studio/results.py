"""Turn a finished run folder into JSON for the page: tallies, mesh maps, tracks."""
import glob
import math
import os

import numpy as np

MAX_TRACK_POINTS = 150_000  # across all particles, to keep the response small


def _num(v):
    v = float(v)
    return v if math.isfinite(v) else None


def _energy_label(lo, hi):
    def f(e):
        if e == 0:
            return "0"
        if e < 1:
            return f"{e:.3g} eV"
        if e < 1e3:
            return f"{e:.3g} eV"
        if e < 1e6:
            return f"{e / 1e3:.3g} keV"
        return f"{e / 1e6:.3g} MeV"
    return f"{f(lo)} – {f(hi)}"


def load(run_dir):
    import openmc

    out = {"summary": None, "tallies": [], "tracks": [], "tracks_truncated": False}
    sps = sorted(glob.glob(os.path.join(run_dir, "statepoint.*.h5")),
                 key=lambda p: int(os.path.basename(p).split(".")[1]))
    if sps:
        with openmc.StatePoint(sps[-1]) as sp:
            summary = {"run_mode": sp.run_mode, "batches": int(sp.n_batches), "particles": int(sp.n_particles),
                       "seed": int(sp.seed), "runtime_s": _num(sp.runtime.get("total", float("nan"))),
                       "statepoint": os.path.basename(sps[-1])}
            if sp.run_mode == "eigenvalue":
                summary["inactive"] = int(sp.n_inactive) if hasattr(sp, "n_inactive") else 0
                if sp.keff is not None:
                    summary["keff"] = [_num(sp.keff.nominal_value), _num(sp.keff.std_dev)]
                if hasattr(sp, "k_generation") and sp.k_generation is not None:
                    summary["k_generation"] = [float(x) for x in sp.k_generation]
                    summary["n_inactive"] = int(sp.n_inactive)
                try:
                    if sp.entropy is not None and len(sp.entropy) > 0:
                        summary["entropy"] = [float(x) for x in sp.entropy]
                except Exception:
                    pass
                if getattr(sp, "k_combined", None) is not None:
                    kc = sp.k_combined
                    nom = getattr(kc, "nominal_value", None)
                    std = getattr(kc, "std_dev", None)
                    if nom is None and isinstance(kc, (list, tuple)) and len(kc) >= 2:
                        nom, std = kc[0], kc[1]
                    summary["k_combined"] = [_num(nom), _num(std)]
            out["summary"] = summary
            cell_names = {}
            mat_names = {}
            if sp.summary is not None:
                cell_names = {c.id: (c.name or f"cell {c.id}") for c in sp.summary.geometry.get_all_cells().values()}
                if hasattr(sp.summary, "materials") and sp.summary.materials is not None:
                    mat_names = {m.id: (m.name or f"mat {m.id}") for m in sp.summary.materials}
            dose = _dose_info(run_dir)
            dosed = []
            for t in sp.tallies.values():
                if str(t.id) in dose.get("tallies", {}):
                    dosed.append(t)
                else:
                    out["tallies"].append(_tally(t, cell_names, mat_names, openmc))
            out["tallies"].extend(_dose(dosed, dose, cell_names, openmc))

    tpath = os.path.join(run_dir, "tracks.h5")
    if os.path.exists(tpath):
        out["tracks"], out["tracks_truncated"] = _tracks(openmc.Tracks(tpath))
    return out


def _dose_info(run_dir):
    """dose.json, written by model.py before the run: dose tallies, cell volumes, source rate."""
    import json
    try:
        with open(os.path.join(run_dir, "dose.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _dose(tallies, info, cell_names, openmc):
    """Dose tallies -> dose per cell, per particle and in total.

    Each tally scores flux x an ICRP coefficient: pSv cm per source particle. Dividing by the cell's volume
    gives pSv per source particle; x source rate x 3600 s/h x 1e-12 Sv/pSv gives Sv/h. The relative error
    combines the tally's and the volume's (the same volume divides every particle's tally, so they share it).
    """
    rate = info.get("source_rate")
    vols = info.get("volumes", {})
    labels = info.get("labels", {})  # Studio part names for parts inside lattices
    maps = {}
    for t in tallies:
        meta = info["tallies"][str(t.id)]
        if meta.get("mesh"):
            maps.setdefault(meta["studio"], []).append((t, meta))
    out = [_dose_map(parts, rate, openmc) for parts in maps.values()]
    groups = {}
    for t in tallies:
        if info["tallies"][str(t.id)].get("mesh"):
            continue
        meta = info["tallies"][str(t.id)]
        g = groups.setdefault(meta["studio"], {"meta": meta, "cells": {}})
        # CellFilter bins are cells; CellInstanceFilter bins are (cell, instance): a part inside a lattice is
        # its unit cell in one element, and its volume is keyed "cell/instance" in dose.json
        inst = t.find_filter(openmc.CellInstanceFilter) if any(isinstance(f, openmc.CellInstanceFilter) for f in t.filters) else None
        bins = [(int(c), int(i)) for c, i in inst.bins] if inst is not None else [(int(c), None) for c in t.find_filter(openmc.CellFilter).bins]
        mean, std = t.mean.reshape(-1), t.std_dev.reshape(-1)
        for i, b in enumerate(bins):
            c = g["cells"].setdefault(b, {})
            c[meta["particle"]] = (float(mean[i]), float(std[i]))
    for studio, g in groups.items():
        rows = []
        for (cid, n), parts in g["cells"].items():
            key = f"{cid}/{n}" if f"{cid}/{n}" in vols else str(cid)
            v, dv = vols.get(key, [None, None])
            name = labels.get(key) or cell_names.get(cid, f"cell {cid}") + (f" #{n}" if n else "")
            row = {"cell": name, "cell_id": cid, "volume": [_num(v), _num(dv)] if v else None}
            if n is not None:
                row["instance"] = n
            vrel = (dv / v) if v else None

            def entry(m, s):
                if not v:
                    return None
                ps = m / v  # pSv per source particle
                rel = math.sqrt((s / m) ** 2 + vrel ** 2) if m > 0 else None
                return {"pSv_per_source": _num(ps), "sv_per_h": _num(ps * rate * 3600e-12) if rate else None,
                        "rel_err": _num(rel) if rel is not None else None}
            for p, (m, s) in parts.items():
                row[p] = entry(m, s)
            m_tot = sum(m for m, _ in parts.values())
            s_tot = math.sqrt(sum(s * s for _, s in parts.values()))
            row["total"] = entry(m_tot, s_tot)
            rows.append(row)
        meta = g["meta"]
        out.append({"name": meta["name"], "kind": "dose", "studio": studio, "data": meta["data"], "geometry": meta["geometry"],
                    "particles": sorted({p for c in g["cells"].values() for p in c}, key=["neutron", "photon"].index),
                    "source_rate": rate, "rows": rows})
    return out


def _dose_map(parts, rate, openmc):
    """A dose map: the per-particle mesh tallies summed, divided by each voxel's (exact) volume.

    Returned as an ordinary mesh result whose one score is "dose", in Sv/h when the source rate is known,
    otherwise pSv per source particle, so the viewport, the flux-map controls and the noise estimate treat it
    like any other map.
    """
    base, total, var = None, None, None
    for t, meta in parts:
        r = _tally(t, {}, {}, openmc)
        v = np.array(r["values"]["flux"])
        s = np.array(r["rel_err"]["flux"]) * v
        base = base or r
        total = v if total is None else total + v
        var = s * s if var is None else var + s * s
    mf = parts[0][0].find_filter(openmc.MeshFilter)
    m = mf.mesh
    if base["mesh_type"] == "cylindrical":
        r_, p_, z_ = (np.asarray(g, float) for g in (m.r_grid, m.phi_grid, m.z_grid))
        vox = (0.5 * (r_[1:] ** 2 - r_[:-1] ** 2)[None, None, :] * np.diff(p_)[None, :, None]
               * np.diff(z_)[:, None, None]).ravel()  # radius fastest, like the values
    else:
        vox = float(np.prod((np.asarray(m.upper_right) - np.asarray(m.lower_left)) / np.asarray(m.dimension)))
    scale = rate * 3600e-12 if rate else 1.0
    dose = total / vox * scale
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.where(total > 0, np.sqrt(var) / total, 0.0)
    meta = parts[0][1]
    res = dict(base)
    res.update(name=meta["name"], scores=["dose"], values={"dose": [float(x) for x in dose]},
               rel_err={"dose": [round(float(x), 4) for x in rel]}, unit="Sv/h" if rate else "pSv/source",
               dose={"data": meta["data"], "geometry": meta["geometry"], "source_rate": rate,
                     "particles": [p["particle"] for _, p in parts]})
    return res


def _tally(t, cell_names, mat_names, openmc):
    mean, std = t.mean, t.std_dev  # (filter bins, nuclides, scores); last filter varies fastest
    scores = list(t.scores)
    mesh_f = next((f for f in t.filters if isinstance(f, openmc.MeshFilter)), None)
    if mesh_f is not None and isinstance(mesh_f.mesh, (openmc.RegularMesh, getattr(openmc, "CylindricalMesh", ()))):
        m = mesh_f.mesh
        is_cyl = hasattr(openmc, "CylindricalMesh") and isinstance(m, openmc.CylindricalMesh)
        dims = [int(d) for d in m.dimension]
        dims += [1] * (3 - len(dims))
        shape = [f.num_bins for f in t.filters]
        k = t.filters.index(mesh_f)
        mean_f = mean.reshape(shape + list(mean.shape[1:]))
        var_f = (std ** 2).reshape(shape + list(std.shape[1:]))
        other = tuple(i for i in range(len(shape)) if i != k)
        mean_m = np.moveaxis(mean_f, k, 0).sum(axis=tuple(a + 1 for a in range(len(other))) + (len(shape), ))
        var_m = np.moveaxis(var_f, k, 0).sum(axis=tuple(a + 1 for a in range(len(other))) + (len(shape), ))
        # mean_m: (mesh bins, scores), in MeshFilter.bins order; place into grid explicitly
        n = dims[0] * dims[1] * dims[2]
        values, rel = {}, {}
        idx = np.array([(b[0] - 1) + dims[0] * ((b[1] - 1) + dims[1] * (b[2] - 1)) for b in mesh_f.bins])
        for s, score in enumerate(scores):
            grid = np.zeros(n)
            grid[idx] = mean_m[:, s]
            err = np.zeros(n)
            with np.errstate(divide="ignore", invalid="ignore"):
                err[idx] = np.where(mean_m[:, s] > 0, np.sqrt(var_m[:, s]) / mean_m[:, s], 0.0)
            values[score] = [float(x) for x in grid]
            rel[score] = [round(float(x), 4) for x in err]
        res = {
            "name": t.name, "kind": "mesh", "dims": dims,
            "mesh_type": "cylindrical" if is_cyl else "regular",
            "scores": scores, "values": values, "rel_err": rel,
            "summed_over": [type(f).__name__ for i, f in enumerate(t.filters) if i != k]
        }
        if is_cyl:
            res["r_grid"] = [float(x) for x in m.r_grid]
            res["phi_grid"] = [float(x) for x in m.phi_grid]
            res["z_grid"] = [float(x) for x in m.z_grid]
            res["origin"] = [float(x) for x in getattr(m, "origin", (0.0, 0.0, 0.0))]
        else:
            res["lower"] = [float(x) for x in m.lower_left]
            res["upper"] = [float(x) for x in m.upper_right]
        return res

    labels_per_filter = []
    for f in t.filters:
        if isinstance(f, openmc.CellInstanceFilter):  # (cell, instance): a part inside a lattice, or a plain cell (0)
            labels_per_filter.append([cell_names.get(int(c), f"cell {int(c)}") + (f" #{int(i)}" if int(i) else "")
                                      for c, i in f.bins])
        elif isinstance(f, openmc.CellFilter):
            labels_per_filter.append([cell_names.get(int(b), f"cell {int(b)}") for b in f.bins])
        elif isinstance(f, openmc.EnergyFilter):
            labels_per_filter.append([_energy_label(lo, hi) for lo, hi in f.bins])
        elif isinstance(f, openmc.ParticleFilter):
            labels_per_filter.append([str(b) for b in f.bins])
        elif isinstance(f, openmc.MaterialFilter):
            labels_per_filter.append([mat_names.get(int(b), f"material {int(b)}") for b in f.bins])
        elif isinstance(f, openmc.SurfaceFilter):
            labels_per_filter.append([f"surface {int(b)}" for b in f.bins])
        elif isinstance(f, openmc.EnergyFunctionFilter):
            labels_per_filter.append(["response"])
        elif hasattr(f, "bins"):
            labels_per_filter.append([str(b) for b in f.bins])
        else:
            labels_per_filter.append(["response"])
    shape = [len(l) for l in labels_per_filter] or [1]
    rows = []
    for flat in range(mean.shape[0]):
        combo = np.unravel_index(flat, shape) if labels_per_filter else ()
        labels = [labels_per_filter[i][j] for i, j in enumerate(combo)]
        for s, score in enumerate(scores):
            mu = float(mean[flat, :, s].sum())
            sd = float(np.sqrt((std[flat, :, s] ** 2).sum()))
            rows.append({"labels": labels, "score": score, "mean": mu, "std": sd,
                         "rel_err": (sd / mu) if mu > 0 else None})
    return {"name": t.name, "kind": "table", "filters": [type(f).__name__ for f in t.filters], "scores": scores,
            "rows": rows}


def _tracks(tracks):
    total = sum(len(pt.states) for tr in tracks for pt in tr.particle_tracks)
    stride = max(1, math.ceil(total / MAX_TRACK_POINTS))
    out = []
    for tr in tracks:
        parts = []
        for pt in tr.particle_tracks:
            st = pt.states
            keep = np.arange(0, len(st), stride)
            if len(st) and keep[-1] != len(st) - 1:
                keep = np.append(keep, len(st) - 1)  # always keep where the particle ended
            r = st["r"][keep]
            parts.append({"particle": str(pt.particle).split(".")[-1].lower(),
                          "xyz": np.round(np.stack([r["x"], r["y"], r["z"]], axis=1), 3).ravel().tolist(),
                          "E": [float(f"{e:.4g}") for e in st["E"][keep]],
                          "cell": [int(c) for c in st["cell_id"][keep]]})
        out.append({"id": [int(v) for v in tr.identifier], "tracks": parts})
    return out, stride > 1
