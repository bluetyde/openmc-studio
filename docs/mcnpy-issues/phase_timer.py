"""Timestamp MCNPy's stage lines during translate (scratch). python phase_timer.py <project> <folder> wc|direct [limit s]
wc = world_complement only (needs cell_regions to switch it off); direct = the exporter as it is checked out."""
import contextlib, io, os, sys, threading, time

project, folder, variant = sys.argv[1], sys.argv[2], sys.argv[3]
limit = float(sys.argv[4]) if len(sys.argv) > 4 else 900
sys.path.insert(0, os.path.join(project, "src"))
with contextlib.redirect_stdout(io.StringIO()):
    import openmc
    from export_mcnp import translate
    from remediate_deck import load_model
    from mcnpy.translate_mcnp_openmc import openmc_to_mcnp  # noqa: F401
if variant == "wc":  # cell_regions exists only once the direct-cell-cards change is merged in the exporter
    import cell_regions
    cell_regions.plan = lambda *a, **k: None
os.chdir(folder)
model = load_model("model.xml")
t0 = time.perf_counter()
events = []


class Stamp(io.TextIOBase):
    def __init__(self):
        self.buf = ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip():
                events.append((time.perf_counter() - t0, line.strip()[:90]))
        return len(s)


def report(tag):
    out = [f"{variant}: {tag} at {time.perf_counter() - t0:.1f} s"]
    last = 0.0
    for t, line in events:
        out.append(f"  {t:7.1f} s  (+{t - last:6.1f})  {line}")
        last = t
    sys.__stdout__.write("\n".join(out) + "\n")
    sys.__stdout__.flush()


def watchdog():
    time.sleep(limit)
    report("STOPPED by the limit")
    os._exit(0)


threading.Thread(target=watchdog, daemon=True).start()
translate(model, f"phase_{variant}.mcnp", stdout=Stamp())
report("finished")
