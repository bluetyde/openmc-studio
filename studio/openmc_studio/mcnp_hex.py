"""Hexagonal lattices (LAT=2) in imported MCNP decks.

openmc_mcnp_adapter stops at a LAT=2 cell ("Hexagonal lattices not supported"), so this module reads those cells
itself, in two steps around the adapter:

  prepare(text)   finds each LAT=2 cell and the surfaces it uses, works out the element's pitch, centre, index
                  steps and orientation from the deck's own planes, and gives the adapter a deck in which that
                  cell is a rectangular LAT=1 placeholder with the same universe numbers and fill list.
  install(model)  swaps each placeholder for an ``openmc.HexLattice`` holding the deck's universes.

Index order is the manual's (MCNP 6.3.0, p. 290 and the hex example on p. 766): an element is a hexagonal prism
listed [1,0,0], [-1,0,0], [0,1,0], [0,-1,0], [-1,1,0], [1,-1,0] and then the two bases when it is 3D. The element
across the first listed face is [1,0,0] and across the third is [0,1,0], so the steps T1 and T2 are the
outward normals of those faces times the flat-to-flat distance; the fifth face must be [-1,1,0], that is
T2 - T1. Anything that isn't a regular hexagon in that order is refused. The universes' own coordinates are
those of element [0,0,0], so a centre that isn't at the origin is undone with a translation, as the adapter
does for rectangular lattices.

Which OpenMC ring and position holds element [i,j,k] is not worked out from a formula: the lattice is built
with distinct stand-in universes and each element's centre is looked up with ``find_element``, so OpenMC's own
ring conventions decide, and the importer and the placement in mcnp_import.py never agree by construction.
"""
import contextlib
import math
import os
import re
import tempfile

MAX_RINGS = 80
COMMENT = re.compile(r"^\s{0,4}[cC](\s|$)")
HEX_CELL = re.compile(r"(?i)\blat\s*=\s*2\b")
TOL = 1e-6


class Unsupported(Exception):
    """A hexagonal lattice this importer can't read faithfully; the message says why."""


def _blocks(lines):
    """Index of the first blank line (end of the cell block) and of the second (end of the surface block)."""
    blanks = [i for i, ln in enumerate(lines) if not ln.strip()]
    return (blanks + [len(lines), len(lines)])[:2]


def _cards(lines, start, stop):
    """[(first line, [line indices], text without $ comments)] for the cards in lines[start:stop]."""
    out = []
    for i in range(start, stop):
        ln = lines[i]
        if COMMENT.match(ln):
            continue
        cont = ln.startswith("     ") and out and ln.strip()
        if not cont and out and out[-1][2].rstrip().endswith("&"):
            cont = True
        body = re.sub(r"\$.*$", "", ln)
        if cont:
            out[-1][1].append(i)
            out[-1] = (out[-1][0], out[-1][1], out[-1][2].rstrip().rstrip("&") + " " + body.strip())
        elif ln.strip():
            out.append((i, [i], body.strip()))
    return out


def _fill_numbers(tokens):
    """Universe numbers from a fill list, with nR repeats."""
    out = []
    for t in tokens:
        m = re.fullmatch(r"(\d+)[rR]", t)
        if m:
            if not out:
                raise Unsupported("a fill list starts with a repeat")
            out += [out[-1]] * int(m.group(1))
        elif re.fullmatch(r"\d+", t):
            out.append(int(t))
        else:
            raise Unsupported(f"the fill list uses '{t}', which isn't read in a hexagonal lattice")
    return out


def _plane(card_text):
    """(n, d) for a P, PX, PY or PZ card: points x with n.x = d."""
    toks = card_text.split()
    if len(toks) < 3:
        return None
    kind = toks[1].upper() if not re.fullmatch(r"\d+", toks[1]) else None
    if kind is None:
        raise Unsupported(f"surface {toks[0]} has a transformation, which isn't read in a hexagonal lattice")
    try:
        nums = [float(t.replace("D", "E").replace("d", "e")) for t in toks[2:]]
    except ValueError:
        return None
    if kind == "P" and len(nums) == 4:
        return (nums[0], nums[1], nums[2]), nums[3]
    if kind in ("PX", "PY", "PZ") and len(nums) == 1:
        n = [0.0, 0.0, 0.0]
        n["XYZ".index(kind[1])] = 1.0
        return tuple(n), nums[0]
    return None


def _unit(v):
    m = math.sqrt(sum(x * x for x in v))
    return tuple(x / m for x in v), m


def _faces(surface_ids, planes):
    """Outward unit normals and offsets of the cell's faces: the cell is every point inside all of them."""
    out = []
    for token in surface_ids:
        sid, sign = abs(int(token)), (-1.0 if token.startswith("-") else 1.0)
        if sid not in planes or planes[sid] is None:
            raise Unsupported(f"surface {sid} of a hexagonal lattice cell isn't a plane (P, PX, PY or PZ)")
        n, d = planes[sid]
        u, m = _unit(n)
        if m == 0:
            raise Unsupported(f"surface {sid} is not a plane")
        # a point is on the +side when n.x > d; the cell is on the -side of a face written -s and the +side of +s
        out.append((tuple(-sign * x for x in u), -sign * d / m))
    return out


def _geometry(faces, cell):
    """Pitch, centre, steps and orientation from the six side faces (and the two bases) in the manual's order."""
    side = faces[:6]
    widths = [side[0][1] + side[1][1], side[2][1] + side[3][1], side[4][1] + side[5][1]]
    for a, b in ((0, 1), (2, 3), (4, 5)):
        if any(abs(side[a][0][k] + side[b][0][k]) > TOL for k in range(3)) or abs(side[a][0][2]) > TOL:
            raise Unsupported(f"cell {cell}: faces {a + 1} and {b + 1} of the hexagon aren't parallel side planes")
    p = widths[0]
    if p <= 0 or any(abs(w - p) > TOL * max(1.0, p) for w in widths):
        raise Unsupported(f"cell {cell}: the hexagon's three face-to-face widths differ ({', '.join(f'{w:.6g}' for w in widths)}), so it isn't regular")
    m0, m2, m4 = side[0][0], side[2][0], side[4][0]
    if abs(m0[0] * m2[0] + m0[1] * m2[1] - 0.5) > TOL:
        raise Unsupported(f"cell {cell}: the first and third faces aren't 60 degrees apart, so [1,0,0] and [0,1,0] aren't neighbours")
    if any(abs(m4[k] - (m2[k] - m0[k])) > TOL for k in range(3)):
        raise Unsupported(f"cell {cell}: the fifth face isn't the [-1,1,0] neighbour (T2 - T1) the manual's order requires")
    # centre: m.c = (e_out - e_back)/2 for two non-parallel pairs, solved for x and y
    r0, r2 = (side[0][1] - side[1][1]) / 2, (side[2][1] - side[3][1]) / 2
    det = m0[0] * m2[1] - m0[1] * m2[0]
    cx = (r0 * m2[1] - r2 * m0[1]) / det
    cy = (m0[0] * r2 - m2[0] * r0) / det
    if abs(m4[0] * cx + m4[1] * cy - (side[4][1] - side[5][1]) / 2) > TOL * max(1.0, p):
        raise Unsupported(f"cell {cell}: the three pairs of hexagon faces don't meet at one centre")
    t1, t2 = (p * m0[0], p * m0[1]), (p * m2[0], p * m2[1])
    dirs = [(m0[0], m0[1]), (m2[0], m2[1]), (m2[0] - m0[0], m2[1] - m0[1])]
    if any(abs(abs(d[0]) - 1) < 1e-4 and abs(d[1]) < 1e-4 for d in dirs):
        orientation = "x"
    elif any(abs(abs(d[1]) - 1) < 1e-4 and abs(d[0]) < 1e-4 for d in dirs):
        orientation = "y"
    else:
        raise Unsupported(f"cell {cell}: the hexagon is turned to neither the x nor the y axis, and OpenMC's hexagonal lattice can't be turned")
    geo = {"pitch": p, "t1": t1, "t2": t2, "centre": [cx, cy, 0.0], "orientation": orientation, "dz": None, "zstep": 0.0}
    if len(faces) == 8:
        up, dn = faces[6], faces[7]
        if abs(up[0][2] + dn[0][2]) > TOL or abs(abs(up[0][2]) - 1) > TOL or abs(up[0][0]) > TOL or abs(up[0][1]) > TOL:
            raise Unsupported(f"cell {cell}: the 7th and 8th faces aren't z planes")
        geo["dz"] = up[1] + dn[1]
        geo["zstep"] = geo["dz"] * up[0][2]
        geo["centre"][2] = (up[1] - dn[1]) / 2 * up[0][2]
        if geo["dz"] <= 0:
            raise Unsupported(f"cell {cell}: the two base planes enclose nothing")
    return geo


def _parse_cell(first_line, text, planes):
    toks = text.split()
    cell = int(toks[0])
    mat = int(toks[1])
    k = 3 if mat else 2
    region = []
    while k < len(toks) and re.fullmatch(r"[+-]?\d+", toks[k]):
        region.append(toks[k])
        k += 1
    rest = " ".join(toks[k:])
    if len(region) not in (6, 8):
        raise Unsupported(f"cell {cell}: a hexagonal lattice cell lists {len(region)} surfaces; the manual's element has 6 sides (and 2 bases)")
    geo = _geometry(_faces(region, planes), cell)
    um = re.search(r"(?i)\bu\s*=\s*(-?\d+)", rest)
    if not um:
        raise Unsupported(f"cell {cell}: the lattice cell has no U=")
    fm = re.search(r"(?i)\*?\bfill\s*=\s*(.*)$", rest)
    if not fm:
        raise Unsupported(f"cell {cell}: the lattice cell has no FILL")
    # i1:i2 j1:j2 k1:k2 then the universes, ending at the next KEYWORD=value
    spec = re.match(r"\s*(-?\d+)\s*:\s*(-?\d+)\s+(-?\d+)\s*:\s*(-?\d+)\s+(-?\d+)\s*:\s*(-?\d+)\s*(.*)$", fm.group(1))
    if not spec:
        raise Unsupported(f"cell {cell}: a hexagonal lattice with a single universe or no index range isn't read yet")
    i1, i2, j1, j2, k1, k2 = (int(spec.group(n)) for n in range(1, 7))
    tail = []
    for t in spec.group(7).split():
        if not re.fullmatch(r"\d+[rR]?", t):
            break
        tail.append(t)
    ids = _fill_numbers(tail)
    n = (i2 - i1 + 1) * (j2 - j1 + 1) * (k2 - k1 + 1)
    if i2 < i1 or j2 < j1 or k2 < k1 or len(ids) != n:
        raise Unsupported(f"cell {cell}: the fill list has {len(ids)} universes for an index range of {n} elements")
    if geo["dz"] is None and (k1, k2) != (0, 0):
        raise Unsupported(f"cell {cell}: a 2D hexagonal lattice (six faces) with a k range other than 0:0")
    uid = abs(int(um.group(1)))
    if uid in ids:
        raise Unsupported(f"cell {cell}: universe {uid} is in its own fill list")
    rec = {"cell": cell, "lattice": uid, "ranges": [i1, i2, j1, j2, k1, k2], "ids": ids, **geo}
    return rec, region, rest, mat, toks


def prepare(text):
    """(deck text for the adapter, records). With no LAT=2 cell the text is returned as it came."""
    if not HEX_CELL.search(text):
        return text, []
    lines = text.splitlines()
    e0, e1 = _blocks(lines)
    cell_cards = _cards(lines, 1, e0)
    surf_cards = _cards(lines, e0 + 1, e1)
    planes, top = {}, 0
    for _first, _idx, body in surf_cards:
        toks = body.split()
        if toks and re.fullmatch(r"\*?\+?\d+", toks[0]):
            sid = int(toks[0].lstrip("*+"))
            top = max(top, sid)
            if toks[0][0] in "*+":
                planes[sid] = None
                continue
            try:
                planes[sid] = _plane(body)
            except Unsupported:
                planes[sid] = None
    records, new_surfaces = [], []
    replace = {}
    for first, idx, body in cell_cards:
        if not HEX_CELL.search(body):
            continue
        rec, region, rest, mat, toks = _parse_cell(first, body, planes)
        three = rec["dz"] is not None
        ids = [top + 1 + k for k in range(4 + (2 if three else 0))]
        top = ids[-1]
        new_surfaces += [f"{ids[0]} PX 0.5", f"{ids[1]} PX -0.5", f"{ids[2]} PY 0.5", f"{ids[3]} PY -0.5"]
        faces = f"-{ids[0]} {ids[1]} -{ids[2]} {ids[3]}"
        if three:
            new_surfaces += [f"{ids[4]} PZ 0.5", f"{ids[5]} PZ -0.5"]
            faces += f" -{ids[4]} {ids[5]}"
        dens = f" {toks[2]}" if mat else ""
        card = f"{rec['cell']} {mat}{dens} {faces} " + re.sub(r"(?i)\blat\s*=\s*2\b", "LAT=1", rest)
        replace[first] = card
        for extra in idx[1:]:
            replace[extra] = None
        records.append(rec)
    out = []
    for i, ln in enumerate(lines):
        if i in replace:
            if replace[i] is not None:
                out.append(replace[i])
            continue
        if i == e0 + 1:
            out += new_surfaces
        out.append(ln)
    return "\n".join(out) + "\n", records


def _ring_slots(n, nz):
    """The positions of an OpenMC hexagonal lattice with n rings and nz axial levels, as (axial, ring, position)."""
    sizes = [1 if r == n - 1 else 6 * (n - 1 - r) for r in range(n)]
    return [(a, r, p) for a in range(nz) for r in range(n) for p in range(sizes[r])], sizes


def build(rec, universes):
    """An openmc.HexLattice for one record; `universes` maps deck universe number to openmc.Universe."""
    import openmc
    i1, i2, j1, j2, k1, k2 = rec["ranges"]
    nz = k2 - k1 + 1
    three = rec["dz"] is not None
    ring = max(max(abs(i), abs(j), abs(i + j)) for i in range(i1, i2 + 1) for j in range(j1, j2 + 1))
    n = ring + 1
    if n > MAX_RINGS:
        raise Unsupported(f"cell {rec['cell']}: the fill range needs {n} rings; the limit is {MAX_RINGS}")
    p, (t1, t2), (cx, cy, cz) = rec["pitch"], (rec["t1"], rec["t2"]), rec["centre"]
    zstep = rec["zstep"]
    lat = openmc.HexLattice()
    lat.orientation = rec["orientation"]
    lat.pitch = (p, rec["dz"]) if three else (p,)
    lat.center = (0.0, 0.0, (k1 + k2) / 2 * zstep) if three else (0.0, 0.0)
    slots, sizes = _ring_slots(n, nz)

    def nest(table):
        levels = [[[table[(a, r, q)] for q in range(sizes[r])] for r in range(n)] for a in range(nz)]
        return levels if three else levels[0]

    stand_in = {s: openmc.Universe() for s in slots}
    lat.universes = nest(stand_in)
    by_id = {u.id: s for s, u in stand_in.items()}
    filler = openmc.Universe(cells=[openmc.Cell()])
    filler._studio_filler = True
    shift = (-cx, -cy, -cz)
    wrapped = {}

    def inside(uid):
        if uid not in universes:
            raise Unsupported(f"cell {rec['cell']}: the fill list names universe {uid}, which no cell defines")
        if uid not in wrapped:
            if any(abs(v) > 1e-12 for v in shift[:3 if three else 2]):
                c = openmc.Cell(fill=universes[uid])
                c.translation = shift if three else (shift[0], shift[1], 0.0)
                wrapped[uid] = openmc.Universe(cells=[c])
            else:
                wrapped[uid] = universes[uid]
        return wrapped[uid]

    target = {s: filler for s in slots}
    it = iter(rec["ids"])
    for k in range(k1, k2 + 1):
        for j in range(j2 - j1 + 1):
            for i in range(i2 - i1 + 1):
                uid = next(it)
                ii, jj = i1 + i, j1 + j
                pt = (ii * t1[0] + jj * t2[0], ii * t1[1] + jj * t2[1], k * zstep)
                idx, _ = lat.find_element(pt if three else (pt[0], pt[1], 0.0))
                if not lat.is_valid_index(idx):
                    raise Unsupported(f"cell {rec['cell']}: element [{ii},{jj},{k}] falls outside the OpenMC lattice built for it")
                s = by_id[lat.get_universe(idx).id]
                if target[s] is not filler:
                    raise Unsupported(f"cell {rec['cell']}: two elements of the fill list land on the same OpenMC position")
                target[s] = inside(uid)
    lat.universes = nest(target)
    return lat


def install(model, records):
    """Replace each placeholder lattice (rectangular, with the hexagonal one's universe number) in the model."""
    if not records:
        return []
    geom = model.geometry
    universes = geom.get_all_universes()
    lattices = geom.get_all_lattices()
    cells = list(geom.get_all_cells().values())
    done = []
    for rec in records:
        ph = lattices.get(rec["lattice"])
        if ph is None:
            continue
        hexlat = build(rec, universes)
        for c in cells:
            if c.fill is ph:
                c.fill = hexlat
        done.append(rec["cell"])
    return done


def read_deck(path, convert):
    """(model, numbers of the hexagonal lattice cells installed) for a deck file: the adapter's `convert` (its
    mcnp_to_model) on the deck with each LAT=2 cell held as a placeholder, then the hexagonal lattices put in."""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    new_text, records = prepare(text)
    if not records:
        return convert(str(path)), []
    tmp = tempfile.NamedTemporaryFile("w", suffix=".mcnp", delete=False, encoding="utf-8", newline="\n")
    try:
        tmp.write(new_text)
        tmp.close()
        model = convert(tmp.name)
    finally:
        tmp.close()
        with contextlib.suppress(OSError):
            os.unlink(tmp.name)
    return model, install(model, records)
