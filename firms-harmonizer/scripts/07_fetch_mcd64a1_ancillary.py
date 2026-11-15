"""Fetch MODIS MCD64A1 v6.1 burned area for the registered regions and publish cell_day_ancillary.parquet.

This is a network acquisition step, like the FIRMS downloads: it reads the public MCD64A1 v6.1 monthly
Burn_Date rasters from the Microsoft Planetary Computer STAC catalog (anonymous signed reads). Stages 01-05
stay offline and only read the published lookup. Every burned 500 m pixel (Burn_Date 1-366) whose centre lies
inside a region box is assigned to its H3 R7 cell and burn date; areas use the sinusoidal grid's constant
pixel area. Cloud cover is not supplied here and is published as null (missing, never observed zero).
Requires: pip install -r scripts/requirements-acquisition.txt
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import h3
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path("data/lookup/cell_day_ancillary.parquet")
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "modis-64A1-061"
PIXEL_METRES = 463.3127165279167  # MODIS sinusoidal 500 m grid; the projection is equal-area
PIXEL_HA = PIXEL_METRES ** 2 / 10_000
SCHEMA = pa.schema([("h3_r7", pa.uint64()), ("acq_date", pa.date32()),
                    ("cloud_cover_pct", pa.float32()), ("burned_area_ha_mcd64", pa.float32())])


def burn_dates(year, doy):
    """Calendar dates for Burn_Date ordinal days of the composite's year; invalid ordinals raise."""
    doy = np.asarray(doy)
    first = np.datetime64(f"{year}-01-01")
    days_in_year = int((np.datetime64(f"{year + 1}-01-01") - first).astype(int))
    if doy.size and (doy.min() < 1 or doy.max() > days_in_year):
        raise ValueError(f"Burn_Date ordinal outside 1..{days_in_year} for {year}")
    return first + (doy.astype("int64") - 1).astype("timedelta64[D]")


def aggregate_burned_pixels(lat, lon, dates):
    """Sum unique burned pixels into (h3_r7, burn date) rows with burned area in hectares."""
    lat, lon = np.asarray(lat, dtype=float), np.asarray(lon, dtype=float)
    days = np.asarray(dates, dtype="datetime64[D]").astype("int64")
    if not len(lat):
        return SCHEMA.empty_table()
    # The same pixel can be read for two overlapping region boxes; count it once.
    _, first = np.unique(np.column_stack([lat, lon, days.astype(float)]), axis=0, return_index=True)
    lat, lon, days = lat[first], lon[first], days[first]
    cells = np.fromiter((int(h3.latlng_to_cell(a, o, 7), 16) for a, o in zip(lat, lon)),
                        dtype=np.uint64, count=len(lat))
    keys, counts = np.unique(np.column_stack([cells, days.astype(np.uint64)]), axis=0, return_counts=True)
    return pa.table({
        "h3_r7": pa.array(keys[:, 0], pa.uint64()),
        "acq_date": pa.array(keys[:, 1].astype("int64").astype("datetime64[D]"), pa.date32()),
        "cloud_cover_pct": pa.nulls(len(keys), pa.float32()),
        "burned_area_ha_mcd64": pa.array(counts * PIXEL_HA, pa.float32()),
    }, schema=SCHEMA)


def extract_burned_pixels(dataset, bounds, year, quality=None):
    """Centres (lat, lon) and dates of burned pixels of an open Burn_Date raster inside a lon/lat box."""
    from rasterio.transform import xy
    from rasterio.warp import transform, transform_bounds
    from rasterio.windows import Window, from_bounds

    west, south, east, north = bounds
    native = transform_bounds("EPSG:4326", dataset.crs, west, south, east, north, densify_pts=41)
    window = from_bounds(*native, transform=dataset.transform).round_offsets().round_lengths()
    window = window.intersection(Window(0, 0, dataset.width, dataset.height)) if (
        window.col_off < dataset.width and window.row_off < dataset.height
        and window.col_off + window.width > 0 and window.row_off + window.height > 0) else None
    empty = (np.array([]), np.array([]), np.array([], dtype="datetime64[D]"))
    if window is None or window.width < 1 or window.height < 1:
        return empty
    data = dataset.read(1, window=window)
    valid = (data >= 1) & (data <= 366)
    if quality is not None:
        if quality.crs != dataset.crs or quality.transform != dataset.transform:
            raise ValueError('Burn_Date and QA must share a grid.')
        flags = quality.read(1, window=window)
        valid &= (flags & 3) == 3  # MCD64A1 QA: land and sufficient valid observations.
    rows, cols = np.nonzero(valid)
    if not len(rows):
        return empty
    xs, ys = xy(dataset.window_transform(window), rows, cols, offset="center")
    lon, lat = (np.asarray(v) for v in transform(dataset.crs, "EPSG:4326", xs, ys))
    inside = (lat >= south) & (lat <= north) & (lon >= west) & (lon <= east)
    return lat[inside], lon[inside], burn_dates(year, data[rows, cols][inside])


def composite_year(item_id):
    return int(item_id.split(".")[1][1:5])  # MCD64A1.AYYYYDDD.hXXvYY.061.<production>


def complete_years(item_ids):
    """Calendar years in which every tile of the region has all 12 monthly composites."""
    tiles = {item_id.split(".")[2] for item_id in item_ids}
    months = {}
    for item_id in item_ids:
        months.setdefault(composite_year(item_id), set()).add((item_id.split(".")[1][5:8], item_id.split(".")[2]))
    return sorted(year for year, present in months.items() if len(present) == 12 * len(tiles))


def fetch_region(catalog, sign, name, bounds, start, end, cache, workers):
    import rasterio

    items = {item.id: item for item in catalog.search(collections=[COLLECTION], bbox=bounds,
                                                      datetime=f"{start}/{end}").items()}
    region_cache = cache / name / 'qa-v1'
    region_cache.mkdir(parents=True, exist_ok=True)

    def read(item):
        path = region_cache / f"{item.id}.npz"
        if not path.exists():
            for attempt in range(5):
                try:
                    with rasterio.open(sign(item.assets["Burn_Date"].href)) as dataset, rasterio.open(sign(item.assets['QA'].href)) as quality:
                        lat, lon, dates = extract_burned_pixels(dataset, bounds, composite_year(item.id), quality)
                    break
                except Exception as error:  # transient HTTP/COG failures; abort after five attempts
                    if attempt == 4:
                        raise RuntimeError(f"{name} {item.id} failed: {error}") from error
                    time.sleep(10 * (attempt + 1))
            np.savez(path, lat=lat, lon=lon, days=dates.astype("int64"))
        stored = np.load(path)
        return stored["lat"], stored["lon"], stored["days"].astype("datetime64[D]")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        parts = list(pool.map(read, items.values()))
    years = sorted({composite_year(item_id) for item_id in items})
    print(f"{name}: {len(items)} MCD64A1 tiles-months ({years[0] if years else '-'}-{years[-1] if years else '-'}), "
          f"{sum(len(p[0]) for p in parts):,} burned pixels", flush=True)
    return parts, sorted(items)


def build_ancillary(output=OUTPUT, start="2000-11-01", end="2026-11-01", cache=None, workers=8, only=None):
    import planetary_computer
    import pystac_client

    regions = json.loads((ROOT / "data/regions.json").read_text(encoding="utf-8"))
    selected = {name: spec for name, spec in regions.items() if "coverage" in spec and (not only or name in only)}
    catalog = pystac_client.Client.open(STAC)
    cache = Path(cache) if cache else ROOT / "data/cache/mcd64a1"
    parts, item_ids, complete = [], {}, {}
    for name, spec in selected.items():
        region_parts, ids = fetch_region(catalog, planetary_computer.sign, name, spec["bounds"], start, end,
                                         cache, workers)
        parts.extend(region_parts)
        item_ids[name] = len(ids)
        complete[name] = complete_years(ids)
        missing = sorted(set(range(2001, int(end[:4]))) - set(complete[name]))
        print(f"   {name}: complete years {complete[name][0] if complete[name] else '-'}-"
              f"{complete[name][-1] if complete[name] else '-'}; incomplete or absent: {missing}", flush=True)
    lat = np.concatenate([p[0] for p in parts]) if parts else np.array([])
    lon = np.concatenate([p[1] for p in parts]) if parts else np.array([])
    dates = np.concatenate([p[2] for p in parts]) if parts else np.array([], dtype="datetime64[D]")
    table = aggregate_burned_pixels(lat, lon, dates)
    metadata = {
        b"source": f"MODIS MCD64A1 v6.1 Burn_Date via {STAC} collection {COLLECTION}".encode(),
        b"pixel_area_ha": repr(PIXEL_HA).encode(),
        b"regions": json.dumps(item_ids, sort_keys=True).encode(),
        b"requested_range": f"{start}/{end}".encode(),
        b"complete_years": json.dumps(complete, sort_keys=True).encode(),
        b"quality": b"Burn_Date pixels require QA land and valid-data bits; complete years require all monthly tile composites, not independent truth or full cloud-free coverage",
        b"cloud_cover_pct": b"not supplied: null for every row (missing, not observed zero)",
        b"retrieved_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ").encode(),
    }
    path = ROOT / output
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.parquet")
    pq.write_table(table.replace_schema_metadata(metadata), temporary, compression="zstd")
    temporary.replace(path)
    print(f"Wrote {table.num_rows:,} burned cell-days ({int(pc_sum(table)):,} ha) to {path}.")
    return path


def pc_sum(table):
    return float(np.sum(table["burned_area_ha_mcd64"].to_numpy())) if table.num_rows else 0.0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", default=OUTPUT)
    parser.add_argument("--start", default="2000-11-01")
    parser.add_argument("--end", default="2026-11-01")
    parser.add_argument("--cache-dir")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--region", action="append", help="Limit to registered region(s); default: all with coverage")
    args = parser.parse_args()
    sys.exit(0 if build_ancillary(args.output, args.start, args.end, args.cache_dir, args.workers, args.region) else 1)
