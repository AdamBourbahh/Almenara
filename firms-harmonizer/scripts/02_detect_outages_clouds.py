"""Build offline outage evidence and coincident Terra/Aqua diurnal ratios."""

import argparse
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
STAGED = ROOT / "data/processed/staged_firms.parquet"
GLOBAL_COUNTS = Path("data/lookup/global_daily_counts.csv")
# Measured in FIRMS world counts (VIIRS_SNPP_SP = 0 detections; Aqua, Terra and NOAA-20 nominal).
KNOWN_OUTAGES = (("SNPP", "2022-07-27", "2022-08-10"),)


def read_counts_sql(path):
    if Path(path).suffix.lower() == ".csv":
        return ("read_csv(?, header = true, columns = {'satellite': 'VARCHAR', 'acq_date': 'DATE', "
                "'detection_count': 'BIGINT'})")
    return "read_parquet(?)"


def build_outages_table(staged=STAGED, output_dir="data/lookup", global_counts=None):
    """Record documented outages, drops and interior zero days in global daily counts.

    Uses the tracked lookup by default.
    """
    if global_counts is None and (ROOT / GLOBAL_COUNTS).is_file():
        global_counts = GLOBAL_COUNTS
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
    return output / "sensor_outages.parquet"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", default=STAGED)
    parser.add_argument("--output-dir", default="data/lookup")
    parser.add_argument("--global-counts", help="Local CSV or Parquet of satellite, acq_date, detection_count "
                                                f"(default: {GLOBAL_COUNTS} when present)")
    args = parser.parse_args()
    build_outages_table(args.staged, args.output_dir, args.global_counts)
