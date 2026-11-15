"""Download annual MCD12Q1 land classes for the four study regions (free Earthdata)."""
import argparse
from datetime import date
from importlib import import_module
import json
from pathlib import Path
import re
import tempfile

import h3
import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

coverage = import_module('09_fetch_observation_coverage')
ROOT = coverage.ROOT


def summarize(data, granule_id, bounds):
    match = re.search(r'\.A(\d{4})\d{3}\.h(\d{2})v(\d{2})\.', granule_id)
    if not match or np.asarray(data).ndim != 2:
        raise ValueError('Expected a tiled annual MCD12Q1 LC_Type1 image.')
    year, horizontal, vertical = map(int, match.groups())
    height, width = data.shape
    positions, cells, groups, _ = coverage.pixel_groups(horizontal, vertical, height, width,
                                                      height, width, (0,0), tuple(bounds))
    values = data.ravel()[positions].astype(int)
    valid = (values >= 1) & (values <= 17)
    counts = np.bincount(groups[valid] * 18 + values[valid], minlength=len(cells)*18).reshape(-1,18)
    sampled = np.bincount(groups, minlength=len(cells))
    return [dict(h3_r7=int(cell), year=year, igbp_biome=int(row.argmax()),
                 dominant_fraction=float(row.max() / max(total,1)), class_counts=row.tolist(),
                 sampled_pixels=int(total))
            for cell, row, total in zip(cells,counts,sampled) if row.sum() > 0]


def acquire(start_year, end_year):
    import earthaccess
    auth = earthaccess.login(strategy='environment', persist=False)
    if not auth.authenticated:
        raise RuntimeError('Configure free Earthdata credentials locally.')
    registry = json.loads((ROOT / 'data/regions.json').read_text(encoding='utf-8'))
    shards = ROOT / 'data/cache/land_cover'
    shards.mkdir(parents=True, exist_ok=True)
    for region, config in registry.items():
        for year in range(start_year, end_year + 1):
            output = shards / f'{region}_{year}.parquet'
            if output.exists():
                continue
            granules = earthaccess.search_data(short_name='MCD12Q1', version='061',
                bounding_box=tuple(config['bounds']), temporal=(f'{year}-01-01', f'{year}-12-31'))
            if not granules:
                print(f'{region} {year}: unavailable, not substituted', flush=True)
                continue
            rows = []
            for granule in granules:
                gid = granule['umm']['DataGranule']['Identifiers'][0]['Identifier']
                with tempfile.TemporaryDirectory(dir=shards) as cache:
                    files = earthaccess.download([granule], local_path=cache, threads=1)
                    if len(files) != 1:
                        raise RuntimeError(f'Incomplete land-cover download: {gid}')
                    rows.extend(summarize(coverage.read_mask(Path(files[0]), 'LC_Type1'), gid, config['bounds']))
            table = pa.Table.from_pylist(rows)
            temporary = output.with_suffix('.tmp')
            pq.write_table(table, temporary, compression='zstd')
            temporary.replace(output)
            print(f'{region} {year}: {len(rows):,} measured cell/tile classes', flush=True)
    if not list(shards.glob('*.parquet')):
        raise RuntimeError('No measured annual land cover available.')
    consolidate(shards)


def consolidate(shards):
    # Aggregate tile-edge counts with bounded SQL memory instead of constructing
    # millions of Python dictionaries containing eighteen-element lists.
    sums = ', '.join('sum(class_counts['+str(i+1)+']) AS c'+str(i) for i in range(18))
    counts = ', '.join('c'+str(i) for i in range(18))
    sql = ('WITH totals AS (SELECT h3_r7, year, '+sums+', sum(sampled_pixels) AS sampled '
           'FROM read_parquet(?) GROUP BY h3_r7,year), modes AS (SELECT h3_r7,year, '
           'list_value('+counts+') AS counts, sampled FROM totals) '
           'SELECT h3_r7,year,(list_position(counts,list_max(counts))-1)::UTINYINT AS igbp_biome, '
           'list_max(counts)/greatest(sampled,1) AS dominant_fraction FROM modes ORDER BY h3_r7,year')
    print('Consolidating measured annual classes...', flush=True)
    output = ROOT / 'data/lookup/igbp_cells.parquet'
    temporary = output.with_suffix('.tmp')
    # Stream the result to disk: materializing every annual class in Arrow can
    # exhaust laptop memory even when DuckDB's own memory is bounded.
    with tempfile.TemporaryDirectory(dir=shards) as staging:
        raw = Path(staging) / 'annual.parquet'
        with duckdb.connect(config={'threads': 2, 'memory_limit': '512MB',
                                    'temp_directory': staging}) as cursor:
            cursor.execute('COPY (' + sql + ') TO ? (FORMAT PARQUET, COMPRESSION ZSTD)',
                           [str(shards/'*.parquet'), str(raw)])
        source = pq.ParquetFile(raw)
        schema = source.schema_arrow.with_metadata({
            b'source': b'NASA MCD12Q1.061 LC_Type1, measured annual modal pixel class; no temporal extrapolation'})
        with pq.ParquetWriter(temporary, schema, compression='zstd') as writer:
            for batch in source.iter_batches(batch_size=65536):
                writer.write_batch(batch)
        source.close()
    temporary.replace(output)
    print(f'Published measured annual classes: {output.name}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-year', type=int, default=2001)
    parser.add_argument('--end-year', type=int, default=date.today().year - 1)
    parser.add_argument('--consolidate-only', action='store_true')
    args = parser.parse_args()
    if args.consolidate_only:
        consolidate(ROOT / 'data/cache/land_cover')
    else:
        acquire(args.start_year, args.end_year)
