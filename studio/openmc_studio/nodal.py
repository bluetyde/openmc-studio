"""Nodal solver wrapper (plan P1: docs/design/nodal-package-plan.md).

Takes two-group constants per kind of assembly and a core map, solves with openndm, and returns k and the assembly power map in the orientation the user's map
has. Also holds the numerical recipe the P2 experiments (docs/design/nodal-p2/, E10 to E15) found for making those constants from OpenMC tallies:

  1. tally in an intermediate structure (CASMO-25: its edges contain 0.625 eV and the outer edges equal the two-group ones), every type including the diffusion
     coefficient, then condense with OpenMC's own `Library.get_condensed_library`, which flux-averages D (`intermediate_structure`, `condensed_constants`);
  2. fuel from an infinite lattice, collapsed with a critical-buckling spectrum correction of its fine-group constants (`critical_buckling_fuel`);
  3. reflector from a fuel-and-reflector strip, condensed as in 1.

Nothing here runs Monte Carlo and nothing here imports openmc or openndm at load time: the Studio server imports this module whether or not the nodal package is
installed, and an operation that needs it calls `require_openndm()` and gets `NodalUnavailable` naming what is missing.

Conventions (each one found by an experiment and held by test/nodal/test_nodal_wrapper.py, with a negative control):
  * the map given to `solve_core` is TOP ROW FIRST like an OpenMC lattice; openndm's row 0 is the lowest y, so the map is flipped on the way in and the power map on the way
    out. A map symmetric under a flip hides a mistake here (E11b).
  * one node per assembly, one composition per kind; discontinuity factors are not applied (they were found to damage the power shape or to need pieces this wrapper
    does not have, E3 to E9), so the wrapper has no argument for them.
  * group order fast first; scattering is `[from, to]`.

What the wrapper does NOT promise: an accuracy. The P2 comparison put the two-step k +0.5k to +1.2k above OpenMC's on three small cores (one seed); the pass line is the
user's to set.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

SCHEMA = "openmc-studio.nodal/0.1"
TWO_GROUP_EV = (0.0, 0.625, 20.0e6)
INTERMEDIATE_NAME = "CASMO-25"
D_TOLERANCE = 10.0          # openndm warns when D differs from 1/(3 sigma_tr); the flux-averaged D legitimately differs by 20 to 35 %
MIN_OPENNDM = (0, 3, 0)
MAX_OPENNDM_EXCLUSIVE = (0, 4, 0)       # the reading rules were found on 0.3.0; a new minor version has to be checked again before it is trusted

FIELDS = ("D", "absorption", "nu_fission", "kappa_fission", "chi", "scatter", "inv_velocity")
_VECTORS = ("D", "absorption", "nu_fission", "kappa_fission", "chi", "inv_velocity")


class NodalUnavailable(RuntimeError):
    """The nodal package (openndm) or OpenMC is missing or not a version the rules were checked on; the message names what to do."""


class NodalInputError(ValueError):
    """The core map or constants cannot be solved as given."""


def _version_tuple(text: str) -> tuple[int, ...]:
    out = []
    for part in text.split("."):
        digits = "".join(c for c in part if c.isdigit())
        if not digits:
            break
        out.append(int(digits))
    return tuple(out)


def require_openndm():
    """Import and return the openndm module, or raise NodalUnavailable. Refuses a version outside [0.3.0, 0.4.0)."""
    try:
        import openndm
    except ImportError as e:
        raise NodalUnavailable("needs the nodal package (openndm 0.3.x); it is not installed in this Python (" + str(e) + ")") from e
    v = _version_tuple(getattr(openndm, "__version__", "0"))
    if not (MIN_OPENNDM <= v < MAX_OPENNDM_EXCLUSIVE):
        raise NodalUnavailable(f"openndm {getattr(openndm, '__version__', '?')} is installed; the reading rules were checked on 0.3.x only, so the wrapper refuses it until they are rechecked")
    return openndm


def versions() -> dict:
    """Installed versions, for the provenance of a nodal result (None when absent)."""
    out = {}
    for name in ("openndm", "openmc", "numpy"):
        try:
            mod = __import__(name)
            out[name] = getattr(mod, "__version__", None)
        except ImportError:
            out[name] = None
    return out


# ── constants ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def check_constants(kind: str, c: dict) -> dict:
    """Return a clean copy of one kind's two-group constants, or raise NodalInputError naming the field."""
    out = {}
    for f in _VECTORS:
        if f not in c and f == "inv_velocity":
            out[f] = np.ones(2)                  # enters transients only
            continue
        if f not in c and f == "kappa_fission" and "nu_fission" in c:
            out[f] = np.asarray(c["nu_fission"], float).reshape(-1)       # the power map then follows the fission-neutron source (a uniform energy per fission); k is unaffected
            continue
        if f not in c:
            raise NodalInputError(f"kind {kind!r}: missing {f}")
        v = np.asarray(c[f], float).reshape(-1)
        if v.shape != (2,) or not np.all(np.isfinite(v)):
            raise NodalInputError(f"kind {kind!r}: {f} must be two finite numbers, got {c[f]!r}")
        out[f] = v
    if "scatter" not in c:
        raise NodalInputError(f"kind {kind!r}: missing scatter")
    s = np.asarray(c["scatter"], float)
    if s.size != 4 or not np.all(np.isfinite(s)):
        raise NodalInputError(f"kind {kind!r}: scatter must be 2 x 2 [from, to], got {c['scatter']!r}")
    out["scatter"] = s.reshape(2, 2)
    if np.any(out["D"] <= 0):
        raise NodalInputError(f"kind {kind!r}: D must be positive, got {out['D'].tolist()}")
    if np.any(out["absorption"] < 0):
        raise NodalInputError(f"kind {kind!r}: absorption must not be negative")
    if np.any(out["nu_fission"] < 0):
        raise NodalInputError(f"kind {kind!r}: nu_fission must not be negative")
    if abs(out["chi"].sum() - 1.0) > 1e-6 and out["nu_fission"].sum() > 0:
        raise NodalInputError(f"kind {kind!r}: chi must sum to 1, got {out['chi'].tolist()}")
    return out


# ── the solve ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class NodalResult:
    k_eff: float
    power: np.ndarray               # (ny, nx), the user's map orientation (top row first); mean 1 over the fuelled positions; 0 elsewhere
    kinds: list                     # the map as given
    kernel: str
    converged: bool
    node_size_cm: float
    height_cm: float
    boundaries: dict
    provenance: dict = field(default_factory=dict)


def solve_core(layout, constants: dict, pitch_cm: float, height_cm: float = 1.0, *, kernel: str = "sanm", boundaries: dict | None = None, threads: int = 4) -> NodalResult:
    """Solve a 2D core, one node per assembly.

    layout     rows of kind names, TOP ROW FIRST (as an OpenMC lattice lists them); None marks a position outside the core.
    constants  kind -> two-group constants (D, absorption, nu_fission, chi, scatter [from, to], optional kappa_fission, inv_velocity), fast group first.
    boundaries physical faces 'x_min', 'x_max', 'y_min', 'y_max' (y_max is the TOP of the map) -> 'vacuum' | 'reflective' | 'zero_flux'; default all vacuum.
    """
    openndm = require_openndm()
    rows = [list(r) for r in layout]
    if not rows or not rows[0]:
        raise NodalInputError("the core map is empty")
    if any(len(r) != len(rows[0]) for r in rows):
        raise NodalInputError("the core map rows must all have the same length")
    used = sorted({k for r in rows for k in r if k is not None}, key=str)
    if not used:
        raise NodalInputError("the core map has no assembly")
    missing = [k for k in used if k not in constants]
    if missing:
        raise NodalInputError(f"no constants for kind(s) {missing}")
    if not (pitch_cm > 0 and height_cm > 0):
        raise NodalInputError("pitch and height must be positive")
    index = {k: i for i, k in enumerate(used)}
    clean = {k: check_constants(str(k), constants[k]) for k in used}
    if not any(c["nu_fission"].sum() > 0 for c in clean.values()):
        raise NodalInputError("no kind has nu_fission: there is nothing to make a critical eigenvalue from")
    comp = np.array([[index[k] if k is not None else openndm.INACTIVE for k in r] for r in rows], dtype=int)[::-1]     # openndm's row 0 is the lowest y
    bc = {"x_min": "vacuum", "x_max": "vacuum", "y_min": "vacuum", "y_max": "vacuum", "z_min": "reflective", "z_max": "reflective"}
    if boundaries:
        bad = [f for f in boundaries if f not in bc]
        if bad:
            raise NodalInputError(f"unknown boundary face(s) {bad}")
        bc.update(boundaries)
    geom = openndm.Geometry.from_lattice(comp, pitch=pitch_cm, dz=[float(height_cm)], boundaries=bc, outside="vacuum", subdivide=1)
    xs = openndm.XSLibrary(2, len(used))
    for k in used:
        c = clean[k]
        i = index[k]
        xs.set_composition(i, D=c["D"], absorption=c["absorption"], nu_fission=c["nu_fission"], kappa_fission=c["kappa_fission"], chi=c["chi"], scatter=c["scatter"],
                           inv_velocity=c["inv_velocity"])
        xs.set_adf(i, np.ones((4, 2)), n_axes=2)
    xs.finalize(warn=False)
    res = openndm.Model(geom, xs, openndm.Settings(kernel=kernel, verbosity=0, threads=int(threads))).solve()
    power = np.asarray(res.radial_power(), float)[::-1]          # back to the map's orientation
    power = np.where(np.isfinite(power), power, 0.0)
    return NodalResult(k_eff=float(res.k_eff), power=power, kinds=rows, kernel=kernel, converged=bool(getattr(res, "converged", True)), node_size_cm=float(pitch_cm),
                       height_cm=float(height_cm), boundaries=dict(bc), provenance=dict(schema=SCHEMA, versions=versions(), kernel=kernel, discontinuity_factors="none",
                                                                                          nodes_per_assembly=1))


# ── the fine-group spectrum correction (E15) ────────────────────────────────────────────────────────────────────────────────────────────
def spectrum(a: dict, b2: float):
    """Fine-group spectrum (sums to 1) and k of the homogeneous medium of `a` with buckling b2 (per cm^2).

    Balance: (Sigma_a,g + sum_{h != g} Sigma_s(g->h) + D_g b2) phi_g - sum_{h != g} Sigma_s(h->g) phi_h = (chi_g / k) sum_h nuSigma_f,h phi_h.
    `a` holds D, absorption, nu_fission, chi (n,) and scatter (n, n) as [from, to], fast group first."""
    s = np.array(a["scatter"], float)
    np.fill_diagonal(s, 0.0)
    m = np.diag(np.asarray(a["absorption"], float) + s.sum(axis=1) + np.asarray(a["D"], float) * b2) - s.T
    fm = np.outer(np.asarray(a["chi"], float), np.asarray(a["nu_fission"], float))
    w, v = np.linalg.eig(np.linalg.solve(m, fm))
    j = int(np.argmax(w.real))
    phi = np.abs(v[:, j].real)
    return phi / phi.sum(), float(w[j].real)


def critical_b2(a: dict, target: float = 1.0) -> float:
    """The buckling at which the homogeneous medium has k = target; 0 when it is not above target without leakage."""
    if spectrum(a, 0.0)[1] <= target:
        return 0.0
    lo, hi = 0.0, 0.05
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if spectrum(a, mid)[1] > target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def fast_mask(edges_ev, cutoff_ev: float = 0.625):
    """Which fine groups (fast first) are collapsed into the fast group. `edges_ev` ascending as OpenMC lists a structure."""
    e = np.asarray(edges_ev, float)
    if not np.any(np.isclose(e, cutoff_ev, rtol=1e-9, atol=0)):
        raise NodalInputError(f"the intermediate structure has no edge at {cutoff_ev} eV, so its groups cannot be collapsed onto the two-group structure")
    return e[:-1][::-1] >= cutoff_ev - 1e-9


def collapse(a: dict, weight, fast) -> dict:
    """Two-group constants from fine-group arrays with the given weights: flux-averaged D, flux-weighted absorption, nu-fission, kappa-fission and inverse velocity, the
    scattering matrix weighted by the flux of the group it leaves, chi as the fine groups' fractions summed."""
    fast = np.asarray(fast, bool)
    groups = (fast, ~fast)
    weight = np.asarray(weight, float)
    w = [weight[g] / weight[g].sum() for g in groups]
    out = {"D": np.array([(w[i] * np.asarray(a["D"], float)[g]).sum() for i, g in enumerate(groups)])}
    for f in ("absorption", "nu_fission", "kappa_fission", "inv_velocity"):
        out[f] = np.array([(w[i] * np.asarray(a[f], float)[g]).sum() for i, g in enumerate(groups)])
    sc = np.zeros((2, 2))
    s = np.asarray(a["scatter"], float)
    for i, gi in enumerate(groups):
        for j, gj in enumerate(groups):
            sc[i, j] = (w[i][:, None] * s[np.ix_(gi, gj)]).sum()
    out["scatter"] = sc
    chi = np.array([np.asarray(a["chi"], float)[g].sum() for g in groups])
    out["chi"] = chi / chi.sum()
    return out


def critical_buckling_fuel(fine: dict, edges_ev, target_k: float = 1.0, *, correct: bool = True) -> dict:
    """Two-group constants of a fuel assembly from its infinite-lattice fine-group data (D, absorption, nu_fission, kappa_fission, chi, scatter, inv_velocity, flux).

    The Monte Carlo flux of each fine group is multiplied by the ratio of the homogeneous spectrum at the buckling where k = target_k to the one at zero buckling (so the
    self-shielding the Monte Carlo flux carries is kept) and the constants are collapsed with those weights. correct=False collapses with the Monte Carlo flux alone.
    E15: target 1 gave k +0.5k..+1.2k on three small cores, against +2.3k..+2.7k plain; the core's own k as target changed it by under 0.35k, so 1 is the default."""
    fast = fast_mask(edges_ev)
    flux = np.asarray(fine["flux"], float)
    weight = flux / flux.sum()
    if correct:
        phi0, _ = spectrum(fine, 0.0)
        phic, _ = spectrum(fine, critical_b2(fine, target_k))
        weight = weight * (phic / np.maximum(phi0, 1e-300))
    return collapse(fine, weight, fast)


# ── from OpenMC (lazy imports: only a run that builds a library needs openmc) ───────────────────────────────────────────────────────────
def intermediate_structure():
    import openmc.mgxs
    return openmc.mgxs.EnergyGroups(openmc.mgxs.GROUP_STRUCTURES[INTERMEDIATE_NAME])


def two_group_structure():
    import openmc.mgxs
    return openmc.mgxs.EnergyGroups(list(TWO_GROUP_EV))


MGXS_TYPES = ["absorption", "transport", "diffusion-coefficient", "nu-fission", "kappa-fission", "chi", "inverse-velocity", "consistent nu-scatter matrix",
              "consistent scatter matrix"]


def configure_library(lib, domains):
    """Set an openmc.mgxs.Library up the way the recipe needs (intermediate structure, P0, universe domains, all types, no per-nuclide)."""
    lib.energy_groups = intermediate_structure()
    lib.legendre_order, lib.correction = 0, "P0"
    lib.mgxs_types, lib.domain_type, lib.by_nuclide = list(MGXS_TYPES), "universe", False
    lib.domains = list(domains)
    return lib


def condensed_constants(lib, domain) -> dict:
    """Two-group constants of one domain of a loaded intermediate-structure library, condensed by OpenMC (D flux-averaged), through openndm's loader."""
    require_openndm()
    from openndm.gc.mgxs import from_mgxs_library
    cond = lib.get_condensed_library(two_group_structure())
    xs = from_mgxs_library(cond, d_tolerance=D_TOLERANCE)
    rec = xs.composition([d.id for d in cond.domains].index(domain.id))
    return {"D": np.asarray(rec.D, float), "absorption": np.asarray(rec.absorption, float), "nu_fission": np.asarray(rec.nu_fission, float),
            "kappa_fission": np.asarray(rec.kappa_fission, float), "chi": np.asarray(rec.chi, float), "scatter": np.asarray(rec.scatter, float).reshape(2, 2),
            "inv_velocity": np.asarray(rec.inv_velocity, float)}


def fine_arrays(lib, domain) -> dict:
    """Fine-group arrays of one domain of a loaded intermediate-structure library, fast group first, with the Monte Carlo flux, for `critical_buckling_fuel`."""
    require_openndm()
    from openndm.gc.mgxs import from_mgxs_library
    n = len(lib.energy_groups.group_edges) - 1
    xs = from_mgxs_library(lib, d_tolerance=D_TOLERANCE)
    rec = xs.composition([d.id for d in lib.domains].index(domain.id))
    flux = np.asarray(lib.get_mgxs(domain, "transport").tallies["flux (tracklength)"].get_values()).reshape(-1)[::-1]
    s = np.asarray(rec.scatter, float).reshape(n, n)
    if np.tril(s, -1).sum() > np.triu(s, 1).sum():          # down-scatter must sit above the diagonal in [from, to] with the fast group first
        s = s.T
    return {"D": np.asarray(rec.D, float), "absorption": np.asarray(rec.absorption, float), "nu_fission": np.asarray(rec.nu_fission, float),
            "kappa_fission": np.asarray(rec.kappa_fission, float), "chi": np.asarray(rec.chi, float), "scatter": s, "inv_velocity": np.asarray(rec.inv_velocity, float),
            "flux": flux}
