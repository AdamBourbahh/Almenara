"""Stage 3: global daily counts, sensor outages and Terra/Aqua diurnal ratios.

Port of ``scripts/02_detect_outages_clouds.py`` (Germán), fed with the global counts that script
expects but nobody produced:
* ``global_daily_counts.parquet``: ``satellite, acq_date, detection_count`` for every calendar day between
  a sensor's first and last ingested day, including observed zero-count days;
* ``sensor_outages.parquet``: the known Aqua safe mode (2022-07-31..2022-08-16), every day whose count
  is below a quarter of the mean of the previous 15 complete days (``scripts/02`` rule), and every day with
  zero global detections inside the sensor's span (the ``scripts/02`` rule stops flagging once the 15-day
  mean itself reaches 0, e.g. the last days of the Terra outage of 2001-06-15..07-02);
* ``diurnal_ratios.parquet``: ``sum(Aqua) / sum(Terra)`` corrected daytime FRP per H3 R4 and month, over
  cell-days where both sensors detected.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline import config, industrial

OUTAGES = config.LOOKUP / "sensor_outages.parquet"
RATIOS = config.LOOKUP / "diurnal_ratios.parquet"


def _copy(con: duckdb.DuckDBPyConnection, sql: str, params: list, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".parquet.tmp")
    con.execute("COPY (" + sql + ") TO ? (FORMAT parquet, COMPRESSION zstd)", params + [str(tmp)])
    tmp.replace(output)
    return output


def build_global_counts(con, detections: str, output: Path = config.GLOBAL_COUNTS) -> Path:
    return _copy(con, """
        WITH counts AS (SELECT satellite, acq_date, count(*) AS n FROM read_parquet(?) GROUP BY ALL),
        span AS (SELECT satellite, min(acq_date) AS lo, max(acq_date) AS hi FROM counts GROUP BY ALL),
        days AS (SELECT satellite, unnest(generate_series(lo, hi, INTERVAL 1 DAY))::DATE AS acq_date FROM span)
        SELECT satellite, acq_date, coalesce(n, 0)::BIGINT AS detection_count
        FROM days LEFT JOIN counts USING (satellite, acq_date) ORDER BY satellite, acq_date""",
                 [detections], output)


def build_outages(con, global_counts: Path = config.GLOBAL_COUNTS, output: Path = OUTAGES) -> Path:
    start, end = config.AQUA_SAFE_MODE
    return _copy(con, """
        WITH known AS (
            SELECT day::DATE AS acq_date, 'Aqua' AS satellite, 'known_safe_mode' AS evidence
            FROM generate_series(?::DATE, ?::DATE, INTERVAL 1 DAY) t(day)),
        counts AS (SELECT satellite, acq_date, detection_count::DOUBLE AS n FROM read_parquet(?)),
        baseline AS (
            SELECT *, avg(n) OVER w AS baseline, count(n) OVER w AS days FROM counts
            WINDOW w AS (PARTITION BY satellite ORDER BY acq_date
                         RANGE BETWEEN INTERVAL 15 DAYS PRECEDING AND INTERVAL 1 DAY PRECEDING)),
        drops AS (
            SELECT acq_date, satellite, 'global_count_drop' AS evidence FROM baseline
            WHERE days = ? AND baseline > 0 AND n * ? < baseline),
        zeros AS (SELECT acq_date, satellite, 'zero_global_count' AS evidence FROM counts WHERE n = 0)
        SELECT acq_date, satellite, min(evidence) AS evidence
        FROM (SELECT * FROM known UNION ALL SELECT * FROM drops UNION ALL SELECT * FROM zeros)
        GROUP BY acq_date, satellite ORDER BY satellite, acq_date""",
                 [start, end, str(global_counts), config.OUTAGE_WINDOW_DAYS, config.OUTAGE_DROP_FACTOR], output)


def build_diurnal_ratios(con, detections: str, industrial_path: Path = industrial.INDUSTRIAL,
                         output: Path = RATIOS) -> Path:
    fp = industrial.footprint_sql("satellite IN ('Terra', 'Aqua') AND daynight = 'D'")
    return _copy(con, """
        WITH f AS (""" + fp + """),
        matched AS (
            SELECT h3_r4, acq_date,
                   sum(corrected_frp) FILTER (WHERE satellite = 'Terra') AS terra,
                   sum(corrected_frp) FILTER (WHERE satellite = 'Aqua') AS aqua
            FROM f GROUP BY h3_r4, acq_date)
        SELECT h3_r4, month(acq_date)::UTINYINT AS month, (sum(aqua) / sum(terra))::DOUBLE AS ratio,
               count(*) AS matched_days
        FROM matched WHERE terra > 0 AND aqua > 0 GROUP BY h3_r4, month ORDER BY h3_r4, month""",
                 industrial.footprint_params(detections, industrial_path), output)
