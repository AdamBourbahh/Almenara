"""Stage 2: global daily detection counts, the input that ``scripts/02_detect_outages_clouds.py`` expects.

``global_daily_counts.parquet`` has ``satellite, acq_date, detection_count`` for every calendar day between a
sensor's first and last ingested day, including observed zero-count days, counted over every ingested
detection (inside or outside the configured regions). Outage evidence is not computed here: the canonical
``scripts/02`` reads this file (``pipeline.cube.build_lookups``), together with its ``KNOWN_OUTAGES``.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline import config


def build_global_counts(con: duckdb.DuckDBPyConnection, detections: str,
                        output: Path = config.GLOBAL_COUNTS) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".parquet.tmp")
    con.execute("""COPY (
        WITH counts AS (SELECT satellite, acq_date, count(*) AS n FROM read_parquet(?) GROUP BY ALL),
        span AS (SELECT satellite, min(acq_date) AS lo, max(acq_date) AS hi FROM counts GROUP BY ALL),
        days AS (SELECT satellite, unnest(generate_series(lo, hi, INTERVAL 1 DAY))::DATE AS acq_date FROM span)
        SELECT satellite, acq_date, coalesce(n, 0)::BIGINT AS detection_count
        FROM days LEFT JOIN counts USING (satellite, acq_date) ORDER BY satellite, acq_date
    ) TO ? (FORMAT parquet, COMPRESSION zstd)""", [detections, str(tmp)])
    tmp.replace(output)
    return output
