"""Generate fixtures first; set OPENMC_MCNP_PROJECT. Requires exclusive MCNPy use."""
import contextlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import sys
import tempfile
from urllib.parse import unquote

sys.path.insert(0, str(Path(os.environ['OPENMC_MCNP_PROJECT']) / 'src'))
import openmc
from export_mcnp import translate
from remediate_deck import remediate
from validate_deck import validate_deck


def read_ids(deck):
    parts = {}
    for kind, number, index, total, chunk in re.findall(
            r'^c @studio-v1 (\w+) (\w+) (\d+)/(\d+) (\S+)$', deck, re.M):
        parts.setdefault((kind, number), {})[int(index)] = chunk
    return {key: json.loads(unquote(''.join(chunks[i] for i in sorted(chunks)))) for key, chunks in parts.items()}


root = Path(__file__).parent / 'generated'
for name in ('detectors', 'current_box', 'rect_tally', 'hex_tally', 'graphite_pile'):
    with tempfile.TemporaryDirectory(prefix='studio_ids_') as folder:
        openmc.reset_auto_ids()
        ns = runpy.run_path(str(root / f'{name}_mcnp.py'), run_name='test_export')
        model, ids = ns['model'], ns['studio_ids']
        for tally in model.tallies:
            tally.name = 'Same repeated label'
        base, output = Path(folder) / 'raw.mcnp', Path(folder) / 'ready.mcnp'
        with contextlib.redirect_stdout(io.StringIO()):
            translate(model, str(base))
            remediate(str(base), model, str(output), detector_responses=ns.get('detector_responses'), studio_ids=ids)
            assert validate_deck(str(output),model=model,geometry_samples=3000), name
        deck = output.read_text()
        records = read_ids(deck)
        assert records and all(len(line) <= 128 for line in deck.splitlines()), name
        expected = {r['id'] for r in ids['tally'].values()}
        actual = {r['id'] for (kind, _), r in records.items() if kind == 'tally'}
        assert actual == expected, (name,actual,expected)
        for head in re.findall(r'^(?:F|FMESH)(\d+):N',deck,re.M):
            assert ('tally',head) in records, (name,head)
        if 'tally' in name or name == 'graphite_pile':
            for group in ids['lattice'].values():
                assert any(kind == 'surface' and r['id'] == group['id'] for (kind,_),r in records.items()), name
        # Reusing translated geometry must still use the new request's stable IDs.
        for r in ids['tally'].values():
            r['id'] += '-changed'
        with contextlib.redirect_stdout(io.StringIO()):
            remediate(str(base),model,str(output),detector_responses=ns.get('detector_responses'),studio_ids=ids)
        assert all(r['id'].endswith('-changed') for (kind,_),r in read_ids(output.read_text()).items() if kind == 'tally')
        print(f'PASS {name}: validated stable cell/surface/tally IDs, duplicate labels and reused translation',flush=True)
