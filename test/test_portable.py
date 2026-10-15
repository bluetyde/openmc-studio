"""Offline package contract tests; no WSL, installed solver or real nuclear data needed."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PORTABLE = Path(__file__).resolve().parents[1] / "setup/portable"
sys.path.insert(0, str(PORTABLE))
from build_package import assemble, record
from runtime import environment, nuclear_files


class PortableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        (self.data / "H1.h5").write_bytes(b"test data")
        self.index('<library path="H1.h5"/>')

    def index(self, body):
        (self.data / "cross_sections.xml").write_text(f"<cross_sections>{body}</cross_sections>")

    def test_complete_relative_data(self):
        self.assertEqual(nuclear_files(self.data), [self.data / "H1.h5"])

    def test_missing_data_fails(self):
        self.index('<library path="absent.h5"/>')
        with self.assertRaisesRegex(ValueError, "Missing"):
            nuclear_files(self.data)

    def test_escape_and_empty_index_fail(self):
        for body in ('<library path="../elsewhere.h5"/>', '', '<directory>/root/data</directory>'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.index(body)
                nuclear_files(self.data)

    def test_runtime_does_not_use_host_paths(self):
        from unittest.mock import patch
        with patch.dict('os.environ', {'PYTHONPATH': '/personal', 'CONDA_PREFIX': '/personal',
                                      'OPENMC_CROSS_SECTIONS': '/personal/data'}):
            env = environment(self.root)
        self.assertNotIn('CONDA_PREFIX', env)
        self.assertNotIn('/personal', json.dumps(env))
        self.assertEqual(env['OPENMC_STUDIO_RUNS'], str(self.root / 'results'))

    def test_manifest_hash_changes_with_file(self):
        file = self.data / "H1.h5"
        old = record(file, self.root)
        file.write_bytes(b"corrupted")
        self.assertNotEqual(old['sha256'], record(file, self.root)['sha256'])

    def test_package_does_not_overwrite_user_folder(self):
        with self.assertRaisesRegex(ValueError, 'already exists'):
            assemble(self.root, self.data, self.root / 'none', self.root, self.root, 'v1')

    def test_packaging_allowlist_and_hashes(self):
        from unittest.mock import patch
        repo = self.root / 'repo'
        (repo / 'setup/portable').mkdir(parents=True)
        (repo / 'studio').mkdir()
        (repo / 'studio/server.py').write_text('print("test")\n')
        (repo / '.env').write_text('PRIVATE_SECRET=yes')
        for name in ('Start Studio.cmd', 'Start-Studio.ps1', 'USER-README.txt', 'VERIFICATION.md'):
            (repo / 'setup/portable' / name).write_text('test\n')
        notices = self.root / 'notices'
        notices.mkdir()
        (notices / 'LICENSE').write_text('test license')
        archive = self.root / 'runtime.tar'
        archive.write_bytes(b'fake runtime' * 1024)
        output = self.root / 'delivery'
        def git(args, **kwargs):
            if 'rev-parse' in args:
                return 'a' * 40
            if '--others' in args:
                return ''
            return 'studio/server.py\0.env\0setup/portable/Start-Studio.ps1\0'
        with patch('subprocess.check_output', side_effect=git):
            assemble(repo, self.data, archive, notices, output, 'v1')
        self.assertFalse((output / 'app/.env').exists())
        self.assertFalse((output / 'app/.git').exists())
        manifest = json.loads((output / 'manifest.json').read_text())
        for item in manifest['files']:
            self.assertEqual(item, record(output / item['path'], output))
        self.assertTrue((output / 'results').is_dir())


if __name__ == '__main__':
    unittest.main()
