"""The parts of studio/openmc_studio/nodal.py that need neither openndm nor OpenMC (the Studio server imports the module either way).

  * importing the module loads neither openndm nor openmc (so the server starts without the nodal package);
  * a missing openndm gives NodalUnavailable with a message naming the package, and a solve refuses before doing anything;
  * the constants check, and the fine-group arithmetic (spectrum, critical buckling, collapse) against hand-solved cases.
The solves themselves are checked in test/nodal/test_nodal_wrapper.py (profile `nodal`).

    python test/test_nodal_light.py
"""
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import nodal  # noqa: E402


class Import(unittest.TestCase):
    def test_import_loads_neither_openndm_nor_openmc(self):
        code = "import sys; sys.path.insert(0, sys.argv[1]); import openmc_studio.nodal; bad = [m for m in ('openndm', 'openmc') if m in sys.modules]; print('LOADED', bad); sys.exit(1 if bad else 0)"
        r = subprocess.run([sys.executable, "-c", code, str(ROOT / "studio")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_missing_openndm_is_a_named_refusal(self):
        saved = sys.modules.get("openndm", "absent")
        sys.modules["openndm"] = None                    # makes `import openndm` raise ImportError
        try:
            with self.assertRaises(nodal.NodalUnavailable) as cm:
                nodal.solve_core([["F"]], {"F": GOOD}, 20.0, 1.0)
            self.assertIn("openndm", str(cm.exception))
            self.assertEqual(nodal.versions()["openndm"], None)
        finally:
            if saved == "absent":
                del sys.modules["openndm"]
            else:
                sys.modules["openndm"] = saved


GOOD = dict(D=[1.4, 0.4], absorption=[0.008, 0.07], nu_fission=[0.006, 0.12], chi=[1.0, 0.0], scatter=[[0.0, 0.02], [0.0, 0.0]])


class Constants(unittest.TestCase):
    def test_a_good_set_is_cleaned(self):
        c = nodal.check_constants("F", GOOD)
        self.assertEqual(c["scatter"].shape, (2, 2))
        np.testing.assert_allclose(c["kappa_fission"], GOOD["nu_fission"])       # defaulted to the fission-neutron source
        np.testing.assert_allclose(c["inv_velocity"], [1.0, 1.0])

    def test_each_defect_is_named(self):
        for field, value in (("D", [0.0, 0.4]), ("D", [1.4]), ("absorption", [-1e-3, 0.07]), ("nu_fission", [np.inf, 0.1]), ("chi", [0.6, 0.6]), ("scatter", [1, 2, 3])):
            with self.assertRaises(nodal.NodalInputError, msg=f"{field} {value}") as cm:
                nodal.check_constants("F", dict(GOOD, **{field: value}))
            self.assertIn(field, str(cm.exception))


def two_fine_groups():
    """A homogeneous two-group medium written as fine groups: fast then thermal, fission only in thermal, born fast."""
    return dict(D=np.array([1.4, 0.4]), absorption=np.array([0.01, 0.1]), nu_fission=np.array([0.0, 0.2]), chi=np.array([1.0, 0.0]),
                scatter=np.array([[0.0, 0.02], [0.0, 0.0]]), kappa_fission=np.array([0.0, 0.2]), inv_velocity=np.array([1.0, 1.0]), flux=np.array([1.0, 0.5]))


class FineGroups(unittest.TestCase):
    def test_spectrum_and_k_of_a_two_group_medium_match_the_closed_form(self):
        a = two_fine_groups()
        phi, k = nodal.spectrum(a, 0.0)
        k_hand = (0.2 / 0.1) * (0.02 / (0.01 + 0.02))              # k_inf = nuSigma_f2 / Sigma_a2 * Sigma_s12 / Sigma_R1
        self.assertAlmostEqual(k, k_hand, places=10)
        self.assertAlmostEqual(phi[1] / phi[0], 0.02 / 0.1, places=10)   # phi2 / phi1 = Sigma_s12 / Sigma_a2
        self.assertAlmostEqual(phi.sum(), 1.0)

    def test_leakage_hardens_the_spectrum_and_the_critical_buckling_gives_k_one(self):
        a = two_fine_groups()
        b2 = nodal.critical_b2(a)
        self.assertGreater(b2, 0)
        self.assertAlmostEqual(nodal.spectrum(a, b2)[1], 1.0, places=9)
        phi0, _ = nodal.spectrum(a, 0.0)
        phic, _ = nodal.spectrum(a, b2)
        self.assertGreater(phic[0] / phic[1], phi0[0] / phi0[1])
        sub = dict(a, nu_fission=a["nu_fission"] * 0.5)              # below critical without leakage: no buckling is asked for
        self.assertEqual(nodal.critical_b2(sub), 0.0)

    def test_collapse_with_the_identity_grouping_returns_the_input(self):
        a = two_fine_groups()
        out = nodal.collapse(a, a["flux"], np.array([True, False]))
        np.testing.assert_allclose(out["D"], a["D"])
        np.testing.assert_allclose(out["absorption"], a["absorption"])
        np.testing.assert_allclose(out["scatter"], a["scatter"])
        np.testing.assert_allclose(out["chi"], a["chi"])

    def test_collapse_of_four_groups_conserves_the_reaction_rates(self):
        rng = np.random.default_rng(3)
        a = dict(D=rng.uniform(0.3, 1.5, 4), absorption=rng.uniform(0.005, 0.1, 4), nu_fission=rng.uniform(0, 0.1, 4), kappa_fission=rng.uniform(0, 0.1, 4),
                 chi=np.array([0.7, 0.3, 0.0, 0.0]), inv_velocity=rng.uniform(1, 2, 4), scatter=np.triu(rng.uniform(0, 0.05, (4, 4)), 1))
        w = rng.uniform(0.5, 2.0, 4)
        fast = np.array([True, True, False, False])
        out = nodal.collapse(a, w, fast)
        for f in ("absorption", "nu_fission", "kappa_fission"):
            rate_fine = (a[f] * w).sum()
            rate_two = out[f][0] * w[fast].sum() + out[f][1] * w[~fast].sum()
            self.assertAlmostEqual(rate_fine, rate_two, places=12, msg=f)
        self.assertAlmostEqual(out["chi"].sum(), 1.0)
        np.testing.assert_allclose(out["chi"], [1.0, 0.0])             # chi = [0.7, 0.3, 0, 0]: all born in the two fast groups
        half = nodal.collapse(dict(a, chi=np.array([0.35, 0.15, 0.0, 0.0])), w, fast)
        self.assertAlmostEqual(half["chi"].sum(), 1.0, msg="a chi that sums to one half is normalised, not passed on")
        # scattering out of the fast group, summed over destinations, is the flux-weighted fine total
        tot = (w[fast][:, None] * a["scatter"][fast]).sum()
        self.assertAlmostEqual(out["scatter"][0].sum() * w[fast].sum(), tot, places=12)

    def test_the_fast_mask_follows_the_edge(self):
        edges = [0.0, 0.1, 0.625, 5.0, 20.0e6]                       # ascending, as OpenMC lists a structure
        np.testing.assert_array_equal(nodal.fast_mask(edges), [True, True, False, False])
        with self.assertRaises(nodal.NodalInputError):
            nodal.fast_mask([0.0, 0.5, 20.0e6])


if __name__ == "__main__":
    unittest.main(verbosity=2)
