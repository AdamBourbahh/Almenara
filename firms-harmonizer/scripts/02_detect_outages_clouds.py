"""Build offline outage evidence and coincident Terra/Aqua diurnal ratios."""

import argparse
import hashlib
import json
from pathlib import Path

import duckdb
import h3
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
STAGED = ROOT / "data/processed/staged_firms.parquet"
GLOBAL_COUNTS = Path("data/lookup/global_daily_counts.csv")
ARCHIVE_COUNTS = Path("data/lookup/global_daily_counts_archive.csv")
# Measured in FIRMS world counts (VIIRS_SNPP_SP = 0 detections; Aqua, Terra and NOAA-20 nominal).
KNOWN_OUTAGES = (("SNPP", "2022-07-27", "2022-08-10"),)
CLOUD_GRID_NAME = "cloud_power_daily.parquet"
ANCILLARY_NAME = "cell_day_ancillary.parquet"
ANCILLARY_SCHEMA = pa.schema([("h3_r7", pa.uint64()), ("acq_date", pa.date32()),
                              ("cloud_cover_pct", pa.float64()), ("burned_area_ha_mcd64", pa.float64())])


def read_counts_sql(path):
    if Path(path).suffix.lower() == ".csv":
        return ("read_csv(?, header = true, columns = {'satellite': 'VARCHAR', 'acq_date': 'DATE', "
                "'detection_count': 'BIGINT'})")
    return "read_parquet(?)"


def default_global_counts():
    """Relative path of the counts file used when none is given, or None when neither exists."""
    for candidate in (ARCHIVE_COUNTS, GLOBAL_COUNTS):
        if (ROOT / candidate).is_file():
            return candidate
    return None


def build_outages_table(staged=STAGED, output_dir="data/lookup", global_counts=None):
    """Record documented outages, drops and interior zero days in global daily counts.

    Default counts: the 2000-2025 archive series when it exists, else the tracked 50-day lookup.
    """
    if global_counts is None:
        global_counts = default_global_counts()
    output = ROOT / output_dir
    output.mkdir(parents=True, exist_ok=True)
    # Serial aggregation fixes floating-point summation order for identical local inputs.
    with duckdb.connect(config={"threads": 1}) as con:
        con.execute("CREATE TABLE outages (acq_date DATE, satellite VARCHAR, evidence VARCHAR)")
        for satellite, first, last in KNOWN_OUTAGES:
            con.execute("""INSERT INTO outages
                SELECT day::DATE, ?, 'known_outage'
                FROM generate_series(?::DATE, ?::DATE, INTERVAL 1 DAY) t(day)
            """, [satellite, first, last])
        if global_counts:
            con.execute(f"""CREATE TEMP TABLE counts AS
                SELECT satellite, acq_date::DATE AS acq_date, detection_count::DOUBLE AS n
                FROM {read_counts_sql(global_counts)}
            """, [str(ROOT / global_counts)])
            duplicate = con.execute("""SELECT satellite, acq_date FROM counts
                GROUP BY satellite, acq_date HAVING count(*) > 1 LIMIT 1
            """).fetchone()
            if duplicate is not None:
                raise ValueError(f"Duplicate global count instrument-day: {duplicate}")
            con.execute("""INSERT INTO outages
                WITH baseline AS (
                    SELECT *, avg(n) OVER w AS baseline, count(n) OVER w AS days
                    FROM counts WINDOW w AS (
                        PARTITION BY satellite ORDER BY acq_date
                        RANGE BETWEEN INTERVAL 15 DAYS PRECEDING AND INTERVAL 1 DAY PRECEDING
                    )
                )
                SELECT acq_date, satellite, 'global_count_drop'
                FROM baseline WHERE days = 15 AND baseline > 0 AND n * 4 < baseline
            """)
            # The 15-day mean is all zeros after 15 zero days; an observed zero strictly inside the
            # instrument's positive-count record stays outage evidence for the whole run.
            con.execute("""INSERT INTO outages
                WITH life AS (
                    SELECT satellite, min(acq_date) AS first_day, max(acq_date) AS last_day
                    FROM counts WHERE n > 0 GROUP BY satellite
                )
                SELECT acq_date, satellite, 'zero_global_count'
                FROM counts JOIN life USING (satellite)
                WHERE n = 0 AND acq_date > first_day AND acq_date < last_day
            """)
        con.table("outages").distinct().order("acq_date, satellite, evidence").write_parquet(
            str(output / "sensor_outages.parquet"))
        path = ROOT / staged
        if path.exists():
            ratios = con.sql("""WITH matched AS (
                SELECT h3_r4, acq_date,
                       sum(corrected_frp) FILTER (WHERE satellite = 'Terra') AS terra,
                       sum(corrected_frp) FILTER (WHERE satellite = 'Aqua') AS aqua
                FROM read_parquet(?) WHERE satellite IN ('Terra', 'Aqua') AND daynight = 'D'
                GROUP BY h3_r4, acq_date
            )
            SELECT h3_r4, month(acq_date)::UTINYINT AS month,
                   (sum(aqua) / sum(terra))::DOUBLE AS ratio, count(*) AS matched_days
            FROM matched WHERE terra > 0 AND aqua > 0 GROUP BY h3_r4, month
            ORDER BY h3_r4, month
            """, params=[str(path)])
        else:
            ratios = con.sql("""SELECT 0::UBIGINT AS h3_r4, 0::UTINYINT AS month,
                0::DOUBLE AS ratio, 0::BIGINT AS matched_days WHERE false""")
        ratios.write_parquet(str(output / "diurnal_ratios.parquet"))
    print("Wrote sensor_outages.parquet and diurnal_ratios.parquet.")
    build_cell_day_ancillary(staged, output_dir)
    return output / "sensor_outages.parquet"


def build_cell_day_ancillary(staged=STAGED, output_dir="data/lookup", grid=None):
    """Join the staged cell-days to the POWER cloud grid table; offline, returns the path or None.

    Rows are exactly the unique ``(h3_r7, acq_date)`` pairs of the staged detections (footprint-spread
    cells included), which is the set of cell-days stage 04 publishes. ``cloud_cover_pct`` is the grid cell
    (1 degree, integer-degree edges, ``floor`` on both axes) that contains the H3 R7 centroid; days or cells
    without a value stay NULL so stage 04 counts them as missing, never as clear sky. No burned-area source
    exists here, so ``burned_area_ha_mcd64`` is NULL. Without a grid table nothing is written.
    """
    output = ROOT / output_dir
    grid = Path(grid) if grid is not None else output / CLOUD_GRID_NAME
    path = ROOT / staged
    if not grid.is_file():
        return None
    if not path.is_file():
        print(f"No staged detections at {path}; cell_day_ancillary.parquet not built.")
        return None
    with duckdb.connect(config={"threads": 1}) as con:
        cells = [row[0] for row in con.execute(
            "SELECT DISTINCT h3_r7 FROM read_parquet(?) ORDER BY h3_r7", [str(path)]).fetchall()]
        centroids = []
        for cell in cells:
            lat, lng = h3.cell_to_latlng(format(cell, "x"))
            centroids.append((cell, int(lat // 1), int(lng // 1)))
        con.register("centroids", pa.Table.from_pylist(
            [dict(h3_r7=c, grid_lat_sw=a, grid_lon_sw=b) for c, a, b in centroids],
            schema=pa.schema([("h3_r7", pa.uint64()), ("grid_lat_sw", pa.int16()), ("grid_lon_sw", pa.int16())])))
        table = con.execute("""
            SELECT d.h3_r7, d.acq_date::DATE AS acq_date,
                   g.cloud_fraction::DOUBLE AS cloud_cover_pct,
                   NULL::DOUBLE AS burned_area_ha_mcd64
            FROM (SELECT DISTINCT h3_r7, acq_date FROM read_parquet(?)) d
            JOIN centroids c USING (h3_r7)
            LEFT JOIN read_parquet(?) g ON g.grid_lat_sw = c.grid_lat_sw
                 AND g.grid_lon_sw = c.grid_lon_sw AND g.acq_date = d.acq_date
            ORDER BY d.h3_r7, d.acq_date
        """, [str(path), str(grid)]).to_arrow_table().cast(ANCILLARY_SCHEMA)
    source = {}
    raw = pq.read_schema(grid).metadata or {}
    if b"cloud_power" in raw:
        source = json.loads(raw[b"cloud_power"])
    provenance = dict(source, grid_file=grid.name, grid_sha256=hashlib.sha256(grid.read_bytes()).hexdigest(),
                      cell_days=table.num_rows, cloud_rows=table.num_rows - table.column("cloud_cover_pct").null_count,
                      mapping="H3 R7 centroid -> 1 degree grid cell (floor of latitude and longitude); "
                              "same acq_date; no value stays NULL",
                      burned_area="NULL: no burned-area source in this ancillary")
    table = table.replace_schema_metadata({"cell_day_ancillary": json.dumps(provenance, sort_keys=True)})
    output.mkdir(parents=True, exist_ok=True)
    target = output / ANCILLARY_NAME
    temporary = target.with_suffix(".parquet.part")
    pq.write_table(table, temporary, compression="zstd")
    temporary.replace(target)
    print(f"Wrote {ANCILLARY_NAME} ({table.num_rows} cell-days, {provenance['cloud_rows']} with cloud).")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", default=STAGED)
    parser.add_argument("--output-dir", default="data/lookup")
    parser.add_argument("--global-counts", help="Local CSV or Parquet of satellite, acq_date, detection_count "
                                                f"(default: {ARCHIVE_COUNTS} when present, else {GLOBAL_COUNTS})")
    args = parser.parse_args()
    build_outages_table(args.staged, args.output_dir, args.global_counts)
