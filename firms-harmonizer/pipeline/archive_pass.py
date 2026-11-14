"""Streaming pass over the FIRMS yearly archives: global daily counts and preset-region clipping.

No global ingest and no global cube are built. For every (product, year) this module downloads one zip
(``download.download_one``: resumable, size and zip verified), extracts its CSV members to ``data/real/.tmp``,
runs DuckDB over those files and keeps only two small products:

* ``data/real/archive_pass/product=<p>/year=<y>/counts.csv``: detections per canonical satellite and day,
  counted with the very same rules as the global ingest (``pipeline.ingest.prepare_kept``: validity window,
  exact-identity de-duplication, SAMA rule; unknown satellite codes raise);
* ``data/real/regions/<region>/archive_csv/<region>_<product>_archive_<year>.csv``: the de-duplicated rows
  inside the region box of ``data/regions.json``, in the original FIRMS columns and text, ready for
  ``scripts/01_ingest_firms.py --extra-raw-dir data/real/regions/<region>/archive_csv``.

The chunk is finished when ``_SUCCESS`` is written (after ``counts.csv``, ``stats.json`` and the clipped CSVs);
the zip is deleted afterwards unless ``keep_zips``. ``merge_counts`` turns the partial counts into
``data/lookup/global_daily_counts_archive.csv`` and refuses to run when a chunk is missing, because a missing
year would otherwise look like zero-count outage days to ``scripts/02``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path

import duckdb
import httpx

from pipeline import config, download, ingest

CLIP_DIR = "archive_csv"
COUNTS_NAME, STATS_NAME, SUCCESS_NAME = "counts.csv", "stats.json", "_SUCCESS"


class ArchiveIncomplete(RuntimeError):
    """Raised when the partial counts do not cover every required (product, year) chunk."""


def chunk_dir(product: str, year: int) -> Path:
    return config.ARCHIVE_PASS / f"product={product}" / f"year={year}"


def clip_path(region: str, product: str, year: int) -> Path:
    """Clipped FIRMS CSV; the name never contains ``nrt`` so ``scripts/01`` treats it as standard (archive)."""
    return config.region_dir(region) / CLIP_DIR / f"{region}_{product}_archive_{year}.csv"


def _read_stats(product: str, year: int) -> dict | None:
    folder = chunk_dir(product, year)
    if not (folder / SUCCESS_NAME).is_file():
        return None
    return json.loads((folder / STATS_NAME).read_text(encoding="utf-8"))


def is_complete(product: str, year: int, regions: list[str]) -> bool:
    """True when the chunk finished and already clipped every requested region."""
    stats = _read_stats(product, year)
    return stats is not None and set(regions) <= set(stats["regions"])


def _atomic_text(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _bounds(regions: list[str]) -> dict[str, list[float]]:
    known = config.load_regions()
    unknown = [r for r in regions if r not in known]
    if unknown:
        raise ValueError(f"Unknown regions {unknown} (see data/regions.json)")
    return {r: known[r]["bounds"] for r in regions}


def process_archive(con: duckdb.DuckDBPyConnection, archive: Path, product: str, year: int,
                    regions: list[str]) -> dict:
    """Count and clip one zip. Writes the chunk outputs and ``_SUCCESS``; returns the chunk statistics."""
    previous = _read_stats(product, year)
    regions = sorted(set(regions) | set(previous["regions"] if previous else ()))
    bounds = _bounds(regions)
    folder = chunk_dir(product, year)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / SUCCESS_NAME).unlink(missing_ok=True)
    extract = config.TMP / f"archive_{product}_{year}"
    n_groups = 0
    try:
        files = ingest.extract_csvs(archive, extract)
        extracted_bytes = sum(f.stat().st_size for f in files)
        with files[0].open(encoding="utf-8", errors="replace") as handle:
            header = handle.readline().strip()
        n_groups = ingest.prepare_kept(con, files, keep_original=True)

        counts_tmp = folder / (COUNTS_NAME + ".tmp")
        con.execute("COPY (SELECT sensor AS satellite, acq_date, count(*)::BIGINT AS detection_count "
                    "FROM kept WHERE NOT is_sama GROUP BY ALL ORDER BY 1, 2) TO ? (FORMAT csv, HEADER)",
                    [str(counts_tmp)])
        satellites = {row[0]: {"detections": row[1], "first_day": str(row[2]), "last_day": str(row[3]),
                               "days": row[4]}
                      for row in con.execute("SELECT sensor, count(*) FILTER (WHERE NOT is_sama), "
                                             "min(acq_date) FILTER (WHERE NOT is_sama), "
                                             "max(acq_date) FILTER (WHERE NOT is_sama), "
                                             "count(DISTINCT acq_date) FILTER (WHERE NOT is_sama) "
                                             "FROM kept GROUP BY 1 ORDER BY 1").fetchall()}
        rows_read, rows_valid = (con.execute("SELECT count(*) FROM norm").fetchone()[0],
                                 con.execute("SELECT count(*) FROM valid").fetchone()[0])
        rows_dedup, rows_sama = con.execute("SELECT count(*), count(*) FILTER (WHERE is_sama) FROM kept").fetchone()

        clipped, outputs = {}, {}
        for region, (west, south, east, north) in bounds.items():
            target = clip_path(region, product, year)
            where, params = "lon BETWEEN ? AND ? AND lat BETWEEN ? AND ?", [west, east, south, north]
            n = con.execute("SELECT count(*) FROM dedup WHERE " + where, params).fetchone()[0]
            clipped[region] = n
            target.parent.mkdir(parents=True, exist_ok=True)
            if n == 0:
                target.unlink(missing_ok=True)
                continue
            tmp = target.with_name(target.name + ".tmp")
            con.execute("COPY (SELECT orig.* EXCLUDE (filename) FROM dedup WHERE " + where +
                        " ORDER BY acq_date, acq_time_int, lat, lon, sensor, frp, source_file) "
                        "TO ? (FORMAT csv, HEADER)", params + [str(tmp)])
            tmp.replace(target)
            outputs[region] = str(target.relative_to(config.ROOT) if target.is_relative_to(config.ROOT) else target)
        counts_tmp.replace(folder / COUNTS_NAME)
        stats = {"product": product, "year": year, "zip_bytes": archive.stat().st_size,
                 "members": len(files), "extracted_bytes": extracted_bytes, "header": header,
                 "rows_read": rows_read, "rows_valid": rows_valid, "rows_after_dedup": rows_dedup,
                 "rows_sama_removed": rows_sama, "satellites": satellites, "regions": clipped,
                 "region_files": outputs}
        _atomic_text(folder / STATS_NAME, json.dumps(stats, indent=1))
        _atomic_text(folder / SUCCESS_NAME, "ok\n")
        return stats
    finally:
        if n_groups:
            ingest.drop_prepared(con, n_groups)
        shutil.rmtree(extract, ignore_errors=True)


def run_pass(products=None, years=None, regions=None, keep_zips: bool = False, force: bool = False,
             con: duckdb.DuckDBPyConnection | None = None) -> list[dict]:
    """Sequential, resumable pass; one zip on disk at a time. Prints one line per chunk."""
    regions = list(regions or config.PRESET_REGIONS)
    _bounds(regions)
    chunks = download.wanted(products, years)
    if not chunks:
        raise ValueError("No (product, year) chunk matches --products/--years")
    con = con or config.connect()
    results = []
    with httpx.Client(timeout=httpx.Timeout(60.0, read=300.0),
                      headers={"User-Agent": "firms-harmonizer-pipeline"}) as client:
        for i, (product, year) in enumerate(chunks, 1):
            label = f"[{i}/{len(chunks)}] {product:12s} {year}"
            if not force and is_complete(product, year, regions):
                print(f"{label}  skipped (_SUCCESS present)", flush=True)
                results.append(_read_stats(product, year))
                continue
            t0 = time.perf_counter()
            archive = download.download_one(client, product, year)
            t1 = time.perf_counter()
            stats = process_archive(con, archive, product, year, regions)
            t2 = time.perf_counter()
            if not keep_zips:
                archive.unlink()
            per_sat = ", ".join(f"{s}={v['detections']:,}" for s, v in stats["satellites"].items())
            per_region = ", ".join(f"{r}={n:,}" for r, n in stats["regions"].items())
            print(f"{label}  zip {stats['zip_bytes'] / 1e6:8.1f} MB  download {t1 - t0:6.1f} s  "
                  f"process {t2 - t1:6.1f} s  rows {stats['rows_read']:,}  counted {per_sat}  "
                  f"clipped {per_region}", flush=True)
            results.append(stats)
    return results


def merge_counts(output: Path | None = None, partial: bool = False) -> dict:
    """Merge the partial counts into one CSV: every calendar day of each satellite's span, zeros included.

    Fails (``ArchiveIncomplete``) when a required chunk has no ``_SUCCESS``. Required chunks: every published
    year of every product, or with ``partial`` the contiguous year range between the first and last finished
    chunk of each finished product. A day present in two chunks also fails instead of being summed.
    """
    output = Path(config.ARCHIVE_COUNTS if output is None else output)
    done: dict[str, set[int]] = {}
    for marker in sorted(config.ARCHIVE_PASS.glob(f"product=*/year=*/{SUCCESS_NAME}")):
        product = marker.parent.parent.name.split("=", 1)[1]
        done.setdefault(product, set()).add(int(marker.parent.name.split("=", 1)[1]))
    if not done:
        raise ArchiveIncomplete(f"No finished chunk under {config.ARCHIVE_PASS}; run the archive pass first.")
    missing = []
    for product, (first, last) in config.PRODUCTS.items():
        have = done.get(product, set())
        if partial:
            if not have:
                continue
            first, last = min(have), max(have)
        missing += [f"{product} {y}" for y in range(first, last + 1) if y not in have]
    if missing:
        raise ArchiveIncomplete(f"Missing archive-pass chunks ({len(missing)}): {', '.join(missing)}. "
                                "Run them with --archive-pass or merge with --partial.")
    files = [str(chunk_dir(p, y) / COUNTS_NAME) for p in sorted(done) for y in sorted(done[p])]
    columns = "{'satellite': 'VARCHAR', 'acq_date': 'DATE', 'detection_count': 'BIGINT'}"  # constant, no input
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    with duckdb.connect() as con:
        con.execute("CREATE TEMP TABLE partial AS SELECT * FROM read_csv(?, header = true, columns = "
                    + columns + ")", [files])
        duplicate = con.execute("SELECT satellite, acq_date FROM partial GROUP BY ALL HAVING count(*) > 1 "
                                "LIMIT 1").fetchone()
        if duplicate is not None:
            raise ArchiveIncomplete(f"Day {duplicate[1]} of {duplicate[0]} appears in more than one chunk")
        if con.execute("SELECT count(*) FROM partial").fetchone()[0] == 0:
            raise ArchiveIncomplete("The finished chunks contain no detection")
        con.execute("""COPY (
            WITH span AS (SELECT satellite, min(acq_date) AS lo, max(acq_date) AS hi FROM partial GROUP BY 1),
            days AS (SELECT satellite, unnest(generate_series(lo, hi, INTERVAL 1 DAY))::DATE AS acq_date FROM span)
            SELECT satellite, acq_date, coalesce(detection_count, 0)::BIGINT AS detection_count
            FROM days LEFT JOIN partial USING (satellite, acq_date) ORDER BY satellite, acq_date
        ) TO ? (FORMAT csv, HEADER)""", [str(tmp)])
        summary = {s: {"first_day": str(a), "last_day": str(b), "days": n, "zero_days": z, "detections": d}
                   for s, a, b, n, z, d in con.execute(
                       "SELECT satellite, min(acq_date), max(acq_date), count(*), "
                       "count(*) FILTER (WHERE detection_count = 0), sum(detection_count)::BIGINT "
                       "FROM read_csv(?, header = true, columns = " + columns + ") GROUP BY 1 ORDER BY 1",
                       [str(tmp)]).fetchall()}
    os.replace(tmp, output)
    return {"output": str(output), "chunks": len(files), "satellites": summary}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--merge-counts", action="store_true",
                        help="merge the partial counts into data/lookup/global_daily_counts_archive.csv")
    parser.add_argument("--partial", action="store_true",
                        help="with --merge-counts: only require a contiguous year range per finished product")
    parser.add_argument("--products", nargs="*", choices=sorted(config.PRODUCTS))
    parser.add_argument("--years", nargs="*", type=int)
    parser.add_argument("--regions", nargs="*", default=list(config.PRESET_REGIONS),
                        help="regions of data/regions.json to clip (default: the three presets)")
    parser.add_argument("--keep-zips", action="store_true", help="keep each zip after its chunk succeeded")
    parser.add_argument("--force", action="store_true", help="redo chunks that already have _SUCCESS")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.merge_counts:
        result = merge_counts(partial=args.partial)
        for satellite, s in result["satellites"].items():
            print(f"{satellite:6s} {s['first_day']} .. {s['last_day']}  {s['days']:6d} days  "
                  f"{s['zero_days']:5d} zero  {s['detections']:,} detections")
        print(f"Wrote {result['output']} from {result['chunks']} chunks")
        return 0
    run_pass(args.products, args.years, args.regions, args.keep_zips, args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
