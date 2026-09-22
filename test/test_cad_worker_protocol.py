"""CAD integrity: reject approximate imports and validate exact export requests."""
import math
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'studio'))
from openmc_studio import cad_worker as cad
from openmc_studio.server import CadWorker, Studio


class Shape:
    def __init__(self, kind, dims):
        self.kind, self.dims, self.ops = kind, dims, []
    def translate(self, v): self.ops.append(('translate', v))
    def rotate(self, origin, axis, angle): self.ops.append(('rotate', axis, angle))
    def isNull(self): return False
    def isValid(self): return True


class TestCadIntegrity(unittest.TestCase):
    def test_import_never_fabricates_solids_even_with_geouned(self):
        with patch.object(cad, 'probe_environment', return_value={'freecad':'yes', 'geouned':'yes'}):
            result = cad.run_cad_to_csg(1, 'anything.step', {}, time.time())
        self.assertFalse(result['ok'])
        self.assertNotIn('parts', result)
        with self.assertRaises(ValueError): cad.parse_step_analytical('anything.step')
        with self.assertRaises(ValueError): cad.export_step_analytical([], 'anything.step')

    def test_units_and_oriented_cylinder(self):
        fc = SimpleNamespace(Vector=lambda *xyz: xyz)
        part = SimpleNamespace(makeCylinder=lambda *d: Shape('cylinder', d))
        s = cad.make_cad_solid(dict(shape='cylinder', r=1, h=7, axis='x',
                                    x=2, y=3, z=4, rx=30, ry=20, rz=10), fc, part)
        self.assertEqual(s.dims, (10, 70))  # cm -> mm, radius and height.
        self.assertEqual(s.ops[0], ('translate', (0, 0, -35)))
        self.assertEqual(s.ops[1], ('rotate', (0, 1, 0), 90))
        self.assertEqual(s.ops[2:5], [('rotate',(1,0,0),30), ('rotate',(0,1,0),20), ('rotate',(0,0,1),10)])
        self.assertEqual(s.ops[-1], ('translate', (20,30,40)))

    def test_dimensions_reject_unsupported_and_invalid_before_export(self):
        for shape in ('wedge', 'hex_prism', 'ellipsoid', 'unknown'):
            with self.assertRaises(ValueError): cad.part_dimensions({'shape':shape})
        for r in (-1, math.nan, math.inf, 0):
            with self.assertRaises(ValueError): cad.part_dimensions({'shape':'sphere', 'r':r})
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'bad.step'
            with patch.object(cad, 'probe_environment', return_value={'can_export':False}):
                result = cad.run_csg_to_cad(1, {'parts':[{'shape':'sphere','r':1}]}, out, {'units':'mm'}, time.time())
                self.assertFalse(result['ok'])
                self.assertIn('FreeCAD', result['error'])
            self.assertFalse(out.exists())
            result = cad.run_csg_to_cad(1, {'parts':[{'shape':'sphere','r':1}]}, out, {'units':'cm'}, time.time())
            self.assertFalse(result['ok'])
            self.assertIn('millimeters', result['error'])

    def test_protocol_reports_limitations(self):
        with tempfile.TemporaryDirectory() as temp:
            worker = CadWorker(temp)
            try:
                status = worker.get_status()
                self.assertTrue(status['ready'])
                self.assertFalse(status['env']['can_import'])
                self.assertEqual(status['env']['supported_inputs'], [])
                src = Path(temp) / 'unsupported.step'
                src.write_text('ISO-10303-21;')
                self.assertFalse(worker.cad_to_csg(src)['ok'])
                self.assertFalse(worker.csg_to_cad({'parts':[{'shape':'wedge'}]}, Path(temp)/'out.step', {'units':'mm'})['ok'])
            finally:
                worker.stop()

    def test_server_rejects_import_without_writing_upload(self):
        with tempfile.TemporaryDirectory() as temp:
            studio = Studio(Path(temp), token='test', port=8768)
            self.assertFalse(studio.cad_to_csg(b'bad', '../../escape.step')['ok'])
            self.assertFalse((Path(temp)/'_cad_work').exists())

    @unittest.skipUnless(cad.probe_environment()['can_export'], 'FreeCAD is not installed in this Python')
    def test_real_freecad_step_bounds_and_volume(self):
        import Part
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'real.step'
            p = dict(shape='cylinder', r=1, h=7, axis='x', x=2, y=3, z=4)
            result = cad.run_csg_to_cad(1, {'parts':[p]}, out, {'units':'mm'}, time.time())
            self.assertTrue(result['ok'], result)
            shape = Part.read(str(out))
            self.assertAlmostEqual(shape.Volume, math.pi*10**2*70, places=4)
            self.assertAlmostEqual(shape.BoundBox.XLength, 70, places=5)
            self.assertAlmostEqual(shape.BoundBox.XMin, -15, places=5)


if __name__ == '__main__': unittest.main()
