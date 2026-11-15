"""Acquire free published EOG upstream flare-site evidence for the study regions.

Zhizhin et al. (2026), MYC25Q4 v1.0, doi:10.5281/zenodo.23091822.
CC BY-NC 4.0. This catalogue excludes refinery/LNG flares. An empty regional
subset establishes no upstream catalogue matches, not absence of industrial heat.
"""
import csv
import hashlib
import io
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
RECORD = 'https://zenodo.org/api/records/23091822'


def acquire():
    registry = json.loads((ROOT / 'data/regions.json').read_text(encoding='utf-8'))
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        response = client.get(RECORD)
        response.raise_for_status()
        file = next(f for f in response.json()['files'] if f['key'] == 'annual_flare_site_records.csv')
        response = client.get(file['links']['self'])
        response.raise_for_status()
    algorithm, expected = file['checksum'].split(':', 1)
    if hashlib.new(algorithm, response.content).hexdigest() != expected:
        raise ValueError('Published flare catalogue checksum mismatch.')
    rows = []
    for row in csv.DictReader(io.StringIO(response.text)):
        lat, lon = float(row['lat']), float(row['lon'])
        regions = [key for key, config in registry.items()
                   if config['bounds'][0] <= lon <= config['bounds'][2]
                   and config['bounds'][1] <= lat <= config['bounds'][3]]
        if regions and float(row.get('n_det') or 0) > 0:
            rows.append(dict(year=int(row['year']), latitude=lat, longitude=lon,
                site_id=row['flare_id'], region=regions[0]))
    output = ROOT / 'data/lookup/flare_reference.csv'
    temporary = output.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['year', 'latitude', 'longitude', 'site_id', 'region'])
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(output)
    output.with_suffix('.provenance.json').write_text(json.dumps({
        'doi': '10.5281/zenodo.23091822', 'license': 'CC BY-NC 4.0', 'checksum': file['checksum'],
        'scope': 'Documented upstream flare sites only; refinery/LNG sites excluded',
        'regional_site_years': len(rows)}, indent=2), encoding='utf-8')
    print(f'Published {len(rows)} documented regional upstream flare site-years.')


if __name__ == '__main__':
    acquire()
