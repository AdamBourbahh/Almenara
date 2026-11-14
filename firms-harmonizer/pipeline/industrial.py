"""Stage 2: industrial score per H3 R10 cell and MODIS footprint contributions.

Vectorized port of the second half of ``scripts/01_ingest_firms.py``:
* ``h_temp``: Shannon entropy of the 12 calendar-month detection counts, normalized by ln 12;
* ``industrial_prob = 1 / (1 + exp(-20 (h_temp - 0.72)))`` when the positional variance of the cell's
  detections (metres², population variance) is below 50, else 0;
* deformed MODIS pixels (scan·track > 3.5 km²) spread their power over the R7 cell and its 6 neighbours
  with a rotated Gaussian (azimuth 98.2°, FWHM = scan/track) normalized to 1; every other detection
  stays in its own cell with weight 1. ``corrected_frp = frp · bowtie_weight · footprint_weight``.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline import config

INDUSTRIAL = config.LOOKUP / "industrial_r10.parquet"
DEG_KM = 111.195      # km per degree, scripts/01 footprint()
DEG_M = 111195.0      # m per degree, scripts/01 positional variance
FWHM = 2.355


def build_industrial(con: duckdb.DuckDBPyConnection, detections: str, output: Path = INDUSTRIAL) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".parquet.tmp")
    con.execute("""COPY (
        WITH d AS (SELECT h3_r10, month(acq_date) AS mo, latitude, longitude FROM read_parquet(?)),
        months AS (SELECT h3_r10, mo, count(*)::DOUBLE AS c FROM d GROUP BY ALL),
        entropy AS (
            SELECT h3_r10, -sum((c / tot) * ln(c / tot)) / ln(12) AS h_temp
            FROM (SELECT *, sum(c) OVER (PARTITION BY h3_r10) AS tot FROM months) GROUP BY h3_r10),
        spread AS (
            SELECT h3_r10, var_pop(latitude * ?) + var_pop(longitude) * pow(? * cos(radians(avg(latitude))), 2)
                   AS variance_m2
            FROM d GROUP BY h3_r10)
        SELECT h3_r10, h_temp,
               CASE WHEN variance_m2 < ? THEN 1.0 / (1.0 + exp(-? * (h_temp - ?))) ELSE 0.0 END AS industrial_prob
        FROM entropy JOIN spread USING (h3_r10)
    ) TO ? (FORMAT parquet, COMPRESSION zstd)""",
                [detections, DEG_M, DEG_M, config.POSITION_VARIANCE_M2, config.ENTROPY_SLOPE,
                 config.ENTROPY_CENTRE, str(tmp)])
    tmp.replace(output)
    return output


def footprint_sql(where: str = "true") -> str:
    """SELECT producing one row per (detection, target R7 cell), Germán's staged columns.

    Parameters, in order: detections path/glob, industrial path, MODIS sensor list, min footprint area,
    and then the scalars used by the Gaussian (azimuth, km/deg, FWHM). ``where`` is a constant SQL predicate
    defined in this package; any value it needs is a ``?`` bound through ``footprint_params(where_params=...)``.
    """
    return """
    WITH d AS (
        SELECT d.*, i.h_temp, i.industrial_prob FROM read_parquet(?, hive_partitioning = true) d
        JOIN read_parquet(?) i USING (h3_r10) WHERE """ + where + """),
    spread AS (SELECT *, list_contains(?, satellite) AND scan * track > ? AS spreads FROM d),
    targets AS (SELECT * EXCLUDE (spreads), unnest(h3_grid_disk(h3_r7, 1)) AS target FROM spread WHERE spreads),
    geo AS (
        SELECT *, (h3_cell_to_lat(target) - latitude) * ? AS north,
               ((h3_cell_to_lng(target) - longitude + 180) - 360 * floor((h3_cell_to_lng(target) - longitude + 180) / 360)
                - 180) * ? * cos(radians(latitude)) AS east
        FROM targets),
    rot AS (
        SELECT *, north * cos(radians(?)) + east * sin(radians(?)) AS along,
               -north * sin(radians(?)) + east * cos(radians(?)) AS across
        FROM geo),
    logw AS (SELECT *, -0.5 * (pow(along * ? / track, 2) + pow(across * ? / scan, 2)) AS lw FROM rot),
    expw AS (SELECT *, exp(lw - max(lw) OVER (PARTITION BY product, year, det_id)) AS e FROM logw),
    spread_rows AS (
        SELECT * EXCLUDE (north, east, along, across, lw, e),
               e / sum(e) OVER (PARTITION BY product, year, det_id) AS footprint_weight
        FROM expw),
    w AS (
        SELECT * EXCLUDE (spreads), h3_r7 AS target, 1.0::DOUBLE AS footprint_weight FROM spread WHERE NOT spreads
        UNION ALL BY NAME
        SELECT * FROM spread_rows)
    SELECT product, year, det_id, latitude, longitude, acq_date, acq_time, satellite, instrument, frp, scan, track,
           brightness_mir, brightness_tir, confidence_norm, daynight,
           h3_cell_to_parent(target, 4)::UBIGINT AS h3_r4, target::UBIGINT AS h3_r7, h3_r10,
           target = h3_r7 AS is_center, bowtie_weight, footprint_weight,
           frp * bowtie_weight * footprint_weight AS corrected_frp, h_temp, industrial_prob, region, igbp_biome,
           scan_bin, source_file, sensor_bit
    FROM w"""


def footprint_params(detections: str, industrial: Path = INDUSTRIAL, where_params: list | None = None) -> list:
    """Parameters for ``footprint_sql``; ``where_params`` bind the ``?`` placeholders of ``where``."""
    az = config.SCAN_AZIMUTH_DEG
    return [detections, str(industrial)] + list(where_params or []) + [list(config.MODIS_SENSORS),
            config.FOOTPRINT_MIN_AREA_KM2,
            DEG_KM, DEG_KM, az, az, az, az, FWHM, FWHM]


def footprint_relation(con: duckdb.DuckDBPyConnection, detections: str, industrial: Path = INDUSTRIAL,
                       where: str = "true", where_params: list | None = None) -> duckdb.DuckDBPyRelation:
    return con.sql(footprint_sql(where), params=footprint_params(detections, industrial, where_params))
