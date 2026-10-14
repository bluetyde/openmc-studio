"""The nodal two-step driver (studio/openmc_studio/nodal_driver.py) against the saved Monte Carlo cores and against its own refusals.

The cores are the three saved runs of docs/design/nodal-p2/data/ (an 8 x 8 checkerboard and 9 x 9 and 11 x 11 zoned cores of two 5 x 5 pin assemblies and a water
reflector, vacuum outside); the driver builds the same lattices, runs its own small pieces (6,000 x 60 particles: noise of a few hundred pcm on each piece) and solves.
References: OpenMC's own k and kappa-fission power per assembly from the saved runs, and E15's printed two-step k (+539 / +1,150 / +1,018 pcm at 20,000 x 150, one seed).
The windows below are wide enough for the pieces' statistics (several hundred pcm) and narrow enough to catch a wrong recipe: the plain collapse is +2.3k to +2.7k.

  Planning     which pieces the map asks for (no Monte Carlo): roles, strips, refusals.
  TwoStep      the three cores through the driver: k window, power rms, the orientation control, the pieces' own k against E15's.

Needs openmc, openndm 0.3.0 and OPENMC_CROSS_SECTIONS; run it with `node test/run_all.cjs nodal` or  python test/nodal/test_nodal_driver.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "studio"))
try:
    import openmc
    import openndm  # noqa: F401
    from openmc_studio import nodal, nodal_driver
except ImportError as e:  # a test that cannot run is a failure, not a quiet pass
    raise SystemExit(f"test_nodal_driver: needs openmc and openndm ({e}). Run it with `node test/run_all.cjs nodal`.")

DATA = ROOT / "docs" / "design" / "nodal-p2" / "data"
PITCH, N = 1.26, 5
ASM = N * PITCH


def make_core(kinds):
    """The saved cores' lattice: returns (lattice, materials). Fresh objects every call."""
    openmc.reset_auto_ids()

    def uo2(name, enr):
        m = openmc.Material(name=name)
        m.add_nuclide("U235", enr / 100)
        m.add_nuclide("U238", 1 - enr / 100)
        m.add_nuclide("O16", 2.0)
        m.set_density("g/cm3", 10.4)
        return m
    fa, fb = uo2("fuel 2.4%", 2.4), uo2("fuel 3.1%", 3.1)
    clad = openmc.Material(name="clad")
    clad.add_element("Zr", 1.0)
    clad.set_density("g/cm3", 6.55)
    water = openmc.Material(name="water")
    water.add_nuclide("H1", 2.0)
    water.add_nuclide("O16", 1.0)
    water.set_density("g/cm3", 0.74)
    water.add_s_alpha_beta("c_H_in_H2O")

    def assembly(fuel, name):
        def pin():
            f, c = openmc.ZCylinder(r=0.4096), openmc.ZCylinder(r=0.475)
            return openmc.Universe(cells=[openmc.Cell(fill=fuel, region=-f), openmc.Cell(fill=clad, region=+f & -c), openmc.Cell(fill=water, region=+c)])
        a, b = openmc.ZCylinder(r=0.56), openmc.ZCylinder(r=0.60)
        tube = openmc.Universe(cells=[openmc.Cell(fill=water, region=-a), openmc.Cell(fill=clad, region=+a & -b), openmc.Cell(fill=water, region=+b)])
        lat = openmc.RectLattice()
        lat.pitch, lat.lower_left = (PITCH, PITCH), (-ASM / 2, -ASM / 2)
        p = pin()
        lat.universes = [[tube if (i == N // 2 and j == N // 2) else p for i in range(N)] for j in range(N)]
        return openmc.Universe(cells=[openmc.Cell(fill=lat, region=-openmc.model.RectangularPrism(ASM, ASM))], name=name)
    u = {"A": assembly(fa, "asm A"), "B": assembly(fb, "asm B"), "R": openmc.Universe(cells=[openmc.Cell(fill=water)], name="reflector")}
    lattice = openmc.RectLattice(name="core")
    lattice.pitch = (ASM, ASM)
    nc = len(kinds)
    lattice.lower_left = (-nc * ASM / 2, -nc * ASM / 2)
    lattice.universes = [[u[k] for k in row] for row in kinds]
    return lattice, openmc.Materials([fa, fb, clad, water])


def load(name):
    d = np.load(DATA / f"{name}.npz")
    return {k: d[k] for k in d.files} | {"kinds": [[str(x) for x in row] for row in d["kinds"]], "name": name}


class Planning(unittest.TestCase):
    def test_the_checkerboard_asks_for_two_infinite_lattices_and_strips(self):
        lattice, _ = make_core(load("checker1")["kinds"])
        pieces, kinds, labels = nodal_driver.plan_pieces(lattice)
        roles = {lab.split("#")[0]: r for lab, (u, r) in kinds.items()}
        self.assertEqual(roles, {"asm A": "fuel", "asm B": "fuel", "reflector": "reflector"})
        self.assertEqual(sorted(p.role for p in pieces).count("infinite"), 2)
        strips = [p for p in pieces if p.role == "strip"]
        self.assertGreaterEqual(len(strips), 2, "the checkerboard's two arrangements behind the reflector give distinct strips")
        for s in strips:
            row = s.grid[0]
            self.assertEqual(row[-1].name, "reflector", "the outer end is the reflector")
            self.assertEqual(s.x_bcs, ("reflective", "vacuum"))
            self.assertLessEqual(sum(u.name != "reflector" for u in row), nodal_driver.FUEL_DEPTH)
        self.assertEqual(len(labels), 8)

    def test_the_strip_runs_from_the_inner_fuel_out_to_the_reflector(self):
        # zoned1's middle row is R A B B B B B A R: from the left edge inwards R, A, B, B; the strip is B B A R (inner end first), three fuel assemblies deep
        lattice, _ = make_core(load("zoned1")["kinds"])
        pieces, _, _ = nodal_driver.plan_pieces(lattice)
        strips = [p for p in pieces if p.role == "strip"]
        self.assertEqual(len(strips), 1, "the four lines through the middle of this symmetric core are the same strip")
        self.assertEqual([u.name for u in strips[0].grid[0]], ["asm B", "asm B", "asm A", "reflector"])
        self.assertEqual(strips[0].x_bcs, ("reflective", "vacuum"))

    def test_constants_of_a_kind_in_several_strips_are_averaged(self):
        a = {f: np.array([1.0, 2.0]) for f in nodal.FIELDS}
        b = {f: np.array([3.0, 6.0]) for f in nodal.FIELDS}
        m = nodal_driver.mean_constants([a, b])
        np.testing.assert_allclose(m["D"], [2.0, 4.0])
        np.testing.assert_allclose(nodal_driver.mean_constants([a])["D"], [1.0, 2.0])

    def test_a_thick_reflector_makes_a_strip_with_every_layer(self):
        lattice, _ = make_core(load("zoned2")["kinds"])
        pieces, _, _ = nodal_driver.plan_pieces(lattice)
        strip = next(p for p in pieces if p.role == "strip")
        self.assertEqual([u.name for u in strip.grid[0]].count("reflector"), 2, "11 x 11 core: two reflector layers at the edge of the middle row")
        self.assertEqual(len(strip.domains), 1, "one composition for the reflector kind")

    def test_refusals(self):
        lattice, _ = make_core(load("zoned1")["kinds"])
        lattice.outer = lattice.universes[0][0]
        with self.assertRaises(nodal.NodalInputError):
            nodal_driver.plan_pieces(lattice)
        lattice, _ = make_core(load("zoned1")["kinds"])
        lattice.pitch = (12.6, 6.3)
        with self.assertRaises(nodal.NodalInputError):
            nodal_driver.plan_pieces(lattice)
        with self.assertRaises(nodal.NodalInputError):
            nodal_driver.plan_pieces(openmc.HexLattice())
        lattice, _ = make_core(load("zoned1")["kinds"])
        lattice.universes = [lattice.universes, lattice.universes]            # two axial layers
        lattice.lower_left, lattice.pitch = (*lattice.lower_left, 0.0), (*lattice.pitch, 10.0)
        self.assertEqual(lattice.ndim, 3)
        with self.assertRaises(nodal.NodalInputError):
            nodal_driver.plan_pieces(lattice)
        lattice, _ = make_core([["R", "R"], ["R", "R"]])                      # nothing fissile
        with self.assertRaises(nodal.NodalInputError):
            nodal_driver.plan_pieces(lattice)
        lattice, _ = make_core([["A", "A", "A"]])                              # fuel to the edges and no reflector: nothing to condense, but fine
        pieces, kinds, _ = nodal_driver.plan_pieces(lattice)
        self.assertEqual([p.role for p in pieces], ["infinite"])
        lattice, _ = make_core([["A", "A", "A"], ["A", "A", "A"], ["A", "A", "R"]])    # a reflector kind in a corner only: no strip reaches it
        with self.assertRaises(nodal.NodalInputError):
            nodal_driver.plan_pieces(lattice)

    def test_fuel_is_told_from_reflector_by_its_nuclides(self):
        lattice, _ = make_core(load("zoned1")["kinds"])
        _, kinds, _ = nodal_driver.plan_pieces(lattice)
        self.assertEqual(sorted(r for _, r in kinds.values()), ["fuel", "fuel", "reflector"])


# E15's printed two-step k at 20,000 x 150 (docs/design/nodal-p2/e15_output.txt), pcm over OpenMC's k
E15 = {"checker1": 1018, "zoned1": 539, "zoned2": 1150}
WINDOW = 1100       # pcm each side: the pieces here have 1/8 of E15's histories, and the strips differ from E13/E15's


class TwoStep(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="nodal_driver_")
        cls.results = {}
        for name in os.environ.get("NODAL_DRIVER_CORES", "checker1,zoned1,zoned2").split(","):      # the variable only narrows a mutation run
            core = load(name)
            lattice, materials = make_core(core["kinds"])
            cls.results[name] = (core, nodal_driver.two_step(lattice, materials, workdir=Path(cls.tmp) / name, particles=6000, batches=60, inactive=15, seed=11,
                                                              threads=int(os.environ.get("OMP_NUM_THREADS", "4"))))
            r = cls.results[name][1]
            print(f"[{name}] two-step k {r.nodal.k_eff:.5f} vs OpenMC {float(core['k']):.5f}: {(r.nodal.k_eff - float(core['k'])) * 1e5:+.0f} pcm; pieces " + "; ".join(f"{l.split('#')[0]} {k:.4f}" for l, _, k, _, _ in r.pieces), flush=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_k_is_in_the_window_of_each_core(self):
        for name, (core, res) in self.results.items():
            d = (res.nodal.k_eff - float(core["k"])) * 1e5
            self.assertLess(abs(d - E15[name]), WINDOW, f"{name}: two-step k is {d:+.0f} pcm from OpenMC's, E15 had {E15[name]:+d}")
            self.assertGreater(d, -300, f"{name}: the nodal k is not meant to fall below OpenMC's here ({d:+.0f})")

    def test_the_pieces_look_like_e15s(self):
        # infinite lattices: E15 printed k 1.30560 (A) and 1.36276 (B) at 20,000 x 150; strips are sub-critical
        for name, (core, res) in self.results.items():
            self.assertAlmostEqual(next(k for lab, r, k, s, _ in res.pieces if lab.startswith("infinite asm A")), 1.30560, delta=0.02, msg=name)
            self.assertAlmostEqual(next(k for lab, r, k, s, _ in res.pieces if lab.startswith("infinite asm B")), 1.36276, delta=0.02, msg=name)
            for lab, role, k, s, _ in res.pieces:
                if role == "strip":
                    self.assertLess(k, 1.25, lab)

    def test_assembly_power_against_the_monte_carlo_run_and_the_orientation_control(self):
        for name, (core, res) in self.results.items():
            fuel = np.array([[k != "R" for k in row] for row in core["kinds"]])
            ref = core["power"] / core["power"][fuel].mean()

            def rms(p):
                p = p / p[fuel].mean()
                return 100 * np.sqrt(((p[fuel] / ref[fuel] - 1) ** 2).mean())
            self.assertLess(rms(res.nodal.power), 5.0, f"{name}: assembly power rms against the Monte Carlo run")
            if name == "checker1":
                self.assertGreater(rms(res.nodal.power[::-1]), 8.0, "reading the checkerboard upside down must be visibly wrong")

    def test_constants_are_by_kind_and_carry_the_recipe(self):
        core, res = self.results["checker1"]
        self.assertEqual(sorted(l.split("#")[0] for l in res.constants), ["asm A", "asm B", "reflector"])
        a = next(c for l, c in res.constants.items() if l.startswith("asm A"))
        r = next(c for l, c in res.constants.items() if l.startswith("reflector"))
        self.assertGreater(a["nu_fission"][1], 0.1)
        self.assertEqual(float(r["nu_fission"].sum()), 0.0)
        self.assertIn("critical-buckling", res.provenance["recipe"])
        self.assertEqual(res.provenance["intermediate_structure"], "CASMO-25")
        self.assertEqual(res.nodal.provenance["kernel"], "sanm")


# ── from a Studio-style model.py ─────────────────────────────────────────────────────────────────────────────────────────────────────
SCRIPT = '''"""core model, Studio style"""
import openmc
mat_a = openmc.Material(name="fuel 2.4%"); mat_a.add_nuclide("U235", 0.024); mat_a.add_nuclide("U238", 0.976); mat_a.add_nuclide("O16", 2.0); mat_a.set_density("g/cm3", 10.4)
mat_b = openmc.Material(name="fuel 3.1%"); mat_b.add_nuclide("U235", 0.031); mat_b.add_nuclide("U238", 0.969); mat_b.add_nuclide("O16", 2.0); mat_b.set_density("g/cm3", 10.4)
clad = openmc.Material(name="clad"); clad.add_element("Zr", 1.0); clad.set_density("g/cm3", 6.55)
water = openmc.Material(name="water"); water.add_nuclide("H1", 2.0); water.add_nuclide("O16", 1.0); water.set_density("g/cm3", 0.74); water.add_s_alpha_beta("c_H_in_H2O")
materials = openmc.Materials([mat_a, mat_b, clad, water])
PITCH, N = 1.26, 5
ASM = N * PITCH
def assembly(fuel, name):
    f, c = openmc.ZCylinder(r=0.4096), openmc.ZCylinder(r=0.475)
    pin = openmc.Universe(cells=[openmc.Cell(fill=fuel, region=-f), openmc.Cell(fill=clad, region=+f & -c), openmc.Cell(fill=water, region=+c)])
    a, b = openmc.ZCylinder(r=0.56), openmc.ZCylinder(r=0.60)
    tube = openmc.Universe(cells=[openmc.Cell(fill=water, region=-a), openmc.Cell(fill=clad, region=+a & -b), openmc.Cell(fill=water, region=+b)])
    lat = openmc.RectLattice(name="pins " + name)
    lat.pitch, lat.lower_left = (PITCH, PITCH), (-ASM / 2, -ASM / 2)
    lat.universes = [[tube if (i == N // 2 and j == N // 2) else pin for i in range(N)] for j in range(N)]
    return openmc.Universe(cells=[openmc.Cell(fill=lat, region=-openmc.model.RectangularPrism(ASM, ASM))], name=name)
u = {"A": assembly(mat_a, "asm A"), "B": assembly(mat_b, "asm B"), "R": openmc.Universe(cells=[openmc.Cell(fill=water)], name="reflector")}
KINDS = __KINDS__
nc = len(KINDS)
core = openmc.RectLattice(name="Core")
core.pitch = [ASM, ASM, 10.0]
core.lower_left = [-nc * ASM / 2, -nc * ASM / 2, -5.0]
core.universes = [[[u[k] for k in row] for row in KINDS] for _ in range(__LAYERS__)]
xm, xp = openmc.XPlane(-nc * ASM / 2, boundary_type="vacuum"), openmc.XPlane(nc * ASM / 2, boundary_type="vacuum")
ym, yp = openmc.YPlane(-nc * ASM / 2, boundary_type="vacuum"), openmc.YPlane(nc * ASM / 2, boundary_type="vacuum")
zm, zp = openmc.ZPlane(-5.0 * __LAYERS__, boundary_type="reflective"), openmc.ZPlane(5.0 * __LAYERS__, boundary_type="reflective")
cell_core = openmc.Cell(name="Core", fill=core, region=+xm & -xp & +ym & -yp & +zm & -zp)
settings = openmc.Settings()
settings.batches, settings.inactive, settings.particles = 20, 5, 100
model = openmc.Model(geometry=openmc.Geometry([cell_core]), materials=materials, settings=settings)
if __name__ == "__main__":
    print("RAN THE MODEL")
    model.run()
'''


def script_text(kinds, layers=1):
    """A model.py in the form Studio writes: a one-layer three-dimensional lattice in a world cell, `model` defined, the run under `__main__`."""
    return SCRIPT.replace("__KINDS__", repr(kinds)).replace("__LAYERS__", str(layers))


class FromScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="nodal_script_"))
        cls.kinds = load("checker1")["kinds"]
        cls.script = cls.tmp / "model.py"
        cls.script.write_text(script_text(cls.kinds), encoding="utf-8", newline="\n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_core_lattice_is_the_outermost_one_and_one_layer_gives_its_height(self):
        model = nodal_driver.load_model(self.script)
        self.assertGreater(len(model.geometry.get_all_lattices()), 1, "the assemblies hold pin lattices of their own")
        lat = nodal_driver.core_lattice(model)
        self.assertEqual(lat.name, "Core")
        unis, pitch, height = nodal_driver.layer(lat)
        self.assertEqual((unis.shape, round(pitch, 6), height), ((8, 8), 6.3, 10.0))
        self.assertEqual(nodal_driver.core_lattice(model, "Core").name, "Core")
        with self.assertRaises(nodal.NodalInputError):
            nodal_driver.core_lattice(model, "Not there")
        pieces, kinds, labels = nodal_driver.plan_pieces(lat)
        self.assertEqual(sorted(r for _, r in kinds.values()), ["fuel", "fuel", "reflector"])
        self.assertEqual([[l.split("#")[0] for l in row] for row in labels][1][:3], ["reflector", "asm A", "asm B"], "top row first, as the script lists it")

    def test_loading_does_not_run_the_model(self):
        r = subprocess.run([sys.executable, "-m", "openmc_studio.nodal_driver", str(self.script), "--list"], cwd=ROOT / "studio", capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("RAN THE MODEL", r.stdout)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual([(x["name"], x["shape"]) for x in out["lattices"]], [("Core", [1, 8, 8])])

    def test_two_layers_a_missing_model_and_a_script_without_fuel_are_refused(self):
        two = self.tmp / "two_layers.py"
        two.write_text(script_text(self.kinds, layers=2), encoding="utf-8", newline="\n")
        with self.assertRaises(nodal.NodalInputError) as cm:
            nodal_driver.plan_pieces(nodal_driver.core_lattice(nodal_driver.load_model(two)))
        self.assertIn("axial layer", str(cm.exception))
        bad = self.tmp / "no_model.py"
        bad.write_text("x = 1\n", encoding="utf-8")
        with self.assertRaises(nodal.NodalInputError):
            nodal_driver.load_model(bad)
        water_only = self.tmp / "water_only.py"
        water_only.write_text(script_text([["R", "R"], ["R", "R"]]), encoding="utf-8", newline=chr(10))
        with self.assertRaises(nodal.NodalInputError) as cm:
            nodal_driver.plan_pieces(nodal_driver.core_lattice(nodal_driver.load_model(water_only)))
        self.assertIn("fissile", str(cm.exception))

    def test_the_command_line_runs_the_whole_thing(self):
        env = dict(os.environ, OMP_NUM_THREADS=os.environ.get("OMP_NUM_THREADS", "4"))
        r = subprocess.run([sys.executable, "-W", "ignore", "-m", "openmc_studio.nodal_driver", str(self.script), "--workdir", str(self.tmp / "run"), "--particles", "6000",
                            "--batches", "60", "--inactive", "15", "--seed", "11"], cwd=ROOT / "studio", capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stdout[-500:] + r.stderr[-1500:])
        out = json.loads(r.stdout.strip().splitlines()[-1])
        core = load("checker1")
        d = (out["k_eff"] - float(core["k"])) * 1e5
        self.assertLess(abs(d - E15["checker1"]), WINDOW, f"through the command line: {d:+.0f} pcm")
        self.assertEqual(out["height_cm"], 10.0)
        self.assertEqual(out["provenance"]["boundaries"]["x_min"], "vacuum")
        self.assertEqual(np.array(out["power"]).shape, (8, 8))
        self.assertEqual(len(out["pieces"]), 4)
        self.assertEqual(sorted(k.split("#")[0] for k in out["constants"]), ["asm A", "asm B", "reflector"])

    def test_a_refusal_is_one_json_line_and_exit_one(self):
        bad = subprocess.run([sys.executable, "-m", "openmc_studio.nodal_driver", str(self.script), "--workdir", str(self.tmp / "x"), "--lattice", "Nope"],
                             cwd=ROOT / "studio", capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)
        reply = json.loads(bad.stdout.strip().splitlines()[-1])
        self.assertFalse(reply["ok"])
        self.assertIn("Nope", reply["message"])


    def test_reflective_faces_reach_the_solve(self):
        seen = {}

        def stub(*args, **kw):
            seen.update(kw)
            raise nodal.NodalInputError("stopped after reading the arguments")
        real = nodal_driver.two_step
        nodal_driver.two_step = stub
        try:
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = nodal_driver.main([str(self.script), "--workdir", str(self.tmp / "y"), "--reflective", "x_min", "y_max", "--kernel", "nem"])
        finally:
            nodal_driver.two_step = real
        self.assertEqual(rc, 1)
        self.assertEqual(seen["boundaries"], {"x_min": "reflective", "y_max": "reflective"})
        self.assertEqual(seen["kernel"], "nem")


    def test_reflective_faces_change_the_solve_and_are_recorded(self):
        # the same seed gives the same pieces, so only the solve differs: a reflective left face must raise k by a lot (a quarter of the leakage path is closed)
        env = dict(os.environ, OMP_NUM_THREADS=os.environ.get("OMP_NUM_THREADS", "4"))
        ks = {}
        for tag, extra in (("vac", []), ("refl", ["--reflective", "x_min"])):
            r = subprocess.run([sys.executable, "-W", "ignore", "-m", "openmc_studio.nodal_driver", str(self.script), "--workdir", str(self.tmp / ("b_" + tag)), "--particles", "3000",
                                "--batches", "40", "--inactive", "10", "--seed", "5"] + extra, cwd=ROOT / "studio", capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stdout[-300:] + r.stderr[-1000:])
            ks[tag] = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(ks["refl"]["provenance"]["boundaries"]["x_min"], "reflective")
        self.assertEqual(ks["refl"]["provenance"]["boundaries"]["x_max"], "vacuum")
        self.assertGreater((ks["refl"]["k_eff"] - ks["vac"]["k_eff"]) * 1e5, 1500)


if __name__ == "__main__":
    unittest.main(verbosity=2)
