"""Pinned, single-solid STEP-to-XML spike. Run only in a disposable process.

This is not the Studio import API: assembly mapping, jobs and the bounded Studio
CSG schema are later gates. No generated Python is requested or executed.
"""
from importlib.metadata import version
from pathlib import Path
import hashlib
import platform
import sys


ADAPTER_VERSION = "stage0-1"


def configure_runtime():
    # conda-forge installs the headless FreeCAD modules in the environment's lib.
    library = Path(sys.prefix) / "lib"
    if (library / "FreeCAD.so").is_file() and str(library) not in sys.path:
        sys.path.insert(0, str(library))


def convert_step(source, output, progress=None):
    configure_runtime()
    import FreeCAD
    import Part
    import geouned

    if version("geouned") != "1.6.2":
        raise ValueError("This adapter is validated only against GEOUNED 1.6.2")
    source = Path(source).resolve(strict=True)
    output = Path(output).resolve()
    if source.suffix.lower() not in {".step", ".stp"}:
        raise ValueError("Stage 0 accepts STEP/STP only")
    if source.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("Stage 0 input exceeds 16 MiB")
    output.mkdir(parents=True, exist_ok=False)
    shape = Part.read(str(source))
    if len(shape.Solids) != 1 or not shape.isValid() or not shape.isClosed():
        raise ValueError("Stage 0 requires exactly one valid closed solid")
    supported = {"Plane", "Cylinder", "Cone", "Sphere"}
    surfaces = sorted({type(face.Surface).__name__ for face in shape.Faces})
    if set(surfaces) - supported:
        raise ValueError(f"Unsupported surfaces: {surfaces}")
    settings = geouned.Settings(voidGen=False, compSolids=False, outPath=str(output))
    converter = geouned.CadToCsg(settings=settings)
    if progress:
        progress("reading STEP")
    converter.load_step_file(filename=str(source), spline_surfaces="stop")
    if len(converter.meta_list) != 1:
        raise ValueError("GEOUNED did not retain the single source solid")
    if progress:
        progress("decomposing solids")
    converter.start()
    if progress:
        progress("writing OpenMC XML")
    converter.export_csg(geometryName=str(output / "geometry"), outFormat=("openmc_xml",))
    suspicious = [p for p in output.rglob("*")
                  if p.is_file() and any("suspicious" in part.lower() for part in p.relative_to(output).parts)]
    if suspicious:
        raise ValueError("GEOUNED reported suspicious geometry")
    xml = output / "geometry.xml"
    if not xml.is_file() or xml.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Missing or oversized OpenMC XML")
    bounds = shape.BoundBox
    return {
        "adapter": ADAPTER_VERSION,
        "versions": {"python": platform.python_version(), "platform": platform.platform(),
                     "freecad": ".".join(FreeCAD.Version()[:3]),
                     "occt": Part.OCC_VERSION, "geouned": version("geouned"),
                     "openmc": version("openmc")},
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_units": "mm", "xml_units": "cm", "source_solids": 1,
        "surface_types": surfaces, "volume_cm3": shape.Volume / 1000,
        "bounds_cm": [getattr(bounds, key) / 10 for key in
                      ("XMin", "YMin", "ZMin", "XMax", "YMax", "ZMax")],
        "xml": str(xml), "xml_sha256": hashlib.sha256(xml.read_bytes()).hexdigest(),
        "can_import_into_studio": False,
    }
