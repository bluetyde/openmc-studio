"""Recognize Studio primitives (box, sphere, capped cylinder, cone/frustum) in a solid.

Face counts are only hints: a CAD kernel may split one cylindrical face at a seam
or one box side into several coplanar faces. Recognition therefore groups faces by
their support surface (same plane, same cylinder, ...) and checks the geometry of
those groups. A candidate is only a proposal: validate.py rebuilds it the way
Studio will and compares it with the source before anything is accepted.

All lengths here are millimetres (the kernel's unit); emit_part converts to
Studio's centimetres, once.
"""
import itertools
import math


class NotPrimitive(Exception):
    """The solid is not one of the supported primitives; the message says why."""


def _v(p):
    return (float(p.x), float(p.y), float(p.z))


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    n = _norm(a)
    return (a[0] / n, a[1] / n, a[2] / n)


def tolerances(shape):
    """Scale-aware tolerances, recorded in every report.

    Linear: 1e-7 of the solid's size, never below 1e-6 mm (a TRISO coating layer is
    ~0.035 mm, 35,000 times larger) and allowing for coordinates far from the
    origin. Angular: the same relative precision, as a sine."""
    b = shape.BoundBox
    diag = max(b.DiagonalLength, 1e-9)
    far = max(abs(b.XMin), abs(b.XMax), abs(b.YMin), abs(b.YMax), abs(b.ZMin), abs(b.ZMax))
    lin = max(1e-6, 1e-7 * diag, 1e-10 * far)
    return {"linear_mm": lin, "angular_sin": max(1e-9, lin / diag), "size_mm": diag}


def _supports(shape):
    """Group the faces by surface type; unsupported surfaces end recognition."""
    groups = {"Plane": [], "Cylinder": [], "Sphere": [], "Cone": []}
    for face in shape.Faces:
        kind = type(face.Surface).__name__
        if kind not in groups:
            raise NotPrimitive(f"it has a {kind} surface, which no supported primitive has")
        groups[kind].append(face.Surface)
    return groups


def _distinct_planes(planes, tol):
    """[(unit normal, offset)] with coplanar faces merged (normal sign-normalized)."""
    out = []
    for p in planes:
        n = _unit(_v(p.Axis))
        d = _dot(n, _v(p.Position))
        for i, (m, e) in enumerate(out):
            if _norm(_cross(n, m)) <= tol["angular_sin"]:
                if _dot(n, m) < 0:
                    n, d = _mul(n, -1), -d
                if abs(d - e) <= tol["linear_mm"]:
                    break
        else:
            out.append((n, d))
    return out


def _same_axis_line(p0, a0, p1, a1, tol):
    """Two axis lines coincide: parallel, and each point lies on the other line."""
    if _norm(_cross(a0, a1)) > tol["angular_sin"]:
        return False
    off = _sub(p1, p0)
    return _norm(_cross(off, a0)) <= tol["linear_mm"]


def _frame_closest_to_identity(axes, sizes):
    """Among the 24 proper orientations of a box frame, the one nearest identity.

    axes: three orthonormal world vectors (columns); sizes: extents along them.
    Returns (R as rows, sizes reordered to R's columns)."""
    best = None
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            cols = [_mul(axes[perm[k]], signs[k]) for k in range(3)]
            if _dot(_cross(cols[0], cols[1]), cols[2]) < 0:
                continue
            trace = cols[0][0] + cols[1][1] + cols[2][2]
            if best is None or trace > best[0] + 1e-12:
                best = (trace, cols, [sizes[perm[k]] for k in range(3)])
    cols = best[1]
    R = [[cols[j][i] for j in range(3)] for i in range(3)]
    return R, best[2]


def _clean_angle(deg):
    deg = round(deg, 12)
    nearest = round(deg / 90) * 90
    if abs(deg - nearest) < 1e-9:
        deg = float(nearest)
    if deg <= -180:
        deg += 360
    elif deg > 180:
        deg -= 360
    return 0.0 if deg == 0 else deg


def euler_xyz(R):
    """Angles (rx, ry, rz) in degrees with R = Rz(rz) * Ry(ry) * Rx(rx), Studio's order.
    Uniqueness isn't expected: callers rebuild the matrix and compare."""
    sy = max(-1.0, min(1.0, -R[2][0]))
    b = math.asin(sy)
    if abs(math.cos(b)) > 1e-12:
        a = math.atan2(R[2][1], R[2][2])
        c = math.atan2(R[1][0], R[0][0])
    else:  # gimbal lock: ry = +/-90, fold rz into rx
        c = 0.0
        a = math.atan2(R[0][1], R[1][1]) if sy > 0 else math.atan2(-R[0][1], R[1][1])
    return tuple(_clean_angle(math.degrees(x)) for x in (a, b, c))


def rot_xyz(rx, ry, rz):
    """The same matrix as Studio's rotXYZ (index.html)."""
    cx, sx = math.cos(math.radians(rx)), math.sin(math.radians(rx))
    cy, sy = math.cos(math.radians(ry)), math.sin(math.radians(ry))
    cz, sz = math.cos(math.radians(rz)), math.sin(math.radians(rz))
    return [[cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
            [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
            [-sy, cy * sx, cy * cx]]


def _axis_rotation(u):
    """(rx, ry) so that Ry(ry) * Rx(rx) maps local +z onto the unit vector u."""
    a = math.asin(max(-1.0, min(1.0, -u[1])))
    b = math.atan2(u[0], u[2]) if abs(math.cos(a)) > 1e-12 else 0.0
    return _clean_angle(math.degrees(a)), _clean_angle(math.degrees(b))


def classify(shape):
    """Return a primitive candidate in millimetres, or raise NotPrimitive.

    Candidate: {"shape": ..., dimensions..., "center": (x, y, z), "R": 3x3 rows or
    None, "axis": unit vector or None}."""
    if len(shape.Solids) != 1:
        raise NotPrimitive("it is not a single solid")
    if not shape.isValid() or not shape.isClosed():
        raise NotPrimitive("the solid is not valid and closed")
    if len(shape.Shells) != 1:
        raise NotPrimitive("it has an internal void (more than one shell)")
    tol = tolerances(shape)
    g = _supports(shape)
    used = [k for k, v in g.items() if v]

    if used == ["Sphere"]:
        c0, r0 = _v(g["Sphere"][0].Center), float(g["Sphere"][0].Radius)
        for s in g["Sphere"][1:]:
            if _norm(_sub(_v(s.Center), c0)) > tol["linear_mm"] or abs(s.Radius - r0) > tol["linear_mm"]:
                raise NotPrimitive("its spherical faces belong to different spheres (a shell or a lens)")
        return {"shape": "sphere", "r": r0, "center": c0, "R": None, "axis": None, "tol": tol}

    if used == ["Plane"]:
        planes = _distinct_planes(g["Plane"], tol)
        if len(planes) != 6:
            raise NotPrimitive(f"it is bounded by {len(planes)} distinct planes, not the 6 of a box")
        dirs = []
        for n, d in planes:
            for entry in dirs:
                if _norm(_cross(n, entry[0])) <= tol["angular_sin"]:
                    entry[1].append(d if _dot(n, entry[0]) > 0 else -d)
                    break
            else:
                dirs.append([n, [d]])
        if len(dirs) != 3 or any(len(e[1]) != 2 for e in dirs):
            raise NotPrimitive("its planes are not three parallel pairs")
        for (n1, _), (n2, _) in itertools.combinations(dirs, 2):
            if abs(_dot(n1, n2)) > tol["angular_sin"]:
                raise NotPrimitive("its faces are not perpendicular (a parallelepiped, not a box)")
        axes = [e[0] for e in dirs]
        sizes = [abs(e[1][0] - e[1][1]) for e in dirs]
        center = (0.0, 0.0, 0.0)
        for n, ds in dirs:
            center = _add(center, _mul(n, (ds[0] + ds[1]) / 2))
        R, sizes = _frame_closest_to_identity(axes, sizes)
        return {"shape": "box", "sx": sizes[0], "sy": sizes[1], "sz": sizes[2],
                "center": center, "R": R, "axis": None, "tol": tol}

    if sorted(used) == ["Cylinder", "Plane"]:
        c = g["Cylinder"][0]
        p0, a0, r0 = _v(c.Center), _unit(_v(c.Axis)), float(c.Radius)
        for s in g["Cylinder"][1:]:
            if not _same_axis_line(p0, a0, _v(s.Center), _unit(_v(s.Axis)), tol) or abs(s.Radius - r0) > tol["linear_mm"]:
                raise NotPrimitive("its curved faces belong to different cylinders (a shell, a step or a fillet)")
        planes = _distinct_planes(g["Plane"], tol)
        if len(planes) != 2:
            raise NotPrimitive(f"it has {len(planes)} flat faces, not the two caps of a cylinder")
        ts = []
        for n, d in planes:
            if _norm(_cross(n, a0)) > tol["angular_sin"]:
                raise NotPrimitive("a cap is not perpendicular to the axis (a sheared cylinder)")
            # Plane: n . x = d, with n parallel to a0; the cap sits at t along the axis.
            ts.append((d - _dot(n, p0)) / _dot(n, a0))
        h = abs(ts[0] - ts[1])
        center = _add(p0, _mul(a0, (ts[0] + ts[1]) / 2))
        return {"shape": "cylinder", "r": r0, "h": h, "center": center, "R": None, "axis": a0, "tol": tol}

    if sorted(used) in (["Cone"], ["Cone", "Plane"]):
        k = g["Cone"][0]
        apex, a0, semi = _v(k.Apex), _unit(_v(k.Axis)), float(k.SemiAngle)
        for s in g["Cone"][1:]:
            if (_norm(_sub(_v(s.Apex), apex)) > tol["linear_mm"] or abs(s.SemiAngle - semi) > tol["angular_sin"]
                    or _norm(_cross(_unit(_v(s.Axis)), a0)) > tol["angular_sin"]):
                raise NotPrimitive("its conical faces belong to different cones")
        planes = _distinct_planes(g["Plane"], tol)
        if not 1 <= len(planes) <= 2:
            raise NotPrimitive(f"it has {len(planes)} flat faces, not the one or two caps of a cone")
        ts = []
        for n, d in planes:
            if _norm(_cross(n, a0)) > tol["angular_sin"]:
                raise NotPrimitive("a cap is not perpendicular to the axis")
            ts.append((d - _dot(n, apex)) / _dot(n, a0))  # signed distance from the apex
        if len(ts) == 1:
            ts.append(0.0)  # the other end is the apex itself
        if ts[0] * ts[1] < 0:
            raise NotPrimitive("the caps are on both sides of the apex (a double cone)")
        radii = [abs(t) * math.tan(abs(semi)) for t in ts]
        base, top = (0, 1) if radii[0] >= radii[1] else (1, 0)
        p_base = _add(apex, _mul(a0, ts[base]))
        p_top = _add(apex, _mul(a0, ts[top]))
        h = _norm(_sub(p_top, p_base))
        if h <= tol["linear_mm"]:
            raise NotPrimitive("the cone has no height")
        return {"shape": "cone", "r": radii[base], "r2": radii[top], "h": h,
                "center": _mul(_add(p_base, p_top), 0.5), "R": None,
                "axis": _unit(_sub(p_top, p_base)), "tol": tol}

    raise NotPrimitive("its surfaces ({}) don't form a box, sphere, capped cylinder or cone".format(", ".join(sorted(used))))


def _tidy(value):
    """12 significant digits: removes float noise (2.539999999999999 -> 2.54) far
    below any tolerance. validate.py checks the tidied part, so what is stored is
    what was proven."""
    return 0.0 if value == 0 else float(f"{value:.12g}")


def emit_part(c, name):
    """A Studio native part (centimetres, degrees) from a candidate. No ID: the
    browser assigns fresh IDs when the user commits the import."""
    part = _emit(c, name)
    return {k: _tidy(v) if isinstance(v, float) else v for k, v in part.items()}


def _emit(c, name):
    to_cm = 0.1
    part = {"name": name, "shape": c["shape"],
            "x": c["center"][0] * to_cm, "y": c["center"][1] * to_cm, "z": c["center"][2] * to_cm,
            "rx": 0.0, "ry": 0.0, "rz": 0.0}
    if c["shape"] == "sphere":
        part["r"] = c["r"] * to_cm
    elif c["shape"] == "box":
        part.update(sx=c["sx"] * to_cm, sy=c["sy"] * to_cm, sz=c["sz"] * to_cm)
        part["rx"], part["ry"], part["rz"] = euler_xyz(c["R"])
    elif c["shape"] == "cylinder":
        part.update(r=c["r"] * to_cm, h=c["h"] * to_cm)
        u = c["axis"]
        aligned = [i for i in range(3) if abs(abs(u[i]) - 1) < 1e-12]
        if aligned:  # a cylinder is symmetric end to end: the axis field says it exactly
            part["axis"] = "xyz"[aligned[0]]
        else:
            part["axis"] = "z"
            part["rx"], part["ry"] = _axis_rotation(u)
    elif c["shape"] == "cone":
        part.update(r=c["r"] * to_cm, r2=c["r2"] * to_cm, h=c["h"] * to_cm)
        part["rx"], part["ry"] = _axis_rotation(c["axis"])
    return part
