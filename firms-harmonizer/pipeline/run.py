"""Run the real-data pipeline end to end (resumable).

    python -m pipeline.run --download                       # fetch the FIRMS yearly global archives
    python -m pipeline.run                                  # ingest the archives, global daily counts, report
    python -m pipeline.run --region amazonas_manaus         # same, then the regional cube

Stages: ingest (per product-year, skipped when ``_SUCCESS`` exists) -> global daily counts -> with
``--region``: canonical staging (``scripts/01``) -> outages and diurnal ratios (``scripts/02``) -> EQM/GPD
LUT (``scripts/03``) -> cube (``scripts/04``) -> Aqua-SNPP pairs -> quality report. Regional outputs go to
``data/real/regions/<region>/``. The region needs a ``coverage`` in ``data/regions.json``.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from pipeline import config, cube, download, ingest, lookups, pairs, quality


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
    parser.add_argument("--region", choices=sorted(config.load_regions()),
                        help="build the cube for one data/regions.json region")
    parser.add_argument("--force-ingest", action="store_true", help="re-ingest chunks that already succeeded")
    parser.add_argument("--output", type=Path,
                        help="cube path (default data/real/regions/<region>/fire_cube.parquet)")
    args = parser.parse_args(argv)
    if args.output is not None and args.region is None:
        parser.error("--output needs --region")

    if args.download:
        download.main((["--products", *args.products] if args.products else [])
                      + (["--years", *map(str, args.years)] if args.years else []))
    con = config.connect()
    for product, year in download.wanted(args.products, args.years):
        if not (config.RAW / product / f"{year}.zip").is_file():
            continue
        _step(f"ingest {product} {year}", lambda: ingest.ingest_archive(con, product, year, args.force_ingest))
    det = ingest.detections_glob()
    _step("global daily counts", lambda: lookups.build_global_counts(con, det))
    cube_path = None
    if args.region:
        build = _step(f"cube {args.region}", lambda: cube.build_region(con, det, args.region, output=args.output))
        _step("aqua-snpp pairs", lambda: pairs.build_pairs(con, build.staged,
                                                          config.region_dir(args.region) / pairs.PAIRS_NAME))
        cube_path = build.cube
    _step("quality report", lambda: quality.build_report(con, args.region, cube_path=cube_path))
    print(f"Report: {config.REPORT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
