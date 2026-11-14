"""Build offline outage evidence and coincident Terra/Aqua diurnal ratios."""

import argparse
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
STAGED = ROOT / "data/processed/staged_firms.parquet"


def build_outages_table(staged=STAGED, output_dir="data/lookup", global_counts=None):
    """Use optional global daily counts for anomaly detection, plus the known Aqua outage."""
    output = ROOT / output_dir
    output.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as con:
        con.execute("""CREATE TABLE outages AS
            SELECT day::DATE AS acq_date, 'Aqua' AS satellite, 'known_safe_mode' AS evidence
            FROM generate_series(DATE '2022-07-31', DATE '2022-08-16', INTERVAL 1 DAY) t(day)
        """)
        if global_counts:
            con.execute("""INSERT INTO outages
                WITH counts AS (
                    SELECT satellite, acq_date::DATE AS acq_date, detection_count::DOUBLE AS n
                    FROM read_parquet(?)
                ), baseline AS (
                    SELECT *, avg(n) OVER w AS baseline, count(n) OVER w AS days
                    FROM counts WINDOW w AS (
                        PARTITION BY satellite ORDER BY acq_date
                        RANGE BETWEEN INTERVAL 15 DAYS PRECEDING AND INTERVAL 1 DAY PRECEDING
                    )
                )
                SELECT acq_date, satellite, 'global_count_drop'
                FROM baseline WHERE days = 15 AND baseline > 0 AND n * 4 < baseline
            """, [str(ROOT / global_counts)])
        con.table("outages").distinct().write_parquet(str(output / "sensor_outages.parquet"))
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
    return output / "sensor_outages.parquet"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", default=STAGED)
    parser.add_argument("--output-dir", default="data/lookup")
    parser.add_argument("--global-counts", help="Local Parquet of satellite, acq_date, detection_count")
    args = parser.parse_args()
    build_outages_table(args.staged, args.output_dir, args.global_counts)
