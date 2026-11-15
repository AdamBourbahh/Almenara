"""Area-weighted union of qualified FireMask cells over measured terrestrial area.

This is a sampled cell support proxy, not a pixel-exact clear-land fraction.
Legacy packed masks retain a conservative 95% valid-sample qualification per cell.
Annual land/water fractions use the preceding year's measured pixels only.
"""
from pathlib import Path
import json
from functools import lru_cache
import duckdb
import h3.api.basic_int as h3
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


@lru_cache(maxsize=4)
def _revision(root,mask_stamp,land_stamp):
    root = Path(root)
    paths = list((root/'data/processed/observation_coverage').glob('*.parquet'))
    paths += list((root/'data/cache/land_cover').glob('*.parquet'))
    return str((len(paths),max((p.stat().st_mtime_ns for p in paths),default=0)))


def revision(root):
    root = Path(root)
    mask,land = root/'data/processed/observation_coverage',root/'data/cache/land_cover'
    return _revision(str(root),mask.stat().st_mtime_ns if mask.exists() else 0,
                     land.stat().st_mtime_ns if land.exists() else 0)


def fractions(root, cells, first, last):
    root = Path(root)
    cells = np.array(sorted(cells), dtype=np.uint64)
    days = np.arange(first, last + 1)
    years = (np.datetime64('1970-01-01') + days.astype('timedelta64[D]')).astype('datetime64[Y]').astype(int)+1970
    result = np.full(len(days), np.nan)
    shards = root/'data/cache/land_cover'
    if not list(shards.glob('*.parquet')) or not len(cells):
        return result
    registry = json.loads((root/'data/regions.json').read_text(encoding='utf-8'))
    centers = np.array([h3.cell_to_latlng(int(c)) for c in cells])
    regions = [key for key,r in registry.items() if r['bounds'][0] <= centers[:,1].max()
               and r['bounds'][2] >= centers[:,1].min() and r['bounds'][1] <= centers[:,0].max()
               and r['bounds'][3] >= centers[:,0].min()]
    groups = {}
    for region in regions:
        for path in (root/'data/processed/observation_coverage').glob(region+'_*.parquet'):
            meta = pq.read_schema(path).metadata or {}
            if meta.get(b'encoding') != b'packed-v1':
                continue
            dates = json.loads(meta[b'days'])
            if max(dates) < first or min(dates) > last:
                continue
            period = meta[b'granule'].decode().split('.')[1]
            groups.setdefault((meta[b'satellite'],period),[]).append((path,dates))
    area = np.array([h3.cell_area(int(c),unit='km^2') for c in cells])
    mappings = {}
    with duckdb.connect(config={'threads':1,'memory_limit':'512MB'}) as con:
        con.register('selected',pa.table({'h3_r7':cells}))
        for year in np.unique(years):
            land = np.ones(len(cells))
            known_land = np.zeros(len(cells),dtype=bool)
            rows = con.execute('SELECT h3_r7, sum(class_counts[18])::DOUBLE/sum(sampled_pixels), '
                'sum(list_sum(class_counts))::DOUBLE/sum(sampled_pixels) FROM read_parquet(?) '
                'SEMI JOIN selected USING(h3_r7) WHERE year=? GROUP BY h3_r7',
                [str(shards/'*.parquet'),int(year)-1]).fetchall()
            for cell, water, known in rows:
                if known >= .95:
                    index = np.searchsorted(cells,cell)
                    land[index] = 1-water
                    known_land[index] = True
            # Unknown land/water area remains potential unobserved land; it can
            # never increase coverage by disappearing from the denominator.
            if not known_land.any() or np.dot(area,land) <= 0:
                continue
            selected_days = days[years==year]
            union = np.zeros((len(selected_days),len(cells)),dtype=bool)
            for paths in groups.values():
                relevant = sorted({d for _,dates in paths for d in dates if selected_days[0] <= d <= selected_days[-1]})
                if not relevant:
                    continue
                clear = np.ones((len(relevant),len(cells)),dtype=bool)
                covered = np.zeros(len(cells),dtype=bool)
                for path,dates in paths:
                    row = pq.read_table(path).to_pylist()[0]
                    source = np.frombuffer(row['cells'],dtype=np.uint64)
                    key = row['cells']
                    if key not in mappings:
                        destination = np.searchsorted(cells,source)
                        valid = destination < len(cells)
                        valid[valid] &= cells[destination[valid]] == source[valid]
                        mappings[key] = (destination[valid],np.flatnonzero(valid))
                    destination,source_index = mappings[key]
                    covered[destination] = True
                    flags = np.unpackbits(np.frombuffer(row['clear_bits'],dtype=np.uint8).reshape(len(dates),-1),axis=1,count=len(source))
                    for k,day in enumerate(relevant):
                        clear[k,destination] &= flags[dates.index(day),source_index].astype(bool) if day in dates else False
                for k,day in enumerate(relevant):
                    union[day-selected_days[0]] |= clear[k] & covered & known_land
            result[years==year] = union @ (area*land) / np.dot(area,land)
    return result


def load(root,cells,days):
    """Only consume published matching indexes; arbitrary AOIs stay unavailable."""
    for path in (Path(root)/'data/processed/observation_coverage').glob('land_*.npz'):
        with np.load(path,allow_pickle=False) as data:
            if 'revision' not in data.files or str(data['revision']) != revision(root):
                continue
            if np.array_equal(data['cells'],np.array(sorted(cells),dtype=np.uint64)):
                idx = np.asarray(days,dtype=int)-int(data['first'])
                result = np.full(len(idx),np.nan)
                keep = (idx>=0)&(idx<len(data['fraction']))
                result[keep] = data['fraction'][idx[keep]]
                return result
    return np.full(len(days),np.nan)
