"""Stage 4: Aqua–Suomi-NPP coincident pairs, a diagnostic table read from the canonical regional staging.

``pairs_aqua_snpp.parquet`` has one row per ``(h3_r7, epoch_day, daynight)`` where SNPP detected a fire and
Aqua contributed energy to the same R7 cell (directly or through its MODIS footprint), from 2012-01-19.
Per sensor it keeps the **raw** centre-pixel statistics (count, FRP sum/max, mean scan/track, first UTC
time) and the footprint/bow-tie corrected FRP sum computed by ``scripts/01``. ``aqua_count`` is 0 when Aqua
only reached the cell through a neighbouring pixel's footprint; filter on ``aqua_count > 0`` for
centre-to-centre pairs. The EQM/GPD lookup is not trained from this table: ``scripts/03`` trains it from
the same staging (``pipeline.cube.build_lookups``).
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from pipeline import config

PAIRS_NAME = "pairs_aqua_snpp.parquet"
PAIR_COLUMNS = ("h3_r4", "h3_r7", "epoch_day", "year", "doy", "acq_date", "daynight", "region", "igbp_biome",
                "aqua_count", "aqua_frp_sum_mw", "aqua_frp_max_mw", "aqua_scan_mean", "aqua_track_mean",
                "aqua_acq_time_min", "aqua_frp_corrected_mw",
                "snpp_count", "snpp_frp_sum_mw", "snpp_frp_max_mw", "snpp_scan_mean", "snpp_track_mean",
                "snpp_acq_time_min", "snpp_frp_corrected_mw", "snpp_scan_bin", "dt_minutes")


def build_pairs(con: duckdb.DuckDBPyConnection, staged: Path, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".parquet.tmp")
    con.execute("""COPY (
        WITH g AS (
            SELECT h3_r7, acq_date, daynight, satellite, any_value(h3_r4) AS h3_r4,
                   count(*) FILTER (WHERE is_center)::INTEGER AS cnt,
                   coalesce(sum(frp) FILTER (WHERE is_center), 0) AS frp_sum,
                   max(frp) FILTER (WHERE is_center) AS frp_max,
                   avg(scan) FILTER (WHERE is_center) AS scan_mean,
                   avg(track) FILTER (WHERE is_center) AS track_mean,
                   min(acq_time::INTEGER // 100 * 60 + acq_time::INTEGER % 100) FILTER (WHERE is_center) AS tmin,
                   sum(corrected_frp) AS frp_corr, any_value(igbp_biome) AS biome,
                   mode(scan_bin)::UTINYINT AS angle, mode(region) AS region
            FROM read_parquet(?)
            WHERE satellite IN ('Aqua', 'SNPP') AND acq_date >= ?
            GROUP BY h3_r7, acq_date, daynight, satellite)
        SELECT s.h3_r4, s.h3_r7, (s.acq_date - DATE '1970-01-01')::USMALLINT AS epoch_day,
               year(s.acq_date)::USMALLINT AS year, dayofyear(s.acq_date)::USMALLINT AS doy, s.acq_date,
               s.daynight, s.region, s.biome AS igbp_biome,
               a.cnt AS aqua_count, a.frp_sum AS aqua_frp_sum_mw, a.frp_max AS aqua_frp_max_mw,
               a.scan_mean AS aqua_scan_mean, a.track_mean AS aqua_track_mean, a.tmin AS aqua_acq_time_min,
               a.frp_corr AS aqua_frp_corrected_mw,
               s.cnt AS snpp_count, s.frp_sum AS snpp_frp_sum_mw, s.frp_max AS snpp_frp_max_mw,
               s.scan_mean AS snpp_scan_mean, s.track_mean AS snpp_track_mean, s.tmin AS snpp_acq_time_min,
               s.frp_corr AS snpp_frp_corrected_mw, s.angle AS snpp_scan_bin,
               a.tmin - s.tmin AS dt_minutes
        FROM g s JOIN g a ON a.h3_r7 = s.h3_r7 AND a.acq_date = s.acq_date AND a.daynight = s.daynight
        WHERE s.satellite = 'SNPP' AND a.satellite = 'Aqua' AND a.frp_corr > 0
        ORDER BY s.h3_r4, epoch_day, s.h3_r7, s.daynight
    ) TO ? (FORMAT parquet, COMPRESSION zstd)""", [str(staged), config.PAIRS_START, str(tmp)])
    tmp.replace(output)
    return output
