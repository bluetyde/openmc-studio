"""pin_power_view.py: a mesh tally read as a pin map, and the /api/runs/<id>/pin-power endpoint over real HTTP.

The numbers are small grids worked out by hand (a uniform 3 x 3, a 4 x 4 with one hot pin at a known place, an excluded cell, two axial layers).
pin_power_table.py and peak_stats.py have their own tests; these check how the view puts them together and what it refuses.

Linux/WSL (same server startup as the other HTTP tests). Run: python test/test_pin_power_view.py
"""
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import peak_stats, pin_power_view, results, server as srv  # noqa: E402
from openmc_studio.pin_power_view import PinPowerError, analyse  # noqa: E402

TOKEN = "t" * 32
RID = "20261008-120000-pins"


def mesh(values, std=None, dims=(3, 3, 1), lower=(0.0, 0.0, 0.0), upper=(3.0, 3.0, 1.0), score="kappa-fission", name="Pin power", **extra):
    std = std if std is not None else [0.0] * len(values)
    return dict({"name": name, "kind": "mesh", "mesh_type": "regular", "dims": list(dims), "lower": list(lower), "upper": list(upper),
                 "scores": [score], "values": {score: list(values)}, "std": {score: list(std)}}, **extra)


class Reading(unittest.TestCase):
    def test_a_uniform_mesh_is_all_ones_with_the_noise_allowance_of_nine_pins(self):
        a = analyse(mesh([2.0] * 9, [0.1] * 9))
        self.assertEqual([r["relative_power"] for r in a["rows"]], [1.0] * 9)
        self.assertAlmostEqual(a["peak"]["relative_power"], 1.0)
        # sigma 0.1 on 2.0: 5 percent of the mean in every pin; the expected largest of 9 standard normals is 1.485 (Harter's table)
        self.assertAlmostEqual(a["rows"][0]["relative_sigma"], 0.05)
        self.assertAlmostEqual(a["noise"]["noise_allowance"], 0.05 * 1.4850, places=3)
        self.assertAlmostEqual(a["noise"]["noise_allowance"], 0.05 * peak_stats.expected_max_normal(9), places=12)

    def test_x_runs_fastest_and_y_up_and_each_pin_has_its_centre(self):
        # 4 x 3 pins of 0.5 x 2 cm from (10, -4): the hot one at ix = 3, iy = 1 is flat index 3 + 4 * 1 = 7
        v = [1.0] * 12
        v[7] = 3.0
        a = analyse(mesh(v, dims=(4, 3, 1), lower=(10.0, -4.0, 0.0), upper=(12.0, 2.0, 1.0)))
        hot = a["rows"][7]
        self.assertEqual((hot["ix"], hot["iy"]), (3, 1))
        self.assertAlmostEqual(hot["x_cm"], 10.0 + 3.5 * 0.5)
        self.assertAlmostEqual(hot["y_cm"], -4.0 + 1.5 * 2.0)
        self.assertEqual((a["peak"]["ix"], a["peak"]["iy"]), (3, 1))
        # mean of eleven 1s and one 3 is 1.5 / 0.75: hot 3 / 1.1667
        self.assertAlmostEqual(a["peak"]["relative_power"], 3.0 / (14.0 / 12.0))
        self.assertEqual(a["pitch_cm"], [0.5, 2.0])
        self.assertEqual(a["lower_cm"], [10.0, -4.0])

    def test_a_cell_that_scored_nothing_is_left_out_of_the_mean_and_counted(self):
        v = [1.0, 1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.0, 2.0]
        a = analyse(mesh(v))
        self.assertIsNone(a["rows"][4]["relative_power"])
        self.assertFalse(a["rows"][4]["included"])
        self.assertEqual((a["peak"]["n_used"], a["peak"]["n_excluded"]), (8, 1))
        self.assertAlmostEqual(a["peak"]["relative_power"], 2.0 / (9.0 / 8.0))  # mean of the eight that scored
        self.assertEqual(a["peak"]["ix"], 2)
        self.assertIn("left out of the mean", a["assumes"])

    def test_the_layer_picks_the_slice_and_a_layer_that_is_not_there_is_refused(self):
        v = [1.0] * 9 + [1.0] * 8 + [4.0]  # layer 1 has its hot pin at ix = 2, iy = 2
        t = mesh(v, dims=(3, 3, 2), upper=(3.0, 3.0, 2.0))
        self.assertEqual((analyse(t, layer=1)["peak"]["ix"], analyse(t, layer=1)["peak"]["iy"]), (2, 2))
        self.assertAlmostEqual(analyse(t, layer=0)["peak"]["relative_power"], 1.0)
        self.assertEqual(analyse(t, layer=1)["layers"], 2)
        for bad in (2, -1, True, "0", 0.5):
            with self.assertRaises(PinPowerError):
                analyse(t, layer=bad)

    def test_the_score_is_chosen_or_the_first_one_is_used(self):
        t = mesh([1.0] * 9)
        t["scores"].append("fission")
        t["values"]["fission"] = [1.0, 1.0, 1.0, 1.0, 5.0, 1.0, 1.0, 1.0, 1.0]
        t["std"]["fission"] = [0.0] * 9
        self.assertEqual(analyse(t)["score"], "kappa-fission")
        self.assertEqual(analyse(t, "fission")["peak"]["ix"], 1)
        with self.assertRaises(PinPowerError) as ctx:
            analyse(t, "flux")
        self.assertIn("kappa-fission, fission", str(ctx.exception))

    def test_things_that_are_not_a_pin_map_are_refused_with_a_reason(self):
        cases = [
            (dict(mesh([1.0] * 9), kind="cell"), "not a mesh"),
            (dict(mesh([1.0] * 9), mesh_type="cylindrical"), "cylindrical"),
            (mesh([1.0] * 3, dims=(3, 1, 1)), "more than one mesh cell"),
            (mesh([1.0] * 3, dims=(1, 3, 1)), "more than one mesh cell"),
            (mesh([0.0] * 9), "scored anything"),
            (mesh([1.0] * 8), "do not fill"),
        ]
        for t, word in cases:
            with self.assertRaises(PinPowerError) as ctx:
                analyse(t)
            self.assertIn(word, str(ctx.exception))
        with self.assertRaises(PinPowerError):
            analyse("nope")


class Symmetry(unittest.TestCase):
    def test_a_layout_that_matches_itself_is_within_noise_and_one_hot_pin_is_not(self):
        sym = [1.0, 2.0, 2.0, 1.0,
               2.0, 3.0, 3.0, 2.0,
               2.0, 3.0, 3.0, 2.0,
               1.0, 2.0, 2.0, 1.0]
        s = analyse(mesh(sym, [0.05] * 16, dims=(4, 4, 1), upper=(4.0, 4.0, 1.0)))
        self.assertTrue(s["symmetry"]["within_noise"])
        self.assertAlmostEqual(s["symmetry"]["max_deviation"], 0.0)
        self.assertEqual(len(s["quarter"]), 4)
        hot = list(sym)
        hot[3] = 2.0  # the corner at ix = 3, iy = 0 now differs from its three mirror images
        h = analyse(mesh(hot, [0.05] * 16, dims=(4, 4, 1), upper=(4.0, 4.0, 1.0)))
        self.assertFalse(h["symmetry"]["within_noise"])
        self.assertGreater(h["symmetry"]["max_z"], 3.0)
        self.assertGreater(h["symmetry"]["max_deviation"], 0.1)

    def test_pins_that_differ_by_less_than_their_sigma_are_still_symmetric(self):
        v = [1.0, 2.0, 2.0, 1.02,
             2.0, 3.0, 3.0, 2.0,
             2.0, 3.0, 3.0, 2.0,
             1.0, 2.0, 2.0, 1.0]
        self.assertTrue(analyse(mesh(v, [0.1] * 16, dims=(4, 4, 1), upper=(4.0, 4.0, 1.0)))["symmetry"]["within_noise"])


class Csv(unittest.TestCase):
    def test_one_line_per_pin_after_a_header_with_the_values_as_they_are(self):
        a = analyse(mesh([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0], [0.5] * 9))
        lines = pin_power_view.csv_text(a).splitlines()
        self.assertEqual(lines[0], "ix,iy,x_cm,y_cm,value,sigma,included,relative_power,relative_sigma")
        self.assertEqual(len(lines), 10)
        self.assertEqual(lines[1].split(",")[:2], ["0", "0"])
        self.assertEqual(lines[9].split(",")[:2], ["2", "2"])
        self.assertAlmostEqual(float(lines[9].split(",")[7]), 9.0 / 5.0)

    def test_a_cell_left_out_has_empty_relative_columns(self):
        a = analyse(mesh([1.0, 1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.0, 1.0]))
        row = pin_power_view.csv_text(a).splitlines()[5].split(",")
        self.assertEqual(row[6:], ["False", "", ""])


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PAYLOAD = {"summary": {"run_mode": "eigenvalue"}, "tracks": [], "tracks_truncated": False, "tallies": [
    {"name": "flux", "kind": "table", "filters": ["CellFilter"], "scores": ["flux"], "rows": []},
    mesh([1.0] * 4 + [3.0] + [1.0] * 4, [0.01] * 9, name="Pin power"),
    mesh([1.0] * 18, dims=(3, 3, 2), upper=(3.0, 3.0, 2.0), name="Two layers"),
    {"name": "Cyl", "kind": "mesh", "mesh_type": "cylindrical", "dims": [2, 2, 1], "scores": ["flux"], "values": {"flux": [1, 1, 1, 1]}, "std": {"flux": [0] * 4}}]}


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pin-power-http-"))
        cls.port = free_port()
        cls.studio = srv.Studio(cls.tmp / "runs", TOKEN, cls.port)
        (cls.tmp / "runs" / RID).mkdir(parents=True)
        cls.real_load = results.load
        results.load = lambda run_dir: json.loads(json.dumps(PAYLOAD))
        srv.Handler.studio = cls.studio
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", cls.port), srv.Handler)
        cls.httpd.daemon_threads = True
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        results.load = cls.real_load
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def get(self, path, token=TOKEN):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request("GET", path, headers={"Host": f"127.0.0.1:{self.port}", "X-Studio-Token": token} if token else {"Host": f"127.0.0.1:{self.port}"})
        r = conn.getresponse()
        return r.status, r.read()

    def test_the_named_mesh_gives_its_map_with_a_csv(self):
        status, body = self.get(f"/api/runs/{RID}/pin-power?tally=Pin%20power")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual((data["tally"], data["nx"], data["ny"]), ("Pin power", 3, 3))
        self.assertEqual((data["peak"]["ix"], data["peak"]["iy"]), (1, 1))
        self.assertEqual(len(data["csv"].splitlines()), 10)

    def test_no_name_takes_the_first_mesh_tally_and_the_layer_is_passed_on(self):
        self.assertEqual(json.loads(self.get(f"/api/runs/{RID}/pin-power")[1])["tally"], "Pin power")
        data = json.loads(self.get(f"/api/runs/{RID}/pin-power?tally=Two%20layers&layer=1")[1])
        self.assertEqual((data["layer"], data["layers"]), (1, 2))

    def test_refusals_say_why_and_use_the_right_status(self):
        self.assertEqual(self.get(f"/api/runs/{RID}/pin-power?tally=Nope")[0], 404)
        self.assertEqual(self.get(f"/api/runs/{RID}/pin-power?tally=Two%20layers&layer=2")[0], 422)
        self.assertEqual(self.get(f"/api/runs/{RID}/pin-power?layer=x")[0], 400)
        status, body = self.get(f"/api/runs/{RID}/pin-power?tally=Cyl")
        self.assertEqual(status, 422)
        self.assertIn("cylindrical", body.decode())
        self.assertEqual(self.get(f"/api/runs/{RID}/pin-power?tally=Pin%20power&score=flux")[0], 422)

    def test_it_needs_the_token_and_a_real_run(self):
        self.assertEqual(self.get(f"/api/runs/{RID}/pin-power", token=None)[0], 401)
        self.assertEqual(self.get("/api/runs/20261008-120000-nope/pin-power")[0], 404)


if __name__ == "__main__":
    unittest.main()
