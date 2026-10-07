"""Validate one translated deck against its OpenMC model, in its own process (no MCNPy, no Java).

The live model.mcnp tab shows a deck as soon as it is translated and remediated; the server runs this on a copy of
the deck and model.xml while the user keeps working, and a newer deck kills it. It does what the worker's last stage
does when a job asks for validation: validate_deck(deck, model=model, geometry_samples=N).

    python mcnp_validate.py /path/to/openmc-mcnp-project <deck file name> <samples>

Run in the folder holding the deck and model.xml. Writes result.json there: {"ok", "validation", "seconds"}, or
{"ok": false, "error", ...} if validation itself could not run (so the page can say so instead of waiting).
"""
import contextlib
import io
import json
import os
import sys
import time
import traceback


def main(project, deck, samples):
    sys.path.insert(0, os.path.join(project, "src"))
    t0 = time.time()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            import openmc  # noqa: F401  (the exporter's modules need it)
            from remediate_deck import load_model
            from validate_deck import validate_deck
        model = load_model("model.xml")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = validate_deck(deck, model=model, geometry_samples=samples)
        result = {"ok": bool(ok), "validation": buf.getvalue()}
    except Exception as e:  # noqa: BLE001  report what stopped validation; the page shows it
        result = {"ok": False, "validation": "", "error": f"{type(e).__name__}: {e}",
                  "trace": traceback.format_exc()[-1500:]}
    result["seconds"] = round(time.time() - t0, 2)
    with open("result.json.tmp", "w", encoding="utf-8") as f:
        json.dump(result, f)
    os.replace("result.json.tmp", "result.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], int(sys.argv[3])))
