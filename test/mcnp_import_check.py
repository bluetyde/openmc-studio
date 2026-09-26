"""Helper for test/test_mcnp_import_gate.cjs: does Studio's model.py for an imported deck describe the deck?

usage: mcnp_import_check.py <deck.mcnp> <report.json> <folder with Studio's model.py>
Loads the deck with openmc_mcnp_adapter and Studio's model.py (--export-xml), finds the material at points spread
over the model and inside each imported component with OpenMC's own C++ geometry (openmc.lib) in both, and prints
one JSON line: {"compared", "differ", "examples"}. Materials are compared by atom density (IDs differ).
"""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

import numpy as np

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
    res.append(0.0 if m is None else float(f"{m.get_density('atom/b-cm'):.6g}"))
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


def main():
    import openmc
    from openmc_mcnp_adapter import mcnp_to_model
    deck, report, folder = sys.argv[1:4]
    rep = json.loads(Path(report).read_text())
    folder = Path(folder)
    r = subprocess.run([sys.executable, "model.py", "--export-xml"], cwd=folder, capture_output=True, text=True, timeout=600)
    if r.returncode:
        print(json.dumps({"error": "model.py --export-xml failed: " + (r.stdout + r.stderr)[-1500:]}))
        return
    openmc.reset_auto_ids()
    with warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):
        warnings.simplefilter("ignore")
        ref = mcnp_to_model(deck)
        ref.export_to_model_xml(str(folder / "deck_model.xml"))
    b = rep["bounds_cm"]
    rng = np.random.default_rng(99)
    pts = [np.array(b[:3]) + (np.array(b[3:]) - np.array(b[:3])) * rng.random((3000, 3))]
    for k in rep["components"]:
        kb = k["bounds_cm"]
        pts.append(np.array(kb[:3]) + (np.array(kb[3:]) - np.array(kb[:3])) * rng.random((300, 3)))
    pts = np.concatenate(pts)
    want, got = densities(folder / "deck_model.xml", pts), densities(folder / "model.xml", pts)
    same = lambda a, b: a == b or (a is not None and b is not None and abs(a - b) <= 1e-5 * max(abs(a), abs(b)))
    pairs = [(p, a, g) for p, a, g in zip(pts, want, got) if a is not None]
    bad = [(p, a, g) for p, a, g in pairs if not same(a, g)]
    print(json.dumps({"compared": len(pairs), "differ": len(bad),
                      "examples": [{"at": [round(float(v), 3) for v in p], "deck": a, "studio": g} for p, a, g in bad[:5]]}))


if __name__ == "__main__":
    main()
