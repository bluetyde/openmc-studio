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


def voxel_fluence(points_per_axis, lo, hi):
    """Mean of 1/(4 pi d^2) over a box voxel, by the midpoint rule (the source is at the origin, outside it)."""
    axes = [lo[i] + (np.arange(points_per_axis) + 0.5) * (hi[i] - lo[i]) / points_per_axis for i in range(3)]
    x, y, z = np.meshgrid(*axes, indexing="ij")
    return float(np.mean(1.0 / (4 * math.pi * (x * x + y * y + z * z))))


def ring_fluence(r0, r1, z0, z1, n=400):
    """Mean of 1/(4 pi d^2) over a full ring r0..r1, z0..z1 around the source (volume-weighted in r)."""
    r = r0 + (np.arange(n) + 0.5) * (r1 - r0) / n
    z = z0 + (np.arange(n) + 0.5) * (z1 - z0) / n
    R, Z = np.meshgrid(r, z, indexing="ij")
    w = R  # dV = r dr dphi dz
    return float(np.sum(w / (4 * math.pi * (R * R + Z * Z))) / np.sum(w))


class DoseMaps(unittest.TestCase):
    """A box map and a cylindrical map of the same point source in void: every voxel against the hand value."""

    @classmethod
    def setUpClass(cls):
        cls.work, cls.res, _ = run_fixture("dose_map")
        cls.maps = {t["name"]: t for t in cls.res["tallies"] if t["kind"] == "mesh"}
        cls.coef = coefficient("neutron", "AP", "icrp116", 14.1e6) * 1e8 * 3600e-12  # Sv/h per (1/cm^2 per source)

    def compare(self, t, want):
        got, rel = np.array(t["values"]["dose"]), np.array(t["rel_err"]["dose"])
        self.assertEqual(t["unit"], "Sv/h")
        self.assertTrue(np.all(rel > 0) and np.all(rel < 0.08), rel)
        z = (got - want) / (rel * got)
        self.assertLess(np.max(np.abs(z)), 4.5, f"worst voxel {np.argmax(np.abs(z))}: z = {z[np.argmax(np.abs(z))]:.2f}")
        self.assertLess(abs(np.mean(z)), 4 / math.sqrt(len(z)), f"mean z {np.mean(z):.3f}: a bias across all voxels")
        return got

    def test_box_map_every_voxel(self):
        t = self.maps["t_box"]
        self.assertEqual((t["scores"], t["dims"], t["dose"]["source_rate"]), (["dose"], [4, 4, 4], 1e8))
        lo, step = np.array([20.0, -10, -10]), 5.0
        want = [self.coef * voxel_fluence(24, lo + step * np.array([i, j, k]), lo + step * np.array([i + 1, j + 1, k + 1]))
                for k in range(4) for j in range(4) for i in range(4)]  # x fastest, like the map
        got = self.compare(t, np.array(want))
        self.assertEqual(int(np.argmax(got)) % 4, 0, "the voxels nearest the source are the hottest")

    def test_cylindrical_map_every_ring(self):
        t = self.maps["t_cyl"]
        self.assertEqual((t["mesh_type"], t["dims"]), ("cylindrical", [4, 1, 1]))
        want = [self.coef * ring_fluence(10 + 5 * i, 15 + 5 * i, -5, 5) for i in range(4)]
        self.compare(t, np.array(want))

    def test_paraview_export_matches_results(self):
        """The VTK writer (vtk_export.py) and results.py compute the dose map separately; they must agree."""
        from openmc_studio import vtk_export
        man = vtk_export.export_run(self.work, self.work / "vtk")
        f = next(x for x in man["files"] if x.get("dose") and x["cells"] == 64)
        self.assertEqual(f["dose"], "neutron_dose_Sv_per_h")
        raw = (self.work / "vtk" / f["file"]).read_bytes()
        key = b"SCALARS neutron_dose_Sv_per_h_mean double 1\nLOOKUP_TABLE default\n"
        i = raw.index(key) + len(key)
        vtk_vals = np.frombuffer(raw[i:i + 64 * 8], dtype=">f8")
        np.testing.assert_allclose(vtk_vals, self.maps["t_box"]["values"]["dose"], rtol=1e-12)
        self.assertIn("Dose maps", (self.work / "vtk" / "README.txt").read_text())

    def test_maps_need_no_volume_calculation(self):
        info = json.loads((self.work / "dose.json").read_text())
        self.assertEqual(info["volumes"], {})
        self.assertFalse(list(self.work.glob("volume_*.h5")))


class DoseInLattices(unittest.TestCase):
    """Dose on parts inside a RectLattice and a HexLattice (fixtures dose_lattice, dose_hex and their flat twins).

    Each lattice part is its lattice's unit cell in one element: a (cell, instance) bin, whose volume is measured in
    the box around that part only. The flat twin writes the same parts as ordinary cells, so its doses are the same
    physics: they must agree within the Monte Carlo error, and every volume must match the shape's own.
    """

    @classmethod
    def setUpClass(cls):
        if not (GEN / "dose_lattice.py").exists():
            raise RuntimeError("run `node test/generate_fixtures.js` first")
        cls.runs = {n: run_fixture(n)[1] for n in ("dose_lattice", "dose_lattice_flat", "dose_hex", "dose_hex_flat")}

    def rows(self, name):
        d = [t for t in self.runs[name]["tallies"] if t["kind"] == "dose"]
        self.assertEqual(len(d), 1, [t.get("name") for t in self.runs[name]["tallies"]])
        return {r["cell"].replace(" [unit]", ""): r for r in d[0]["rows"]}

    def test_rows_are_named_after_the_parts(self):
        self.assertEqual(sorted(self.rows("dose_lattice")), ["probe", "rod_0_0", "rod_2_1"])
        self.assertEqual(sorted(self.rows("dose_hex")), ["pin_-2_1", "pin_0_0", "pin_1_0"])
        self.assertTrue(all("instance" in r for r in self.rows("dose_hex").values()))

    def test_each_instance_volume_is_its_own_part(self):
        want = {"rod_0_0": math.pi * 4 * 12, "rod_2_1": math.pi * 4 * 12, "probe": 64.0,
                "pin_0_0": math.pi * 1.21 * 30, "pin_1_0": math.pi * 1.21 * 30, "pin_-2_1": math.pi * 1.21 * 30}
        for name in ("dose_lattice", "dose_hex"):
            for part, r in self.rows(name).items():
                v, dv = r["volume"]
                self.assertLess(abs(v - want[part]), 4 * dv + 1e-9, f"{name} {part}: {v} +/- {dv}, shape {want[part]}")

    def test_lattice_and_flat_doses_agree(self):
        for name in ("dose_lattice", "dose_hex"):
            lat, flat = self.rows(name), self.rows(name + "_flat")
            self.assertEqual(sorted(lat), sorted(flat))
            for part in lat:
                a, b = lat[part]["total"], flat[part]["total"]
                ka = "sv_per_h" if a["sv_per_h"] is not None else "pSv_per_source"
                x, y = a[ka], b[ka]
                sigma = math.hypot(x * a["rel_err"], y * b["rel_err"])
                self.assertGreater(x, 0, f"{name} {part}")
                self.assertLess(abs(x - y), 4.5 * sigma, f"{name} {part}: lattice {x:.4g}, flat {y:.4g} (sigma {sigma:.3g})")
                self.assertLess(a["rel_err"], 0.2, f"{name} {part}: {a['rel_err']}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
