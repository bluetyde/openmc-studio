"""Writes aperture_block.mcnp: the 'aperture_block' project of test/generate_fixtures.js exported as MCNP, the way Studio's
model.mcnp tab does (translate, remediate, validate against OpenMC). The deck is a test fixture for importing MCNP decks:
a 14 x 1 x 9 lattice of tilted square channels (LAT=1, translated FILL, GQ surfaces for the turned boxes), about 250 cells
once imported, a box source with a tabulated spectrum and mesh tallies. The geometry and numbers are invented.

In WSL, with the MCNPy gateway claimed (port 25333):
    node test/generate_fixtures.js
    OPENMC_MCNP_PROJECT=/path/to/openmc-mcnp-project python test/fixtures/mcnp/make_aperture_block.py
"""
import contextlib
import io
import os
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(Path(os.environ["OPENMC_MCNP_PROJECT"]) / "src"))
import openmc  # noqa: E402
from export_mcnp import translate  # noqa: E402
from remediate_deck import remediate  # noqa: E402
from validate_deck import validate_deck  # noqa: E402

openmc.reset_auto_ids()
ns = runpy.run_path(str(REPO / "test" / "generated" / "aperture_block_mcnp.py"), run_name="make_fixture")
model = ns["model"]
raw, out = HERE / "aperture_block.raw.mcnp", HERE / "aperture_block.mcnp"
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    translate(model, str(raw))
    remediate(str(raw), model, str(out), detector_responses=ns.get("detector_responses"), studio_ids=ns.get("studio_ids"))
    ok = validate_deck(str(out), model=model, geometry_samples=20000)
raw.unlink()
print(buf.getvalue()[-600:])
print(f"{out}: {'validated against OpenMC' if ok else 'DID NOT VALIDATE'}")
sys.exit(0 if ok else 1)
