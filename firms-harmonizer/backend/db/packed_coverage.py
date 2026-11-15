"""Compact daily mask evidence, with bounded memory per eight-day granule group."""
from functools import lru_cache
import json

import h3.api.basic_int as h3i
import numpy as np
import pyarrow.parquet as pq


@lru_cache(maxsize=4)
def read_selected(root, revision, cells, first, last, allow_preset=True):
    from pathlib import Path
    root = Path(root)
    folder = root / 'data/processed/observation_coverage'
    selected = np.array(cells, dtype=np.uint64)
    if allow_preset:
        for path in folder.glob('preset_*.npz'):
            if '.tmp.' in path.name:
                continue
            with np.load(path, allow_pickle=False) as index:
                if not np.array_equal(index['cells'], selected):
                    continue
                zero, complete = np.zeros(last - first + 1, dtype=np.int64), np.zeros(last - first + 1, dtype=np.int64)
                origin = int(index['first'])
                lo, hi = max(first, origin), min(last + 1, origin + len(index['zero_codes']))
                if hi > lo:
                    zero[lo - first:hi - first] = index['zero_codes'][lo - origin:hi - origin]
                    complete[lo - first:hi - first] = index['complete_codes'][lo - origin:hi - origin]
                zero.setflags(write=False)
                complete.setflags(write=False)
                return zero, complete
    registry = json.loads((root / 'data/regions.json').read_text(encoding='utf-8'))
    latlon = np.array([h3i.cell_to_latlng(c) for c in cells])
    lo, hi = latlon.min(axis=0), latlon.max(axis=0)
    regions = [key for key, r in registry.items() if
               r['bounds'][0] <= hi[1] and r['bounds'][2] >= lo[1]
               and r['bounds'][1] <= hi[0] and r['bounds'][3] >= lo[0]]
    groups = {}
    for region in regions:
        for path in folder.glob(region + '_*.parquet'):
            metadata = pq.read_schema(path).metadata or {}
            if metadata.get(b'encoding') != b'packed-v1':
                continue
            days = tuple(json.loads(metadata[b'days']))
            if max(days) < first or min(days) > last:
                continue
            # Tiles can omit different dates during an outage. Group by the
            # nominal composite, then align actual dates; missing tile-days stay
            # unknown instead of borrowing another tile's observation support.
            period = metadata.get(b'granule', b'').decode().split('.')
            period = period[1] if len(period) > 1 else str(min(days))
            groups.setdefault((metadata[b'satellite'].decode(), period), []).append((path, days))
    codes = np.zeros(last - first + 1, dtype=np.int64)
    complete_codes = codes.copy()
    bits = {'Terra': 1, 'Aqua': 2, 'SNPP': 4, 'NOAA-20': 8, 'NOAA-21': 16}
    for (satellite, _), paths in groups.items():
        days = sorted({day for _, dates in paths for day in dates})
        clear = np.ones((len(days), len(cells)), dtype=bool)
        covered = np.zeros_like(clear)
        fire = np.zeros_like(clear)
        for path, source_days in paths:
            row = pq.read_table(path).to_pylist()[0]
            source = np.frombuffer(row['cells'], dtype=np.uint64)
            index = np.searchsorted(source, selected)
            keep = index < len(source)
            keep[keep] &= source[index[keep]] == selected[keep]
            if not keep.any():
                continue
            width = (len(source) + 7) // 8
            covered[:, keep] = True
            for field, target in [('clear_bits', clear), ('fire_bits', fire)]:
                packed = np.frombuffer(row[field], dtype=np.uint8).reshape(len(source_days), width)
                flags = np.unpackbits(packed, axis=1, count=len(source))
                for day_index, day in enumerate(days):
                    values = (flags[source_days.index(day), index[keep]].astype(bool)
                              if day in source_days else np.zeros(int(keep.sum()), dtype=bool))
                    if field == 'clear_bits':
                        target[day_index, keep] &= values
                    else:
                        target[day_index, keep] |= values
        for d, epoch in enumerate(days):
            if first <= epoch <= last and (clear[d] & covered[d]).all():
                complete_codes[epoch - first] |= bits[satellite]
                if not fire[d].any():
                    codes[epoch - first] |= bits[satellite]
    codes.setflags(write=False)
    complete_codes.setflags(write=False)
    return codes, complete_codes


def publish_preset(root, region, start, end):
    """Publish a tiny immutable daily index for the exact registered AOI."""
    from datetime import date
    registry = json.loads((root / 'data/regions.json').read_text(encoding='utf-8'))
    intervals = registry[region].get('coverage', [])
    if intervals:
        start = min(start, min(date.fromisoformat(first) for first, _ in intervals))
        end = max(end, max(date.fromisoformat(last) for _, last in intervals))
    w, s, e, n = registry[region]['bounds']
    polygon = h3i.LatLngPoly([(s, w), (s, e), (n, e), (n, w)])
    cells = tuple(sorted(h3i.polygon_to_cells(polygon, 7)))
    folder = root / 'data/processed/observation_coverage'
    first, last = (start - date(1970, 1, 1)).days, (end - date(1970, 1, 1)).days
    zero, complete = read_selected(str(root), folder.stat().st_mtime_ns, cells, first, last, False)
    path = folder / ('preset_' + region + '.npz')
    temporary = path.with_suffix('.tmp')
    with temporary.open('wb') as stream:
        np.savez_compressed(stream, cells=np.array(cells, dtype=np.uint64), first=first,
                            zero_codes=zero, complete_codes=complete)
    temporary.replace(path)
