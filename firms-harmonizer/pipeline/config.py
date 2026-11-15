"""Paths, constants and the DuckDB connection factory for the real-data pipeline.

All outputs live under ``data/real/`` (see ``pipeline/README.md``). Outage, radiometric, footprint and
cube constants are not repeated here: they live only in the canonical ``scripts/01-04`` stages.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "data/real"
RAW = REAL / "raw"
STAGED = REAL / "staged"
TMP = REAL / ".tmp"
REGIONS = REAL / "regions"
GLOBAL_COUNTS = REAL / "global_daily_counts.parquet"
ARCHIVE_PASS = REAL / "archive_pass"
ARCHIVE_COUNTS = ROOT / "data/lookup/global_daily_counts_archive.csv"
PRESET_REGIONS = ("chilecito_la_rioja", "iberia_med", "orlando_florida", "amazonas_manaus")
REPORT_MD = REAL / "quality_report.md"
REPORT_JSON = REAL / "quality_report.json"
REGIONS_PATH = ROOT / "data/regions.json"

ARCHIVE_URL = "https://firms.modaps.eosdis.nasa.gov/data/country/zips/{product}_{year}_all_countries.zip"
# product -> first and last yearly archive published by FIRMS (verified 2026-11-14 with HEAD requests)
PRODUCTS = {"modis": (2000, 2025), "viirs-snpp": (2012, 2025), "viirs-jpss1": (2018, 2025)}

# FIRMS `satellite` codes -> canonical sensor names (same canon as scripts/01_ingest_firms.py)
SENSORS = {"T": "Terra", "TERRA": "Terra", "A": "Aqua", "AQUA": "Aqua", "N": "SNPP", "NPP": "SNPP",
           "SUOMI-NPP": "SNPP", "SNPP": "SNPP", "1": "N20", "N20": "N20", "NOAA20": "N20", "NOAA-20": "N20",
           "J1": "N20", "2": "N21", "N21": "N21", "NOAA21": "N21", "NOAA-21": "N21", "J2": "N21"}
SENSOR_BITS = {"Terra": 1, "Aqua": 2, "SNPP": 4, "N20": 8, "N21": 16}
MODIS_SENSORS = ("Terra", "Aqua")

EPOCH = date(1970, 1, 1)
FIRST_DAY, LAST_DAY = date(2000, 11, 1), date(2026, 12, 31)      # scripts/01 validity window
PAIRS_START = date(2012, 1, 19)                                  # first SNPP science data

# Global-ingest pre-filter, identical to backend.core.industrial_filter.filter_sama_anomalies (the rule
# scripts/01 applies). Parity with scripts/01 is tested in pipeline/tests.
SAMA_BOX = (-35.0, -15.0, -65.0, -30.0)                           # lat_min, lat_max, lon_min, lon_max
SAMA_MAX_CONTRAST_K = 1.5

DUCKDB_MEMORY_LIMIT = "2GB"
DUCKDB_THREADS = 2
EXTENSION_DIR = Path(sys.prefix) / "duckdb_extensions"


def load_regions(path: Path = REGIONS_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def region_dir(region: str) -> Path:
    """Working folder of one regional build: canonical staging, lookups, pairs and cube."""
    return REGIONS / region


def connect(memory_limit: str = DUCKDB_MEMORY_LIMIT, threads: int = DUCKDB_THREADS) -> duckdb.DuckDBPyConnection:
    """DuckDB connection with the H3 extension loaded from the pipeline venv (never downloaded here)."""
    if not (EXTENSION_DIR.is_dir() and any(EXTENSION_DIR.rglob("h3.duckdb_extension"))):
        raise RuntimeError(
            f"DuckDB h3 extension not found in {EXTENSION_DIR}. Install it once with the interpreter that runs "
            "the pipeline (see pipeline/README.md): python -c \"import duckdb,sys; duckdb.connect(config="
            "{'extension_directory': sys.prefix + '/duckdb_extensions'}).execute('INSTALL h3 FROM community')\"")
    TMP.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(config={"extension_directory": str(EXTENSION_DIR), "autoinstall_known_extensions": False,
                                 "autoload_known_extensions": False})
    con.execute("LOAD h3")
    con.execute("SET memory_limit = ?", [memory_limit])
    con.execute("SET threads = ?", [threads])
    con.execute("SET temp_directory = ?", [str(TMP)])
    con.execute("SET preserve_insertion_order = false")
    return con
