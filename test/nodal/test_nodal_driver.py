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

    def test_model_warnings(self):
        w = nodal_driver.model_warnings(6.3, 10.0, {})
        self.assertEqual(len(w), 1)
        self.assertIn("10 cm tall", w[0])
        self.assertIn("1.6 node widths", w[0])
        self.assertEqual(nodal_driver.model_warnings(21.5, 366.0, {}), [], "a full-height core is not warned")
        self.assertEqual(nodal_driver.model_warnings(6.3, 25.2, {}), [], "four node widths is the edge: not warned")

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
        self.assertEqual(len(out["warnings"]), 1, "10 cm is 1.6 node widths")
        self.assertEqual(out["provenance"]["boundaries"]["x_min"], "vacuum")
        self.assertEqual((out["faces"]["x_min"]["source"], out["faces"]["x_min"]["boundary"]), ("model", "vacuum"), "the solve used the model's own plane")
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
                rc = nodal_driver.main([str(self.script), "--workdir", str(self.tmp / "y"), "--reflective", "x_min", "y_max", "--vacuum", "x_max", "--kernel", "nem"])
        finally:
            nodal_driver.two_step = real
        self.assertEqual(rc, 1)
        self.assertEqual(seen["boundaries"], {"x_min": "reflective", "y_max": "reflective", "x_max": "vacuum"})
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


# ── the outer faces, read from the model ────────────────────────────────────────────────────────────────────────────────────────────────
def variant(kinds, *edits):
    """The Studio-style script with text edits (old, new) applied; each old text must occur once."""
    text = script_text(kinds)
    for old, new in edits:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    return text


XM_LINE = 'xm, xp = openmc.XPlane(-nc * ASM / 2, boundary_type="vacuum"), openmc.XPlane(nc * ASM / 2, boundary_type="vacuum")'
YM_LINE = 'ym, yp = openmc.YPlane(-nc * ASM / 2, boundary_type="vacuum"), openmc.YPlane(nc * ASM / 2, boundary_type="vacuum")'
MODEL_LINE = "model = openmc.Model(geometry=openmc.Geometry([cell_core]), materials=materials, settings=settings)"


class OuterFaces(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="nodal_faces_"))
        cls.kinds = load("checker1")["kinds"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def model(self, name, text):
        p = self.tmp / f"{name}.py"
        p.write_text(text, encoding="utf-8", newline="\n")
        m = nodal_driver.load_model(p)
        return m.geometry, nodal_driver.core_lattice(m)

    def test_planes_through_the_faces_give_their_boundary_conditions(self):
        g, lat = self.model("plain", script_text(self.kinds))
        det = nodal_driver.detect_faces(g, lat)
        half = 4 * 6.3
        for f in nodal_driver.FACES:
            self.assertEqual(det[f]["type"], "vacuum", f)
        self.assertAlmostEqual(det["x_min"]["position_cm"], -half)
        self.assertAlmostEqual(det["y_max"]["position_cm"], half)
        g, lat = self.model("refl", variant(self.kinds, (XM_LINE, XM_LINE.replace('-nc * ASM / 2, boundary_type="vacuum"', '-nc * ASM / 2, boundary_type="reflective"'))))
        det = nodal_driver.detect_faces(g, lat)
        self.assertEqual((det["x_min"]["type"], det["x_max"]["type"]), ("reflective", "vacuum"), "only the left plane was changed")
        chosen, used, warns = nodal_driver.resolve_faces(det, None)
        self.assertEqual(chosen, {"x_min": "reflective", "x_max": "vacuum", "y_min": "vacuum", "y_max": "vacuum"})
        self.assertEqual(used["x_min"]["source"], "model")
        self.assertEqual(warns, [])

    def test_y_faces_are_the_right_way_up(self):
        # a reflective plane at the TOP of the lattice (larger y) is y_max, which is the top row of the map
        g, lat = self.model("top", variant(self.kinds, (YM_LINE, YM_LINE.replace('openmc.YPlane(nc * ASM / 2, boundary_type="vacuum")', 'openmc.YPlane(nc * ASM / 2, boundary_type="reflective")'))))
        det = nodal_driver.detect_faces(g, lat)
        self.assertEqual((det["y_max"]["type"], det["y_min"]["type"]), ("reflective", "vacuum"))

    def test_material_outside_a_face_is_named_and_warned_about(self):
        tank = (XM_LINE.replace(', boundary_type="vacuum"', ""), YM_LINE.replace(', boundary_type="vacuum"', ""))
        text = variant(self.kinds, (XM_LINE, tank[0]), (YM_LINE, tank[1]),
                       (MODEL_LINE, 'tx0, tx1 = openmc.XPlane(-nc * ASM / 2 - 5, boundary_type="vacuum"), openmc.XPlane(nc * ASM / 2 + 5, boundary_type="vacuum")\n'
                                    'ty0, ty1 = openmc.YPlane(-nc * ASM / 2 - 5, boundary_type="vacuum"), openmc.YPlane(nc * ASM / 2 + 5, boundary_type="vacuum")\n'
                                    'tank = openmc.Cell(name="tank", fill=clad, region=+tx0 & -tx1 & +ty0 & -ty1 & +zm & -zp & ~(+xm & -xp & +ym & -yp))\n'
                                    "model = openmc.Model(geometry=openmc.Geometry([cell_core, tank]), materials=materials, settings=settings)"))
        g, lat = self.model("tank", text)
        det = nodal_driver.detect_faces(g, lat)
        for f in nodal_driver.FACES:
            self.assertEqual(det[f]["type"], "material", f)
            self.assertIn("clad", det[f]["detail"].lower(), "the material just outside, not one inside the lattice")
        chosen, used, warns = nodal_driver.resolve_faces(det, None)
        self.assertEqual(set(chosen.values()), {"vacuum"})
        self.assertEqual({u["source"] for u in used.values()}, {"assumed"})
        self.assertEqual(len(warns), 4)
        self.assertTrue(all("treats the face as vacuum" in w for w in warns))
        chosen, used, warns = nodal_driver.resolve_faces(det, {"x_min": "reflective"})
        self.assertEqual((chosen["x_min"], used["x_min"]["source"], len(warns)), ("reflective", "override", 3))

    def test_a_translated_core_cell_moves_the_faces(self):
        text = variant(self.kinds, (XM_LINE, 'xm, xp = openmc.XPlane(-nc * ASM / 2 + 5.0, boundary_type="reflective"), openmc.XPlane(nc * ASM / 2 + 5.0, boundary_type="vacuum")'),
                       ("settings = openmc.Settings()", "cell_core.translation = (5.0, 0.0, 0.0)\nsettings = openmc.Settings()"))
        g, lat = self.model("moved", text)
        det = nodal_driver.detect_faces(g, lat)
        self.assertEqual((det["x_min"]["type"], det["x_max"]["type"]), ("reflective", "vacuum"))
        self.assertAlmostEqual(det["x_min"]["position_cm"], -4 * 6.3 + 5.0)

    def test_a_nested_lattice_is_unknown_and_says_so(self):
        text = variant(self.kinds, (MODEL_LINE, "model = openmc.Model(geometry=openmc.Geometry(openmc.Universe(cells=[openmc.Cell(fill=openmc.Universe(cells=[cell_core]), "
                                                "region=+xm & -xp & +ym & -yp & +zm & -zp)])), materials=materials, settings=settings)"))
        g, lat = self.model("nested", text)
        det = nodal_driver.detect_faces(g, lat)
        self.assertEqual({d["type"] for d in det.values()}, {"unknown"})
        chosen, used, warns = nodal_driver.resolve_faces(det, None)
        self.assertEqual((set(chosen.values()), len(warns)), ({"vacuum"}, 4))

    def test_white_and_periodic_are_refused_unless_overridden(self):
        g, lat = self.model("white", variant(self.kinds, (XM_LINE, XM_LINE.replace('-nc * ASM / 2, boundary_type="vacuum"', '-nc * ASM / 2, boundary_type="white"'))))
        det = nodal_driver.detect_faces(g, lat)
        self.assertEqual(det["x_min"]["type"], "white")
        with self.assertRaises(nodal.NodalInputError) as cm:
            nodal_driver.resolve_faces(det, None)
        self.assertIn("left face", str(cm.exception))
        chosen, used, warns = nodal_driver.resolve_faces(det, {"x_min": "vacuum"})
        self.assertEqual(chosen["x_min"], "vacuum")

    def test_conflicting_planes_on_one_face_are_refused(self):
        text = variant(self.kinds, (MODEL_LINE, 'extra = openmc.XPlane(-nc * ASM / 2, boundary_type="reflective")\n'
                                                "model = openmc.Model(geometry=openmc.Geometry([cell_core, openmc.Cell(fill=water, region=+extra & -xm)]), materials=materials, settings=settings)"))
        g, lat = self.model("conflict", text)
        with self.assertRaises(nodal.NodalInputError) as cm:
            nodal_driver.detect_faces(g, lat)
        self.assertIn("different boundary conditions", str(cm.exception))

    def test_without_the_geometry_every_face_is_vacuum_and_says_so(self):
        chosen, used, warns = nodal_driver.resolve_faces(None, None)
        self.assertEqual((set(chosen.values()), {u["source"] for u in used.values()}, len(warns)), ({"vacuum"}, {"default"}, 4))
        with self.assertRaises(nodal.NodalInputError):
            nodal_driver.resolve_faces(None, {"left": "vacuum"})

    def test_the_command_line_prints_what_the_model_has(self):
        p = self.tmp / "cli.py"
        p.write_text(variant(self.kinds, (XM_LINE, XM_LINE.replace('-nc * ASM / 2, boundary_type="vacuum"', '-nc * ASM / 2, boundary_type="reflective"'))), encoding="utf-8", newline="\n")
        r = subprocess.run([sys.executable, "-m", "openmc_studio.nodal_driver", str(p), "--faces"], cwd=ROOT / "studio", capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual((out["used"]["x_min"]["boundary"], out["used"]["x_min"]["source"], out["used"]["x_max"]["boundary"]), ("reflective", "model", "vacuum"))
        r = subprocess.run([sys.executable, "-m", "openmc_studio.nodal_driver", str(p), "--faces", "--vacuum", "x_min"], cwd=ROOT / "studio", capture_output=True, text=True)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual((out["used"]["x_min"]["boundary"], out["used"]["x_min"]["source"]), ("vacuum", "override"), "--vacuum wins over the model")
        self.assertEqual(out["detected"]["x_min"]["type"], "reflective", "and the detection is still what the model has")



# ── material outside a face as part of the solve ─────────────────────────────────────────────────────────────────────────────────────────
def tank_text(kinds, *, fill="water", thickness=5.0, extra_cells="", end_bc="vacuum"):
    """The Studio-style script with the core lattice in a tank of `thickness` cm of `fill` (a material variable of the script) bounded by planes with `end_bc`."""
    open_planes = (XM_LINE.replace(', boundary_type="vacuum"', ""), YM_LINE.replace(', boundary_type="vacuum"', ""))
    return variant(kinds, (XM_LINE, open_planes[0]), (YM_LINE, open_planes[1]),
                   (MODEL_LINE, f'T = {thickness}\n'
                                f'tx0, tx1 = openmc.XPlane(-nc * ASM / 2 - T, boundary_type="{end_bc}"), openmc.XPlane(nc * ASM / 2 + T, boundary_type="{end_bc}")\n'
                                f'ty0, ty1 = openmc.YPlane(-nc * ASM / 2 - T, boundary_type="{end_bc}"), openmc.YPlane(nc * ASM / 2 + T, boundary_type="{end_bc}")\n'
                                f'tank = openmc.Cell(name="tank", fill={fill}, region=+tx0 & -tx1 & +ty0 & -ty1 & +zm & -zp & ~(+xm & -xp & +ym & -yp))\n'
                                f'{extra_cells}'
                                "model = openmc.Model(geometry=openmc.Geometry([cell_core, tank" + (", extra" if extra_cells else "") + "]), materials=materials, settings=settings)"))


class OutsideLayers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="nodal_outside_"))
        cls.kinds = load("checker1")["kinds"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def model(self, name, text):
        p = self.tmp / f"{name}.py"
        p.write_text(text, encoding="utf-8", newline="\n")
        m = nodal_driver.load_model(p)
        return m.geometry, nodal_driver.core_lattice(m)

    def test_a_tank_is_one_layer_with_its_thickness_and_the_planes_behind_it(self):
        g, lat = self.model("tank", tank_text(self.kinds, fill="clad", thickness=5.0))
        for face in nodal_driver.FACES:
            pr = nodal_driver.probe_outside(g, lat, face)
            self.assertEqual(pr["status"], "ok", (face, pr))
            self.assertEqual(len(pr["layers"]), 1)
            self.assertEqual(pr["layers"][0]["name"], "clad", "the material just outside, not one inside the lattice")
            self.assertAlmostEqual(pr["layers"][0]["thickness"], 5.0, places=4)
            self.assertEqual(pr["end_bc"], "vacuum")
            self.assertIn("plane", pr["reason"])
        g, lat = self.model("tank_refl", tank_text(self.kinds, fill="clad", thickness=5.0, end_bc="reflective"))
        self.assertEqual(nodal_driver.probe_outside(g, lat, "x_min")["end_bc"], "reflective", "the plane behind the tank decides the face")

    def test_two_layers_come_nearest_first(self):
        # water 2 cm next to the core, then clad 3 cm: a second box 2 cm out, cut out of the tank cell
        text = tank_text(self.kinds, fill="clad", thickness=5.0, extra_cells=(
            'wx0, wx1 = openmc.XPlane(-nc * ASM / 2 - 2), openmc.XPlane(nc * ASM / 2 + 2)\n'
            'wy0, wy1 = openmc.YPlane(-nc * ASM / 2 - 2), openmc.YPlane(nc * ASM / 2 + 2)\n'
            'tank.region = tank.region & ~(+wx0 & -wx1 & +wy0 & -wy1)\n'
            'extra = openmc.Cell(name="water layer", fill=water, region=+wx0 & -wx1 & +wy0 & -wy1 & +zm & -zp & ~(+xm & -xp & +ym & -yp))\n'))
        g, lat = self.model("two", text)
        pr = nodal_driver.probe_outside(g, lat, "y_max")
        self.assertEqual(pr["status"], "ok", pr)
        self.assertEqual([(l["name"], round(l["thickness"], 4)) for l in pr["layers"]], [("water", 2.0), ("clad", 3.0)], "nearest first")
        self.assertEqual(nodal_driver.describe_layers(pr), "water 2 cm then clad 3 cm")

    def test_a_void_gap_ends_the_layers(self):
        text = tank_text(self.kinds, fill="water", thickness=5.0, extra_cells=(
            'gx0, gx1 = openmc.XPlane(-nc * ASM / 2 - 3), openmc.XPlane(nc * ASM / 2 + 3)\n'
            'gy0, gy1 = openmc.YPlane(-nc * ASM / 2 - 3), openmc.YPlane(nc * ASM / 2 + 3)\n'
            'tank.region = tank.region & (+gx0 & -gx1 & +gy0 & -gy1)\n'
            'extra = openmc.Cell(name="gap", fill=None, region=~(+gx0 & -gx1 & +gy0 & -gy1) & +tx0 & -tx1 & +ty0 & -ty1 & +zm & -zp)\n'))
        g, lat = self.model("gap", text)
        pr = nodal_driver.probe_outside(g, lat, "x_max")
        self.assertEqual(pr["status"], "ok", pr)
        self.assertEqual([(l["name"], round(l["thickness"], 4)) for l in pr["layers"]], [("water", 3.0)], "the void gap is not a layer")
        self.assertIn("end in void", pr["reason"])
        self.assertEqual(pr["end_bc"], "vacuum")

    def test_what_cannot_be_a_slab_is_refused_with_its_reason(self):
        # a cylindrical tank round a square core: thinner at the corners than at the middle of a face
        cyl = variant(self.kinds, (XM_LINE, XM_LINE.replace(', boundary_type="vacuum"', "")), (YM_LINE, YM_LINE.replace(', boundary_type="vacuum"', "")),
                      (MODEL_LINE, 'rc = openmc.ZCylinder(r=nc * ASM / 2 + 9.0, boundary_type="vacuum")\n'
                                   'tank = openmc.Cell(name="tank", fill=water, region=-rc & +zm & -zp & ~(+xm & -xp & +ym & -yp))\n'
                                   "model = openmc.Model(geometry=openmc.Geometry([cell_core, tank]), materials=materials, settings=settings)"))
        g, lat = self.model("cyl", cyl)
        pr = nodal_driver.probe_outside(g, lat, "x_max")
        self.assertEqual(pr["status"], "nonuniform", pr)
        self.assertIn("not the same along the face", pr["reason"])
        # a medium that goes on past 60 cm
        g, lat = self.model("deep", tank_text(self.kinds, fill="water", thickness=90.0))
        self.assertEqual(nodal_driver.probe_outside(g, lat, "x_min")["status"], "deep")
        # nothing outside but the end of the model
        g, lat = self.model("plain", script_text(self.kinds))
        self.assertEqual(nodal_driver.probe_outside(g, lat, "x_min")["status"], "none")
        # a nested lattice cannot be placed
        nested = variant(self.kinds, (MODEL_LINE, "model = openmc.Model(geometry=openmc.Geometry(openmc.Universe(cells=[openmc.Cell(fill=openmc.Universe(cells=[cell_core]), "
                                                  "region=+xm & -xp & +ym & -yp & +zm & -zp)])), materials=materials, settings=settings)"))
        g, lat = self.model("nested", nested)
        self.assertEqual(nodal_driver.probe_outside(g, lat, "x_min")["status"], "unsupported")

    def test_the_map_with_its_layers_has_the_right_shape_widths_and_corners(self):
        import openmc
        mk = lambda label, w: nodal_driver.Layer(label, openmc.Universe(cells=[openmc.Cell()]), w, label)
        L1, L2, R1, T1, T2 = mk("left1", 2.0), mk("left2", 3.0), mk("right1", 4.0), mk("top1", 5.0), mk("top2", 7.0)
        labels = [["A", "B"], ["B", "A"]]
        rows, wx, wy, n_top, n_left = nodal_driver.extend_layout(labels, 6.3, {"x_min": [L1, L2], "x_max": [R1], "y_max": [T1, T2]})
        self.assertEqual((n_top, n_left), (2, 2))
        self.assertEqual(wx, [3.0, 2.0, 6.3, 6.3, 4.0], "left layers outermost first, then the core, then the right layers nearest first")
        self.assertEqual(wy, [7.0, 5.0, 6.3, 6.3], "top layers outermost first, no bottom layer")
        self.assertEqual(rows[0], ["left2", "left1", "top2", "top2", "right1"], "the corners take the left or right side's label; the outermost top layer is the first row")
        self.assertEqual(rows[1], ["left2", "left1", "top1", "top1", "right1"])
        self.assertEqual(rows[2], ["left2", "left1", "A", "B", "right1"])
        self.assertEqual(rows[3], ["left2", "left1", "B", "A", "right1"])
        self.assertEqual(len(rows), len(wy))
        self.assertTrue(all(len(r) == len(wx) for r in rows))
        # no layers at all: the map as it was
        rows0, wx0, wy0, t0, l0 = nodal_driver.extend_layout(labels, 6.3, {})
        self.assertEqual((rows0, wx0, wy0, t0, l0), (labels, [6.3, 6.3], [6.3, 6.3], 0, 0))

    def test_strips_end_in_the_layers_and_a_fuel_edge_gets_a_strip(self):
        g, lat = self.model("tank6", tank_text([r[1:-1] for r in self.kinds[1:-1]], fill="water", thickness=6.3))
        probes = {f: nodal_driver.probe_outside(g, lat, f) for f in nodal_driver.FACES}
        rings = nodal_driver.make_layers(probes)
        self.assertEqual(sorted(rings), sorted(nodal_driver.FACES))
        labels = {l.label for ls in rings.values() for l in ls}
        self.assertEqual(len(labels), 1, "identical slabs on four sides share one label and so one set of constants")
        pieces, kinds, _ = nodal_driver.plan_pieces(lat, rings)
        strips = [p for p in pieces if p.role == "strip"]
        self.assertTrue(strips, "a core whose edge is fuel gets strips because layers follow it")
        for st in strips:
            self.assertAlmostEqual(st.widths[-1], 6.3, places=6)
            self.assertEqual(st.widths[:-1], [6.3] * (len(st.widths) - 1), "the lattice entries keep the pitch")
            self.assertIn("| water 6.3 cm", st.label)
            self.assertEqual(st.x_bcs, ("reflective", "vacuum"))
        # without layers the same core has no strip at all (fuel to the edge)
        pieces0, _, _ = nodal_driver.plan_pieces(lat)
        self.assertEqual([p.role for p in pieces0], ["infinite", "infinite"])

    def test_the_reading_names_the_boundary_behind_the_layers_and_leaves_overridden_faces_alone(self):
        g, lat = self.model("tank_refl2", tank_text(self.kinds, fill="clad", thickness=5.0, end_bc="reflective"))
        det, probes, rings = nodal_driver.read_outside(g, lat, None)
        self.assertEqual({d["type"] for d in det.values()}, {"reflective"}, "the plane behind the tank is the boundary of the extended core")
        self.assertEqual(sorted(rings), sorted(nodal_driver.FACES))
        self.assertIn("clad 5 cm", det["x_min"]["detail"])
        det, probes, rings = nodal_driver.read_outside(g, lat, {"x_min": "vacuum"})
        self.assertNotIn("x_min", rings, "a face the caller named is not probed: the caller's word is taken")
        self.assertEqual(det["x_min"]["type"], "material")
        self.assertEqual(sorted(rings), ["x_max", "y_max", "y_min"])
        self.assertEqual(nodal_driver.read_outside(None, lat, None), (None, {}, {}))

    def test_a_face_that_cannot_be_a_slab_keeps_its_reason_and_stays_vacuum_with_a_warning(self):
        cyl = variant(self.kinds, (XM_LINE, XM_LINE.replace(', boundary_type="vacuum"', "")), (YM_LINE, YM_LINE.replace(', boundary_type="vacuum"', "")),
                      (MODEL_LINE, 'rc = openmc.ZCylinder(r=nc * ASM / 2 + 9.0, boundary_type="vacuum")\n'
                                   'tank = openmc.Cell(name="tank", fill=water, region=-rc & +zm & -zp & ~(+xm & -xp & +ym & -yp))\n'
                                   "model = openmc.Model(geometry=openmc.Geometry([cell_core, tank]), materials=materials, settings=settings)"))
        g, lat = self.model("cyl2", cyl)
        det, probes, rings = nodal_driver.read_outside(g, lat, None)
        self.assertEqual(rings, {})
        self.assertEqual({d["type"] for d in det.values()}, {"material"})
        self.assertIn("not the same along the face", det["x_max"]["detail"])
        chosen, used, warns = nodal_driver.resolve_faces(det, None)
        self.assertEqual(set(chosen.values()), {"vacuum"})
        self.assertEqual(len(warns), 4)
        self.assertTrue(all("not taken into the solve" in w for w in warns))

    def test_more_layers_than_the_limit_are_refused(self):
        g, lat = self.model("tank_limit", tank_text(self.kinds, fill="clad", thickness=5.0))
        self.assertEqual(nodal_driver.MAX_LAYERS, 3, "the documented limit")
        saved = nodal_driver.MAX_LAYERS
        nodal_driver.MAX_LAYERS = 0
        try:
            pr = nodal_driver.probe_outside(g, lat, "x_min")
        finally:
            nodal_driver.MAX_LAYERS = saved
        self.assertEqual(pr["status"], "unsupported")
        self.assertIn("at most 0", pr["reason"])
        self.assertEqual(nodal_driver.probe_outside(g, lat, "x_min")["status"], "ok", "and the limit is back")

    def test_the_walk_sees_the_layer_start_where_the_face_is(self):
        # a thin layer (0.4 cm, eight steps of the probe) next to the core is found with its thickness
        g, lat = self.model("thin", tank_text(self.kinds, fill="clad", thickness=0.4))
        pr = nodal_driver.probe_outside(g, lat, "y_min")
        self.assertEqual(pr["status"], "ok")
        self.assertAlmostEqual(pr["layers"][0]["thickness"], 0.4, places=4)

    def test_the_command_line_reports_the_layers_taken_into_the_solve(self):
        p = self.tmp / "cli_tank.py"
        p.write_text(tank_text(self.kinds, fill="clad", thickness=5.0), encoding="utf-8", newline="\n")
        r = subprocess.run([sys.executable, "-m", "openmc_studio.nodal_driver", str(p), "--faces"], cwd=ROOT / "studio", capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual({o["status"] for o in out["outside"].values()}, {"ok"})
        self.assertEqual([l["name"] for l in out["outside"]["x_min"]["layers"]], ["clad"])
        for face in nodal_driver.FACES:
            self.assertEqual((out["used"][face]["boundary"], out["used"][face]["source"]), ("vacuum", "model"))
            self.assertIn("clad 5 cm", out["used"][face]["detail"])
        self.assertEqual(out["warnings"], [], "a tank taken into the solve is nothing to warn about")


class TankInTheSolve(unittest.TestCase):
    """The checkerboard of the saved Monte Carlo run is a 6 x 6 fuel lattice with a ring of water lattice sites round it. The same physics is the 6 x 6 lattice in a tank of 6.3 cm of water (one
    assembly width) with vacuum behind: OpenMC's k is the saved run's (0.94469). The driver must treat the tank as part of the solve (about +1.0k, as with the ring in the lattice) and, with
    the layers switched off by naming the faces vacuum, as a bare core (far lower)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="nodal_tank_run_"))
        cls.core = load("checker1")
        inner = [row[1:-1] for row in cls.core["kinds"][1:-1]]
        script = cls.tmp / "model.py"
        script.write_text(tank_text(inner, fill="water", thickness=6.3), encoding="utf-8", newline="\n")
        model = nodal_driver.load_model(script)
        lattice = nodal_driver.core_lattice(model)
        mats = __import__("openmc").Materials(model.geometry.get_all_materials().values())
        kw = dict(particles=6000, batches=60, inactive=15, seed=11, threads=int(os.environ.get("OMP_NUM_THREADS", "4")), geometry=model.geometry)
        cls.on = nodal_driver.two_step(lattice, mats, workdir=cls.tmp / "on", **kw)
        cls.off = nodal_driver.two_step(lattice, mats, workdir=cls.tmp / "off", boundaries={f: "vacuum" for f in nodal_driver.FACES}, **kw)
        thin_script = cls.tmp / "thin.py"
        thin_script.write_text(tank_text(inner, fill="water", thickness=3.15), encoding="utf-8", newline="\n")
        thin_model = nodal_driver.load_model(thin_script)
        cls.thin = nodal_driver.two_step(nodal_driver.core_lattice(thin_model), __import__("openmc").Materials(thin_model.geometry.get_all_materials().values()), workdir=cls.tmp / "thin",
                                         **{**kw, "geometry": thin_model.geometry})
        print(f"[tank] with the layers {(cls.on.nodal.k_eff - float(cls.core['k'])) * 1e5:+.0f} pcm, without {(cls.off.nodal.k_eff - float(cls.core['k'])) * 1e5:+.0f} pcm; pieces "
              + "; ".join(f"{l.split(' | ')[-1] if ' | ' in l else l} {k:.4f}" for l, _, k, _, _ in cls.on.pieces), flush=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_k_with_the_tank_is_the_rings_k(self):
        d = (self.on.nodal.k_eff - float(self.core["k"])) * 1e5
        self.assertLess(abs(d - E15["checker1"]), WINDOW, f"{d:+.0f} pcm; the same core with the ring as lattice sites gave +1,018 (E15) and +1,042 (the driver)")

    def test_without_the_layers_the_core_is_bare_and_far_too_low(self):
        d_on = (self.on.nodal.k_eff - float(self.core["k"])) * 1e5
        d_off = (self.off.nodal.k_eff - float(self.core["k"])) * 1e5
        self.assertLess(d_off, d_on - 3000, f"bare {d_off:+.0f} against with the tank {d_on:+.0f}")

    def test_half_the_water_is_worth_less_than_all_of_it_and_more_than_none(self):
        """A 3.15 cm tank is a node 3.15 cm wide, not one assembly wide: k falls between the bare core and the 6.3 cm tank."""
        d = {name: (run.nodal.k_eff - float(self.core["k"])) * 1e5 for name, run in (("bare", self.off), ("thin", self.thin), ("full", self.on))}
        self.assertLess(d["thin"], d["full"] - 150, d)
        self.assertGreater(d["thin"], d["bare"] + 3000, d)
        self.assertIn("water 3.15 cm", self.thin.faces["x_min"]["detail"])

    def test_the_faces_say_what_was_done(self):
        for face in nodal_driver.FACES:
            u = self.on.faces[face]
            self.assertEqual((u["source"], u["boundary"]), ("model", "vacuum"))
            self.assertIn("water 6.3 cm", u["detail"])
            self.assertIn("part of the solve", u["detail"])
            self.assertEqual(self.off.faces[face]["source"], "override")
        self.assertFalse([w for w in self.on.warnings if "treats the face as vacuum" in w], "no vacuum-assumed warning where the tank is in the solve")
        self.assertEqual(len([w for w in self.off.warnings if "treats the face as vacuum" in w]), 0, "overridden faces warn about nothing")
        self.assertIn("extra node layers", self.on.provenance["recipe"])

    def test_the_power_map_is_the_cores_own_and_matches_the_run(self):
        self.assertEqual(np.asarray(self.on.nodal.power).shape, (6, 6))
        ref = self.core["power"][1:-1, 1:-1]
        ref = ref / ref.mean()
        p = np.asarray(self.on.nodal.power)
        p = p / p.mean()
        rms = 100 * np.sqrt(((p / ref - 1) ** 2).mean())
        self.assertLess(rms, 5.0, f"assembly power rms {rms:.1f} % against the saved Monte Carlo run")
        self.assertGreater(100 * np.sqrt(((p[::-1] / ref - 1) ** 2).mean()), 8.0, "the checkerboard read upside down must be visibly wrong")


if __name__ == "__main__":
    unittest.main(verbosity=2)
