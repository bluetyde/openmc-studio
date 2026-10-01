"""Maintainer-only: vendor the fonts already used by Studio, with OFL notices."""
import hashlib
import json
from pathlib import Path
import re
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
CSS_URL = ('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600'
           '&family=JetBrains+Mono:wght@400;500&display=swap')


def main():
    target = ROOT / 'studio/openmc_studio/static/fonts'
    target.mkdir(exist_ok=True)
    css = urllib.request.urlopen(CSS_URL, timeout=60).read().decode()
    entries = []
    for family, weight, url in re.findall(
            r"font-family: '([^']+)';.*?font-weight: (\d+);.*?url\((https://fonts.gstatic.com/[^)]+)\)", css, re.S):
        filename = family.lower().replace(' ', '-') + '-' + weight + '.ttf'
        payload = urllib.request.urlopen(url, timeout=60).read()
        (target / filename).write_bytes(payload)
        css = css.replace(url, '/fonts/' + filename)
        entries.append({'filename': filename, 'source': url, 'sha256': hashlib.sha256(payload).hexdigest()})
    if len(entries) != 5 or 'https://' in css:
        raise ValueError('Unexpected upstream font stylesheet; inspect before vendoring')
    (target / 'fonts.css').write_text(css, encoding='utf-8', newline='\n')
    for slug in ('ibmplexsans', 'jetbrainsmono'):
        url = f'https://raw.githubusercontent.com/google/fonts/main/ofl/{slug}/OFL.txt'
        payload = urllib.request.urlopen(url, timeout=60).read()
        (target / (slug + '-OFL.txt')).write_bytes(payload)
        entries.append({'filename': slug + '-OFL.txt', 'source': url,
                        'sha256': hashlib.sha256(payload).hexdigest()})
    (target / 'sources.json').write_text(json.dumps(entries, indent=2) + '\n', encoding='utf-8', newline='\n')


if __name__ == '__main__':
    main()
