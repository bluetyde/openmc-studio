"""Time the five stages of Studio's model.mcnp worker on a generated model.py (scratch, no repo change).

python time_stages.py <exporter project> <folder with model.py> [samples]
"""
import contextlib, io, os, runpy, sys, time, json, resource

project, folder = sys.argv[1], sys.argv[2]
samples = int(sys.argv[3]) if len(sys.argv) > 3 else 20000
sys.path.insert(0, os.path.join(project, "src"))
T = {}


def stamp(name, t0):
    T[name] = round(time.perf_counter() - t0, 2)
    print(f"{name}: {T[name]} s  (peak RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024} MB)", flush=True)


t = time.perf_counter()
with contextlib.redirect_stdout(io.StringIO()):
    import openmc
    from export_mcnp import translate
    import lattice_cards
    from remediate_deck import load_model, remediate
    from validate_deck import validate_deck
    from mcnpy.translate_mcnp_openmc import openmc_to_mcnp  # noqa: F401
stamp("0 imports + Java bridge", t)

os.chdir(folder)
model_xml, translated, runnable = "model.xml", "deck.mcnp", "deck_runnable.mcnp"
for f in (model_xml, translated, runnable):
    if os.path.exists(f):
        os.remove(f)

t = time.perf_counter()
openmc.reset_auto_ids()
with contextlib.redirect_stdout(io.StringIO()):
    ns = runpy.run_path(os.path.join(folder, "model.py"), run_name="studio_export")
stamp("1a run model.py", t)
t = time.perf_counter()
with contextlib.redirect_stdout(io.StringIO()):
    ns["model"].export_to_model_xml(model_xml)
model = load_model(model_xml)
stamp("1b export model.xml + load_model", t)
geo = model.geometry
print("cells", len(geo.get_all_cells()), "surfaces", len(geo.get_all_surfaces()), "materials", len(model.materials), flush=True)

t = time.perf_counter()
prep = lattice_cards.prepare(model)
stamp("2a lattice prepare", t)
t = time.perf_counter()
translate(model, translated, stdout=io.StringIO())
stamp("2b translate (MCNPy)", t)

t = time.perf_counter()
with contextlib.redirect_stdout(io.StringIO()):
    rep = remediate(translated, model, runnable, detector_responses=ns.get("detector_responses"),
                    studio_ids=ns.get("studio_ids"), dose=None)
stamp("3 remediate", t)

t = time.perf_counter()
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    ok = validate_deck(runnable, model=model, geometry_samples=samples)
stamp(f"5 validate ({samples} samples)", t)
print("validate ok:", ok, flush=True)
print(buf.getvalue()[-600:], flush=True)
print(json.dumps(T), flush=True)
