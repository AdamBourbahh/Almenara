"""Run the real-data pipeline end to end (resumable).

    python -m pipeline.run --download                  # fetch the FIRMS yearly global archives
    python -m pipeline.run --region cerrado_brazil     # ingest, lookups, pairs, Cerrado cube, report
    python -m pipeline.run --global-cube               # same, cube over every ingested detection

Stages: ingest (per product-year, skipped when ``_SUCCESS`` exists) -> industrial scores -> global daily counts
-> outages -> diurnal ratios -> Aqua–SNPP pairs -> EQM/GPD LUT -> cube -> quality report.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from pipeline import config, cube, download, industrial, ingest, lookups, pairs, quality


def _step(name: str, fn):
    t0 = time.perf_counter()
    result = fn()
    print(f"{name:22s} {time.perf_counter() - t0:8.1f} s", flush=True)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--download", action="store_true", help="download missing yearly archives first")
    parser.add_argument("--products", nargs="*", choices=sorted(config.PRODUCTS))
    parser.add_argument("--years", nargs="*", type=int)
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--region", help="build the cube for one data/regions.json region")
    target.add_argument("--global-cube", action="store_true", help="build the cube over all detections")
    parser.add_argument("--force-ingest", action="store_true", help="re-ingest chunks that already succeeded")
    parser.add_argument("--output", default=str(config.CUBE), help="cube path (default data/real/fire_cube_real.parquet)")
    args = parser.parse_args(argv)

    if args.download:
        download.main((["--products", *args.products] if args.products else [])
                      + (["--years", *map(str, args.years)] if args.years else []))
    con = config.connect()
    chunks = download.wanted(args.products, args.years)
    for product, year in chunks:
        if not (config.RAW / product / f"{year}.zip").is_file():
            continue
        _step(f"ingest {product} {year}", lambda: ingest.ingest_archive(con, product, year, args.force_ingest))
    det = ingest.detections_glob()
    _step("industrial scores", lambda: industrial.build_industrial(con, det))
    _step("global daily counts", lambda: lookups.build_global_counts(con, det))
    _step("outages", lambda: lookups.build_outages(con))
    _step("diurnal ratios", lambda: lookups.build_diurnal_ratios(con, det))
    _step("aqua-snpp pairs", lambda: pairs.build_pairs(con, det))
    _step("eqm/gpd lut", lambda: pairs.train_lut(con))
    if args.region or args.global_cube:
        cov = {s["satellite"]: [s["first_day"], s["last_day"]]
               for s in quality._counts_stats(con)["sensors"]}
        _step("cube", lambda: cube.build_cube(con, det, region=args.region, output=Path(args.output), coverage=cov))
    _step("quality report", lambda: quality.build_report(con, Path(args.output)))
    print(f"Report: {config.REPORT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
