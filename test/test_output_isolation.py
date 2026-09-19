"""Run the three simulation tests beside existing files and verify they survive."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class OutputIsolation(unittest.TestCase):
    def test_existing_models_and_results_survive(self):
        scripts = ('test_cylindrical_mesh.py', 'test_ellipsoid_primitive.py', 'test_hex_lattice.py')
        with tempfile.TemporaryDirectory(prefix='studio_existing_files_') as folder:
            root = Path(folder)
            existing = {name: b'existing user data\n' for name in
                        ('model.xml', 'materials.xml', 'statepoint.5.h5', 'other.h5')}
            for name, content in existing.items():
                (root / name).write_bytes(content)
            for script in scripts:
                with self.subTest(script=script):
                    result = subprocess.run([sys.executable, str(Path(__file__).parent / script)],
                                            cwd=root, capture_output=True, text=True, timeout=180)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual({p.name for p in root.iterdir()}, set(existing))
                    for name, content in existing.items():
                        self.assertEqual((root / name).read_bytes(), content)


if __name__ == '__main__':
    unittest.main()
