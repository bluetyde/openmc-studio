#!/bin/bash
# Run only inside a newly imported Ubuntu Base build distribution, never a personal distro.
set -euo pipefail
inputs="${1:?absolute build-input directory}"
runtime_id="${2:?runtime version id}"
[[ "$runtime_id" =~ ^[a-z0-9-]{1,48}$ ]] || exit 2
[[ -x /opt/openmc/conda/bin/conda ]] || { echo 'Install pinned Miniforge first'; exit 2; }
[[ ! -e /opt/openmc/runtime-id && ! -e /build ]] || { echo 'Build must start clean'; exit 2; }
ln -s "$inputs" /build
export CONDA_NO_PLUGINS=true CONDA_SOLVER=classic
/opt/openmc/conda/bin/python - "$(dirname "$0")/locks/wheels.json" <<'PY'
import hashlib, json, pathlib, sys
records = json.loads(pathlib.Path(sys.argv[1]).read_text())
expected = {r['filename'] for r in records}
actual = {p.name for p in pathlib.Path('/build/wheels').glob('*.whl')}
if actual != expected:
    raise SystemExit('Wheel inputs do not match the pinned inventory')
for r in records:
    p = pathlib.Path('/build/wheels') / r['filename']
    if hashlib.sha256(p.read_bytes()).hexdigest() != r['sha256']:
        raise SystemExit('Wheel checksum mismatch: ' + p.name)
PY
for name in openmc-mcnp openmc-cad; do
    /opt/openmc/conda/bin/conda create -y --offline --copy -p "/opt/openmc/conda/envs/$name" --file "/build/$name.explicit.txt"
done
/opt/openmc/conda/envs/openmc-mcnp/bin/python -m pip install --no-index --no-deps /build/wheels/*.whl
mkdir -p /opt/openmc/exporter /opt/openmc/notices /home/studio
tar -xf /build/exporter.tar -C /opt/openmc/exporter
cp -a /build/notices/. /opt/openmc/notices/
cp /build/exporter-revision.txt /opt/openmc/exporter-revision.txt
cp /build/*.explicit.txt /opt/openmc/notices/
printf '%s\n' "$runtime_id" > /opt/openmc/runtime-id
# Explicit launcher activation; never inherit Windows executable lookup or shell profiles.
printf '[interop]\nappendWindowsPath=false\n[automount]\nenabled=true\n[user]\ndefault=root\n' > /etc/wsl.conf
printf 'channels:\n  - conda-forge\ndefault_channels: []\n' > /opt/openmc/conda/.condarc
/opt/openmc/conda/bin/python "$(dirname "$0")/runtime_inventory.py"
/opt/openmc/conda/bin/conda clean --all -y
unlink /build
echo "Runtime $runtime_id built. Run the verifier before exporting."
