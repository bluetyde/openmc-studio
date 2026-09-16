"""Check that OpenMC can find and use the ENDF/B-VIII.0 library.

Run inside the activated conda env:
    python verify.py

It checks the OPENMC_CROSS_SECTIONS setting, confirms the data files the
OpenMC Studio material presets need are present, then runs a small
fixed-source problem twice with the same seed and compares the results.
Nothing is written to the SSD; the test runs in a temporary folder.
"""
import os
import sys
import tempfile
import time

import numpy as np
import openmc
import openmc.data

NEEDED = ["H1", "H2", "He3", "Be9", "B10", "C12", "N14", "O16", "Na23", "Al27", "Si28", "Fe56",
          "Cd113", "W184", "Pb208", "U235", "U238",
          "c_H_in_H2O", "c_D_in_D2O", "c_H_in_CH2", "c_Graphite", "c_Be"]


def fail(msg):
    print(f"FAILED: {msg}")
    sys.exit(1)


def main():
    print(f"OpenMC {openmc.__version__}, Python {sys.version.split()[0]}")
    xs = os.environ.get("OPENMC_CROSS_SECTIONS")
    if not xs:
        fail("OPENMC_CROSS_SECTIONS is not set. Run point_conda_env_here.sh, then reactivate the env.")
    if not os.path.isfile(xs):
        fail(f"OPENMC_CROSS_SECTIONS points at {xs}, which doesn't exist. Is the SSD plugged in?")
    print(f"Library: {xs}")

    lib = openmc.data.DataLibrary.from_xml(xs)
    counts = {}
    for entry in lib.libraries:
        counts[entry["type"]] = counts.get(entry["type"], 0) + 1
    print(f"Data sets: {counts}")
    have = {m for entry in lib.libraries for m in entry["materials"]}
    missing = [n for n in NEEDED if n not in have]
    if missing:
        fail(f"missing data for {missing}")
    base = os.path.dirname(xs)
    absent = [e["path"] for e in lib.libraries if not os.path.isfile(os.path.join(base, e["path"]))]
    if absent:
        fail(f"{len(absent)} files listed in cross_sections.xml are missing, e.g. {absent[:3]}")
    print("All listed data files are present.")

    def run_once(workdir):
        water = openmc.Material(name="Water")
        water.set_density("g/cm3", 1.0)
        water.add_element("H", 2.0)
        water.add_element("O", 1.0)
        water.add_s_alpha_beta("c_H_in_H2O")
        sphere = openmc.Sphere(r=30.0, boundary_type="vacuum")
        cell = openmc.Cell(fill=water, region=-sphere)
        src = openmc.IndependentSource(space=openmc.stats.Point(),
                                       energy=openmc.stats.Discrete([14.1e6], [1.0]))
        settings = openmc.Settings(run_mode="fixed source", particles=2000, batches=3, seed=12345, source=src)
        tally = openmc.Tally(name="flux")
        tally.filters = [openmc.EnergyFilter([0.0, 0.625, 1e5, 2e7])]
        tally.scores = ["flux"]
        model = openmc.Model(openmc.Geometry([cell]), openmc.Materials([water]), settings, openmc.Tallies([tally]))
        sp_path = model.run(cwd=workdir, output=False)
        with openmc.StatePoint(sp_path) as sp:
            return sp.get_tally(name="flux").mean.ravel()

    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        t0 = time.time()
        first = run_once(a)
        t1 = time.time()
        second = run_once(b)
    print(f"Test run: {t1 - t0:.1f} s (includes loading data from the library)")
    print(f"Flux in water [thermal, epithermal, fast]: {first}")
    if not np.allclose(first, second, rtol=1e-12, atol=0.0):
        fail("two runs with the same seed gave different results")
    print("Same seed, same results: OK")
    print("\nOpenMC is ready.")


if __name__ == "__main__":
    main()
