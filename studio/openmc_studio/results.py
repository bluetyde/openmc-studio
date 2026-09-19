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
                if getattr(sp, "k_generation", None) is not None:
                    summary["k_generation"] = [float(k) for k in sp.k_generation]
                if getattr(sp, "entropy", None) is not None and len(sp.entropy) > 0:
                    summary["entropy"] = [float(h) for h in sp.entropy]
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
            for t in sp.tallies.values():
                out["tallies"].append(_tally(t, cell_names, mat_names, openmc))

    tpath = os.path.join(run_dir, "tracks.h5")
    if os.path.exists(tpath):
        out["tracks"], out["tracks_truncated"] = _tracks(openmc.Tracks(tpath))
    return out


def _tally(t, cell_names, mat_names, openmc):
    mean, std = t.mean, t.std_dev  # (filter bins, nuclides, scores); last filter varies fastest
    scores = list(t.scores)
    mesh_f = next((f for f in t.filters if isinstance(f, openmc.MeshFilter)), None)
    if mesh_f is not None and isinstance(mesh_f.mesh, openmc.RegularMesh):
        m = mesh_f.mesh
        dims = [int(d) for d in m.dimension]
        dims += [1] * (3 - len(dims))
        shape = [f.num_bins for f in t.filters]
        k = t.filters.index(mesh_f)
        mean_f = mean.reshape(shape + list(mean.shape[1:]))
        var_f = (std ** 2).reshape(shape + list(std.shape[1:]))
        other = tuple(i for i in range(len(shape)) if i != k)
        mean_m = np.moveaxis(mean_f, k, 0).sum(axis=tuple(a + 1 for a in range(len(other))) + (len(shape), ))
        var_m = np.moveaxis(var_f, k, 0).sum(axis=tuple(a + 1 for a in range(len(other))) + (len(shape), ))
        # mean_m: (mesh bins, scores), in MeshFilter.bins order; place into an x-fastest grid explicitly
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
        return {"name": t.name, "kind": "mesh", "dims": dims,
                "lower": [float(x) for x in m.lower_left], "upper": [float(x) for x in m.upper_right],
                "scores": scores, "values": values, "rel_err": rel,
                "summed_over": [type(f).__name__ for i, f in enumerate(t.filters) if i != k]}

    labels_per_filter = []
    for f in t.filters:
        if isinstance(f, openmc.CellFilter):
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
