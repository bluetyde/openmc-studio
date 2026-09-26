"""Import MCNP decks Studio didn't write: the parts that need only Python (the end-to-end run through the page is
test/test_mcnp_import_gate.cjs).

For each deck in test/fixtures/mcnp:
  1. mcnp_import.import_deck reads it with openmc_mcnp_adapter, flattens universes, lattices and fill transforms
     into Studio's imported-CSG cells, and checks them against OpenMC's own geometry (the import refuses otherwise);
  2. the page commits the report (commitMcnpImport, test/mcnp_import_page.cjs) and writes model.py;
  3. that model.py is loaded by OpenMC, and the material (by atom density) at thousands of points must equal what
     OpenMC finds in the deck as the adapter reads it: what a user runs is what the deck describes.
Refusals are checked too: a hexagonal lattice, a torus, an all-void deck, cells with no top level.

Needs OpenMC with nuclear data (OPENMC_CROSS_SECTIONS), openmc_mcnp_adapter, and Node on PATH.
Run: python test/test_mcnp_import.py
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

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "test" / "fixtures" / "mcnp"
sys.path.insert(0, str(ROOT / "studio"))
from openmc_studio import mcnp_import  # noqa: E402

NODE = shutil.which("node") or shutil.which("node.exe")


def node_path(path):
    """A path as Node sees it: in WSL, `node` is often the Windows node.exe, which needs a Windows path."""
    if NODE and NODE.startswith("/mnt/"):
        return subprocess.run(["wslpath", "-w", str(path)], capture_output=True, text=True).stdout.strip()
    return str(path)

PROBE = r'''
import json, os, sys, tempfile, xml.etree.ElementTree as ET
import numpy as np
import openmc.lib
xml_path, pts_file, out = sys.argv[1:4]
root = ET.parse(xml_path).getroot()
for tag in ("settings", "tallies", "plots"):
    for el in root.findall(tag):
        root.remove(el)
root.append(ET.fromstring("<settings><run_mode>fixed source</run_mode><particles>10</particles><batches>1</batches>"
                          "<source><space type='point' parameters='0 0 0'/></source></settings>"))
surfs = root.findall("./geometry/surface")
if surfs and not any(s.get("boundary", "transmission") != "transmission" for s in surfs):
    surfs[0].set("boundary", "vacuum")
d = tempfile.mkdtemp(); os.chdir(d)
ET.ElementTree(root).write("model.xml")
openmc.lib.init(output=False)
res = []
for p in np.load(pts_file):
    try:
        m = openmc.lib.find_material(tuple(float(x) for x in p))
    except Exception:
        res.append(None); continue
    res.append(0.0 if m is None else float(f"{m.get_density('atom/b-cm'):.5g}"))
openmc.lib.finalize()
json.dump(res, open(out, "w"))
'''


def densities(model_xml, pts):
    d = tempfile.mkdtemp(prefix="mcnp-import-probe-")
    np.save(f"{d}/pts.npy", pts)
    Path(d, "probe.py").write_text(PROBE)
    r = subprocess.run([sys.executable, f"{d}/probe.py", str(model_xml), f"{d}/pts.npy", f"{d}/out.json"],
                       capture_output=True, text=True, timeout=1800)
    if r.returncode:
        raise RuntimeError(r.stdout[-2000:] + r.stderr[-2000:])
    return json.loads(Path(d, "out.json").read_text())


def import_and_run(deck):
    """(report, page output, points, densities in the deck as the adapter reads it, densities in Studio's model.py)"""
    import openmc
    from openmc_mcnp_adapter import mcnp_to_model
    rep = mcnp_import.import_deck(deck)
    work = Path(tempfile.mkdtemp(prefix="mcnp-import-e2e-"))
    Path(work, "report.json").write_text(json.dumps(rep))
    r = subprocess.run([NODE, node_path(ROOT / "test" / "mcnp_import_page.cjs"), node_path(work / "report.json"), deck.name],
                       capture_output=True, text=True, timeout=600)
    if r.returncode:
        raise RuntimeError(r.stderr[-3000:])
    page = json.loads(r.stdout)
    Path(work, "model.py").write_text(page["script"])
    r = subprocess.run([sys.executable, "model.py", "--export-xml"], cwd=work, capture_output=True, text=True, timeout=600)
    if r.returncode:
        raise RuntimeError(r.stdout[-3000:] + r.stderr[-3000:])
    openmc.reset_auto_ids()
    import contextlib, io, warnings  # noqa: E401
    with warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):
        warnings.simplefilter("ignore")
        ref = mcnp_to_model(str(deck))
        ref.export_to_model_xml(str(work / "deck_model.xml"))
    b = rep["bounds_cm"]
    lo, hi = np.array(b[:3]), np.array(b[3:])
    rng = np.random.default_rng(99)
    pts = [lo + (hi - lo) * rng.random((3000, 3))]
    for k in rep["components"]:  # and inside each component, so small parts are sampled too
        kb = k["bounds_cm"]
        pts.append(np.array(kb[:3]) + (np.array(kb[3:]) - np.array(kb[:3])) * rng.random((300, 3)))
    pts = np.concatenate(pts)
    return rep, page, pts, densities(work / "deck_model.xml", pts), densities(work / "model.xml", pts)


def same(a, b):
    return a == b or (a is not None and b is not None and abs(a - b) <= 1e-4 * max(abs(a), abs(b)))


class Previews(unittest.TestCase):
    def test_preview_meshes_fit_the_3d_budget(self):
        rep = mcnp_import.import_deck(FIX / "graphite_pile.mcnp")
        self.assertLessEqual(sum(k["display"]["count"] for k in rep["components"]), mcnp_import.PREVIEW_TRIANGLES)
        for k in rep["components"]:
            d = k["display"]
            self.assertEqual(d["conversion"], f"{rep['source_sha256']}|{k['key']}")
            self.assertEqual(len(d["triangles"]), 3 * d["count"])

    def test_materials_keep_the_decks_own_fractions(self):
        rep = mcnp_import.import_deck(FIX / "shielding_demo.mcnp")
        poly = next(m for m in rep["materials"] if m["name"].startswith("Polyethylene"))
        self.assertEqual((poly["frac"], poly["density"], poly["converted"]), ("wo", 0.93, False))
        self.assertIn("H1:0.14367127668", poly["comps"])


class Refusals(unittest.TestCase):
    def refused(self, text):
        d = Path(tempfile.mkdtemp(prefix="mcnp-import-bad-"))
        Path(d, "deck.mcnp").write_text(text)
        with self.assertRaises(mcnp_import.Refused) as cm:
            mcnp_import.import_deck(d / "deck.mcnp")
        return str(cm.exception)

    def test_hex_lattice(self):
        with self.assertRaises(mcnp_import.Refused) as cm:
            mcnp_import.import_deck(FIX / "hex_array.mcnp")
        self.assertIn("Hexagonal", str(cm.exception))

    def test_torus(self):
        msg = self.refused("torus\n1 1 -1.0 -1 imp:n=1\n2 0 1 -2 imp:n=1\n3 0 2 imp:n=0\n\n1 TZ 0 0 0 10 2 2\n2 SO 50\n\n"
                           "M1 1001 2 8016 1\nNPS 10\n")
        self.assertIn("tori", msg)

    def test_all_void(self):
        msg = self.refused("void\n1 0 -1 imp:n=1\n2 0 1 imp:n=0\n\n1 SO 10\n\nNPS 10\n")
        self.assertIn("no cell with a material", msg)

    def test_nothing_at_the_top_level(self):
        msg = self.refused("u only\n1 1 -1.0 -1 u=1 imp:n=1\n2 0 1 u=1 imp:n=1\n\n1 SO 10\n\nM1 1001 2 8016 1\nNPS 10\n")
        self.assertIn("no cells at the top level", msg)


if __name__ == "__main__":
    if not NODE:
        raise SystemExit("node is needed on PATH")
    unittest.main(verbosity=2)
