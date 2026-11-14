"""NASA FIRMS near-real-time (NRT) area API client.

Fetches active-fire CSV for a bounding box through the FIRMS area endpoint and
parses it into plain dictionaries. The module is intentionally offline-safe:
it performs no request at import time. Automatic polling requires NRT_POLLING=1.

The FIRMS map key is read from ``FIRMS_MAP_KEY`` (``.env`` or the process
environment). The key is part of the request path, so it is never included in
error messages or logs emitted here.
"""

from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
import csv
import io
import json
import logging
import math
import os
import re
import tempfile
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import duckdb
import h3
import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from backend.db import duckdb_engine

try:  # python-dotenv is an optional runtime convenience for the CLI.
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - the pinned requirements include it
    def load_dotenv(*_args, **_kwargs) -> bool:
        return False

ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
MAX_DAY_RANGE = 5
DEFAULT_TIMEOUT_SECONDS = 30.0
_SOURCE_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_FLOAT_FIELDS = frozenset({
    "latitude", "longitude", "bright_ti4", "bright_ti5", "brightness",
    "scan", "track", "frp",
})


class NrtPollerError(RuntimeError):
    """Raised for configuration, transport or response errors."""


def _map_key(explicit: str | None = None) -> str:
    """Return a non-empty FIRMS map key without ever logging it."""
    load_dotenv()
    key = (explicit if explicit is not None else os.environ.get("FIRMS_MAP_KEY", "")).strip()
    if not key:
        raise NrtPollerError(
            "FIRMS_MAP_KEY is not set. Add it to the repository .env or export it before polling."
        )
    return key


def _bbox(value: tuple[float, float, float, float] | list[float]) -> str:
    """Validate ``(west, south, east, north)`` and format it for the FIRMS path."""
    try:
        west, south, east, north = (float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise NrtPollerError("The bounding box must be (west, south, east, north) numbers.") from exc
    if not (-180.0 <= west < east <= 180.0):
        raise NrtPollerError("Longitudes must satisfy -180 <= west < east <= 180.")
    if not (-90.0 <= south < north <= 90.0):
        raise NrtPollerError("Latitudes must satisfy -90 <= south < north <= 90.")
    return f"{west:.4f},{south:.4f},{east:.4f},{north:.4f}"


def _source(value: str) -> str:
    source = value.strip()
    if not _SOURCE_RE.fullmatch(source):
        raise NrtPollerError("The FIRMS source may only contain letters, digits, '_' and '-'.")
    return source


def _day_range(value: int) -> int:
    days = int(value)
    if not 1 <= days <= MAX_DAY_RANGE:
        raise NrtPollerError(f"The FIRMS area API accepts a day range of 1..{MAX_DAY_RANGE}.")
    return days


def _date(value: str | date | None) -> str | None:
    if value in (None, ""):
        return None
    try:
        parsed = value if isinstance(value, date) else date.fromisoformat(str(value))
    except ValueError as exc:
        raise NrtPollerError("The date must be ISO YYYY-MM-DD.") from exc
    if parsed > datetime.now(timezone.utc).date():
        raise NrtPollerError("The date cannot be in the future.")
    return parsed.isoformat()


def fetch_nrt_csv(
    bbox: tuple[float, float, float, float] | list[float],
    *,
    source: str = "VIIRS_SNPP_NRT",
    days: int = 1,
    start_date: str | date | None = None,
    map_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport: httpx.BaseTransport | None = None,
) -> bytes:
    """Return the raw FIRMS CSV for one bbox/source/day-range request.

    ``transport`` is injectable so tests can avoid the network. The request URL
    is built here but never placed in an exception message.
    """
    key = _map_key(map_key)
    area = _bbox(bbox)
    source_id = _source(source)
    day_range = _day_range(days)
    day = _date(start_date)
    url = f"{BASE_URL}/{quote(key, safe='')}/{source_id}/{area}/{day_range}"
    if day is not None:
        url += f"/{day}"
    try:
        with httpx.Client(timeout=timeout, transport=transport, follow_redirects=True) as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        raise NrtPollerError(f"FIRMS NRT request failed: {type(exc).__name__}.") from None
    if response.status_code != 200:
        raise NrtPollerError(f"FIRMS NRT responded with HTTP {response.status_code}.")
    body = response.content
    if body.lstrip().lower().startswith(b"<"):
        raise NrtPollerError("FIRMS NRT returned an HTML error page instead of CSV.")
    return body


def parse_nrt_csv(raw: bytes) -> list[dict]:
    """Parse a FIRMS CSV payload; known numeric fields become ``float``.

    ``confidence`` is kept as text because VIIRS sends ``n``/``h``/``l`` while
    MODIS sends a percentage. ``acq_time`` stays a four-character UTC string.
    """
    if not raw.strip():
        return []
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []
    records: list[dict] = []
    for row in reader:
        record: dict = {}
        for name, value in row.items():
            if name is None:
                continue
            cleaned = value.strip() if isinstance(value, str) else value
            if name in _FLOAT_FIELDS and cleaned not in ("", None):
                try:
                    record[name] = float(cleaned)
                    continue
                except (TypeError, ValueError):
                    pass
            record[name] = cleaned
        records.append(record)
    return records


def fetch_nrt(
    bbox: tuple[float, float, float, float] | list[float],
    **kwargs,
) -> list[dict]:
    """Fetch and parse NRT detections for ``bbox`` (see :func:`fetch_nrt_csv`)."""
    return parse_nrt_csv(fetch_nrt_csv(bbox, **kwargs))


def write_nrt_csv(raw: bytes, output: str | Path) -> Path:
    """Write a raw FIRMS CSV payload to ``output`` and return the final path."""
    path = Path(output)
    if path.suffix.lower() != ".csv":
        path = path / "firms_nrt.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


logger = logging.getLogger(__name__)

EPOCH = date(1970, 1, 1)
DEFAULT_POLL_INTERVAL_SECONDS = 900  # 15 minutes per ADR-03

_NRT_TASK: asyncio.Task[None] | None = None
_NRT_STATUS: dict[str, str | int | None] = {
    "status": "idle",
    "last_poll_utc": None,
    "last_success_utc": None,
    "rows_ingested": 0,
    "last_error": None,
}


def _parse_nrt_records(records: list[dict[str, str]]) -> pa.Table:
    """Parse raw FIRMS CSV records into a typed PyArrow table with H3 indices."""
    h3_r4_list: list[int] = []
    h3_r7_list: list[int] = []
    epoch_day_list: list[int] = []
    year_list: list[int] = []
    doy_list: list[int] = []
    lat_list: list[float] = []
    lon_list: list[float] = []
    frp_list: list[float] = []
    satellite_list: list[str] = []
    daynight_list: list[str] = []

    for row in records:
        try:
            lat = float(row["latitude"])
            lon = float(row["longitude"])
            frp = float(row.get("frp") or 0.0)
            if not (-90 <= lat <= 90 and -180 <= lon <= 180 and math.isfinite(frp) and frp >= 0):
                continue
            acq_date_str = row["acq_date"].strip()
            acq_date = datetime.strptime(acq_date_str, "%Y-%m-%d").date()
            epoch_day = (acq_date - EPOCH).days
            if not 0 <= epoch_day <= 65535:
                continue
            year = acq_date.year
            doy = int(acq_date.strftime("%j"))
            satellite = row.get("satellite", "SNPP").strip()
            daynight = row.get("daynight", "D").strip().upper()

            c7 = int(h3.latlng_to_cell(lat, lon, 7), 16)
            c4 = int(h3.cell_to_parent(format(c7, "x"), 4), 16)

            h3_r4_list.append(c4)
            h3_r7_list.append(c7)
            epoch_day_list.append(epoch_day)
            year_list.append(year)
            doy_list.append(doy)
            lat_list.append(lat)
            lon_list.append(lon)
            frp_list.append(frp)
            satellite_list.append(satellite)
            daynight_list.append(daynight)
        except (KeyError, ValueError, TypeError, OverflowError):
            logger.debug("Skipping invalid NRT row")
            continue

    schema = pa.schema([
        pa.field("h3_r4", pa.uint64()),
        pa.field("h3_r7", pa.uint64()),
        pa.field("epoch_day", pa.uint16()),
        pa.field("year", pa.uint16()),
        pa.field("doy", pa.uint16()),
        pa.field("latitude", pa.float64()),
        pa.field("longitude", pa.float64()),
        pa.field("raw_frp_mw", pa.float32()),
        pa.field("satellite", pa.string()),
        pa.field("daynight", pa.string()),
    ])

    return pa.Table.from_arrays([
        pa.array(h3_r4_list, type=pa.uint64()),
        pa.array(h3_r7_list, type=pa.uint64()),
        pa.array(epoch_day_list, type=pa.uint16()),
        pa.array(year_list, type=pa.uint16()),
        pa.array(doy_list, type=pa.uint16()),
        pa.array(lat_list, type=pa.float64()),
        pa.array(lon_list, type=pa.float64()),
        pa.array(frp_list, type=pa.float32()),
        pa.array(satellite_list, type=pa.string()),
        pa.array(daynight_list, type=pa.string()),
    ], schema=schema)


def ingest_nrt_csv_text(csv_text: str) -> int:
    """Ingest CSV content into the in-memory `nrt_hotspots` DuckDB table."""
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    records = list(reader)
    if not records:
        logger.info("NRT CSV is empty; zero rows ingested.")
        return 0

    arrow_table = _parse_nrt_records(records)
    with duckdb_engine.get_db_cursor() as cursor:
        cursor.register("incoming_nrt_arrow", arrow_table)
        try:
            cursor.execute("CREATE OR REPLACE TABLE nrt_hotspots AS SELECT * FROM incoming_nrt_arrow")
        finally:
            cursor.unregister("incoming_nrt_arrow")

    count = len(arrow_table)
    _NRT_STATUS["rows_ingested"] = count
    _NRT_STATUS["last_success_utc"] = datetime.now(timezone.utc).isoformat()
    _NRT_STATUS["status"] = "active"
    logger.info("Ingested %d NRT hotspots into in-memory table `nrt_hotspots`.", count)
    return count


def ingest_nrt_csv_file(path: Path | str) -> int:
    """Ingest a local FIRMS NRT CSV file into DuckDB."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"NRT file not found: {p}")
    return ingest_nrt_csv_text(p.read_text(encoding="utf-8"))


async def poll_firms_nrt_once(
    map_key: str | None = None,
    bbox: tuple[float, float, float, float] = (-180, -90, 180, 90),
    days: int = 1,
    source: str = "VIIRS_SNPP_NRT",
) -> int:
    """Fetch and ingest one batch without blocking the event loop."""
    key = map_key or os.environ.get("FIRMS_MAP_KEY")
    _NRT_STATUS["last_poll_utc"] = datetime.now(timezone.utc).isoformat()
    if (not key or os.environ.get("OFFLINE_MODE") == "1"
            or os.environ.get("AIRPLANE_MODE") == "1"
            or os.environ.get("USE_SYNTHETIC_CUBE") == "1"):
        _NRT_STATUS.update(status="offline_standby", last_error=None)
        return 0
    try:
        raw = await asyncio.to_thread(fetch_nrt_csv, bbox, map_key=key, days=days, source=source)
        count = await asyncio.to_thread(ingest_nrt_csv_text, raw.decode("utf-8-sig"))
        _NRT_STATUS.update(status="active", rows_ingested=count, last_error=None,
                           last_success_utc=datetime.now(timezone.utc).isoformat())
        return count
    except NrtPollerError as exc:
        _NRT_STATUS.update(status="error", last_error=str(exc))
        return 0
    except (UnicodeError, pa.ArrowException, duckdb.Error) as exc:
        _NRT_STATUS.update(status="error", last_error=f"FIRMS ingestion failed: {type(exc).__name__}.")
        return 0


MIN_ORBITAL_WEIGHT = float(math.cos(math.radians(80.0)))

PRESET_REGIONS: dict[str, tuple[float, float, float, float]] = {
    "chilecito_la_rioja": (-69.5, -31.0, -65.5, -27.5),
    "orlando_florida": (-82.0, 28.0, -80.7, 29.3),
    "amazonas_manaus": (-62.0, -5.0, -58.0, -1.0),
    "iberia_med": (-9.5, 36.0, 4.0, 44.0),
}
NOMINAL_BIOMES: dict[str, int] = {
    "chilecito_la_rioja": 16,
    "orlando_florida": 8,
    "amazonas_manaus": 2,
    "iberia_med": 8,
}
SYNC_SOURCES: tuple[str, ...] = (
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
    "VIIRS_SNPP_NRT",
    "MODIS_NRT",
)
SENSOR_BITS: dict[str, int] = {
    "TERRA": 1,
    "AQUA": 2,
    "SNPP": 4,
    "N20": 8,
    "NOAA20": 8,
    "NOAA-20": 8,
    "J1": 8,
    "N21": 16,
    "NOAA21": 16,
    "NOAA-21": 16,
    "J2": 16,
}

CUBE_SCHEMA = pa.schema([
    pa.field("h3_r4", pa.uint64()),
    pa.field("h3_r7", pa.uint64()),
    pa.field("epoch_day", pa.uint16()),
    pa.field("year", pa.uint16()),
    pa.field("doy", pa.uint16()),
    pa.field("igbp_biome", pa.uint8()),
    pa.field("sensor_obs_mask", pa.uint8()),
    pa.field("gap_status_mask", pa.uint8()),
    pa.field("cloud_cover_pct", pa.float32()),
    pa.field("raw_modis_cnt", pa.uint16()),
    pa.field("raw_viirs_cnt", pa.uint16()),
    pa.field("raw_frp_mw", pa.float32()),
    pa.field("obs_terra_fre", pa.float32()),
    pa.field("obs_aqua_fre", pa.float32()),
    pa.field("obs_viirs_fre", pa.float32()),
    pa.field("neighbor_fre_lag1", pa.float32()),
    pa.field("industrial_prob", pa.float32()),
    pa.field("burned_area_ha_mcd64", pa.float32()),
])

_SYNC_LOCK = threading.Lock()
_CUBE_SYNC_STATUS: dict[str, Any] = {
    "status": "idle",
    "last_synced_utc": None,
    "new_detections_count": 0,
    "date_coverage_start": None,
    "date_coverage_end": None,
    "regions_updated": [],
    "message": "Ready to synchronize.",
    "data_source": "real",
    "error": None,
}


def _orbital_weight(c7: int) -> float:
    latitude, _ = h3.cell_to_latlng(format(c7, "x"))
    return float(max(math.cos(math.radians(latitude)), MIN_ORBITAL_WEIGHT))


def _cell_scale(c7: int) -> float:
    area = h3.cell_area(format(c7, "x"), unit="km^2")
    return (3600.0 / area) * _orbital_weight(c7)


def get_configured_regions() -> dict[str, tuple[float, float, float, float]]:
    regions_file = ROOT / "data/regions.json"
    if regions_file.is_file():
        try:
            data = json.loads(regions_file.read_text(encoding="utf-8"))
            out = {}
            for name, reg in data.items():
                if "bounds" in reg and len(reg["bounds"]) == 4:
                    out[name] = tuple(float(x) for x in reg["bounds"])
            if out:
                return out
        except Exception:
            pass
    return dict(PRESET_REGIONS)


def get_sync_status() -> dict[str, Any]:
    """Return the current synchronization status and latest sync metrics."""
    st = dict(_CUBE_SYNC_STATUS)
    try:
        st["data_source"] = duckdb_engine.data_source()
        with duckdb.connect() as con:
            first, last = con.execute(
                "SELECT min(epoch_day), max(epoch_day) FROM read_parquet(?)",
                [str(duckdb_engine.cube_path())],
            ).fetchone()
        st["date_coverage_start"] = (EPOCH + timedelta(days=first)).isoformat() if first is not None else None
        st["date_coverage_end"] = (EPOCH + timedelta(days=last)).isoformat() if last is not None else None
    except (duckdb.Error, duckdb_engine.CubeNotAvailableError, OSError):
        st.update(date_coverage_start=None, date_coverage_end=None)
    return st


def sync_cube(
    days: int | None = None,
    sync_full_month: bool = False,
    regions: list[str] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Synchronize live NASA FIRMS active-fire data for preset regions into the master cube."""
    with _SYNC_LOCK:
        _CUBE_SYNC_STATUS["status"] = "in_progress"
        _CUBE_SYNC_STATUS["error"] = None
        now_utc = datetime.now(timezone.utc)
        target_regions = [r for r in (regions or list(PRESET_REGIONS.keys())) if r in PRESET_REGIONS]
        if not target_regions:
            target_regions = list(PRESET_REGIONS.keys())

        if os.environ.get("USE_SYNTHETIC_CUBE") == "1":
            _CUBE_SYNC_STATUS.update({
                "status": "idle",
                "message": "FIRMS updates are unavailable in synthetic mode.",
            })
            return get_sync_status()
        if os.environ.get("OFFLINE_MODE") == "1" or os.environ.get("AIRPLANE_MODE") == "1":
            _CUBE_SYNC_STATUS.update(status="error", error="FIRMS updates require an internet connection.")
            return get_sync_status()

        # In real mode, verify API key
        try:
            key = _map_key()
        except NrtPollerError as exc:
            _CUBE_SYNC_STATUS.update({
                "status": "error",
                "error": str(exc),
                "message": "Sync failed due to missing FIRMS key.",
            })
            return get_sync_status()

        today_val = now_utc.date()
        if sync_full_month:
            start_date = today_val.replace(day=1)
        elif days is not None:
            start_date = today_val - timedelta(days=min(max(int(days), 1), 30) - 1)
        else:
            status = get_sync_status()
            last = status["date_coverage_end"]
            if last is None:
                _CUBE_SYNC_STATUS.update(status="error", error="Could not read the local cube dates.")
                return get_sync_status()
            start_date = min(date.fromisoformat(last), today_val) - timedelta(days=1)

        chunks = []
        while start_date <= today_val:
            span = min(MAX_DAY_RANGE, (today_val - start_date).days + 1)
            chunks.append((start_date.isoformat(), span))
            start_date += timedelta(days=span)

        # Fetch concurrently across regions and sources
        def _fetch_worker(item):
            reg, bbox, src, sdate, span = item
            try:
                raw_bytes = fetch_nrt_csv(
                    bbox,
                    source=src,
                    days=span,
                    start_date=sdate,
                    map_key=key,
                    timeout=15.0,
                    transport=transport,
                )
                fields = csv.DictReader(io.StringIO(raw_bytes.decode("utf-8-sig"))).fieldnames or []
                if not {"latitude", "longitude", "acq_date"}.issubset(fields):
                    raise NrtPollerError("FIRMS returned an invalid CSV header.")
                parsed = parse_nrt_csv(raw_bytes)
                csv_path = ROOT / f"data/raw/sync_{reg}_{src}_{sdate}_{span}d.csv"
                write_nrt_csv(raw_bytes, csv_path)
                return reg, src, parsed
            except (NrtPollerError, OSError, UnicodeError, csv.Error) as exc:
                logger.warning("FIRMS sync failed for %s %s: %s", reg, src, exc)
                return reg, src, None

        work_items = []
        for reg in target_regions:
            bbox = PRESET_REGIONS[reg]
            for src in SYNC_SOURCES:
                for sdate, span in chunks:
                    work_items.append((reg, bbox, src, sdate, span))

        all_records: list[tuple[str, str, dict]] = []
        failed = 0
        with ThreadPoolExecutor(max_workers=min(16, max(1, len(work_items)))) as pool:
            for reg, src, rows in pool.map(_fetch_worker, work_items):
                if rows is None:
                    failed += 1
                else:
                    all_records.extend((reg, src, row) for row in rows)
        if failed:
            _CUBE_SYNC_STATUS.update(status="error", error=f"FIRMS update failed for {failed} of {len(work_items)} requests.")
            return get_sync_status()

        # Deduplicate detections
        seen_identities = set()
        deduped: list[tuple[str, str, dict]] = []
        for reg, src, row in all_records:
            try:
                lat = float(row["latitude"])
                lon = float(row["longitude"])
                acq_d = str(row["acq_date"]).strip()
                acq_t = str(row.get("acq_time", "")).strip()
                sat = str(row.get("satellite", "")).strip().upper()
                ident = (sat, acq_d, acq_t, round(lat, 4), round(lon, 4))
                if ident in seen_identities:
                    continue
                seen_identities.add(ident)
                deduped.append((reg, src, row))
            except (KeyError, ValueError, TypeError):
                continue

        # Aggregate into daily H3 cube rows
        daily_cells: dict[tuple[int, int], dict[str, Any]] = {}
        for reg, src, row in deduped:
            try:
                lat = float(row["latitude"])
                lon = float(row["longitude"])
                frp = float(row.get("frp") or 0.0)
                if not (abs(lat) <= 90 and abs(lon) <= 180 and math.isfinite(frp) and frp >= 0):
                    continue
                acq_d = datetime.strptime(str(row["acq_date"]).strip(), "%Y-%m-%d").date()
                epoch_d = (acq_d - EPOCH).days
                c7 = int(h3.latlng_to_cell(lat, lon, 7), 16)
                c4 = int(h3.cell_to_parent(format(c7, "x"), 4), 16)
                key_cell = (c7, epoch_d)

                if key_cell not in daily_cells:
                    daily_cells[key_cell] = {
                        "h3_r4": c4,
                        "h3_r7": c7,
                        "epoch_day": epoch_d,
                        "year": acq_d.year,
                        "doy": int(acq_d.strftime("%j")),
                        "igbp_biome": NOMINAL_BIOMES.get(reg, 8),
                        "sensor_obs_mask": 0,
                        "gap_status_mask": 0,
                        "cloud_cover_pct": 0.0,
                        "raw_modis_cnt": 0,
                        "raw_viirs_cnt": 0,
                        "raw_frp_mw": 0.0,
                        "obs_terra_fre": None,
                        "obs_aqua_fre": None,
                        "obs_viirs_fre": None,
                        "neighbor_fre_lag1": 0.0,
                        "industrial_prob": 0.0,
                        "burned_area_ha_mcd64": 0.0,
                        "_terra": [],
                        "_aqua": [],
                        "_viirs": [],
                    }

                cell_entry = daily_cells[key_cell]
                sat = str(row.get("satellite", "")).strip().upper()
                bit = SENSOR_BITS.get(sat, 4)
                cell_entry["sensor_obs_mask"] |= bit
                cell_entry["raw_frp_mw"] += frp

                is_modis = ("MODIS" in src) or (sat in ("TERRA", "AQUA", "T", "A"))
                if is_modis:
                    cell_entry["raw_modis_cnt"] += 1
                    if sat in ("TERRA", "T"):
                        cell_entry["_terra"].append(frp)
                    else:
                        cell_entry["_aqua"].append(frp)
                else:
                    cell_entry["raw_viirs_cnt"] += 1
                    cell_entry["_viirs"].append(frp)
            except Exception:
                continue

        # Finalize FRE energy proxies
        for entry in daily_cells.values():
            scale = _cell_scale(entry["h3_r7"])
            if entry["_terra"]:
                entry["obs_terra_fre"] = float(sum(entry["_terra"]) * scale)
            if entry["_aqua"]:
                entry["obs_aqua_fre"] = float(sum(entry["_aqua"]) * scale)
            if entry["_viirs"]:
                entry["obs_viirs_fre"] = float((sum(entry["_viirs"]) / len(entry["_viirs"])) * scale)
            del entry["_terra"], entry["_aqua"], entry["_viirs"]

        # Merge with existing master parquet cube
        cube_path = duckdb_engine.cube_path()
        if daily_cells and cube_path.is_file() and duckdb_engine.data_source() == "real":
            incoming_table = pa.Table.from_pylist(list(daily_cells.values()), schema=CUBE_SCHEMA)
            existing_table = pq.read_table(cube_path)
            with duckdb.connect() as con:
                con.register("existing_cube", existing_table)
                con.register("incoming_rows", incoming_table)
                con.execute("""
                    CREATE TABLE merged_cube AS
                    SELECT * FROM existing_cube
                    WHERE NOT EXISTS (
                        SELECT 1 FROM incoming_rows i
                        WHERE i.h3_r7 = existing_cube.h3_r7 AND i.epoch_day = existing_cube.epoch_day
                    )
                    UNION ALL BY NAME
                    SELECT * FROM incoming_rows
                    ORDER BY h3_r4, epoch_day, h3_r7
                """)
                merged_table = con.sql("SELECT * FROM merged_cube").to_arrow_table()

            meta = pq.read_schema(cube_path).metadata or {}
            meta[b"real_rows"] = str(len(merged_table)).encode()
            merged_table = merged_table.replace_schema_metadata(meta)
            with tempfile.NamedTemporaryFile(dir=cube_path.parent, suffix=".parquet", delete=False) as tmp:
                output = Path(tmp.name)
            try:
                pq.write_table(merged_table, output, compression="zstd", row_group_size=32768, write_statistics=True)
                output.replace(cube_path)
            except (pa.ArrowException, OSError) as exc:
                logger.warning("Could not publish the updated FIRMS cube: %s", exc)
                _CUBE_SYNC_STATUS.update(status="error", error="Could not save the updated FIRMS cube. Try again.")
                return get_sync_status()
            finally:
                output.unlink(missing_ok=True)

        _CUBE_SYNC_STATUS.update({
            "status": "success",
            "last_synced_utc": now_utc.isoformat(),
            "new_detections_count": len(deduped),
            "regions_updated": target_regions,
            "message": f"Successfully synchronized {len(deduped)} live FIRMS detections for {len(target_regions)} regions.",
            "data_source": "real",
            "error": None,
        })
        return get_sync_status()


async def nrt_poller_loop(
    interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
    map_key: str | None = None,
) -> None:
    """Continuous background polling loop for FastAPI lifespan."""
    logger.info("Starting FIRMS NRT Poller loop (interval=%ds).", interval_seconds)
    while True:
        try:
            _NRT_STATUS.update(status="polling", last_poll_utc=datetime.now(timezone.utc).isoformat())
            result = await asyncio.to_thread(sync_cube)
            _NRT_STATUS.update(
                status="active" if result["status"] == "success" else result["status"],
                last_success_utc=result.get("last_synced_utc"),
                last_error=result.get("error"),
                rows_ingested=result.get("new_detections_count", 0),
            )
        except asyncio.CancelledError:
            logger.info("NRT Poller loop received cancellation. Stopping.")
            break
        except Exception as exc:
            logger.error("Unexpected error in NRT poller: %s", exc)
            _NRT_STATUS.update(status="error", last_error="FIRMS update failed.")
        await asyncio.sleep(interval_seconds)


def start_nrt_poller(interval_seconds: int | None = None) -> None:
    """Launch the background asyncio NRT poller task."""
    global _NRT_TASK
    if os.environ.get("NRT_POLLING") != "1" and os.environ.get("AUTO_SYNC") != "1":
        return
    if any(os.environ.get(name) == "1" for name in ("USE_SYNTHETIC_CUBE", "OFFLINE_MODE", "AIRPLANE_MODE")):
        _NRT_STATUS.update(status="offline_standby")
        return
    if _NRT_TASK is not None and not _NRT_TASK.done():
        logger.info("NRT Poller task is already running.")
        return
    sec = interval_seconds or int(os.environ.get("NRT_POLL_INTERVAL_SECONDS", DEFAULT_POLL_INTERVAL_SECONDS))
    try:
        loop = asyncio.get_running_loop()
        _NRT_TASK = loop.create_task(nrt_poller_loop(interval_seconds=sec))
    except RuntimeError:
        logger.debug("No running asyncio event loop; poller task not started.")


def stop_nrt_poller() -> None:
    """Cancel the background asyncio NRT poller task."""
    global _NRT_TASK
    if _NRT_TASK is not None and not _NRT_TASK.done():
        _NRT_TASK.cancel()
        _NRT_TASK = None
        _NRT_STATUS["status"] = "stopped"
        _CUBE_SYNC_STATUS["status"] = "idle"
        logger.info("NRT Poller task stopped.")


def get_nrt_status() -> dict[str, str | int | None]:
    """Return live status of the NRT poller."""
    return dict(_NRT_STATUS)



def _cli() -> int:
    parser = argparse.ArgumentParser(description="Fetch NASA FIRMS NRT active-fire CSV for a bounding box.")
    parser.add_argument("--bbox", nargs=4, type=float, required=True,
                        metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    parser.add_argument("--source", default="VIIRS_SNPP_NRT")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--date", dest="start_date", default=None, help="ISO start date (default: FIRMS latest)")
    parser.add_argument("--output", default=str(ROOT / "data/raw/nrt"))
    args = parser.parse_args()
    try:
        raw = fetch_nrt_csv(args.bbox, source=args.source, days=args.days, start_date=args.start_date)
    except NrtPollerError as exc:
        parser.error(str(exc))
    records = parse_nrt_csv(raw)
    if args.output.endswith(".csv"):
        path = write_nrt_csv(raw, args.output)
    else:
        stamp = args.start_date or date.today().isoformat()
        path = write_nrt_csv(raw, Path(args.output) / f"{args.source}_{stamp}.csv")
    print(f"Wrote {len(records)} detections to {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(_cli())
