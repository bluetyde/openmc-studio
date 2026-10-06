"""Read the B-10 cross sections the analytic SEED oracles need, straight from the nuclear data library (no transport).

    OPENMC_CROSS_SECTIONS=/path/cross_sections.xml python studio/tools/seed_oracle_xs.py [OUT.json]

Writes oracles/seed/xs/b10-294K-0.0253eV.json: microscopic total, elastic and absorption cross sections of B-10 at 294 K and 0.0253 eV, the
atomic mass OpenMC uses, and the identity (path and sha256) of the library file and of cross_sections.xml they came from. The generator
(gen_seed_oracles.cjs) computes every expected value from this file by formula; transport never produces an expected value.
Absorption is OpenMC's `absorption` score: the sum of the disappearance reactions MT 102 to 117.
The heating oracle also reads MT 301, the neutron heating (KERMA) cross section in eV-barn, which is what the `heating` score weights the flux with.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

import openmc.data

NUCLIDE, TEMP, ENERGY_EV = "B10", "294K", 0.0253
ROOT = Path(__file__).resolve().parents[2]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "oracles" / "seed" / "xs" / "b10-294K-0.0253eV.json"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


xml = Path(os.environ["OPENMC_CROSS_SECTIONS"])
lib = openmc.data.DataLibrary.from_xml(str(xml))
entry = lib.get_by_material(NUCLIDE)
assert entry and entry["type"] == "neutron", "no neutron data for " + NUCLIDE
path = Path(entry["path"])
if not path.is_absolute():
    path = xml.parent / path
nuc = openmc.data.IncidentNeutron.from_hdf5(str(path))
assert TEMP in nuc.temperatures, f"{TEMP} not in {nuc.temperatures}"


def xs(mt):
    return float(nuc[mt].xs[TEMP](ENERGY_EV))


disappearance = [mt for mt in nuc.reactions if 102 <= mt <= 117]
doc = {
    "nuclide": NUCLIDE,
    "temperature": TEMP,
    "energy_eV": ENERGY_EV,
    "heating_eV_b": xs(301),
    "sigma_total_b": xs(1),
    "sigma_elastic_b": xs(2),
    "sigma_absorption_b": sum(xs(mt) for mt in disappearance),
    "disappearance_mts": sorted(int(mt) for mt in disappearance),
    "atomic_mass_amu": float(openmc.data.atomic_mass(NUCLIDE)),
    "avogadro_per_mol": 6.02214076e23,
    "library": {"cross_sections_xml_sha256": sha256(xml), "file": path.name, "file_sha256": sha256(path), "openmc": openmc.__version__},
    "note": "total = elastic + absorption at this energy (B-10 has no inelastic channel below the MeV range); checked below.",
}
# The identity the analytic cases rely on: nothing but elastic scattering and absorption happens at 0.0253 eV.
assert abs(doc["sigma_total_b"] - doc["sigma_elastic_b"] - doc["sigma_absorption_b"]) <= 1e-6 * doc["sigma_total_b"], doc
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
print(json.dumps(doc, indent=1, sort_keys=True))
