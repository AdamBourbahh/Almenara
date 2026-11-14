"""Stage 3: one regional cube through the canonical ``scripts/01-04`` stages (single source of truth).

The pipeline computes nothing here itself; it only routes its global ingest into the canonical stages:

1. ``stage_region``: the region's normalized detections are written back as FIRMS-format CSVs, one per
   original source file and in a fixed row order, and ``scripts/01_ingest_firms.ingest_raw_firms`` turns
   them into the canonical staging (footprints, bow-tie, biome, scan bin, industrial score).
2. ``build_lookups``: ``scripts/02_detect_outages_clouds.build_outages_table`` with the pipeline's global
   daily counts (``KNOWN_OUTAGES``, ``global_count_drop``, ``zero_global_count``, diurnal ratios), then
   ``scripts/03_train_eqm_lut.generate_eqm_gpd_lut`` on the regional staging.
3. ``publish_cube``: ``scripts/04_build_master_cube.build_master_cube`` (orbital weight, core
   ``RadiometricHarmonizer``, cloud/burned-area ancillary, outage and blackout bits, atomic publication).

``scripts/01`` and ``scripts/04`` read ``data/regions.json``: the region must declare a ``coverage`` that
contains every detection day, or ``scripts/04`` refuses to publish.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import duckdb

from pipeline import config, german

STAGED_NAME = "staged_firms.parquet"
LOOKUP_NAME = "lookup"
CUBE_NAME = "fire_cube.parquet"
LUT_NAME = "eqm_gpd_lut.json"

# FIRMS CSV columns read by scripts/01; MODIS brightness names also carry the VIIRS I4/I5 values.
EXPORT_SQL = """SELECT latitude, longitude, brightness_mir AS brightness, brightness_tir AS bright_t31,
       scan, track, acq_date, acq_time, satellite, confidence_norm AS confidence, frp, daynight
    FROM read_parquet(?) WHERE region = ? AND source_file = ?
    ORDER BY acq_date, acq_time, satellite, latitude, longitude, frp"""


@dataclass(frozen=True)
class RegionBuild:
    staged: Path
    lookup: Path
    cube: Path


def stage_region(con: duckdb.DuckDBPyConnection, detections: str, region: str, work: Path) -> Path:
    """Canonical staging of one region: FIRMS CSV export of the global ingest -> ``scripts/01``."""
    if region not in config.load_regions():
        raise ValueError(f"Unknown region {region!r} (see data/regions.json)")
    names = [row[0] for row in con.execute(
        "SELECT DISTINCT source_file FROM read_parquet(?) WHERE region = ? ORDER BY 1",
        [detections, region]).fetchall()]
    if not names:
        raise ValueError(f"No ingested detections inside region {region!r}; refusing to build an empty cube.")
    work.mkdir(parents=True, exist_ok=True)
    csv_dir = work / "firms_csv"
    shutil.rmtree(csv_dir, ignore_errors=True)
    csv_dir.mkdir()
    try:
        for name in names:
            # Original file names keep scripts/01's provenance column and its NRT-last file order.
            if Path(name).name != name or not name.lower().endswith(".csv"):
                raise ValueError(f"Unexpected FIRMS source file name {name!r}")
            con.execute("COPY (" + EXPORT_SQL + ") TO ? (FORMAT csv, HEADER)",
                        [detections, region, name, str(csv_dir / name)])
        return Path(german.load("01_ingest_firms").ingest_raw_firms(csv_dir, work / STAGED_NAME))
    finally:
        shutil.rmtree(csv_dir, ignore_errors=True)


def build_lookups(staged: Path, lookup: Path, global_counts: Path) -> Path:
    """Outages and diurnal ratios (``scripts/02``) and the EQM/GPD lookup (``scripts/03``)."""
    if not Path(global_counts).is_file():
        raise FileNotFoundError(f"Global daily counts not found at {global_counts}; run the ingest first.")
    german.load("02_detect_outages_clouds").build_outages_table(staged, lookup, global_counts)
    german.load("03_train_eqm_lut").generate_eqm_gpd_lut(lookup / LUT_NAME, staged)
    return lookup


def publish_cube(staged: Path, output: Path, lookup: Path) -> Path:
    """Atomic master-cube publication by ``scripts/04`` (it refuses the synthetic fixture path)."""
    return Path(german.load("04_build_master_cube").build_master_cube(staged, output, False, lookup))


def build_region(con: duckdb.DuckDBPyConnection, detections: str, region: str,
                 global_counts: Path = config.GLOBAL_COUNTS, work: Path | None = None,
                 output: Path | None = None) -> RegionBuild:
    work = config.region_dir(region) if work is None else Path(work)
    staged = stage_region(con, detections, region, work)
    lookup = build_lookups(staged, work / LOOKUP_NAME, global_counts)
    cube = publish_cube(staged, work / CUBE_NAME if output is None else Path(output), lookup)
    return RegionBuild(staged=staged, lookup=lookup, cube=cube)
