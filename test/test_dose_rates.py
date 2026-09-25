"""Dose rates (plans/dose-rates-plan.md, stage 1) against an answer worked out by hand.

The fixtures (test/generate_fixtures.js, `dose_point*`) are Studio projects: point sources at the origin in empty
space and a void detector sphere of radius a = 2 cm centred D = 30 cm away. With nothing to scatter off, the
fluence in the sphere is geometry alone. Averaged over the ball, 1/(4 pi d^2) integrates to

    <phi> = [2 D a + (a^2 - D^2) ln((D + a)/(D - a))] / (4 pi D) / (4/3 pi a^3) per source particle,

and the dose is that times the ICRP coefficient at the line energy (log-log between table points, as both
OpenMC's filter and MCNP's DE/DF cards interpolate). The generated model.py runs as a user's run would
(volume calculation, then transport), results.py turns it into dose rates, and both must agree with the hand
calculation within the Monte Carlo error. Neither code is trusted for the reference.

Needs OpenMC and nuclear data (OPENMC_CROSS_SECTIONS). Run `node test/generate_fixtures.js` first.
Run: python test/test_dose_rates.py
"""
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import openmc
import openmc.data

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "test" / "generated"
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import results  # noqa: E402

A, D = 2.0, 30.0


def mean_fluence():
    """Average of 1/(4 pi d^2) over a ball of radius A centred D from a point source (per source particle)."""
    integral = (math.pi / D) * (2 * D * A + (A * A - D * D) * math.log((D + A) / (D - A)))  # of 1/d^2 over the ball
    return integral / (4 * math.pi) / (4 / 3 * math.pi * A ** 3)


def coefficient(particle, geometry, data, energy_ev):
    e, c = openmc.data.dose_coefficients(particle, geometry=geometry, data_source=data)
    i = np.searchsorted(e, energy_ev) - 1
    f = math.log(energy_ev / e[i]) / math.log(e[i + 1] / e[i])
    return math.exp(math.log(c[i]) + f * math.log(c[i + 1] / c[i]))  # log-log, pSv cm^2


def run_fixture(name):
    work = Path(tempfile.mkdtemp(prefix=f"studio-{name}-"))
    shutil.copy(GEN / f"{name}.py", work / "model.py")
    r = subprocess.run([sys.executable, "model.py"], cwd=work, capture_output=True, text=True, timeout=1800)
    if r.returncode:
        raise RuntimeError(f"{name} failed:\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}")
    return work, results.load(str(work)), r.stdout


class DoseRates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (GEN / "dose_point.py").exists():
            raise RuntimeError("run `node test/generate_fixtures.js` first")
        cls.work, cls.res, cls.log = run_fixture("dose_point")
        cls.work_nr, cls.res_nr, _ = run_fixture("dose_point_nr")

    def dose(self, res):
        d = [t for t in res["tallies"] if t["kind"] == "dose"]
        self.assertEqual(len(d), 1, [t["kind"] for t in res["tallies"]])
        return d[0]

    def test_volume_from_openmc(self):
        row = self.dose(self.res)["rows"][0]
        v, dv = row["volume"]
        exact = 4 / 3 * math.pi * A ** 3
        self.assertLess(dv / v, 0.01)
        self.assertLess(abs(v - exact), 4 * dv, f"volume {v} +/- {dv}, exact {exact}")

    def check(self, got, want, what):
        val, rel = got
        self.assertIsNotNone(rel, what)
        self.assertLess(rel, 0.05, f"{what}: statistics too poor ({rel:.1%})")
        self.assertLess(abs(val - want), 4 * rel * val, f"{what}: {val:.5g} vs hand {want:.5g} ({(val / want - 1):+.2%}, rel err {rel:.2%})")

    def test_neutron_and_photon_dose_rate(self):
        t = self.dose(self.res)
        self.assertEqual((t["data"], t["geometry"], t["source_rate"], t["particles"]), ("icrp116", "AP", 1e8, ["neutron", "photon"]))
        row = t["rows"][0]
        phi = 0.5 * mean_fluence()  # each source emits half the particles
        for p, e in (("neutron", 14.1e6), ("photon", 1.25e6)):
            want = coefficient(p, "AP", "icrp116", e) * phi * 1e8 * 3600e-12  # Sv/h
            self.check((row[p]["sv_per_h"], row[p]["rel_err"]), want, f"{p} dose rate")
        self.assertAlmostEqual(row["total"]["sv_per_h"], row["neutron"]["sv_per_h"] + row["photon"]["sv_per_h"], places=15)

    def test_per_source_particle_without_a_rate(self):
        t = self.dose(self.res_nr)
        self.assertIsNone(t["source_rate"])
        row = t["rows"][0]
        self.assertIsNone(row["total"]["sv_per_h"])
        want = coefficient("neutron", "ISO", "icrp74", 14.1e6) * mean_fluence()  # pSv per source particle
        self.check((row["total"]["pSv_per_source"], row["total"]["rel_err"]), want, "ICRP-74 ISO neutron dose per source particle")

    def test_dose_tallies_replace_their_raw_tallies(self):
        kinds = [t["kind"] for t in self.res["tallies"]]
        self.assertEqual(kinds, ["dose"], "the raw per-particle tallies are folded into the dose entry")
        info = json.loads((self.work / "dose.json").read_text())
        self.assertEqual(sorted(v["particle"] for v in info["tallies"].values()), ["neutron", "photon"])

    def test_tables_are_padded_like_mcnp(self):
        """Below the table OpenMC would score 0 and MCNP holds the end value: model.py pads the table down to the
        lowest transported energy with the first value, so both codes see the same function."""
        ns = {}
        exec(compile((GEN / "dose_point.py").read_text().split("\nif __name__")[0], "dose_point.py", "exec"), ns)
        f = ns["_dose_filter"]("photon", "AP", "icrp116", 1000.0)
        e, c = openmc.data.dose_coefficients("photon", geometry="AP", data_source="icrp116")
        self.assertEqual(f.interpolation, "log-log")
        self.assertEqual((f.energy[0], f.y[0]), (1000.0, c[0]))
        np.testing.assert_array_equal(f.energy[1:], e)
        n = ns["_dose_filter"]("neutron", "AP", "icrp116", 1e-5)
        self.assertEqual((n.energy[0], n.y[0], n.y[1]), (1e-5, n.y[1], n.y[1]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
