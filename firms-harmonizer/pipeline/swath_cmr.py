"""MODIS swath-gap evidence from NASA CMR granule footprints of ``MOD03``/``MYD03`` (network).

This is the only module of the swath-evidence chain that uses the network; ``scripts/04`` consumes the
compact table it writes, offline. The CMR granule search needs no key. Verified on 2026-11-14:

* ``MOD03`` (Terra) and ``MYD03`` (Aqua) each exist as versions ``6.1`` (``C1379767668-LAADS``,
  ``C1379841358-LAADS``), ``7`` and ``6.1NRT``. Versions 6.1 and 7 have the same granule count over the
  Amazonas box for 2000-11-01..2026-11-01 (Terra 24,739 / 24,739, Aqua 23,527 / 23,524) and run to the
  present; an unpinned search lists every granule once per version. FIRMS MODIS is Collection 6.1, so the
  search pins ``version=6.1`` and still merges entries that share ``time_start``.
* ``page_size`` is limited to 2000. ``CMR-Hits`` gives the total and ``CMR-Search-After`` (sent back as a
  request header) the next page; the page after the last one is empty.
* Each entry has ``time_start``, ``time_end``, ``day_night_flag`` (``DAY``/``NIGHT``/``BOTH``),
  ``coordinate_system = "GEODETIC"`` and ``polygons = [["lat lon lat lon ..."]]``: one closed 5-point ring
  per 5-minute granule, latitude first, with great-circle edges.

    python -m pipeline.swath_cmr                 # fetch missing chunks (resumable) and build the table
    python -m pipeline.swath_cmr --build-only    # rebuild the table from the cache, no network
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import h3
import httpx
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from pipeline import config

URL = "https://cmr.earthdata.nasa.gov/search/granules.json"
COLLECTIONS = {"Terra": ("MOD03", "6.1"), "Aqua": ("MYD03", "6.1")}
START, END = date(2000, 11, 1), date(2026, 11, 1)
HEADERS = {"User-Agent": "firms-harmonizer-etl/1.0 (research pipeline)"}
CACHE_DIR = config.REAL / "swath_cmr"
GAPS_PATH = config.ROOT / "data/lookup/modis_swath_gaps.parquet"
OUTAGES_PATH = config.ROOT / "data/lookup/sensor_outages.parquet"
PAGE_SIZE = 2000
RETRIES = 6
SLEEP = 1.0
TIMEOUT = 180
# A staged R7 cell is the detection's cell or one of its 1-ring footprint neighbours (centres within about
# 4 km of the box); 0.1 degree is at least 8 km at every region latitude.
CELL_MARGIN_DEG = 0.1
BBOX_MARGIN_DEG = 0.01
SCHEMA = pa.schema([("satellite", pa.string()), ("h3_r4", pa.uint64()), ("acq_date", pa.date32())])
COVERAGE_RULE = ("an H3 R4 cell is covered by a satellite on a UTC day when any granule ring of that satellite "
                 "whose time_start or time_end falls on that day contains the cell centre or any cell boundary "
                 "vertex; rings are spherical polygons with great-circle edges (CMR GEODETIC); every ring of "
                 "every listing of a granule counts")
ACQUIRING_RULE = ("a satellite is acquiring on a UTC day when at least one of its granules over any of the "
                  "region boxes falls on that day; gaps are declared only on acquiring days, never before the "
                  "satellite's first granule, never on stage 02 outage days of that satellite and never on a "
                  "day with a granule that has no footprint polygon")
CELL_RULE = ("every H3 R4 parent of an H3 R7 cell whose centre lies in a region box expanded by "
             f"{CELL_MARGIN_DEG} degree")
LIMITS = ("4-corner granule rings approximate the curved swath edges; UTC-day granularity (a covered cell may "
          "still be unobserved at a given hour); MODIS only: VIIRS swaths are not modelled")


def parse_rings(polygons) -> list[list[tuple[float, float]]]:
    """Outer rings of CMR ``polygons`` (``[["lat lon lat lon ..."], ...]``) as ``(lat, lon)`` lists.

    Holes (second and later rings of a polygon) are ignored, so coverage can only be overstated.
    """
    rings = []
    for polygon in polygons or []:
        values = [float(token) for token in polygon[0].split()]
        if len(values) % 2 or len(values) < 6:
            raise ValueError(f"CMR ring needs lat/lon pairs (at least three points): {polygon[0]!r}")
        points = list(zip(values[0::2], values[1::2]))
        if any(not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0 for lat, lon in points):
            raise ValueError(f"CMR ring latitude/longitude out of range (rings are lat-first): {polygon[0]!r}")
        if points[0] == points[-1]:
            points = points[:-1]
        rings.append(points)
    return rings


def compact_entry(entry: dict) -> list:
    """``[time_start, time_end, day_night_flag, [flat lat/lon ring, ...]]``: all the cache keeps per granule."""
    rings = parse_rings(entry.get("polygons"))
    return [entry["time_start"], entry["time_end"], entry.get("day_night_flag", "UNSPECIFIED"),
            [[value for point in ring for value in point] for ring in rings]]


def dedupe(granules: list) -> list:
    """Merge listings with the same ``time_start`` (collection versions): union of rings, latest end."""
    merged = {}
    for start, end, flag, rings in granules:
        if start in merged:
            item = merged[start]
            item[1] = max(item[1], end)
            item[2] = min(item[2], flag)
            item[3] = sorted({tuple(ring) for ring in item[3]} | {tuple(ring) for ring in rings})
        else:
            merged[start] = [start, end, flag, sorted({tuple(ring) for ring in rings})]
    return [[s, e, f, [list(ring) for ring in rings]] for s, (_, e, f, rings) in sorted(merged.items())]


def year_windows(start: date, end: date) -> list[tuple[int, str, str]]:
    """Calendar-year temporal windows ``[t0, t1)`` covering the days ``start..end``."""
    out = []
    for year in range(start.year, end.year + 1):
        t0 = max(start, date(year, 1, 1))
        t1 = min(end + timedelta(days=1), date(year + 1, 1, 1))
        out.append((year, f"{t0.isoformat()}T00:00:00Z", f"{t1.isoformat()}T00:00:00Z"))
    return out


def region_r4_cells(bounds) -> list[int]:
    """Sorted H3 R4 cells (integers) that can parent a staged R7 cell of a region box."""
    west, south, east, north = bounds
    m = CELL_MARGIN_DEG
    polygon = h3.LatLngPoly([(south - m, west - m), (south - m, east + m), (north + m, east + m),
                             (north + m, west - m)])
    return sorted({int(h3.cell_to_parent(cell, 4), 16) for cell in h3.polygon_to_cells(polygon, 7)})


def query_bbox(cells) -> tuple[float, float, float, float]:
    """``(west, south, east, north)`` enclosing every centre and boundary vertex of the cells, plus a margin.

    Any granule that contains one of those points intersects this box, so the search returns it.
    """
    points = [point for cell in cells for point in _lat_lon_points(format(cell, "x"))]
    lats, lons = [p[0] for p in points], [p[1] for p in points]
    floor = lambda v: float(np.floor((v - BBOX_MARGIN_DEG) * 1000) / 1000)
    ceil = lambda v: float(np.ceil((v + BBOX_MARGIN_DEG) * 1000) / 1000)
    west, east = floor(min(lons)), ceil(max(lons))
    if east - west > 180:
        raise ValueError("Region boxes crossing the antimeridian are not supported")
    return west, max(-90.0, floor(min(lats))), east, min(90.0, ceil(max(lats)))


def _lat_lon_points(cell: str) -> list[tuple[float, float]]:
    """Centre and boundary vertices; pentagons repeat the centre so every cell has seven points."""
    points = [h3.cell_to_latlng(cell)] + list(h3.cell_to_boundary(cell))
    return points + [points[0]] * (7 - len(points))


def unit_vectors(lat_lon: np.ndarray) -> np.ndarray:
    lat, lon = np.deg2rad(lat_lon[..., 0]), np.deg2rad(lat_lon[..., 1])
    return np.stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)], axis=-1)


def cell_points(cells) -> np.ndarray:
    """``(n_cells, 7, 3)`` unit vectors of each cell's centre and boundary vertices."""
    return unit_vectors(np.array([_lat_lon_points(format(cell, "x")) for cell in cells], dtype=float))


def ring_contains(ring, points: np.ndarray) -> np.ndarray:
    """Whether each unit vector lies inside a spherical ring with great-circle edges.

    Gnomonic projection about the ring's centre maps great circles to straight lines, so an even-odd test in
    that plane is exact on the sphere. Points on the far hemisphere are outside.
    """
    vertices = unit_vectors(np.asarray(ring, dtype=float))
    centre = vertices.sum(axis=0)
    centre /= np.linalg.norm(centre)
    if np.any(vertices @ centre <= 1e-9):
        raise ValueError("Granule ring spans a hemisphere; the gnomonic test does not apply")
    axis = np.array([0.0, 0.0, 1.0]) if abs(centre[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    e1 = np.cross(axis, centre)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(centre, e1)
    vx, vy = (vertices @ e1) / (vertices @ centre), (vertices @ e2) / (vertices @ centre)
    depth = points @ centre
    front = depth > 1e-9
    safe = np.where(front, depth, 1.0)
    px, py = (points @ e1) / safe, (points @ e2) / safe
    inside = np.zeros(points.shape[:-1], dtype=bool)
    j = len(vx) - 1
    for i in range(len(vx)):
        crosses = (vy[i] > py) != (vy[j] > py)
        with np.errstate(divide="ignore", invalid="ignore"):
            x_at = (vx[j] - vx[i]) * (py - vy[i]) / (vy[j] - vy[i]) + vx[i]
        inside ^= crosses & (px < x_at)
        j = i
    return inside & front


def covered_cells(ring, points: np.ndarray) -> np.ndarray:
    """Cells (rows of ``cell_points``) whose centre or any boundary vertex lies inside the ring."""
    vertices = unit_vectors(np.asarray(ring, dtype=float))
    centre = vertices.sum(axis=0)
    centre /= np.linalg.norm(centre)
    reach = float((vertices @ centre).min())
    # Cheap cap prefilter: a cell can only be covered if one of its points lies in the ring's vertex cap.
    near = ((points @ centre) >= reach - 1e-9).any(axis=1)
    out = np.zeros(points.shape[0], dtype=bool)
    if near.any():
        out[near] = ring_contains(ring, points[near]).any(axis=1)
    return out


def granule_days(time_start: str, time_end: str) -> list[date]:
    """UTC days a granule touches: the dates of its start and of its end (both, when it spans midnight)."""
    first, last = date.fromisoformat(time_start[:10]), date.fromisoformat(time_end[:10])
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def cache_path(cache_dir: Path, satellite: str, region: str, year: int) -> Path:
    return Path(cache_dir) / satellite / region / f"{year}.json"


def _signature(satellite, bbox, t0, t1) -> dict:
    short_name, version = COLLECTIONS[satellite]
    return {"satellite": satellite, "short_name": short_name, "version": version,
            "bbox": [round(v, 6) for v in bbox], "temporal": [t0, t1]}


def _cached(path: Path, signature: dict) -> bool:
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    return all(record.get(key) == value for key, value in signature.items())


def fetch_chunk(client: httpx.Client, satellite: str, region: str, bbox, year: int, cache_dir: Path,
                start: date = START, end: date = END, sleep: float = SLEEP, page_size: int = PAGE_SIZE,
                retries: int = RETRIES, backoff=time.sleep) -> tuple[Path, int]:
    """Fetch every granule of one (satellite, region, year) chunk; returns the cache file and requests sent."""
    (year, t0, t1), = [w for w in year_windows(start, end) if w[0] == year]
    signature = _signature(satellite, bbox, t0, t1)
    path = cache_path(cache_dir, satellite, region, year)
    if _cached(path, signature):
        return path, 0
    short_name, version = COLLECTIONS[satellite]
    params = {"short_name": short_name, "version": version, "bounding_box": ",".join(f"{v:g}" for v in bbox),
              "temporal": f"{t0},{t1}", "page_size": page_size, "sort_key": "start_date"}
    requests = 0
    for attempt in range(retries):
        try:
            entries, hits, search_after = [], None, None
            while True:
                headers = {"CMR-Search-After": search_after} if search_after else {}
                requests += 1
                response = client.get(URL, params=params, headers=headers, timeout=TIMEOUT)
                response.raise_for_status()
                page = response.json()["feed"]["entry"]
                hits = int(response.headers["CMR-Hits"]) if hits is None else hits
                entries.extend(page)
                if len(page) < page_size or len(entries) >= hits:
                    break
                search_after = response.headers["CMR-Search-After"]
                time.sleep(sleep)
            if len(entries) != hits:
                raise ValueError(f"paging returned {len(entries)} entries but CMR-Hits is {hits}")
            granules = [compact_entry(entry) for entry in entries]
            break
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"CMR {satellite} {region} {year} failed after {retries} attempts: "
                                   f"{type(exc).__name__}: {exc}") from exc
            wait = 2 ** attempt
            print(f"  {satellite} {region} {year}: {type(exc).__name__}: {exc} -> retry in {wait}s", flush=True)
            backoff(wait)
    record = signature | {
        "region": region, "hits": hits, "url": URL,
        "collection_concept_ids": sorted({entry.get("collection_concept_id", "") for entry in entries}),
        "fetched_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "granules": granules,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.part")
    temporary.write_text(json.dumps(record, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)
    time.sleep(sleep)
    return path, requests


def plan(regions: dict, start: date = START, end: date = END) -> list[tuple[str, str, tuple, int]]:
    """Every ``(satellite, region, query bbox, year)`` chunk, in a fixed order."""
    boxes = {name: query_bbox(region_r4_cells(region["bounds"])) for name, region in sorted(regions.items())}
    return [(satellite, name, boxes[name], year) for satellite in COLLECTIONS for name in boxes
            for year, _, _ in year_windows(start, end)]


def fetch_all(client: httpx.Client, regions: dict, cache_dir: Path = CACHE_DIR, start: date = START,
              end: date = END, sleep: float = SLEEP, page_size: int = PAGE_SIZE, backoff=time.sleep) -> int:
    """Fetch every missing chunk sequentially; returns the number of HTTP requests sent."""
    chunks = plan(regions, start, end)
    sent = 0
    for number, (satellite, region, bbox, year) in enumerate(chunks, 1):
        _, requests = fetch_chunk(client, satellite, region, bbox, year, cache_dir, start, end, sleep,
                                  page_size, backoff=backoff)
        if requests:
            sent += requests
            print(f"  [{number}/{len(chunks)}] {satellite} {region} {year}: {requests} requests", flush=True)
    return sent


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_gap_table(regions: dict, cache_dir: Path = CACHE_DIR, output: Path = GAPS_PATH,
                    outages_path: Path = OUTAGES_PATH, start: date = START, end: date = END) -> Path:
    """Compact table ``(satellite, h3_r4, acq_date)`` of MODIS swath gaps from the cache; no network."""
    cells = sorted({cell for region in regions.values() for cell in region_r4_cells(region["bounds"])})
    points = cell_points(cells)
    outages = pq.read_table(outages_path, columns=["acq_date", "satellite"]).to_pylist()
    outage_days = {(row["satellite"], row["acq_date"]) for row in outages}
    columns = {"satellite": [], "h3_r4": [], "acq_date": []}
    stats = {"granules": {}, "acquiring_days": {}, "first_granule_day": {}, "excluded_days": {}, "rows": {},
             "concept_ids": {}}
    fetched = []
    for satellite in sorted(COLLECTIONS):
        listings, concepts = [], set()
        for name, bbox, year in [(n, b, y) for s, n, b, y in plan(regions, start, end) if s == satellite]:
            (_, t0, t1), = [w for w in year_windows(start, end) if w[0] == year]
            path = cache_path(cache_dir, satellite, name, year)
            if not _cached(path, _signature(satellite, bbox, t0, t1)):
                raise FileNotFoundError(f"Missing CMR cache for {satellite} {name} {year}: {path}. "
                                        "Run the fetch first.")
            record = json.loads(path.read_text())
            fetched.append(record["fetched_utc"])
            concepts.update(record["collection_concept_ids"])
            listings.extend(record["granules"])
        granules = dedupe(listings)
        covered, acquiring, unknown = {}, set(), set()
        for time_start, time_end, _, rings in granules:
            days = [day for day in granule_days(time_start, time_end) if start <= day <= end]
            if not days:
                continue
            acquiring.update(days)
            if not rings:
                unknown.update(days)
                continue
            hit = np.zeros(len(cells), dtype=bool)
            for ring in rings:
                hit |= covered_cells(list(zip(ring[0::2], ring[1::2])), points)
            for day in days:
                covered[day] = covered.get(day, np.zeros(len(cells), dtype=bool)) | hit
        outage = {day for sat, day in outage_days if sat == satellite and day in acquiring}
        count = 0
        for day in sorted(acquiring - unknown - outage):
            for index in np.flatnonzero(~covered.get(day, np.zeros(len(cells), dtype=bool))):
                columns["satellite"].append(satellite)
                columns["h3_r4"].append(cells[index])
                columns["acq_date"].append(day)
                count += 1
        stats["granules"][satellite] = len(granules)
        stats["acquiring_days"][satellite] = len(acquiring)
        stats["first_granule_day"][satellite] = min(acquiring).isoformat() if acquiring else None
        stats["excluded_days"][satellite] = {"outage": len(outage), "missing_footprint": len(unknown)}
        stats["rows"][satellite] = count
        stats["concept_ids"][satellite] = sorted(concepts)
    table = pa.table(columns, schema=SCHEMA).sort_by([(name, "ascending") for name in SCHEMA.names])
    provenance = {
        "source": "NASA CMR granule search, MODIS L1A geolocation (MOD03 Terra, MYD03 Aqua) footprint polygons",
        "url": URL,
        "collections": {sat: {"short_name": COLLECTIONS[sat][0], "version": COLLECTIONS[sat][1],
                              "concept_ids": stats["concept_ids"][sat]} for sat in sorted(COLLECTIONS)},
        "start": start.isoformat(), "end": end.isoformat(),
        "regions": sorted(regions), "cells": len(cells), "cell_rule": CELL_RULE,
        "coverage_rule": COVERAGE_RULE, "acquiring_rule": ACQUIRING_RULE, "limits": LIMITS,
        "granules": stats["granules"], "acquiring_days": stats["acquiring_days"],
        "first_granule_day": stats["first_granule_day"], "excluded_days": stats["excluded_days"],
        "rows": table.num_rows, "rows_by_satellite": stats["rows"],
        "outages_file": Path(outages_path).name, "outages_sha256": _sha256(outages_path),
        "fetch_date_utc": max(fetched)[:10] if fetched else None,
        "meaning": "row = this satellite acquired no granule covering this H3 R4 cell on this UTC day",
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    table = table.replace_schema_metadata({"modis_swath_gaps": json.dumps(provenance, sort_keys=True)})
    temporary = output.with_suffix(".parquet.part")
    pq.write_table(table, temporary, compression="zstd", compression_level=9, row_group_size=1 << 20,
                   use_dictionary=True, write_statistics=True)
    temporary.replace(output)
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--build-only", action="store_true", help="rebuild the table from the cache, no network")
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    parser.add_argument("--output", type=Path, default=GAPS_PATH)
    parser.add_argument("--outages", type=Path, default=OUTAGES_PATH,
                        help="stage 02 sensor_outages.parquet (outage days are never swath gaps)")
    parser.add_argument("--sleep", type=float, default=SLEEP, help="seconds between requests (default 1)")
    args = parser.parse_args(argv)
    regions = config.load_regions()
    print(f"{len(plan(regions))} (satellite, region, year) chunks for {len(regions)} regions", flush=True)
    if not args.build_only:
        with httpx.Client(headers=HEADERS, follow_redirects=True) as client:
            sent = fetch_all(client, regions, args.cache_dir, sleep=args.sleep)
        print(f"{sent} requests sent", flush=True)
    path = build_gap_table(regions, args.cache_dir, args.output, args.outages)
    print(f"Wrote {path} ({pq.ParquetFile(path).metadata.num_rows:,} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
