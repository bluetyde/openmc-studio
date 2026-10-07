"""Sample the main thread's stack during MCNPy translate (scratch). python sample_translate.py <project> <folder> <noworld|worldonly|full> [interval]"""
import collections, contextlib, io, os, sys, threading, time, traceback

project, folder, variant = sys.argv[1], sys.argv[2], sys.argv[3]
interval = float(sys.argv[4]) if len(sys.argv) > 4 else 2.0
sys.path.insert(0, os.path.join(project, "src"))
with contextlib.redirect_stdout(io.StringIO()):
    import openmc
    from export_mcnp import translate
    from remediate_deck import load_model
    from mcnpy.translate_mcnp_openmc import openmc_to_mcnp  # noqa: F401
os.chdir(folder)
model = load_model("model.xml")
cells = list(model.geometry.root_universe.cells.values())
drop = [c for c in cells if (c.name == "World") == (variant == "worldonly")] if variant != "full" else []
for c in drop:
    model.geometry.root_universe.remove_cell(c)
main_id = threading.get_ident()
leaf, chain, n = collections.Counter(), collections.Counter(), [0]
stop = threading.Event()
t0 = time.perf_counter()


def sampler():
    while not stop.wait(interval):
        f = sys._current_frames().get(main_id)
        if f is None:
            continue
        st = traceback.extract_stack(f)
        n[0] += 1
        leaf[f"{'/'.join(st[-1].filename.split('/')[-2:])}:{st[-1].name}:{st[-1].lineno}"] += 1
        chain[" > ".join(f"{os.path.basename(s.filename)}:{s.name}:{s.lineno}" for s in st[-9:])] += 1


LIMIT = float(sys.argv[5]) if len(sys.argv) > 5 else 1e9


def watchdog():
    while not stop.wait(1):
        if time.perf_counter() - t0 > LIMIT:
            lines = [f"-- stopped after {LIMIT:.0f} s, {n[0]} samples", "LEAF:"]
            lines += [f"  {v:4d}  {k}" for k, v in leaf.most_common(10)]
            lines.append("CHAINS:")
            lines += [f"  {v:4d}  {k}" for k, v in chain.most_common(8)]
            sys.__stdout__.write(chr(10).join(lines) + chr(10))
            sys.__stdout__.flush()
            os._exit(0)


threading.Thread(target=watchdog, daemon=True).start()
threading.Thread(target=sampler, daemon=True).start()
translate(model, f"sampled_{variant}.mcnp", stdout=io.StringIO())
stop.set()
print(f"{variant}: translate {time.perf_counter() - t0:.1f} s, {n[0]} samples every {interval} s")
print("LEAF:")
for k, v in leaf.most_common(10):
    print(f"  {v:4d}  {k}")
print("CHAINS (last 5 frames):")
for k, v in chain.most_common(6):
    print(f"  {v:4d}  {k}")
