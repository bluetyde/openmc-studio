"""P2, experiment E17: does the reflector need more than one set of constants?

E16: the two-step k's remaining gap to the core run's own constants by kind is mostly the fuel on the 9 x 9 and the checkerboard (226 and 470 pcm) but mostly the REFLECTOR on the
11 x 11 zoned core (about 420 of 448 pcm), the core with two reflector layers. The pieces give one reflector set, from a strip with one layer; the core run's own set by kind is the mean
of two layers that differ (fast absorption -8.7 %, the 2nd-to-1st-layer scatter +89 %).
Here, still with the core run's own node constants and no new Monte Carlo, the reflector is split by how far a node is from fuel and solved again (SANM, no factors):

    by kind          one reflector set (the mean over all reflector nodes)                  what the wrapper and the pieces give today
    by distance      one set per Manhattan distance to the nearest fuel node (1, 2, ...)    layers, and the corner nodes of a one-layer ring (distance 2)
    by node          every node its own set                                                  the most constants alone can do (fuel kept as the core run's by kind)

Fuel is the core run's own by kind in all three. The k difference between rows is then what splitting the reflector buys, and an upper bound for what a strip with per-layer domains can
give.

    PYTHONPATH=studio:docs/design/nodal-p2 python docs/design/nodal-p2/e17_reflector_layers.py
"""
import numpy as np

import e9_current_d as e9
from openmc_studio import nodal

FIELDS = ("D", "absorption", "nu_fission", "kappa_fission", "chi", "scatter", "inv_velocity")


def node_consts(core, r, c):
    return {f: np.asarray(core["c_" + f][r, c], float).reshape(-1) for f in FIELDS[1:]} | {"D": np.asarray(core["c_Dflux"][r, c], float)}


def distance_to_fuel(kinds):
    nc = len(kinds)
    fuel = [(r, c) for r in range(nc) for c in range(nc) if kinds[r][c] != "R"]
    return {(r, c): min(abs(r - fr) + abs(c - fc) for fr, fc in fuel) for r in range(nc) for c in range(nc) if kinds[r][c] == "R"}


def run(core, labels, consts):
    res = nodal.solve_core(labels, consts, float(core["asm"]), float(core["hz"]))
    fm = np.array([[kd != "R" for kd in row] for row in core["kinds"]])
    ref = core["power"] / core["power"][fm].mean()
    p = res.power / res.power[fm].mean()
    return (res.k_eff - float(core["k"])) * 1e5, 100 * np.sqrt(((p[fm] / ref[fm] - 1) ** 2).mean())


def mean_of(core, nodes):
    cs = [node_consts(core, r, c) for r, c in nodes]
    return {f: np.mean([x[f] for x in cs], axis=0) for f in cs[0]}


def main():
    for name in ("zoned1", "zoned2", "checker1"):
        core = e9.load(name)
        nc = core["NC"]
        kinds = core["kinds"]
        dist = distance_to_fuel(kinds)
        fuel_consts = {kd: mean_of(core, [(r, c) for r in range(nc) for c in range(nc) if kinds[r][c] == kd]) for kd in ("A", "B")}
        print(f"\n===== {name}: OpenMC k {float(core['k']):.5f}; fuel = the core run's own by kind; nodal minus OpenMC (pcm), power rms %, SANM, no factors")
        # by kind
        cons = dict(fuel_consts)
        cons["R"] = mean_of(core, list(dist))
        d, rms = run(core, kinds, cons)
        print(f"  reflector by kind (1 set)                          {d:+7.0f}  {rms:4.1f}")
        # by distance
        labels = [[kinds[r][c] if kinds[r][c] != "R" else f"R{dist[(r, c)]}" for c in range(nc)] for r in range(nc)]
        cons = dict(fuel_consts)
        for dd in sorted(set(dist.values())):
            nodes = [n for n, v in dist.items() if v == dd]
            cons[f"R{dd}"] = mean_of(core, nodes)
            print(f"    distance {dd}: {len(nodes)} nodes; D {cons[f'R{dd}']['D'].round(4).tolist()} absorption {cons[f'R{dd}']['absorption'].round(5).tolist()}")
        d, rms = run(core, labels, cons)
        print(f"  reflector by distance to fuel ({len(set(dist.values()))} sets)                 {d:+7.0f}  {rms:4.1f}")
        # by node
        labels = [[kinds[r][c] if kinds[r][c] != "R" else f"R_{r}_{c}" for c in range(nc)] for r in range(nc)]
        cons = dict(fuel_consts)
        for (r, c) in dist:
            cons[f"R_{r}_{c}"] = node_consts(core, r, c)
        d, rms = run(core, labels, cons)
        print(f"  reflector by node ({len(dist)} sets)                        {d:+7.0f}  {rms:4.1f}")


if __name__ == "__main__":
    main()
