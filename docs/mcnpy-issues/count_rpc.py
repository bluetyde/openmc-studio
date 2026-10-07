"""Count MCNPy's py4j round trips for translate on the lattice test deck: old (world cell expanded) vs new (#cell complements).
python count_rpc.py <project> <folder> old|new"""
import contextlib, io, os, sys, time

project, folder, variant = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, os.path.join(project, "src"))
with contextlib.redirect_stdout(io.StringIO()):
    import openmc
    import world_complement
    from export_mcnp import translate
    from remediate_deck import load_model
    from mcnpy.translate_mcnp_openmc import openmc_to_mcnp  # noqa: F401
    import py4j.java_gateway as jg
if variant == "old":
    world_complement.plan = lambda geometry, min_terms=None: None
os.chdir(folder)
model = load_model("model.xml")
calls = [0, 0.0]
orig = jg.GatewayClient.send_command


def counting(self, command, retry=True, binary=False):
    t = time.perf_counter()
    r = orig(self, command, retry, binary)
    calls[0] += 1
    calls[1] += time.perf_counter() - t
    return r


jg.GatewayClient.send_command = counting
t0 = time.perf_counter()
translate(model, f"rpc_{variant}.mcnp", stdout=io.StringIO())
dt = time.perf_counter() - t0
print(f"{variant}: translate {dt:.1f} s, {calls[0]} py4j calls, {1000 * calls[1] / max(calls[0], 1):.2f} ms per call, "
      f"{calls[1]:.1f} s inside calls", flush=True)
