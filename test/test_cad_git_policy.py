"""Check that CAD runtime artifacts stay ignored and public fixtures can be tracked."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CadGitPolicy(unittest.TestCase):
    def test_paths(self):
        ignored = [".cad-env/bin/python", ".cad-runtime/lib/FreeCAD.so",
                   ".cad-cache/job/report.json", "cad-work/source.step",
                   "setup/cad/local.json", "private/design.FCStd", "private/design.iges",
                   "private/design.brep", "private/mesh.h5m", "test/generated/cad/shape.step"]
        tracked = ["setup/cad/environment.yml", "setup/cad/locks/linux-64.explicit.txt",
                   "test/fixtures/cad/public.step", "test/fixtures/cad/public.iges",
                   "test/fixtures/cad/public.brep", "test/fixtures/cad/public.FCStd",
                   "test/fixtures/cad/expected/reference/geometry.xml"]
        for path in ignored + tracked:
            with self.subTest(path=path):
                result = subprocess.run(
                    ["git", "-c", f"safe.directory={ROOT.as_posix()}", "check-ignore",
                     "--no-index", "-q", path], cwd=ROOT, capture_output=True)
                self.assertIn(result.returncode, (0, 1), result.stderr.decode())
                self.assertEqual(result.returncode == 0, path in ignored)


if __name__ == "__main__":
    unittest.main()
