"""Stage 1: FIRMS CSV (or yearly zip) -> normalized, de-duplicated, SAMA-filtered global detections.

These detections feed the global daily counts (``pipeline.lookups``) and the per-region FIRMS CSV export
that ``pipeline.cube`` hands to the canonical ``scripts/01_ingest_firms.py``. They are not cube staging:
footprint, bow-tie, biome, scan-angle and industrial values are computed only by ``scripts/01``.
The filters match ``scripts/01`` (validity window, sensor canon, confidence normalization, exact-identity
de-duplication, SAMA rule), so re-running them there is a no-op; a parity test proves it. By design:
* detections outside every ``data/regions.json`` box are kept with ``region = NULL`` (global counts);
* the yearly archives can mix standard (SP) and near-real-time rows; ``tier`` comes from ``version``
  (or an ``nrt`` file name) and SP wins exact-identity duplicates, like the NRT-last file order of
  ``scripts/01``;
* the sensor canon also accepts the numeric NOAA-20/21 codes of the yearly archives.
One output row per detection; ``det_id`` is unique inside one output file.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import duckdb
import pyarrow as pa

from pipeline import config

REQUIRED = ("latitude", "longitude", "acq_date", "acq_time", "satellite", "frp", "scan", "track",
            "confidence", "daynight")
OPTIONAL = ("brightness", "bright_t31", "bright_ti4", "bright_ti5", "instrument", "version")

DETECTION_COLUMNS = ("det_id", "latitude", "longitude", "acq_date", "acq_time", "satellite", "instrument", "frp",
                     "scan", "track", "brightness_mir", "brightness_tir", "confidence_norm", "daynight", "h3_r4",
                     "h3_r7", "h3_r10", "region", "source_file", "sensor_bit", "version", "tier")


def _region_case(regions: dict) -> tuple[str, list]:
    """CASE expression for the first matching region (as ``scripts/01.region_at``); text depends on the count."""
    sql, params = ["CASE"], []
    for name, region in regions.items():
        west, south, east, north = region["bounds"]
        sql.append(" WHEN lon BETWEEN ? AND ? AND lat BETWEEN ? AND ? THEN ?")
        params += [west, east, south, north, name]
    sql.append(" ELSE NULL END")
    return "".join(sql), params


def ingest_csvs(con: duckdb.DuckDBPyConnection, files: list[Path], output: Path,
                regions: dict | None = None) -> dict:
    """Normalize ``files`` into one detection Parquet at ``output``. Returns per-sensor stage counts."""
    files = sorted((Path(f) for f in files), key=lambda p: ("nrt" in p.name.lower(), p.name))
    if not files:
        raise FileNotFoundError("No FIRMS CSV files to ingest.")
    regions = config.load_regions() if regions is None else regions
    # Group files by header so each group is scanned without the slow per-file union_by_name sniffing.
    # CREATE VIEW cannot bind prepared parameters, so scans are built through the relation API.
    groups: dict[tuple[str, ...], list[str]] = {}
    for f in files:
        with open(f, encoding="utf-8", errors="replace") as fh:
            header = tuple(h.strip().lower() for h in fh.readline().strip().split(","))
        groups.setdefault(header, []).append(str(f))
    parts = []
    for i, (header, group) in enumerate(groups.items()):
        missing = [c for c in REQUIRED if c not in header]
        if missing:
            raise ValueError(f"FIRMS inputs {Path(group[0]).name} are missing required columns {missing}")
        con.read_csv(group, all_varchar=True, filename=True, header=True).create_view(f"src_{i}", replace=True)
        # Absent optional columns are projected as NULL; names come from the fixed allow-list above.
        projection = ", ".join(f'"{c}" AS {c}' if c in header else f"NULL::VARCHAR AS {c}"
                               for c in REQUIRED + OPTIONAL)
        parts.append("SELECT " + projection + f", parse_filename(filename) AS source_file FROM src_{i}")
    con.execute("CREATE OR REPLACE TEMP VIEW src_named AS " + " UNION ALL ".join(parts))
    n_groups = len(groups)
    con.register("sensor_map", pa.table({"code": list(config.SENSORS), "sensor": list(config.SENSORS.values())}))
    con.register("sensor_bits", pa.table({"sensor": list(config.SENSOR_BITS),
                                          "bit": pa.array(list(config.SENSOR_BITS.values()), pa.uint8())}))
    lat_lo, lat_hi, lon_lo, lon_hi = config.SAMA_BOX
    con.execute("""CREATE OR REPLACE TEMP TABLE norm AS
        SELECT TRY_CAST(latitude AS DOUBLE) AS lat, TRY_CAST(longitude AS DOUBLE) AS lon,
               TRY_CAST(frp AS DOUBLE) AS frp, TRY_CAST(scan AS DOUBLE) AS scan, TRY_CAST(track AS DOUBLE) AS track,
               TRY_CAST(acq_date AS DATE) AS acq_date, TRY_CAST(acq_time AS INTEGER) AS acq_time_int,
               upper(trim(satellite)) AS sat_code, lower(coalesce(confidence, '')) AS conf_raw,
               upper(daynight) AS daynight,
               TRY_CAST(coalesce(nullif(bright_ti4, ''), nullif(brightness, '')) AS DOUBLE) AS mir,
               TRY_CAST(coalesce(nullif(bright_ti5, ''), nullif(bright_t31, '')) AS DOUBLE) AS tir,
               nullif(trim(version), '') AS version,
               CASE WHEN contains(upper(coalesce(version, '')), 'NRT') OR contains(lower(source_file), 'nrt')
                    THEN 'NRT' ELSE 'SP' END AS tier,
               source_file
        FROM src_named""")
    con.execute("""CREATE OR REPLACE TEMP TABLE valid AS
        SELECT n.*, m.sensor FROM norm n LEFT JOIN sensor_map m ON m.code = n.sat_code
        WHERE isfinite(lat) AND isfinite(lon) AND isfinite(frp) AND isfinite(scan) AND isfinite(track)
          AND abs(lat) <= 90 AND abs(lon) <= 180 AND frp >= 0 AND least(scan, track) > 0
          AND acq_date BETWEEN ? AND ?""", [config.FIRST_DAY, config.LAST_DAY])
    unknown = con.execute("SELECT DISTINCT sat_code FROM valid WHERE sensor IS NULL LIMIT 5").fetchall()
    if unknown:
        raise ValueError(f"Unknown FIRMS satellite codes {[u[0] for u in unknown]}")
    bad_time = con.execute("SELECT count(*) FROM valid WHERE acq_time_int IS NULL OR acq_time_int < 0 "
                           "OR acq_time_int // 100 > 23 OR acq_time_int % 100 > 59").fetchall()[0][0]
    if bad_time:
        raise ValueError(f"{bad_time} detections have an invalid UTC acquisition time")
    region_sql, region_params = _region_case(regions)
    con.execute("""CREATE OR REPLACE TEMP TABLE dedup AS
        SELECT *, lpad(acq_time_int::VARCHAR, 4, '0') AS acq_time,
               CASE WHEN regexp_full_match(conf_raw, '[0-9]+') THEN
                         CASE WHEN conf_raw::INTEGER < 30 THEN 'low' WHEN conf_raw::INTEGER < 80 THEN 'nominal'
                              ELSE 'high' END
                    WHEN conf_raw = 'l' THEN 'low' WHEN conf_raw = 'n' THEN 'nominal' WHEN conf_raw = 'h' THEN 'high'
                    ELSE conf_raw END AS confidence_norm
        FROM valid
        QUALIFY row_number() OVER (PARTITION BY sensor, acq_date, acq_time_int, round(lat, 5), round(lon, 5)
                                   ORDER BY tier = 'NRT', source_file, frp, scan, track,
                                            conf_raw, mir, tir, daynight) = 1""")
    con.execute("""CREATE OR REPLACE TEMP TABLE kept AS
        SELECT * , (lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? AND daynight = 'N' AND confidence_norm = 'low'
                    AND mir IS NOT NULL AND tir IS NOT NULL AND mir - tir < ?) AS is_sama
        FROM dedup""", [lat_lo, lat_hi, lon_lo, lon_hi, config.SAMA_MAX_CONTRAST_K])
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".parquet.tmp")
    modis = list(config.MODIS_SENSORS)
    con.execute("""COPY (
        WITH k AS (SELECT *, h3_latlng_to_cell(lat, lon, 7)::UBIGINT AS h3_r7 FROM kept WHERE NOT is_sama)
        SELECT row_number() OVER ()::UBIGINT AS det_id, lat AS latitude, lon AS longitude, acq_date, acq_time,
               k.sensor AS satellite,
               CASE WHEN list_contains(?, k.sensor) THEN 'MODIS' ELSE 'VIIRS' END AS instrument,
               frp, scan, track, mir AS brightness_mir, tir AS brightness_tir, confidence_norm, daynight,
               h3_cell_to_parent(h3_r7, 4)::UBIGINT AS h3_r4, h3_r7,
               h3_latlng_to_cell(lat, lon, 10)::UBIGINT AS h3_r10,
               """ + region_sql + """ AS region,
               source_file, b.bit AS sensor_bit, version, tier
        FROM k JOIN sensor_bits b ON b.sensor = k.sensor
    ) TO ? (FORMAT parquet, COMPRESSION zstd)""", [modis] + region_params + [str(tmp)])
    stats = {}
    for sensor, raw in con.execute("SELECT coalesce(m.sensor, n.sat_code), count(*) FROM norm n "
                                   "LEFT JOIN sensor_map m ON m.code = n.sat_code GROUP BY 1").fetchall():
        stats.setdefault(sensor, {})["rows_read"] = raw
    for name, table, where in (("valid", "valid", "true"), ("after_dedup", "dedup", "true"),
                               ("sama_removed", "kept", "is_sama"), ("kept", "kept", "NOT is_sama")):
        for sensor, n in con.execute("SELECT sensor, count(*) FROM " + table + " WHERE " + where +
                                     " GROUP BY 1").fetchall():
            stats.setdefault(sensor, {})[name] = n
    for s in stats.values():
        for key in ("rows_read", "valid", "after_dedup", "sama_removed", "kept"):
            s.setdefault(key, 0)
    by_region = con.execute("SELECT satellite, coalesce(region, '<none>'), tier, count(*) FROM read_parquet(?) "
                            "GROUP BY ALL", [str(tmp)]).fetchall()
    con.execute("DROP VIEW IF EXISTS src_named")
    for i in range(n_groups):
        con.execute("DROP VIEW IF EXISTS src_" + str(i))
    for name in ("norm", "valid", "dedup", "kept"):
        con.execute("DROP TABLE IF EXISTS " + name)
    tmp.replace(output)
    result = {"files": len(files), "sensors": stats,
              "by_region": [{"satellite": s, "region": r, "tier": t, "kept": n} for s, r, t, n in by_region]}
    output.with_name("_stats.json").write_text(json.dumps(result, indent=1, default=str))
    return result


def chunk_dir(product: str, year: int) -> Path:
    return config.STAGED / "detections" / f"product={product}" / f"year={year}"


def ingest_archive(con: duckdb.DuckDBPyConnection, product: str, year: int, force: bool = False) -> dict | None:
    """Extract one yearly zip to a temporary folder, ingest it and delete the CSVs."""
    out_dir = chunk_dir(product, year)
    done = out_dir / "_SUCCESS"
    if done.exists() and not force:
        return json.loads((out_dir / "_stats.json").read_text())
    archive = config.RAW / product / f"{year}.zip"
    if not archive.is_file():
        return None
    extract = config.TMP / f"extract_{product}_{year}"
    shutil.rmtree(extract, ignore_errors=True)
    extract.mkdir(parents=True)
    try:
        with zipfile.ZipFile(archive) as zf:
            members = [m for m in zf.namelist() if m.lower().endswith(".csv")]
            for member in members:
                target = extract / Path(member).name
                with zf.open(member) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
        stats = ingest_csvs(con, sorted(extract.glob("*.csv")), out_dir / "part.parquet")
    finally:
        shutil.rmtree(extract, ignore_errors=True)
    done.write_text("ok\n")
    return stats


def detections_glob() -> str:
    return str(config.STAGED / "detections" / "*" / "*" / "part.parquet")
