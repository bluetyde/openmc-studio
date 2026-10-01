"""Real offline runtime acceptance. Run with bundled core Python and a MCNPy claim.

Creates evidence under results/acceptance-<timestamp>; never alters existing work.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from runtime import CAD, CORE, PREFIX, environment, verify


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('package', type=Path)
    p.add_argument('--without-mcnp', action='store_true')
    a = p.parse_args()
    package = a.package.resolve()
    env = environment(package)
    os.environ.update(env)
    sys.path.insert(0, str(package / 'app/studio'))
    verify(package)
    out = package / 'results' / ('acceptance-' + time.strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True)
    import openmc
    material = openmc.Material(name='water')
    material.add_nuclide('H1', 2.0)
    material.add_nuclide('O16', 1.0)
    material.set_density('g/cm3', 1.0)
    sphere = openmc.Sphere(r=10, boundary_type='vacuum')
    model = openmc.Model(geometry=openmc.Geometry([openmc.Cell(fill=material, region=-sphere)]),
                         materials=openmc.Materials([material]))
    model.settings.run_mode = 'fixed source'
    model.settings.source = openmc.IndependentSource(space=openmc.stats.Point((0, 0, 0)))
    model.settings.batches = 2
    model.settings.particles = 100
    model.export_to_model_xml(out / 'model.xml')
    with (out / 'transport.log').open('w') as log:
        subprocess.run([str(CORE / 'bin/openmc'), '-s', '2'], cwd=out, env=env,
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
    with openmc.StatePoint(out / 'statepoint.2.h5') as state:
        if state.n_particles != 100:
            raise ValueError('Transport statepoint does not match the test model')
    from openmc_studio.cad.jobs import CadJobs, TERMINAL
    manager = CadJobs(out / 'cad', python=str(CAD / 'bin/python'))
    try:
        job = manager.submit(b'', '', mode='probe')
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            state = manager.get(job['id'])
            if state['state'] in TERMINAL:
                break
            time.sleep(0.2)
        if state['state'] != 'succeeded' or not manager.capabilities()['engine_verified']:
            raise ValueError(f'CAD probe failed: {state}')
    finally:
        manager.close()
    report = {'transport': 'passed', 'cad_real_conversion': 'passed', 'mcnp_export': 'not requested'}
    if not a.without_mcnp:
        with (out / 'export.log').open('w') as log:
            subprocess.run([str(CORE / 'bin/python'), str(PREFIX / 'exporter/src/export_mcnp.py'),
                            str(out / 'model.xml'), '--out-dir', str(out), '--name', 'model'],
                           env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
        if not (out / 'model_runnable.mcnp').is_file():
            raise ValueError('Exporter produced no deck')
        report['mcnp_export'] = 'passed'
    (out / 'acceptance.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), out)


if __name__ == '__main__':
    main()
