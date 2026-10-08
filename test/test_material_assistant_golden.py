"""The golden cases the page's JavaScript port of material_assistant is held to are what the Python module gives today.

If this fails, run test/regen_material_assistant_cases.py, then test/test_material_assistant_page.js to see whether the port still agrees.
Run: python test/test_material_assistant_golden.py
"""
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Golden(unittest.TestCase):
    def test_cases_json_is_what_the_module_gives(self):
        r = subprocess.run([sys.executable, str(ROOT / "test" / "regen_material_assistant_cases.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
