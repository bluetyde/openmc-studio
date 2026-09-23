"""Real-engine rejection tests. Run explicitly with the pinned CAD Python."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "studio"))
from openmc_studio.cad.geouned_adapter import configure_runtime
configure_runtime()
import FreeCAD  # Initialize the kernel before loading Part.
import Part
# FreeCAD clears names in __main__; load the test's dependencies afterward.
from pathlib import Path
from openmc_studio.cad.geouned_adapter import convert_step
import tempfile
import unittest


class Rejections(unittest.TestCase):
    def test_invalid_and_unsupported_inputs(self):
        with tempfile.TemporaryDirectory(prefix="studio-cad-rejections-") as scratch:
            root = Path(scratch)
            shapes = {
                "two_solids": Part.makeCompound([Part.makeBox(1, 1, 1), Part.makeSphere(1)]),
                "open_shell": Part.makePlane(10, 10),
                "torus": Part.makeTorus(10, 2),
            }
            for name, shape in shapes.items():
                with self.subTest(name=name):
                    source = root / f"{name}.step"
                    shape.exportStep(str(source))
                    with self.assertRaisesRegex(ValueError, "exactly one valid closed solid|Unsupported surfaces"):
                        convert_step(source, root / name)
            source = root / "wrong.stl"
            source.write_text("not STEP")
            with self.assertRaisesRegex(ValueError, "STEP/STP only"):
                convert_step(source, root / "wrong")
            source = root / "large.step"
            with source.open("wb") as handle:
                handle.truncate(16 * 1024 * 1024 + 1)
            with self.assertRaisesRegex(ValueError, "16 MiB"):
                convert_step(source, root / "large")


if __name__ == "__main__":
    unittest.main()
