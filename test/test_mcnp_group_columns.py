"""Needs the companion exporter: OPENMC_MCNP_PROJECT (or its src directory on PYTHONPATH)."""
import os
import pathlib
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "studio"))
if os.environ.get("OPENMC_MCNP_PROJECT"):
    sys.path.insert(0, str(pathlib.Path(os.environ["OPENMC_MCNP_PROJECT"]) / "src"))
from openmc_studio.mcnp_worker import add_group_comments
from deck_format import overlong_lines


class GroupColumnsTest(unittest.TestCase):
    def test_long_nested_group_labels_preserve_deck(self):
        deck = "Title\n1 0 -1 imp:n=1\n\n1 so 10\n\nmode n\nnps 100\n"
        groups = {"Assembly " * 40: {"cells": [SimpleNamespace(id=1)],
                  "groups": {"Nested " * 40: [SimpleNamespace(id=2)]}}}
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "model.mcnp"
            path.write_text(deck)
            add_group_comments(path, groups)
            result = path.read_text()
        self.assertEqual(overlong_lines(result), [])
        self.assertEqual("\n".join(line for line in result.split("\n")
                                   if not line.startswith("c ")), deck)
        self.assertIn("Assembly", result)
        self.assertIn("Nested", result)


if __name__ == "__main__":
    unittest.main()
