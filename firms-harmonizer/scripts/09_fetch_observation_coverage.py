"""Acquire regional NASA fire masks and retain compact per-cell observation evidence.

Uses free Earthdata access, never FIRMS detection absence as a coverage mask.
Downloads one granule at a time; successfully reduced inputs are deleted. Shards
are atomic and idempotent per region/sensor/granule. Credentials are environment
variables EARTHDATA_USERNAME/EARTHDATA_PASSWORD, or an existing Earthdata login.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor

import h3
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')
PRODUCTS = {'Terra': 'MOD14A1', 'Aqua': 'MYD14A1', 'SNPP': 'VNP14A1',
            'NOAA-20': 'VJ114A1', 'NOAA-21': 'VJ214A1'}
RADIUS = 6371007.181
TILE_SIZE = 1111950.5196666666


def write_summary(rows, shard, metadata):
    """Store flags in bits rather than repeating cell identifiers every day."""
    if isinstance(rows, dict):
        cells, days, clear, fire = (rows[key] for key in ('cells', 'days', 'clear', 'fire'))
    else:
        cells = np.array(sorted({r['h3_r7'] for r in rows}), dtype=np.uint64)
        days = np.array(sorted({r['epoch_day'] for r in rows}), dtype=np.int64)
        clear = np.zeros((len(days), len(cells)), dtype=bool)
        fire = clear.copy()
        d = np.searchsorted(days, [r['epoch_day'] for r in rows])
        c = np.searchsorted(cells, [r['h3_r7'] for r in rows])
        clear[d, c] = [r['clear_area_km2'] >= .95 * r['sampled_area_km2']
                       and r['sampled_area_km2'] >= .5 * r['cell_area_km2'] for r in rows]
        fire[d, c] = [r['fire_area_km2'] > 0 for r in rows]
    sensor = shard.name.split('_')[-2]
    table = pa.table({'cells': [cells.tobytes()], 'days': [days.tolist()],
        'clear_bits': [np.packbits(clear, axis=1).tobytes()],
        'fire_bits': [np.packbits(fire, axis=1).tobytes()]})
    table = table.replace_schema_metadata({**metadata, b'encoding': b'packed-v1',
        b'satellite': sensor.encode(), b'days': json.dumps(days.tolist()).encode()})
    temporary = shard.with_suffix('.tmp')
    pq.write_table(table, temporary, compression='zstd')
    temporary.replace(shard)


@lru_cache(maxsize=12)
def pixel_groups(horizontal, vertical, full_height, full_width, height, width, offset, bounds):
    xs = (horizontal - 18) * TILE_SIZE + (np.arange(width) + offset[1] + .5) * TILE_SIZE / full_width
    ys = (9 - vertical) * TILE_SIZE - (np.arange(height) + offset[0] + .5) * TILE_SIZE / full_height
    lat = np.broadcast_to(np.degrees(ys / RADIUS)[:, None], (height, width))
    lon = np.degrees(xs[None, :] / (RADIUS * np.cos(np.radians(lat))))
    w, s, e, n = bounds
    inside = (lat >= s) & (lat <= n) & (lon >= w) & (lon <= e)
    positions = np.flatnonzero(inside)
    ids = np.fromiter((int(h3.latlng_to_cell(float(a), float(o), 7), 16)
                       for a, o in zip(lat[inside], lon[inside])), dtype=np.uint64, count=len(positions))
    cells, groups = np.unique(ids, return_inverse=True)
    areas = np.array([h3.cell_area(format(int(cell), 'x'), unit='km^2') for cell in cells])
    return positions, cells, groups, areas


def reduce_mask(mask, granule_id, bounds, first, last, grid_shape=None, offset=(0, 0), band_dates=None):
    match = re.search(r'\.A(\d{4})(\d{3})\.h(\d{2})v(\d{2})\.', granule_id)
    if not match:
        raise ValueError('Expected a standard NASA sinusoidal tile identifier.')
    year, doy, horizontal, vertical = map(int, match.groups())
    array = np.asarray(mask)
    if array.ndim == 2:
        array = array[None, :, :]
    if array.ndim != 3 or not 1 <= array.shape[0] <= 8:
        raise ValueError('Expected one to eight daily mask planes.')
    if band_dates is None:
        if array.shape[0] not in (1, 8):
            raise ValueError('Partial composites require explicit NASA Dates metadata.')
        band_dates = [date(year, 1, 1) + timedelta(days=doy - 1 + k) for k in range(array.shape[0])]
    if len(band_dates) != array.shape[0] or len(set(band_dates)) != len(band_dates):
        raise ValueError('FireMask band dates must match its planes without duplicates.')
    height, width = array.shape[1:]
    full_height, full_width = grid_shape or (height, width)
    positions, cells, groups, area = pixel_groups(horizontal, vertical, full_height, full_width,
                                                 height, width, tuple(offset), tuple(bounds))
    counts = np.bincount(groups, minlength=len(cells))
    sampled = counts * (TILE_SIZE / full_width) * (TILE_SIZE / full_height) / 1e6
    days, clear, fire = [], [], []
    for band, plane in enumerate(array):
        day = band_dates[band]
        if not first <= day <= last:
            continue
        values = plane.ravel()[positions]
        good = (values == 3) | (values == 5) | ((values >= 7) & (values <= 9))
        hot = (values >= 7) & (values <= 9)
        clear.append((np.bincount(groups, weights=good, minlength=len(cells)) >= .95 * counts)
                     & (sampled >= .5 * area))
        fire.append(np.bincount(groups, weights=hot, minlength=len(cells)) > 0)
        days.append((day - date(1970, 1, 1)).days)
    return dict(cells=cells, days=np.array(days, dtype=np.int64), clear=np.array(clear), fire=np.array(fire))


def read_mask(path, field='FireMask'):
    """Read FireMask SDS from standard tiled MODIS HDF4 or VIIRS HDF5."""
    with path.open('rb') as stream:
        signature = stream.read(4)
    if signature == b'\x0e\x03\x13\x01':
        from pyhdf.SD import SD, SDC
        file = SD(str(path), SDC.READ)
        try:
            names = [name for name in file.datasets() if name.lower().replace('_', '') == field.lower().replace('_', '')]
            if len(names) != 1:
                raise ValueError('Expected exactly one FireMask scientific dataset.')
            return np.asarray(file.select(names[0])[:])
        finally:
            file.end()
    import h5py
    with h5py.File(path) as file:
        names = []
        file.visititems(lambda name, item: names.append(name) if isinstance(item, h5py.Dataset)
                        and name.split('/')[-1].lower().replace('_', '') == field.lower().replace('_', '') else None)
        if len(names) != 1:
            raise ValueError('Expected exactly one FireMask scientific dataset.')
        return file[names[0]][:]


def summarize(mask, granule_id, bounds, first, last, grid_shape=None, offset=(0, 0)):
    """Aggregate equal-area sinusoidal pixels by H3 R7 and actual UTC band date."""
    match = re.search(r'\.A(\d{4})(\d{3})\.h(\d{2})v(\d{2})\.', granule_id)
    if not match:
        raise ValueError(f'Not a tiled daily fire-mask granule: {granule_id}')
    year, doy, horizontal, vertical = map(int, match.groups())
    origin = date(year, 1, 1) + timedelta(days=doy - 1)
    array = np.asarray(mask)
    if array.ndim == 2:
        array = array[None, :, :]
    if array.ndim != 3 or array.shape[0] not in (1, 8):
        raise ValueError('FireMask must contain one daily plane or eight daily planes.')
    west, south, east, north = bounds
    rows = []
    height, width = array.shape[1:]
    full_height, full_width = grid_shape or (height, width)
    pixel_area = (TILE_SIZE / full_width) * (TILE_SIZE / full_height) / 1e6
    xs = (horizontal - 18) * TILE_SIZE + (np.arange(width) + offset[1] + .5) * TILE_SIZE / full_width
    for band, plane in enumerate(array):
        day = origin + timedelta(days=band)
        if day < first or day > last:
            continue
        totals = {}
        for top in range(0, height, 128):
            ys = (9 - vertical) * TILE_SIZE - (np.arange(top, min(top + 128, height)) + offset[0] + .5) * TILE_SIZE / full_height
            lat = np.broadcast_to(np.degrees(ys / RADIUS)[:, None], (len(ys), width))
            lon = np.degrees(xs[None, :] / (RADIUS * np.cos(np.radians(lat))))
            inside = (lat >= south) & (lat <= north) & (lon >= west) & (lon <= east)
            values = plane[top:top + len(ys)][inside]
            for a, o, code in zip(lat[inside], lon[inside], values):
                cell = h3.latlng_to_cell(float(a), float(o), 7)
                counts = totals.setdefault(cell, np.zeros(4))
                # NASA FireMask: 5=clear non-fire land, 7..9=fire, 4=cloud.
                counts[0] += int(code in (3, 5) or 7 <= code <= 9)
                counts[1] += int(7 <= code <= 9)
                counts[2] += int(code == 4)
                counts[3] += 1
        for cell, counts in totals.items():
            rows.append(dict(h3_r7=int(cell, 16), epoch_day=(day - date(1970, 1, 1)).days,
                             clear_area_km2=float(counts[0] * pixel_area),
                             fire_area_km2=float(counts[1] * pixel_area),
                             cloud_area_km2=float(counts[2] * pixel_area),
                             sampled_area_km2=float(counts[3] * pixel_area),
                             cell_area_km2=h3.cell_area(cell, unit='km^2')))
    return rows


def acquire_public(regions, start, end):
    """Anonymous Terra/Aqua FireMask COG access; VIIRS remains a separate acquisition.

    One-kilometre mask samples constrain MODIS observation availability. They do
    not establish absence of fires below its detection limit or VIIRS coverage.
    """
    import planetary_computer
    import pystac_client
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds, Window
    catalog = pystac_client.Client.open('https://planetarycomputer.microsoft.com/api/stac/v1')
    registry = json.loads((ROOT / 'data/regions.json').read_text(encoding='utf-8'))
    output = ROOT / 'data/processed/observation_coverage'
    output.mkdir(parents=True, exist_ok=True)
    failures = []
    for region in regions or registry:
        w, s, e, n = registry[region]['bounds']
        bounds = [w - .05, s - .05, e + .05, n + .05]
        for year in range(start.year, end.year + 1):
            first, last = max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
            items = catalog.search(collections=['modis-14A1-061'], bbox=bounds,
                datetime=f'{first.isoformat()}/{last.isoformat()}').items()
            unique = {}
            for item in items:
                key = '.'.join(item.id.split('.')[:3])
                if key not in unique or item.id > unique[key].id:
                    unique[key] = item
            complete = 0
            def process(item):
                sensor = 'Terra' if item.id.startswith('MOD') else 'Aqua'
                shard = output / f'{region}_{sensor}_{hashlib.sha256('.'.join(item.id.split('.')[:3]).encode()).hexdigest()[:20]}.parquet'
                if shard.exists() and (pq.read_schema(shard).metadata or {}).get(b'granule') == item.id.encode():
                    return 1
                try:
                    with rasterio.open(planetary_computer.sign(item.assets['FireMask'].href)) as dataset:
                        native = transform_bounds('EPSG:4326', dataset.crs, *bounds, densify_pts=41)
                        window = from_bounds(*native, transform=dataset.transform).round_offsets().round_lengths()
                        window = window.intersection(Window(0, 0, dataset.width, dataset.height))
                        array = dataset.read(window=window)
                        tags = dataset.tags()
                        explicit = re.findall(r'\d{4}-\d{2}-\d{2}', tags.get('Dates', tags.get('DAYSOFYEAR', '')))
                        rows = reduce_mask(array, item.id, bounds, date(2000, 11, 1), date.today(),
                            (dataset.height, dataset.width), (int(window.row_off), int(window.col_off)),
                            [date.fromisoformat(value) for value in explicit] if explicit else None)
                    if len(rows['days']) and len(rows['cells']):
                        write_summary(rows, shard, {b'product': b'MOD14A1/MYD14A1.061 FireMask',
                            b'granule': item.id.encode(), b'source': b'NASA FireMask via public Planetary Computer COG; 1km sampled coverage'})
                    return 1
                except Exception as error:
                    failures.append({'region': region, 'granule': item.id, 'error': type(error).__name__})
                    return 0
            with ThreadPoolExecutor(max_workers=4) as pool:
                complete = sum(pool.map(process, unique.values()))
            print(f'{region} {year}: {complete}/{len(unique)} MODIS mask granules processed', flush=True)
        import sys
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from backend.db.packed_coverage import publish_preset
        publish_preset(ROOT, region, start, end)
    (output / 'public_acquisition_status.json').write_text(json.dumps({'failures': failures,
        'start': start.isoformat(), 'end': end.isoformat(),
        'scope': 'MODIS Terra/Aqua 1km FireMask only; missing products/VIIRS remain unknown'}, indent=2), encoding='utf-8')
    return not failures


def acquire(regions, start, end, catalog_only=False, sensors=None):
    import earthaccess
    registry = json.loads((ROOT / 'data/regions.json').read_text(encoding='utf-8'))
    output = ROOT / 'data/processed/observation_coverage'
    output.mkdir(parents=True, exist_ok=True)
    failures = []
    if not catalog_only:
        try:
            auth = earthaccess.login(strategy='environment', persist=False)
        except Exception as error:
            raise RuntimeError('Configure EARTHDATA_TOKEN or EARTHDATA_USERNAME/EARTHDATA_PASSWORD locally before acquisition.') from error
        if not auth.authenticated:
            raise RuntimeError('Earthdata authentication required: set EARTHDATA_USERNAME and EARTHDATA_PASSWORD locally. No coverage was fabricated.')
    for region in regions or registry:
        if region not in registry:
            raise ValueError(f'Unknown region: {region}')
        for sensor, product in PRODUCTS.items():
            if sensors and sensor not in sensors:
                continue
            for year in range(start.year, end.year + 1):
                first, last = max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
                try:
                    granules = earthaccess.search_data(short_name=product,
                        bounding_box=tuple(registry[region]['bounds']), temporal=(first.isoformat(), last.isoformat()))
                    print(f'{region} {product} {year}: {len(granules)} granules', flush=True)
                    # Newest production wins if a collection has reprocessed a tile/day.
                    unique = {}
                    for granule in granules:
                        gid = granule['umm']['DataGranule']['Identifiers'][0]['Identifier']
                        key = '.'.join(gid.split('.')[:3])
                        if key not in unique or gid > unique[key][0]:
                            unique[key] = (gid, granule)
                    if catalog_only:
                        continue
                    def process(granule_item):
                        gid, granule = granule_item
                        shard = output / f'{region}_{sensor}_{hashlib.sha256('.'.join(gid.split('.')[:3]).encode()).hexdigest()[:20]}.parquet'
                        if shard.exists() and (pq.read_schema(shard).metadata or {}).get(b'granule',b'').decode().removesuffix('.hdf').removesuffix('.h5') == gid.removesuffix('.hdf').removesuffix('.h5'):
                            return 1
                        with tempfile.TemporaryDirectory(dir=output) as cache:
                            paths = earthaccess.download([granule], local_path=cache, threads=1)
                            if len(paths) != 1:
                                raise RuntimeError(f'Incomplete download: {gid}')
                            rows = reduce_mask(read_mask(Path(paths[0])), gid, registry[region]['bounds'], date(2000, 11, 1), date.today())
                            if not len(rows['days']) or not len(rows['cells']):
                                raise ValueError(f'No regional pixels in {gid}')
                            write_summary(rows, shard, {b'product': product.encode(), b'granule': gid.encode(),
                                b'source': b'NASA Earthdata FireMask; 95% per-cell valid coverage required for observed zero'})
                        return 1
                    with ThreadPoolExecutor(max_workers=4) as pool:
                        list(pool.map(process, unique.values()))
                except Exception as error:
                    # Product gaps are recorded and never converted to observed zeros.
                    failures.append({'region': region, 'product': product, 'year': year, 'error': type(error).__name__})
                    print(f'{region} {product} {year}: acquisition incomplete ({type(error).__name__})', flush=True)
        if not catalog_only:
            import sys
            if str(ROOT) not in sys.path:
                sys.path.insert(0,str(ROOT))
            from backend.db.packed_coverage import publish_preset
            publish_preset(ROOT,region,start,end)
    (output / 'acquisition_status.json').write_text(json.dumps({'failures': failures,
        'catalog_only': catalog_only, 'start': start.isoformat(), 'end': end.isoformat()}, indent=2), encoding='utf-8')
    return not failures


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--region', action='append')
    parser.add_argument('--start', type=date.fromisoformat, default=date(2000, 11, 1))
    parser.add_argument('--end', type=date.fromisoformat, default=date.today())
    parser.add_argument('--catalog-only', action='store_true')
    parser.add_argument('--sensor', action='append', choices=list(PRODUCTS))
    parser.add_argument('--public-modis', action='store_true', help='Anonymous public MODIS masks; no Earthdata account needed')
    args = parser.parse_args()
    if args.start > args.end or args.end > date.today():
        parser.error('Use an ordered historical date range.')
    try:
        result = acquire_public(args.region, args.start, args.end) if args.public_modis else acquire(args.region, args.start, args.end, args.catalog_only, args.sensor)
        sys.exit(0 if result else 1)
    except RuntimeError as error:
        parser.exit(2, f'{error}\n')
