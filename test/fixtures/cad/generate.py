"""Author-owned analytical fixtures in millimeters; no company CAD data."""
import math


def make_fixture(name):
    import FreeCAD as App
    import Part

    if name.startswith("drilled_block"):
        shape = Part.makeBox(40, 30, 20, App.Vector(-20, -15, -10)).cut(
            Part.makeCylinder(5, 22, App.Vector(0, 0, -11)))
        volume = (40 * 30 - math.pi * 5**2) * 20
        solid_points = [(10, 0, 0), (-10, 0, 0)]
    elif name.startswith("annular_cylinder"):
        shape = Part.makeCylinder(12, 30, App.Vector(0, 0, -15)).cut(
            Part.makeCylinder(7, 32, App.Vector(0, 0, -16)))
        volume = math.pi * (12**2 - 7**2) * 30
        solid_points = [(9, 0, 0), (-9, 0, 0)]
    else:
        raise ValueError(name)
    transform = App.Placement()
    if name.endswith("_rotated"):
        transform = App.Placement(App.Vector(37, -23, 51), App.Rotation(App.Vector(1, 2, 3), 37))
        shape.Placement = transform
    hole_points = [(0, 0, 0), (0, 0, 4), (0, 0, -4)]
    probes = [(tuple(transform.multVec(App.Vector(*p))), inside)
              for points, inside in ((solid_points, True), (hole_points, False)) for p in points]
    return shape, volume, probes
