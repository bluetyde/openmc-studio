"""The plasma source the PLOW fusion-source reader writes, sampled by OpenMC (needs OpenMC; run `node test/generate_fixtures.js` first).

fusion_ring_source is the model.py Studio writes for a synthetic 10 x 32 cell record (test/fusion_records.js): one zero-thickness ring source per cell, a Muir spectrum with the cell's own
Gaussian width, isotropic. OpenMC samples 200,000 birth sites (openmc.lib.sample_external_source: the real source definition); they are compared with the record, which this test rebuilds on its own from the same formulas:
every site lies on a cell's ring (radius and height), the sites per cell follow the cells' rates (chi-square), the azimuth is uniform (Kolmogorov-Smirnov), the energy in units of each
cell's sigma has mean 0 and standard deviation 1, and the direction is isotropic. The thresholds are fixed here, at about five sigma of the statistic, before looking at the numbers.

    python test/test_fusion_source_openmc.py
"""
import contextlib
import io
import math
import os
import runpy
import tempfile
import unittest

import numpy as np
import openmc
import openmc.lib

HERE = os.path.dirname(os.path.abspath(__file__))
R0, A, KAPPA, DELTA, N_RHO, N_THETA, MEAN, TOTAL = 2.0, 0.6, 1.7, 0.33, 10, 32, 14.071, 4.0e19
N = 200_000


def record_cells():
    """The cells of test/fusion_records.js, in the same order: (r_cm, z_cm, share, sigma_MeV)."""
    s = math.asin(DELTA)
    rows = []
    for i in range(N_RHO):
        for j in range(N_THETA):
            rho, th = (i + 0.5) / N_RHO, 2 * math.pi * (j + 0.5) / N_THETA
            r = R0 + A * rho * math.cos(th + s * math.sin(th))
            z = KAPPA * A * rho * math.sin(th)
            ti = 1 + 15 * (1 - rho * rho) ** 1.5
            rows.append((r * 100, z * 100, (1 - rho * rho) ** 2 * rho * r, 0.177 * math.sqrt(ti) / 2.355))
    tot = sum(r[2] for r in rows)
    return [(r, z, w / tot, sg) for r, z, w, sg in rows]


def sample():
    openmc.reset_auto_ids()
    with contextlib.redirect_stdout(io.StringIO()):
        ns = runpy.run_path(os.path.join(HERE, "generated", "fusion_ring_source.py"), run_name="studio_test")
    model = ns["model"]
    with tempfile.TemporaryDirectory(prefix="studio_fusion_") as d:
        model.init_lib(directory=d, output=False)
        try:
            parts = openmc.lib.sample_external_source(N, prn_seed=7)
        finally:
            model.finalize_lib()
    r = np.array([p.r for p in parts])
    u = np.array([p.u for p in parts])
    return (r[:, 0], r[:, 1], r[:, 2], np.array([p.E for p in parts]), np.array([p.wgt for p in parts]), u[:, 0], u[:, 1], u[:, 2])


class TestFusionRingSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cells = record_cells()
        cls.x, cls.y, cls.z, cls.E, cls.w, cls.ux, cls.uy, cls.uz = sample()
        cls.rho = np.hypot(cls.x, cls.y)
        cr = np.array([[c[0], c[1]] for c in cls.cells])
        # the cell of every site: the ring whose (radius, height) it lies on
        d = np.hypot(cls.rho[:, None] - cr[None, :, 0], cls.z[:, None] - cr[None, :, 1])
        cls.idx = d.argmin(axis=1)
        cls.dist = d.min(axis=1)

    def test_the_sample_has_the_size_asked_and_unit_weights(self):
        self.assertEqual(len(self.E), N)
        self.assertTrue(np.allclose(self.w, 1.0))

    def test_every_site_lies_on_a_cell_ring(self):
        self.assertLess(self.dist.max(), 1e-4, f"farthest site is {self.dist.max():.3g} cm from any cell's ring (radius, height)")

    def test_the_sites_per_cell_follow_the_cell_rates(self):
        share = np.array([c[2] for c in self.cells])
        counts = np.bincount(self.idx, minlength=len(self.cells))
        expected = N * share
        keep = expected > 5                                       # chi-square needs expected counts that are not tiny
        chi2 = float(((counts[keep] - expected[keep]) ** 2 / expected[keep]).sum())
        dof = int(keep.sum()) - 1
        self.assertLess(chi2, dof + 5 * math.sqrt(2 * dof), f"chi-square {chi2:.0f} for {dof} degrees of freedom")

    def test_the_azimuth_is_uniform(self):
        phi = np.sort((np.arctan2(self.y, self.x) + math.pi) / (2 * math.pi))
        ecdf = np.arange(1, N + 1) / N
        D = max(np.abs(ecdf - phi).max(), np.abs(ecdf - 1 / N - phi).max())
        self.assertLess(D, 1.95 / math.sqrt(N), f"Kolmogorov-Smirnov distance {D:.5f}")

    def test_the_energy_is_gaussian_about_the_mean_with_each_cells_width(self):
        sig = np.array([c[3] for c in self.cells])[self.idx]
        zscore = (self.E / 1e6 - MEAN) / sig
        self.assertLess(abs(zscore.mean()), 5 / math.sqrt(N), f"mean of (E - mean) / sigma is {zscore.mean():.5f}")
        self.assertLess(abs(zscore.std() - 1), 5 / math.sqrt(2 * N), f"standard deviation of (E - mean) / sigma is {zscore.std():.5f}")

    def test_the_direction_is_isotropic(self):
        for name, u in (("ux", self.ux), ("uy", self.uy), ("uz", self.uz)):
            self.assertLess(abs(u.mean()), 5 / math.sqrt(3 * N), f"mean {name} = {u.mean():.5f}")
        self.assertLess(abs((self.uz ** 2).mean() - 1 / 3), 5 * math.sqrt(4 / 45 / N), f"mean uz^2 = {(self.uz ** 2).mean():.5f}")


if __name__ == "__main__":
    unittest.main()
