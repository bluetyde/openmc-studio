"""Record the exact installed runtime and preserve conda source recipes/licenses."""
import json
from pathlib import Path
import shutil


def main():
    base = Path('/opt/openmc/conda')
    notices = Path('/opt/openmc/notices')
    records = []
    for meta in sorted((base / 'conda-meta').glob('*.json')):
        r = json.loads(meta.read_text())
        records.append({k: r.get(k) for k in ('name', 'version', 'build', 'url', 'sha256', 'license')})
        info = base / 'pkgs' / meta.stem / 'info'
        dest = notices / 'miniforge' / meta.stem
        dest.mkdir(parents=True, exist_ok=True)
        for name in ('licenses', 'recipe', 'about.json'):
            source = info / name
            if source.is_dir():
                shutil.copytree(source, dest / name, dirs_exist_ok=True)
            elif source.is_file():
                shutil.copyfile(source, dest / name)
    (notices / 'miniforge.json').write_text(json.dumps(records, indent=2) + '\n')
    # Ubuntu ships copyright/license/source references alongside its binaries.
    shutil.copytree('/usr/share/doc', notices / 'ubuntu', dirs_exist_ok=True, ignore_dangling_symlinks=True)
    shutil.copytree('/usr/share/common-licenses', notices / 'common-licenses', dirs_exist_ok=True)
    shutil.copyfile('/var/lib/dpkg/status', notices / 'ubuntu-packages.txt')
    for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
        shutil.copyfile(Path('/opt/openmc/exporter') / name, notices / ('exporter-' + name))
    print('Runtime license inventory saved:', len(records), 'Miniforge packages')


if __name__ == '__main__':
    main()
