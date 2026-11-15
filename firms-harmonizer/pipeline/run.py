"""Run the real-data pipeline end to end (resumable).

    python -m pipeline.run --download                       # fetch the FIRMS yearly global archives
    python -m pipeline.run                                  # ingest the archives, global daily counts, report
    python -m pipeline.run --region amazonas_manaus         # same, then the regional cube
    python -m pipeline.run --archive-pass --products modis --years 2000   # streaming pass (network)
    python -m pipeline.run --merge-counts                   # partial counts -> data/lookup/*_archive.csv
    python -m pipeline.run --cloud-power                    # NASA POWER CLOUD_AMT grid for every region (network)
    python -m pipeline.run --swath-cmr                      # MODIS swath gaps from CMR footprints (network)

``--archive-pass`` downloads one yearly zip at a time, counts detections per satellite and day, clips the
preset regions to FIRMS CSVs and deletes the zip (see ``pipeline/archive_pass.py``); it does not run the
global ingest below.

``--cloud-power`` fetches NASA POWER daily ``CLOUD_AMT`` for every 1-degree cell that intersects a region box
(resumable cache in ``data/real/cloud_power/``) and writes ``data/lookup/cloud_power_daily.parquet``
(``--cloud-build-only`` rebuilds the table from the cache without network); see ``pipeline/cloud_power.py``.

``--swath-cmr`` fetches the NASA CMR footprints of the MODIS geolocation granules (``MOD03``/``MYD03`` 6.1) over
every region box (resumable cache in ``data/real/swath_cmr/``) and writes ``data/lookup/modis_swath_gaps.parquet``,
the gap-status bit 4 evidence of ``scripts/04`` (``--swath-build-only`` rebuilds it from the cache without
network); see ``pipeline/swath_cmr.py``.

Stages: ingest (per product-year, skipped when ``_SUCCESS`` exists) -> global daily counts -> with
``--region``: canonical staging (``scripts/01``) -> outages and diurnal ratios (``scripts/02``) -> EQM/GPD
LUT (``scripts/03``) -> cube (``scripts/04``) -> Aqua-SNPP pairs -> quality report. Regional outputs go to
``data/real/regions/<region>/``. The region needs a ``coverage`` in ``data/regions.json``.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from pipeline import archive_pass, cloud_power, config, cube, download, ingest, lookups, pairs, quality, swath_cmr


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
    parser.add_argument("--archive-pass", action="store_true",
                        help="streaming pass: global daily counts and preset-region clipping per (product, year)")
    parser.add_argument("--merge-counts", action="store_true",
                        help="merge the archive-pass partial counts into data/lookup/global_daily_counts_archive.csv")
    parser.add_argument("--cloud-power", action="store_true",
                        help="fetch NASA POWER CLOUD_AMT for all regions and write data/lookup/cloud_power_daily.parquet")
    parser.add_argument("--cloud-build-only", action="store_true",
                        help="--cloud-power: rebuild the table from the cache, no network")
    parser.add_argument("--swath-cmr", action="store_true",
                        help="fetch CMR MODIS granule footprints and write data/lookup/modis_swath_gaps.parquet")
    parser.add_argument("--swath-build-only", action="store_true",
                        help="--swath-cmr: rebuild the gap table from the cache, no network")
    parser.add_argument("--regions", nargs="*", default=list(config.PRESET_REGIONS),
                        help="regions clipped by --archive-pass (default: the four current presets)")
    parser.add_argument("--keep-zips", action="store_true", help="--archive-pass: keep each zip after success")
    parser.add_argument("--force", action="store_true", help="--archive-pass: redo chunks that already succeeded")
    parser.add_argument("--partial", action="store_true",
                        help="--merge-counts: require only a contiguous year range per finished product")
    parser.add_argument("--force-ingest", action="store_true", help="re-ingest chunks that already succeeded")
    parser.add_argument("--output", type=Path,
                        help="cube path (default data/real/regions/<region>/fire_cube.parquet)")
    args = parser.parse_args(argv)
    if args.output is not None and args.region is None:
        parser.error("--output needs --region")

    if args.cloud_power or args.cloud_build_only:
        if args.download or args.region or args.archive_pass or args.merge_counts:
            parser.error("--cloud-power does not combine with other steps")
        return cloud_power.main(["--build-only"] if args.cloud_build_only else [])
    if args.swath_cmr or args.swath_build_only:
        if args.download or args.region or args.archive_pass or args.merge_counts:
            parser.error("--swath-cmr does not combine with other steps")
        return swath_cmr.main(["--build-only"] if args.swath_build_only else [])
    if args.archive_pass and args.merge_counts:
        parser.error("--archive-pass and --merge-counts are separate steps")
    if args.archive_pass or args.merge_counts:
        if args.download or args.region:
            parser.error("--archive-pass/--merge-counts do not combine with --download or --region")
        forwarded = ["--regions", *args.regions]
        forwarded += ["--products", *args.products] if args.products else []
        forwarded += ["--years", *map(str, args.years)] if args.years else []
        forwarded += [flag for flag, on in (("--keep-zips", args.keep_zips), ("--force", args.force),
                                            ("--merge-counts", args.merge_counts), ("--partial", args.partial)) if on]
        return archive_pass.main(forwarded)
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
