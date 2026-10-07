"""The refusals every run path shares: what in a project makes a run certainly wrong or impossible.

The page decides this live, in JavaScript (`problems()` in static/index.html), because it has to answer on every keystroke. A
run does not have to come from the page: a script can post a project to /api/run, and SEED's headless runner takes a project file.
This module is the same list of errors in Python, so those paths refuse what the page refuses. Only errors are here (the page's
warnings and notes stay on the page). `test/test_prerun_check.py` and `test/test_prerun_check_page.js` hold the two lists together
on the same projects: a project the page refuses must be refused here with the same objects named, and the reverse.

Not here yet, and so refused only by the page (and by the geometry check): the rules about imported CAD components (a material
missing, a part reaching into one, a component past the world) and the tally of surfaces of a part that sits in a lattice. A
project that breaks only those still runs from a script. Findings: {level, code, path, message}; `path` is a JSON pointer into
the project (`/settings`, `/materials/m1`, `/sources/s1`, `/tallies/t2`, `/parts/p3`, `/world`).
"""
import math
import re

_NUM = r"([0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)"
_COMP_RE = re.compile(r"^([A-Z][a-z]?)(\d{1,3}(?:_m\d)?)?\s*:\s*" + _NUM + r"$")
_LINE_RE = re.compile(r"^" + _NUM + r"\s*(?::\s*" + _NUM + r")?$")
_TRACK_RE = re.compile(r"^(\d+)\s*,\s*(\d+)\s*,\s*(\d+)$")
FISSILE = ("U", "Pu", "U233", "U235", "Pu239", "Pu241")
NO_NATURAL = ("Tc", "Pm", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Np", "Pu", "Am", "Cm", "Bk", "Cf")
NAN = float("nan")


def _n(v):
    """A JSON number as a float; anything else as NaN (so a comparison with it is false, as in JavaScript)."""
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else NAN


def fin(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def pos(v):
    return fin(v) and v > 0


def is_int(v):
    """JavaScript's Number.isInteger: a whole number, 5000 or 5000.0, but not a string or a bool."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and float(v).is_integer()


def _tokens(s):
    return [t.strip() for t in str(s or "").split(",") if t.strip()]


def parse_comps(s):
    out, errs = [], []
    for tok in _tokens(s):
        m = _COMP_RE.match(tok)
        if not m:
            errs.append(tok)
            continue
        out.append({"sym": m.group(1) + (m.group(2) or ""), "el": m.group(1), "nuclide": bool(m.group(2)), "amt": float(m.group(3))})
    return out, errs


def parse_lines(s):
    out, errs = [], []
    for tok in _tokens(s):
        m = _LINE_RE.match(tok)
        if not m:
            errs.append(tok)
            continue
        out.append({"e": float(m.group(1)), "p": 1.0 if m.group(2) is None else float(m.group(2))})
    return out, errs


def _floats(tokens):
    out = []
    for t in tokens:
        try:
            out.append(float(t))
        except ValueError:
            out.append(NAN)
    return out


def parse_nums(s):
    vals = _floats(_tokens(s))
    return vals, all(math.isfinite(v) for v in vals)


def parse_tabular(e_str, p_str):
    clean_e = re.sub(r"^SI\d*\s*H?\s*", "", str(e_str or ""), flags=re.I).replace("&", " ")
    clean_p = re.sub(r"^SP\d*\s*D?\s*", "", str(p_str or ""), flags=re.I).replace("&", " ")
    es = _floats([t for t in re.split(r"[\s,]+", clean_e) if t.strip()])
    ps = _floats([t for t in re.split(r"[\s,]+", clean_p) if t.strip()])
    if len(ps) == len(es) and ps and ps[0] == 0:
        ps = ps[1:]
    ok_e = len(es) >= 2 and all(math.isfinite(v) for v in es) and all(i == 0 or es[i] > es[i - 1] for i in range(len(es))) and es[0] >= 0
    ok_p = len(ps) == len(es) - 1 and all(math.isfinite(v) for v in ps) and all(v >= 0 for v in ps) and any(v > 0 for v in ps)
    return len(es), ok_e, ok_p


def parse_track(s):
    out, errs = [], []
    for tok in [t.strip() for t in str(s or "").split(";") if t.strip()]:
        m = _TRACK_RE.match(tok)
        if m:
            out.append(tuple(int(g) for g in m.groups()))
        else:
            errs.append(tok)
    return out, errs


def _ci(s):
    return str(s or "").lower()


def resolve_detector(t, materials):
    """The detector response's material and nuclide, as the page resolves them (a preset picks a matching material by name)."""
    mat = t.get("responseMat") or ""
    nuc = t.get("responseNuc")
    det = t.get("detector")

    def find(pred):
        for m in materials:
            if pred(m):
                return m.get("id")
        return None

    if det == "he3":
        nuc = "He3"
        if not mat:
            mat = find(lambda m: (m.get("comps") and "He3" in m["comps"]) or re.search(r"he-?3", m.get("name") or "", re.I)) or mat
    elif det == "b10":
        nuc = "B10"
        if not mat:
            mat = find(lambda m: (m.get("comps") and ("B10" in m["comps"] or "B0" in m["comps"] or re.search(r"\bB\b", m["comps"])))
                       or re.search(r"b-?10|bf3|boron", m.get("name") or "", re.I)) or mat
    elif det == "fission":
        nuc = "U235"
        if not mat:
            mat = find(lambda m: (m.get("comps") and "U235" in m["comps"])
                       or re.search(r"u-?235|fiss|fuel|heu|leu", m.get("name") or "", re.I)) or mat
    elif det == "custom":
        if not nuc:
            nuc = "all" if t.get("responseScale") == "macro" else ""
    return mat, nuc


def check(project):
    """The errors in a project, as a list of findings. Empty when nothing in it forbids a run."""
    out = []
    p = project if isinstance(project, dict) else {}
    st = p.get("settings") if isinstance(p.get("settings"), dict) else {}
    eig = st.get("runMode") == "eigenvalue"
    materials = [m for m in (p.get("materials") or []) if isinstance(m, dict)]
    parts = [x for x in (p.get("parts") or []) if isinstance(x, dict)]
    sources = [x for x in (p.get("sources") or []) if isinstance(x, dict)]
    tallies = [x for x in (p.get("tallies") or []) if isinstance(x, dict)]
    csg = ((p.get("csg") or {}).get("components") or []) if isinstance(p.get("csg"), dict) else []
    mat_ids = {m.get("id") for m in materials}
    part_ids = {x.get("id") for x in parts}
    csg_cell_ids = {c.get("id") for k in csg if isinstance(k, dict) for c in (k.get("cells") or []) if isinstance(c, dict)}

    def add(code, path, message):
        out.append({"level": "error", "code": code, "path": path, "message": message})

    # materials the model uses (the page leaves the others out of model.py)
    used = {x.get("material") for x in parts} | {st.get("worldFill")}
    for k in csg:
        for c in (k.get("cells") or []) if isinstance(k, dict) else []:
            used.add(c.get("material"))
    for g in p.get("groups") or []:
        lat = g.get("lattice") if isinstance(g, dict) else None
        if isinstance(lat, dict) and lat.get("fill") and lat.get("fill") != "auto":
            used.add(lat["fill"])
    for t in tallies:
        if t.get("detector") and t.get("detector") != "none":
            mat, _ = resolve_detector(t, materials)
            if mat:
                used.add(mat)
        if t.get("materialFilter"):
            used.add(t["materialFilter"])

    def fissile(m):
        return any(c["sym"] in FISSILE for c in parse_comps(m.get("comps"))[0])

    # world
    if not pos(st.get("worldR")):
        add("world-size", "/world", "World size must be a positive number of cm.")
    if st.get("worldBC") == "periodic" and st.get("worldShape") == "sphere":
        add("world-periodic-sphere", "/world", "A periodic boundary needs a box world (opposite faces are paired). Switch the world to a box or pick another boundary.")
    if st.get("worldFill") != "void" and st.get("worldFill") not in mat_ids:
        add("world-fill-deleted", "/world", "World fill points at a deleted material. Pick another fill.")

    # materials
    for m in materials:
        name, path = m.get("name"), f"/materials/{m.get('id')}"
        comps, errs = parse_comps(m.get("comps"))
        if not pos(m.get("density")):
            add("material-density", path, f"{name}: density must be above 0 g/cm³.")
        if errs:
            add("material-unreadable", path, f"{name}: can't read \"{errs[0]}\". Write Symbol:amount, like H:2 or U235:0.03.")
        elif not comps:
            add("material-empty", path, f"{name}: add at least one element or nuclide.")
        if any(not c["amt"] > 0 for c in comps):
            add("material-amount", path, f"{name}: every amount must be above 0.")
        no_nat = []
        for c in comps:
            if not c["nuclide"] and c["el"] in NO_NATURAL and c["el"] not in no_nat:
                no_nat.append(c["el"])
        if no_nat and m.get("id") in used:
            add("material-no-natural", path, f"{name}: {', '.join(no_nat)} {'has' if len(no_nat) == 1 else 'have'} no natural isotopes, so OpenMC can't add {'it' if len(no_nat) == 1 else 'them'} as an element. List nuclides, like Pu239:1.")

    # parts
    for x in parts:
        name, path = x.get("name"), f"/parts/{x.get('id')}"
        shape = x.get("shape")
        if shape == "sphere":
            dims = [x.get("r")]
        elif shape == "cylinder":
            dims = [x.get("r"), x.get("h")]
        elif shape == "ellipsoid":
            dims = [x.get("a") or x.get("r") or 1, x.get("b") or x.get("r") or 1, x.get("c") or x.get("r") or 1]
        else:
            dims = [x.get("sx"), x.get("sy"), x.get("sz")]
        if not all(fin(x.get(k)) for k in ("x", "y", "z")):
            add("part-center", path, f"{name}: center needs three numbers.")
        if not all(fin(x.get(k) or 0) for k in ("rx", "ry", "rz")):
            add("part-rotation", path, f"{name}: rotation angles must be numbers (degrees).")
        if not all(pos(d) for d in dims):
            add("part-size", path, f"{name}: sizes must be above 0 cm.")
        if x.get("material") != "void" and x.get("material") not in mat_ids:
            add("part-material-deleted", path, f"{name}: its material was deleted. Pick a material or Void.")
        if x.get("materialPending"):
            add("part-material-pending", path, f"{name} needs a material. It came from a CAD file, which carries none: pick one, or Void if it really is empty space.")

    # sources
    def in_world(x, y, z):
        r = _n(st.get("worldR"))
        if st.get("worldShape") == "sphere":
            return x * x + y * y + z * z < r * r
        return abs(x) < r and abs(y) < r and abs(z) < r

    if not sources:
        add("source-none", "/sources", "Add a source. OpenMC needs at least one.")
    for s in sources:
        name, path = s.get("name"), f"/sources/{s.get('id')}"
        if s.get("space") == "box":
            if not (_n(s.get("x0")) < _n(s.get("x1")) and _n(s.get("y0")) < _n(s.get("y1")) and _n(s.get("z0")) < _n(s.get("z1"))):
                add("source-box", path, f"{name}: each lower corner value must be below the upper one.")
        else:
            if not all(fin(s.get(k)) for k in ("x", "y", "z")):
                add("source-center", path, f"{name}: center needs three numbers.")
            elif not in_world(s["x"], s["y"], s["z"]):
                add("source-outside", path, f"{name} starts outside the world boundary, so no particle would be born.")
            rin = s.get("rin")
            if s.get("space") == "sphere" and not (pos(s.get("r")) and fin(rin) and rin >= 0 and rin < s["r"]):
                add("source-sphere", path, f"{name}: outer radius must be above 0 and above the inner radius.")
            if s.get("space") == "cylinder" and not (pos(s.get("r")) and pos(s.get("h")) and fin(rin) and rin >= 0 and rin < s["r"]):
                add("source-cylinder", path, f"{name}: radius and height must be above 0, with inner radius below outer.")
        if s.get("angle") == "mono" and not (fin(s.get("u")) and fin(s.get("v")) and fin(s.get("w")) and math.hypot(s["u"], s["v"], s["w"]) > 0):
            add("source-direction", path, f"{name}: beam direction can't be 0, 0, 0.")
        en = s.get("energy")
        if en == "lines":
            lines, errs = parse_lines(s.get("lines"))
            if errs:
                add("source-lines-unreadable", path, f"{name}: can't read \"{errs[0]}\". Write MeV:intensity, like 14.1:1.")
            elif not lines:
                add("source-lines-empty", path, f"{name}: add at least one energy line.")
            elif any(not l["e"] > 0 or not l["p"] > 0 for l in lines):
                add("source-lines-values", path, f"{name}: line energies and intensities must be above 0.")
        if en == "watt" and not (pos(s.get("wa")) and pos(s.get("wb"))):
            add("source-watt", path, f"{name}: Watt a and b must be above 0.")
        if en == "maxwell" and not pos(s.get("theta")):
            add("source-maxwell", path, f"{name}: Maxwell temperature must be above 0.")
        if en == "uniform" and not (fin(s.get("emin")) and s["emin"] >= 0 and _n(s.get("emax")) > s["emin"]):
            add("source-uniform", path, f"{name}: maximum energy must be above the minimum.")
        if en == "tabulated":
            n_edges, ok_e, ok_p = parse_tabular(s.get("tab_e"), s.get("tab_p"))
            if not ok_e:
                add("source-tab-edges", path, f"{name}: bin edges must have at least 2 increasing values in MeV, starting at or above 0.")
            elif not ok_p:
                add("source-tab-probs", path, f"{name}: probabilities must have exactly {n_edges - 1} non-negative values (one per bin).")
        if not pos(s.get("strength")):
            add("source-strength", path, f"{name}: strength must be above 0.")
        if eig and s.get("particle") != "neutron":
            add("source-eigenvalue-particle", path, f"{name}: eigenvalue runs only take neutron sources.")

    # tallies
    for t in tallies:
        name, path = t.get("name"), f"/tallies/{t.get('id')}"
        kind, scores = t.get("kind"), (t.get("scores") or [])
        if kind == "cell":
            cells = t.get("cells") or []
            if not cells:
                add("tally-cells-none", path, f"{name}: tick at least one cell to tally.")
            for c in cells:
                if c != "world" and c not in part_ids and c not in csg_cell_ids:
                    add("tally-part-deleted", path, f"{name} lists a part that was deleted.")
        elif kind == "surface":
            ids = t.get("surfaces") or []
            if not ids:
                add("tally-surfaces-none", path, f"{name}: tick at least one part whose surfaces to tally.")
            if any(i not in part_ids for i in ids):
                add("tally-part-deleted", path, f"{name} lists a part that was deleted.")
            if any(sc != "current" for sc in scores):
                add("tally-surface-score", path, f"{name}: surface tallies can only score current.")
        elif t.get("meshGeom") == "cylindrical":
            if not all(is_int(_num_or(t.get(k))) and _num_or(t.get(k)) >= 1 for k in ("nr", "nphi", "nz")):
                add("tally-mesh-bins", path, f"{name}: mesh bins must be whole numbers of 1 or more.")
            rmin = 0 if t.get("rmin") is None else t.get("rmin")
            rmax = t.get("rmax") if t.get("rmax") is not None else (t.get("ux") if t.get("ux") is not None else 10)
            if not (_n(rmin) >= 0 and _n(rmin) < _n(rmax)):
                add("tally-radius", path, f"{name}: the radius range needs 0 ≤ min < max.")
            zmin = t.get("zmin") if t.get("zmin") is not None else (t.get("lz") if t.get("lz") is not None else -10)
            zmax = t.get("zmax") if t.get("zmax") is not None else (t.get("uz") if t.get("uz") is not None else 10)
            if not _n(zmin) < _n(zmax):
                add("tally-zrange", path, f"{name}: the z range needs min < max.")
        else:
            if not all(is_int(t.get(k)) and t.get(k) >= 1 for k in ("nx", "ny", "nz")):
                add("tally-mesh-bins", path, f"{name}: mesh bins must be whole numbers of 1 or more.")
            if not (_n(t.get("lx")) < _n(t.get("ux")) and _n(t.get("ly")) < _n(t.get("uy")) and _n(t.get("lz")) < _n(t.get("uz"))):
                add("tally-mesh-corners", path, f"{name}: each lower corner value must be below the upper one.")
        if t.get("dose") and kind in ("cell", "mesh"):
            if eig:
                add("tally-dose-eigenvalue", path, f"{name}: dose needs a fixed-source run. An eigenvalue run has no absolute source rate to scale by.")
            if t.get("dose") == "np" and not st.get("photon"):
                add("tally-dose-photon", path, f"{name}: photon dose needs photon transport. Turn on Photons in Settings, or set Dose to Neutrons.")
            if t.get("detector") and t.get("detector") != "none":
                add("tally-dose-detector", path, f"{name}: a tally can have a dose or a detector response, not both. Both multiply the flux by a function of energy.")
            if kind == "cell" and t.get("materialFilter"):
                add("tally-dose-material", path, f"{name}: a dose tally can't use a material filter (dose is averaged over each whole cell).")
        if t.get("detector") and t.get("detector") != "none":
            mat, nuc = resolve_detector(t, materials)
            micro = t.get("responseScale") == "micro"
            if not micro and mat not in mat_ids:
                add("tally-detector-material", path, f"{name}: pick the detector material (a macroscopic response needs its atom densities).")
            if micro and (not nuc or nuc == "all"):
                add("tally-detector-nuclide", path, f"{name}: a microscopic response needs one target nuclide, like He3 or B10.")
            if any(sc != "flux" for sc in scores):
                add("tally-detector-score", path, f"{name}: a detector response multiplies the flux, so score flux only.")
        if not scores:
            add("tally-scores-none", path, f"{name}: tick at least one score.")
        ebins = str(t.get("ebins") or "")
        if ebins.strip():
            vals, ok = parse_nums(ebins)
            if not ok or len(vals) < 2 or any(i and vals[i] <= vals[i - 1] for i in range(len(vals))) or vals[0] < 0:
                add("tally-energy-bins", path, f"{name}: energy bin edges need 2 or more rising values in MeV, like 0, 1e-6, 1, 20.")

    # settings
    if not (is_int(st.get("particles")) and st["particles"] >= 1):
        add("settings-particles", "/settings", "Particles per batch must be a whole number of 1 or more.")
    if not (is_int(st.get("batches")) and st["batches"] >= 1):
        add("settings-batches", "/settings", "Batches must be a whole number of 1 or more.")
    if eig:
        if not (is_int(st.get("inactive")) and st["inactive"] >= 0 and _n(st.get("inactive")) < _n(st.get("batches"))):
            add("settings-inactive", "/settings", "Inactive batches must be a whole number below the batch count.")
        if not any(m.get("id") in used and fissile(m) for m in materials):
            add("settings-no-fuel", "/settings", "Eigenvalue runs need fissile material (U or Pu) in a part. Switch to fixed source or add fuel.")
        if st.get("fissionNeutrons") is False:
            add("settings-fission-off", "/settings", "Eigenvalue runs need fission neutrons: each generation is born from the last. Turn Fission neutrons back on, or use a fixed source.")
    if not (is_int(st.get("seed")) and st["seed"] >= 1):
        add("settings-seed", "/settings", "Seed must be a whole number of 1 or more.")
    if not (is_int(st.get("maxTracks")) and st["maxTracks"] >= 0):
        add("settings-max-tracks", "/settings", "Tracks to write must be a whole number (0 turns it off).")
    _, track_errs = parse_track(st.get("track"))
    if track_errs:
        add("settings-track", "/settings", f"Can't read track entry \"{track_errs[0]}\". Write batch, generation, particle, like 1, 1, 42.")
    return out


def _num_or(v):
    """JavaScript's +v for the cylindrical mesh bins: a number or a numeric string; anything else is NaN."""
    if isinstance(v, bool):
        return NAN
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except ValueError:
        return NAN
