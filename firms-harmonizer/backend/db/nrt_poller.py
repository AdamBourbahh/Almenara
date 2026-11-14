"""NASA FIRMS Near-Real-Time (NRT) Poller and In-Memory DuckDB Ingestion.

Implements ADR-03 Zero-Broker NRT Ingestion (SPECS.md / docs/Nasa.pdf).
Fetches active hotspots from NASA FIRMS NRT API or local staging,
projects coordinates to H3 resolutions 4 and 7, and updates an in-memory
`nrt_hotspots` table inside DuckDB. Operates with full offline resilience.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import h3
import httpx
import pyarrow as pa

from backend.db import duckdb_engine

logger = logging.getLogger(__name__)

EPOCH = date(1970, 1, 1)
DEFAULT_POLL_INTERVAL_SECONDS = 900  # 15 minutes per ADR-03
FIRMS_NRT_BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
SUPPORTED_SOURCES = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "MODIS_NRT")

_NRT_TASK: asyncio.Task[None] | None = None
_NRT_STATUS: dict[str, Any] = {
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
            acq_date_str = row["acq_date"].strip()
            acq_date = datetime.strptime(acq_date_str, "%Y-%m-%d").date()
            epoch_day = (acq_date - EPOCH).days
            year = acq_date.year
            doy = int(acq_date.strftime("%j"))
            satellite = row.get("satellite", "SNPP").strip()
            daynight = row.get("daynight", "D").strip().upper()

            c7 = int(h3.latlng_to_cell(lat, lon, 7), 16)
            c4 = int(h3.latlng_to_cell(lat, lon, 4), 16)

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
        except (KeyError, ValueError) as err:
            logger.debug("Skipping invalid NRT row %s: %s", row, err)
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
    conn = duckdb_engine.init_engine()

    # Register table atomically in memory
    conn.register("incoming_nrt_arrow", arrow_table)
    try:
        conn.execute("CREATE OR REPLACE TABLE nrt_hotspots AS SELECT * FROM incoming_nrt_arrow")
    finally:
        conn.unregister("incoming_nrt_arrow")

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
    bbox: str = "-180,-90,180,90",
    days: int = 1,
    source: str = "VIIRS_SNPP_NRT",
) -> int:
    """Fetch one batch of NRT observations from NASA FIRMS API."""
    key = map_key or os.environ.get("FIRMS_MAP_KEY")
    _NRT_STATUS["last_poll_utc"] = datetime.now(timezone.utc).isoformat()

    # Offline-first resilience: if no key or offline flag, stay idle without crashing
    if not key or os.environ.get("OFFLINE_MODE") == "1" or os.environ.get("AIRPLANE_MODE") == "1":
        _NRT_STATUS["status"] = "offline_standby"
        logger.info("NRT poller in offline mode (no FIRMS_MAP_KEY or OFFLINE_MODE=1).")
        return 0

    url = f"{FIRMS_NRT_BASE_URL}/{key}/{source}/{bbox}/{days}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and resp.text:
                return ingest_nrt_csv_text(resp.text)
            logger.warning("FIRMS NRT API HTTP %d: %s", resp.status_code, resp.text[:200])
            _NRT_STATUS["status"] = "warning"
            _NRT_STATUS["last_error"] = f"HTTP {resp.status_code}"
            return 0
    except Exception as exc:
        logger.warning("FIRMS NRT network check failed: %s", exc)
        _NRT_STATUS["status"] = "error"
        _NRT_STATUS["last_error"] = str(exc)
        return 0


async def nrt_poller_loop(
    interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
    map_key: str | None = None,
) -> None:
    """Continuous background polling loop for FastAPI lifespan."""
    logger.info("Starting FIRMS NRT Poller loop (interval=%ds).", interval_seconds)
    while True:
        try:
            await poll_firms_nrt_once(map_key=map_key)
        except asyncio.CancelledError:
            logger.info("NRT Poller loop received cancellation. Stopping.")
            break
        except Exception as exc:
            logger.error("Unexpected error in NRT poller: %s", exc)
        await asyncio.sleep(interval_seconds)


def start_nrt_poller(interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS) -> None:
    """Launch the background asyncio NRT poller task."""
    global _NRT_TASK
    if _NRT_TASK is not None and not _NRT_TASK.done():
        logger.info("NRT Poller task is already running.")
        return
    try:
        loop = asyncio.get_running_loop()
        _NRT_TASK = loop.create_task(nrt_poller_loop(interval_seconds=interval_seconds))
    except RuntimeError:
        logger.debug("No running asyncio event loop; poller task not started.")


def stop_nrt_poller() -> None:
    """Cancel the background asyncio NRT poller task."""
    global _NRT_TASK
    if _NRT_TASK is not None and not _NRT_TASK.done():
        _NRT_TASK.cancel()
        _NRT_TASK = None
        _NRT_STATUS["status"] = "stopped"
        logger.info("NRT Poller task stopped.")


def get_nrt_status() -> dict[str, Any]:
    """Return live status of the NRT poller."""
    return dict(_NRT_STATUS)
