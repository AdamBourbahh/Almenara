"""NASA POWER daily ``CLOUD_AMT`` for every 1-degree cell that intersects a region box (network).

This is the only module of the cloud-ancillary chain that uses the network; ``scripts/02`` consumes the
compact table it writes, offline. POWER needs no key. One request returns the whole 2000-11-01..2026-11-01
series of a point. Verified on 2026-11-14: the source is CERES SYN1deg (``header.sources == ["SYN1DEG"]``), a
1 x 1 degree grid whose cells have integer-degree edges (points with the same ``floor(lat), floor(lon)``
return identical series; a point exactly on an integer edge belongs to the cell to its north and east).
Values are percent, the fill value is ``-999.0`` (every day after about 2026-08-30) and the time standard is
local solar time.

    python -m pipeline.cloud_power                 # fetch missing cells (resumable) and build the table
    python -m pipeline.cloud_power --build-only    # rebuild the table from the cache, no network
"""

from __future__ import annotations

import argparse
import json
import math
import time
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from pipeline import config

URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
URL_TEMPLATE = (URL + "?parameters=CLOUD_AMT&community=AG&longitude={lon}&latitude={lat}"
                "&start={start}&end={end}&format=JSON")
PARAMETER = "CLOUD_AMT"
COMMUNITY = "AG"
FILL_VALUE = -999.0
START, END = date(2000, 11, 1), date(2026, 11, 1)
HEADERS = {"User-Agent": "firms-harmonizer-etl/1.0 (research pipeline)"}
CACHE_DIR = config.REAL / "cloud_power"
GRID_PATH = config.ROOT / "data/lookup/cloud_power_daily.parquet"
RETRIES = 6
SLEEP = 1.0
TIMEOUT = 120
GRID_DESCRIPTION = ("1 degree x 1 degree (CERES SYN1deg as served by POWER); a cell is identified by its "
                    "south-west integer corner (grid_lat_sw, grid_lon_sw); cell (lat, lon) covers "
                    "[lat, lat+1) x [lon, lon+1); one request per cell at its centre")
FILL_HANDLING = "POWER fill value -999 is written as NULL, never as 0; percent is divided by 100"
SCHEMA = pa.schema([("grid_lat_sw", pa.int16()), ("grid_lon_sw", pa.int16()),
                    ("acq_date", pa.date32()), ("cloud_fraction", pa.float64())])


def cell_for_point(lat: float, lon: float) -> tuple[int, int]:
    """South-west corner of the 1-degree cell that contains a point (edges belong to the north/east cell)."""
    return math.floor(lat), math.floor(lon)


def cells_for_bounds(bounds) -> list[tuple[int, int]]:
    """Every cell intersecting ``[west, south, east, north]``, including cells touched only at an edge."""
    west, south, east, north = bounds
    return [(lat, lon) for lat in range(math.floor(south), math.floor(north) + 1)
            for lon in range(math.floor(west), math.floor(east) + 1)]


def all_cells(regions: dict) -> list[tuple[int, int]]:
    """Sorted union of the cells of every region in ``data/regions.json``."""
    return sorted({cell for region in regions.values() for cell in cells_for_bounds(region["bounds"])})


def cache_path(cache_dir: Path, cell: tuple[int, int]) -> Path:
    return Path(cache_dir) / f"lat{cell[0]:+03d}_lon{cell[1]:+04d}.json"


def parse_response(body: dict) -> dict[date, float | None]:
    """``YYYYMMDD -> percent`` of a POWER response as ``date -> fraction in [0, 1]`` (fill -> None)."""
    try:
        series = body["properties"]["parameter"][PARAMETER]
    except KeyError as exc:
        raise ValueError(f"POWER response has no {PARAMETER} series") from exc
    fill = float(body.get("header", {}).get("fill_value", FILL_VALUE))
    out = {}
    for key, percent in series.items():
        day = datetime.strptime(key, "%Y%m%d").date()
        if percent is None or float(percent) == fill:
            out[day] = None
        elif 0.0 <= float(percent) <= 100.0:
            out[day] = round(float(percent) / 100.0, 6)   # percent has two decimals
        else:
            raise ValueError(f"{PARAMETER} {percent} on {day} is outside 0-100")
    return out


def _cached(path: Path, start: date, end: date) -> bool:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    return data.get("start") == start.strftime("%Y%m%d") and data.get("end") == end.strftime("%Y%m%d")


def fetch_cell(client: httpx.Client, cell: tuple[int, int], cache_dir: Path, start: date = START,
               end: date = END, sleep: float = SLEEP, retries: int = RETRIES, backoff=time.sleep) -> Path:
    """Fetch one cell (skipped when its cache file matches the date range) and cache the raw series."""
    path = cache_path(cache_dir, cell)
    if _cached(path, start, end):
        return path
    params = {"parameters": PARAMETER, "community": COMMUNITY, "longitude": f"{cell[1] + 0.5:g}",
              "latitude": f"{cell[0] + 0.5:g}", "start": start.strftime("%Y%m%d"),
              "end": end.strftime("%Y%m%d"), "format": "JSON"}
    for attempt in range(retries):
        try:
            response = client.get(URL, params=params, timeout=TIMEOUT)
            response.raise_for_status()
            body = response.json()
            parse_response(body)                        # validate before caching
            break
        except (httpx.HTTPError, ValueError) as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"POWER cell {cell} failed after {retries} attempts: {exc}") from exc
            wait = 2 ** attempt
            print(f"  cell {cell}: {type(exc).__name__}: {exc} -> retry in {wait}s", flush=True)
            backoff(wait)
    record = {"lat_sw": cell[0], "lon_sw": cell[1], "query_lat": cell[0] + 0.5, "query_lon": cell[1] + 0.5,
              "start": params["start"], "end": params["end"], "parameter": PARAMETER,
              "community": COMMUNITY, "source": body.get("header", {}).get("sources"),
              "fetched_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "values": body["properties"]["parameter"][PARAMETER]}
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.part")
    temporary.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
    time.sleep(sleep)
    return path


def fetch_all(client: httpx.Client, cells, cache_dir: Path = CACHE_DIR, start: date = START, end: date = END,
              sleep: float = SLEEP, backoff=time.sleep) -> int:
    """Fetch every missing cell sequentially; returns the number of requests that reached the network."""
    fetched = 0
    cells = list(cells)
    for number, cell in enumerate(cells, 1):
        if _cached(cache_path(cache_dir, cell), start, end):
            continue
        fetch_cell(client, cell, cache_dir, start, end, sleep, backoff=backoff)
        fetched += 1
        print(f"  [{number}/{len(cells)}] cell {cell}", flush=True)
    return fetched


def build_grid_table(cells, cache_dir: Path = CACHE_DIR, output: Path = GRID_PATH, start: date = START,
                     end: date = END) -> Path:
    """Compact table ``(grid_lat_sw, grid_lon_sw, acq_date, cloud_fraction)`` from the cache; no network."""
    cells = sorted(set(cells))
    columns = {"grid_lat_sw": [], "grid_lon_sw": [], "acq_date": [], "cloud_fraction": []}
    fetched = []
    for cell in cells:
        path = cache_path(cache_dir, cell)
        if not _cached(path, start, end):
            raise FileNotFoundError(f"Missing POWER cache for cell {cell}: {path.name}. Run the fetch first.")
        record = json.loads(path.read_text())
        fetched.append(record["fetched_utc"])
        for day, value in sorted(parse_response({"properties": {"parameter": {PARAMETER: record["values"]}},
                                                 "header": {"fill_value": FILL_VALUE}}).items()):
            columns["grid_lat_sw"].append(cell[0])
            columns["grid_lon_sw"].append(cell[1])
            columns["acq_date"].append(day)
            columns["cloud_fraction"].append(value)
    table = pa.table(columns, schema=SCHEMA)
    provenance = {
        "source": "NASA POWER daily point API, CLOUD_AMT (CERES SYN1deg cloud amount)",
        "url_template": URL_TEMPLATE, "parameter": PARAMETER, "community": COMMUNITY,
        "units_source": "percent", "units_table": "fraction 0-1",
        "start": start.isoformat(), "end": end.isoformat(), "grid": GRID_DESCRIPTION,
        "fetch_date_utc": max(fetched)[:10] if fetched else None,
        "fill_handling": FILL_HANDLING, "cells": len(cells), "rows": table.num_rows,
        "note": "daily mean cloud amount on a coarse grid, not cloud at satellite overpass time",
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    table = table.replace_schema_metadata({"cloud_power": json.dumps(provenance, sort_keys=True)})
    temporary = output.with_suffix(".parquet.part")
    pq.write_table(table, temporary, compression="zstd", compression_level=9, row_group_size=1 << 20,
                   use_dictionary=True, write_statistics=True)
    temporary.replace(output)
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--build-only", action="store_true", help="rebuild the table from the cache, no network")
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    parser.add_argument("--output", type=Path, default=GRID_PATH)
    parser.add_argument("--sleep", type=float, default=SLEEP, help="seconds between requests (default 1)")
    args = parser.parse_args(argv)
    cells = all_cells(config.load_regions())
    print(f"{len(cells)} grid cells intersect the {len(config.load_regions())} region boxes", flush=True)
    if not args.build_only:
        with httpx.Client(headers=HEADERS, follow_redirects=True) as client:
            fetched = fetch_all(client, cells, args.cache_dir, sleep=args.sleep)
        print(f"{fetched} requests sent, {len(cells) - fetched} cells already cached", flush=True)
    path = build_grid_table(cells, args.cache_dir, args.output)
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
