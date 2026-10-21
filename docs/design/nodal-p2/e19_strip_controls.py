"""P2, experiment E19: where does the +500 pcm of the strip come from?

E18: the strip [B B A | R] solved as four nodes with the constants the strip run itself gave is 502 pcm above OpenMC's strip (SANM, no factors; FDM -46). Three Monte Carlo pieces, each a row of
nodes with its own wrapper universe per position (so every node has its own constants, from the same run as the k it is compared with):

    periodic    [B B A]      reflective at both ends: an infinite repetition of the three fuel nodes. Only fuel/fuel faces: the error of the nodal solution with node-averaged constants, no leakage.
    vacuum      [B B A]      reflective at one end, vacuum at the other: adds the leakage through a fuel node into vacuum.
    reflector   [B B A | R]  as E13/E18: adds a reflector layer in front of the vacuum.

For each: OpenMC k, and the nodal k from the piece's own node constants (SANM and FDM, no factors), nodal minus OpenMC in pcm. The step from one piece to the next is the cost of that interface. Constants are
CASMO-25 condensed to two groups with OpenMC's flux-averaged D, as everywhere in this series.

    OMP_NUM_THREADS=8 PYTHONPATH=studio:docs/design/nodal-p2 python docs/design/nodal-p2/e19_strip_controls.py [particles batches inactive]
"""
import sys
import tempfile
from pathlib import Path

import numpy as np
import openmc

from openmc_studio import nodal, nodal_driver

particles = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
batches = int(sys.argv[2]) if len(sys.argv) > 2 else 150
inactive = int(sys.argv[3]) if len(sys.argv) > 3 else 30
PITCH, N = 1.26, 5
ASM = N * PITCH
HEIGHT = 1.0


def build():
    openmc.reset_auto_ids()

    def uo2(name, enr):
        m = openmc.Material(name=name)
        m.add_nuclide("U235", enr / 100); m.add_nuclide("U238", 1 - enr / 100); m.add_nuclide("O16", 2.0)
        m.set_density("g/cm3", 10.4)
        return m
    fa, fb = uo2("fuel 2.4%", 2.4), uo2("fuel 3.1%", 3.1)
    clad = openmc.Material(name="clad"); clad.add_element("Zr", 1.0); clad.set_density("g/cm3", 6.55)
    water = openmc.Material(name="water")
    water.add_nuclide("H1", 2.0); water.add_nuclide("O16", 1.0); water.set_density("g/cm3", 0.74); water.add_s_alpha_beta("c_H_in_H2O")

    def assembly(fuel, name):
        f, c = openmc.ZCylinder(r=0.4096), openmc.ZCylinder(r=0.475)
        pin = openmc.Universe(cells=[openmc.Cell(fill=fuel, region=-f), openmc.Cell(fill=clad, region=+f & -c), openmc.Cell(fill=water, region=+c)])
        a, b = openmc.ZCylinder(r=0.56), openmc.ZCylinder(r=0.60)
        tube = openmc.Universe(cells=[openmc.Cell(fill=water, region=-a), openmc.Cell(fill=clad, region=+a & -b), openmc.Cell(fill=water, region=+b)])
        lat = openmc.RectLattice()
        lat.pitch, lat.lower_left = (PITCH, PITCH), (-ASM / 2, -ASM / 2)
        lat.universes = [[tube if (i == N // 2 and j == N // 2) else pin for i in range(N)] for j in range(N)]
        return openmc.Universe(cells=[openmc.Cell(fill=lat, region=-openmc.model.RectangularPrism(ASM, ASM))], name=name)
    return {"A": assembly(fa, "A"), "B": assembly(fb, "B"), "R": openmc.Universe(cells=[openmc.Cell(fill=water)], name="R")}, openmc.Materials([fa, fb, clad, water])


def wrap(u, tag):
    return openmc.Universe(cells=[openmc.Cell(fill=u)], name=f"{u.name}{tag}")


def run_row(label, order, bcs, base, materials, workdir):
    """order: kinds left to right; one wrapper universe per position. Returns (k, k_std, constants per position)."""
    wrappers = [wrap(base[kd], i) for i, kd in enumerate(order)]
    piece = nodal_driver.Piece(label, "strip", [wrappers], wrappers, bcs)
    lib = nodal_driver._run_piece(piece, ASM, HEIGHT, materials, dict(particles=particles, batches=batches, inactive=inactive, seed=11, threads=None), workdir / label)
    consts = {f"{kd}{i}": nodal.condensed_constants(lib, w) for i, (kd, w) in enumerate(zip(order, wrappers))}
    return piece.k, piece.k_std, consts


DATA = Path(__file__).resolve().parent / "data"
FIELDS = ("D", "absorption", "nu_fission", "kappa_fission", "chi", "scatter", "inv_velocity")


def main():
    base, materials = build()
    saved = {}
    work = Path(tempfile.mkdtemp(prefix="e19_"))
    rows = (("periodic [B B A]", ["B", "B", "A"], ("reflective", "reflective")),
            ("vacuum   [B B A]", ["B", "B", "A"], ("reflective", "vacuum")),
            ("reflector [B B A | R]", ["B", "B", "A", "R"], ("reflective", "vacuum")))
    for label, order, bcs in rows:
        k, sd, consts = run_row(label.split()[0], order, bcs, base, materials, work)
        names = [f"{kd}{i}" for i, kd in enumerate(order)]
        tag = label.split()[0]
        saved[f"{tag}__k"], saved[f"{tag}__k_std"] = k, sd
        for n in names:
            for f in FIELDS:
                saved[f"{tag}__{n}__{f}"] = np.asarray(consts[n][f], float)
        out = []
        for kernel in ("sanm", "fdm"):
            res = nodal.solve_core([names], consts, ASM, HEIGHT, kernel=kernel,
                                   boundaries={"x_min": "reflective", "x_max": bcs[1], "y_min": "reflective", "y_max": "reflective"})
            out.append((res.k_eff - k) * 1e5)
        print(f"{label:24s} OpenMC k {k:.5f} +/- {sd * 1e5:.0f} pcm | nodal minus OpenMC: sanm {out[0]:+6.0f}  fdm {out[1]:+6.0f} pcm", flush=True)


    np.savez_compressed(DATA / "strips_e19.npz", **saved)
    print("saved data/strips_e19.npz")


if __name__ == "__main__":
    main()
