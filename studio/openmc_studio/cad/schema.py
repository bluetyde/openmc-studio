"""Studio's analytical CSG representation (project schema 2) and the XML adapter.

GEOUNED's OpenMC XML is consumed as DATA: a bounded reader that refuses DTDs and
entities, an explicit OpenMC region grammar with depth and size limits, and a
fixed table of supported surface types. Nothing generated is ever executed.

The representation (IR_VERSION) for one converted source solid, a "component":

    {"surfaces": [{"id": 1, "type": "z-plane", "coeffs": {"z0": 1.5}}, ...],
     "cells":    [{"name": "...", "region": <AST>}, ...],
     "units": "cm"}

Region AST nodes:  {"half": "-"|"+", "s": <surface id>}
                   {"op": "and"|"or", "args": [<node>, ...]}
                   {"op": "not", "arg": <node>}

Surface ids are local to their component; Studio assigns OpenMC ids when it writes
a model. Surface equations are OpenMC's own (openmc.Plane, openmc.ZCone, ...), so
evaluating a region here and in OpenMC gives the same answer.

Units: GEOUNED writes centimetres (checked on the stage-0 fixtures). The adapter
does NOT rescale; the validation in csg.py compares against the source solid in
millimetres / 10, so a unit slip anywhere fails the component.
"""
import math
import re
import xml.etree.ElementTree as ET

IR_VERSION = 1
MAX_XML_BYTES = 8 * 1024 * 1024
MAX_ELEMENTS = 200_000
MAX_TOKENS = 200_000
MAX_DEPTH = 64
MAX_NODES = 50_000

# OpenMC XML type -> coefficient names, in OpenMC's order.
SURFACES = {
    "plane": ("a", "b", "c", "d"),
    "x-plane": ("x0",), "y-plane": ("y0",), "z-plane": ("z0",),
    "sphere": ("x0", "y0", "z0", "r"),
    "x-cylinder": ("y0", "z0", "r"), "y-cylinder": ("x0", "z0", "r"), "z-cylinder": ("x0", "y0", "r"),
    "x-cone": ("x0", "y0", "z0", "r2"), "y-cone": ("x0", "y0", "z0", "r2"), "z-cone": ("x0", "y0", "z0", "r2"),
    "quadric": ("a", "b", "c", "d", "e", "f", "g", "h", "j", "k"),
}
REFUSED = {"x-torus": "a torus", "y-torus": "a torus", "z-torus": "a torus"}


class AdapterError(ValueError):
    """The XML can't be represented faithfully; the message says why."""


def evaluate(surface, x, y, z):
    """OpenMC's surface function f(x, y, z); a point is on the '-' side where f < 0."""
    t, c = surface["type"], surface["coeffs"]
    if t == "plane":
        return c["a"] * x + c["b"] * y + c["c"] * z - c["d"]
    if t == "x-plane":
        return x - c["x0"]
    if t == "y-plane":
        return y - c["y0"]
    if t == "z-plane":
        return z - c["z0"]
    if t == "sphere":
        return (x - c["x0"]) ** 2 + (y - c["y0"]) ** 2 + (z - c["z0"]) ** 2 - c["r"] ** 2
    if t == "x-cylinder":
        return (y - c["y0"]) ** 2 + (z - c["z0"]) ** 2 - c["r"] ** 2
    if t == "y-cylinder":
        return (x - c["x0"]) ** 2 + (z - c["z0"]) ** 2 - c["r"] ** 2
    if t == "z-cylinder":
        return (x - c["x0"]) ** 2 + (y - c["y0"]) ** 2 - c["r"] ** 2
    if t == "x-cone":
        return (y - c["y0"]) ** 2 + (z - c["z0"]) ** 2 - c["r2"] * (x - c["x0"]) ** 2
    if t == "y-cone":
        return (x - c["x0"]) ** 2 + (z - c["z0"]) ** 2 - c["r2"] * (y - c["y0"]) ** 2
    if t == "z-cone":
        return (x - c["x0"]) ** 2 + (y - c["y0"]) ** 2 - c["r2"] * (z - c["z0"]) ** 2
    if t == "quadric":
        return (c["a"] * x * x + c["b"] * y * y + c["c"] * z * z + c["d"] * x * y + c["e"] * y * z
                + c["f"] * x * z + c["g"] * x + c["h"] * y + c["j"] * z + c["k"])
    raise AdapterError(f"unsupported surface type {t}")


def contains(node, surfaces, x, y, z):
    """Is the point inside the region? surfaces: {id: surface}."""
    if "half" in node:
        f = evaluate(surfaces[node["s"]], x, y, z)
        return f < 0 if node["half"] == "-" else f > 0
    if node["op"] == "and":
        return all(contains(a, surfaces, x, y, z) for a in node["args"])
    if node["op"] == "or":
        return any(contains(a, surfaces, x, y, z) for a in node["args"])
    return not contains(node["arg"], surfaces, x, y, z)


# ── the OpenMC region grammar ──
#   expr   := term ('|' term)*          union, lowest precedence
#   term   := factor factor*            intersection by juxtaposition
#   factor := '~' factor | '(' expr ')' | halfspace
#   halfspace := ['+' | '-'] integer
TOKEN_ONLY = re.compile(r"\(|\)|\||~|[+-]?\d+")
WHITESPACE = re.compile(r"\s+")


def parse_region(text, surface_ids):
    if not isinstance(text, str) or not text.strip():
        raise AdapterError("a cell has an empty region")
    # One linear pass; the tokens must account for every non-space character.
    tokens = TOKEN_ONLY.findall(text)
    if len(tokens) > MAX_TOKENS:
        raise AdapterError("a region is too long")
    if "".join(tokens) != WHITESPACE.sub("", text):
        bad = WHITESPACE.sub("", TOKEN_ONLY.sub(" ", text))[:20]
        raise AdapterError(f"unreadable region near {bad!r}")
    state = {"i": 0, "nodes": 0}

    def node(n):
        state["nodes"] += 1
        if state["nodes"] > MAX_NODES:
            raise AdapterError("a region is too complex")
        return n

    def peek():
        return tokens[state["i"]] if state["i"] < len(tokens) else None

    def take():
        tok = peek()
        state["i"] += 1
        return tok

    def expr(depth):
        if depth > MAX_DEPTH:
            raise AdapterError("a region is nested too deeply")
        args = [term(depth)]
        while peek() == "|":
            take()
            args.append(term(depth))
        return args[0] if len(args) == 1 else node({"op": "or", "args": _flatten("or", args)})

    def term(depth):
        args = [factor(depth)]
        while peek() not in (None, ")", "|"):
            args.append(factor(depth))
        return args[0] if len(args) == 1 else node({"op": "and", "args": _flatten("and", args)})

    def factor(depth):
        tok = take()
        if tok is None:
            raise AdapterError("a region ends too early")
        if tok == "~":
            return node({"op": "not", "arg": factor(depth + 1)})
        if tok == "(":
            inner = expr(depth + 1)
            if take() != ")":
                raise AdapterError("a region has unbalanced parentheses")
            return inner
        if tok in (")", "|"):
            raise AdapterError(f"unexpected {tok!r} in a region")
        sid = abs(int(tok))
        if sid not in surface_ids:
            raise AdapterError(f"a region refers to surface {sid}, which isn't defined")
        return node({"half": "-" if tok.startswith("-") else "+", "s": sid})

    ast = expr(0)
    if state["i"] != len(tokens):
        raise AdapterError("a region has unbalanced parentheses")
    return ast


def _flatten(op, args):
    out = []
    for a in args:
        out.extend(a["args"] if a.get("op") == op else [a])
    return out


def region_text(node):
    """Back to OpenMC's region syntax (fully parenthesized where it matters)."""
    if "half" in node:
        return f"{node['half']}{node['s']}"
    if node["op"] == "not":
        return f"~({region_text(node['arg'])})"
    inner = [region_text(a) for a in node["args"]]
    return "(" + (" | " if node["op"] == "or" else " ").join(inner) + ")"


def surfaces_used(node, into=None):
    into = set() if into is None else into
    if "half" in node:
        into.add(node["s"])
    elif node["op"] == "not":
        surfaces_used(node["arg"], into)
    else:
        for a in node["args"]:
            surfaces_used(a, into)
    return into


def _surface(el):
    t = el.get("type")
    if t in REFUSED:
        raise AdapterError(f"the solid needs {REFUSED[t]} surface, which Studio can't display or export yet")
    if t not in SURFACES:
        raise AdapterError(f"unsupported surface type {t!r}")
    try:
        sid = int(el.get("id"))
        values = [float(v) for v in (el.get("coeffs") or "").split()]
    except (TypeError, ValueError):
        raise AdapterError(f"surface {el.get('id')!r} has unreadable numbers") from None
    names = SURFACES[t]
    if len(values) != len(names) or not all(math.isfinite(v) for v in values):
        raise AdapterError(f"surface {sid} ({t}) needs {len(names)} finite coefficients")
    c = dict(zip(names, values))
    if t == "plane" and not any(c[k] for k in "abc"):
        raise AdapterError(f"surface {sid} is a plane with no normal")
    if "r" in c and not c["r"] > 0:
        raise AdapterError(f"surface {sid} has a non-positive radius")
    if "r2" in c and not c["r2"] > 0:
        raise AdapterError(f"surface {sid} is a cone with a non-positive slope")
    if t == "quadric" and not any(c[k] for k in "abcdefghj"):
        raise AdapterError(f"surface {sid} is a quadric with no terms")
    # boundary= is deliberately dropped: GEOUNED writes vacuum on the last surface it
    # emits even when that surface is an internal hole. Studio's world owns boundaries.
    return {"id": sid, "type": t, "coeffs": c}


def read_openmc_xml(data):
    """Parse GEOUNED's geometry.xml (bytes or str) into {"surfaces", "cells", "units"}."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    if len(raw) > MAX_XML_BYTES:
        raise AdapterError("the converted geometry is too large")
    head = raw[:4096].lower()
    if b"<!doctype" in raw.lower() or b"<!entity" in head:
        raise AdapterError("the converted geometry contains a DTD or entities, which are refused")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise AdapterError(f"the converted geometry isn't well-formed XML ({exc})") from None
    if root.tag != "geometry":
        raise AdapterError("the converted file isn't an OpenMC geometry")
    if sum(1 for _ in root.iter()) > MAX_ELEMENTS:
        raise AdapterError("the converted geometry has too many elements")
    surfaces = [_surface(el) for el in root.findall("surface")]
    ids = [s["id"] for s in surfaces]
    if len(set(ids)) != len(ids):
        raise AdapterError("two surfaces share an id")
    cells = []
    for el in root.findall("cell"):
        if el.get("fill") is not None or el.get("universe") not in (None, "0", "1"):
            raise AdapterError("nested universes or fills aren't supported")
        if el.get("material") not in (None, "void"):
            raise AdapterError("the converter assigned a material; Studio expects unassigned regions")
        cells.append({"name": (el.get("name") or "").strip("/ "), "region": parse_region(el.get("region"), set(ids))})
    if not cells:
        raise AdapterError("the converted geometry has no cells")
    used = set()
    for cell in cells:
        surfaces_used(cell["region"], used)
    # Keep only surfaces a region uses: an unused surface would be an orphan in the model.
    return {"surfaces": [s for s in surfaces if s["id"] in used], "cells": cells, "units": "cm",
            "ir_version": IR_VERSION}


def component_contains(component, x, y, z):
    """Which cells (indices) of a component contain the point (cm)."""
    table = {s["id"]: s for s in component["surfaces"]}
    return [i for i, c in enumerate(component["cells"]) if contains(c["region"], table, x, y, z)]
