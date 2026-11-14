"""Paths, constants and the DuckDB connection factory for the real-data pipeline.

All outputs live under ``data/real/``. Constants inherited from Germán's ``scripts/01-04`` keep
their original values; the new ones are documented in ``pipeline/README.md``.
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
LOOKUP = REAL / "lookup"
TMP = REAL / ".tmp"
CUBE = REAL / "fire_cube_real.parquet"
PAIRS = REAL / "pairs_aqua_snpp.parquet"
GLOBAL_COUNTS = REAL / "global_daily_counts.parquet"
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
AQUA_SAFE_MODE = (date(2022, 7, 31), date(2022, 8, 16))           # scripts/02
OUTAGE_DROP_FACTOR = 4                                            # scripts/02: n * 4 < 15-day mean
OUTAGE_WINDOW_DAYS = 15

# Inherited from scripts/01_ingest_firms.py
FOOTPRINT_MIN_AREA_KM2 = 3.5
SCAN_AZIMUTH_DEG = 98.2
BOWTIE_TRACK_KM = 1.35
ENTROPY_CENTRE = 0.72
ENTROPY_SLOPE = 20.0
POSITION_VARIANCE_M2 = 50.0
SAMA_BOX = (-35.0, -15.0, -65.0, -30.0)                           # lat_min, lat_max, lon_min, lon_max
SAMA_MAX_CONTRAST_K = 1.5
# Inherited from scripts/03_train_eqm_lut.py and scripts/04_build_master_cube.py
EQM_THRESHOLD_MW = 8.0
EQM_MIN_FRP_MW = 0.5
EQM_MIN_SAMPLES = 20
FRP_INTEGRATION_S = 3600.0                                        # one-hour FRE proxy
DIURNAL_MIN_MATCHED_DAYS = 3

# Sentinels for columns FIRMS cannot provide (declared in Parquet metadata and the quality report)
IGBP_FILL = 255                                                   # MCD12Q1 fill value, outside regions
CLOUD_SENTINEL = 0.0
BURNED_SENTINEL = 0.0

DUCKDB_MEMORY_LIMIT = "2GB"
DUCKDB_THREADS = 2
ROW_GROUP_SIZE = 122_880
EXTENSION_DIR = Path(sys.prefix) / "duckdb_extensions"


def load_regions(path: Path = REGIONS_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def connect(memory_limit: str = DUCKDB_MEMORY_LIMIT, threads: int = DUCKDB_THREADS) -> duckdb.DuckDBPyConnection:
    """DuckDB connection with the H3 extension loaded from the pipeline venv (never downloaded here)."""
    if not (EXTENSION_DIR.is_dir() and any(EXTENSION_DIR.rglob("h3.duckdb_extension"))):
        raise RuntimeError(
            f"DuckDB h3 extension not found in {EXTENSION_DIR}. Install it once inside .venv-pipeline: "
            ".venv-pipeline/bin/python -c \"import duckdb,sys; duckdb.connect(config={'extension_directory': "
            "sys.prefix + '/duckdb_extensions'}).execute('INSTALL h3 FROM community')\"")
    TMP.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(config={"extension_directory": str(EXTENSION_DIR), "autoinstall_known_extensions": False,
                                 "autoload_known_extensions": False})
    con.execute("LOAD h3")
    con.execute("SET memory_limit = ?", [memory_limit])
    con.execute("SET threads = ?", [threads])
    con.execute("SET temp_directory = ?", [str(TMP)])
    con.execute("SET preserve_insertion_order = false")
    return con
