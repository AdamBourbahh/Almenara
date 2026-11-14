# `pipeline/` — real FIRMS data pipeline

`pipeline/` turns the public FIRMS yearly global archives into a regional master cube and a measured
data-quality report. It adds what the offline stages in `scripts/` do not have (archive download, a
global ingest and the global daily detection counts) and routes everything else through those stages.
There is **one implementation** of every scientific rule: outages, footprints, harmonization and cube
building live only in `scripts/01–04` and `backend/core/`.

## Stages and how they relate to `scripts/01–04`

| Step | Module | What it does |
| --- | --- | --- |
| Download | `download.py` | Resumable download of `{modis, viirs-snpp, viirs-jpss1}` yearly `*_all_countries.zip` archives to `data/real/raw/` (size and zip integrity checked). The only module that uses the network. |
| Global ingest | `ingest.py` | Vectorized DuckDB normalization of every archive row: validity window, sensor canon (including the numeric NOAA-20/21 codes of the archives), confidence, exact-identity de-duplication (standard beats NRT) and the SAMA rule, with H3 r4/r7/r10 keys. Detections outside every `data/regions.json` box are kept with `region = NULL`. Output: `data/real/staged/detections/product=*/year=*/part.parquet`. |
| Global counts | `lookups.py` | `data/real/global_daily_counts.parquet`: `satellite, acq_date, detection_count` for every day of each sensor's record, explicit zeros included. |
| Canonical staging | `cube.stage_region` | Writes the region's detections back as FIRMS-format CSVs (original file names, fixed row order) and calls `scripts/01_ingest_firms.ingest_raw_firms`. The global-ingest filters equal those of `scripts/01`, so re-applying them is a no-op; a parity test proves the staging is identical to `scripts/01` on the original CSVs. |
| Lookups | `cube.build_lookups` | `scripts/02_detect_outages_clouds.build_outages_table` with the global counts (`KNOWN_OUTAGES`, `global_count_drop`, `zero_global_count`, diurnal ratios), then `scripts/03_train_eqm_lut.generate_eqm_gpd_lut` on the regional staging. |
| Cube | `cube.publish_cube` | `scripts/04_build_master_cube.build_master_cube`: orbital weight, core `RadiometricHarmonizer`, optional cloud/burned-area ancillary, outage and blackout bits, atomic publication. |
| Pairs | `pairs.py` | Diagnostic Aqua–SNPP coincidences per `(h3_r7, day, pass)` read from the canonical staging. Not used for training. |
| Report | `quality.py` | `data/real/quality_report.{md,json}`: stage counts per year and satellite, counts and outage evidence, cube contract checks and column provenance, pairs. |

`german.py` imports a `scripts/0N_*.py` file by name without modifying it. Regional outputs go to
`data/real/regions/<region>/` (`staged_firms.parquet`, `lookup/`, `fire_cube.parquet`,
`pairs_aqua_snpp.parquet`). Only regional cubes are built: `scripts/01` refuses detections outside the
configured regions, and `scripts/04` requires the region to declare a `coverage` in `data/regions.json`
that contains every detection day.

## Streaming archive pass (global counts and preset clipping without a global ingest)

`archive_pass.py` gets two small things out of the 48 yearly zips (modis 2000-2025, viirs-snpp 2012-2025,
viirs-jpss1 2018-2025; about 9.75 GB zipped; there is no NOAA-21 yearly archive) in one streaming pass that
keeps **at most one zip on disk**:

1. **Global daily detection counts per satellite**, for `scripts/02`'s outage detector. They use the same
   rules as the global ingest (`ingest.prepare_kept`: validity window, exact-identity de-duplication, SAMA
   rule, canonical satellite names; an unknown satellite code raises).
2. **The real detections inside the box of each preset region** (`cerrado_brazil`, `california_usa`,
   `niger_delta_flaring`, or any `--regions`) as FIRMS-format CSVs with the original columns and text.

Per (product, year): download (`download.download_one`, resumable, verified) -> extract the CSV members to
`data/real/.tmp/` -> DuckDB (2 GB, 2 threads, spilling to `.tmp`) -> write outputs -> delete the extraction
and, unless `--keep-zips`, the zip. Disk peak is therefore one zip plus its extracted CSVs; network is the
full 9.75 GB, once. Everything under `data/real/` is git-ignored.

| Output | Path |
| --- | --- |
| Partial counts, stats and marker | `data/real/archive_pass/product=<p>/year=<y>/{counts.csv,stats.json,_SUCCESS}` |
| Clipped CSV (only when rows exist) | `data/real/regions/<region>/archive_csv/<region>_<product>_archive_<year>.csv` |
| Merged counts | `data/lookup/global_daily_counts_archive.csv` (`satellite,acq_date,detection_count`) |

A chunk is finished only when `_SUCCESS` exists (written last); it is skipped on the next run unless
`--force`, or unless a requested region was not clipped yet. Clipped file names never contain `nrt`, so
`scripts/01` treats them as standard archive data. Stage them with the tracked CSVs:

```bash
python scripts/01_ingest_firms.py --extra-raw-dir data/real/regions/cerrado_brazil/archive_csv \
    --extra-raw-dir data/real/regions/california_usa/archive_csv \
    --extra-raw-dir data/real/regions/niger_delta_flaring/archive_csv
```

```bash
python -m pipeline.run --archive-pass --products modis --years 2000     # one chunk (the smallest probe)
python -m pipeline.run --archive-pass                                   # everything, sequential, resumable
python -m pipeline.run --merge-counts                                   # partial counts -> lookup CSV
```

**Splitting between machines or people.** Chunks are independent: run
`--archive-pass --products viirs-snpp` on one machine, `--products viirs-jpss1` on another, and split MODIS
with `--years 2000 2001 ...`. Copy each machine's `data/real/archive_pass/` and
`data/real/regions/*/archive_csv/` folders into the same paths on the machine that merges, then run
`--merge-counts`. The merge writes one row for **every** calendar day between each satellite's first and last
observed day, explicit zeros included, sorted by satellite and day. It fails with `ArchiveIncomplete` when a
(product, year) chunk has no `_SUCCESS` (by default all 48 are required; `--partial` only demands a
contiguous year range per finished product, for probes), and when a day appears in two chunks, so a partial
download can never fabricate zero-count outage days. `scripts/02` then prefers
`data/lookup/global_daily_counts_archive.csv` over the tracked 50-day `global_daily_counts.csv` unless
`--global-counts` is given.

Limits: the archives are per country (open-sea detections are absent, relevant for flaring offshore of
the Niger Delta), end in 2025, and every member of a zip must share one CSV header.

## One-time setup

Install the backend requirements, then the DuckDB `h3` community extension **once**, with the same
interpreter that runs the pipeline (it is stored in `<venv>/duckdb_extensions`; the pipeline loads it from
there and never downloads it):

```bash
cd firms-harmonizer
python -m pip install -r backend/requirements.txt
python -c "import duckdb, sys; duckdb.connect(config={'extension_directory': sys.prefix + '/duckdb_extensions'}).execute('INSTALL h3 FROM community')"
```

## Running

```bash
python -m pipeline.run --download --products modis --years 2022   # fetch archives (network)
python -m pipeline.run                                             # ingest, global counts, report (offline)
python -m pipeline.run --region amazonas_manaus                    # also stage, lookups, cube, pairs
python -m pipeline.run --help
```

Ingest is resumable: a product-year with `_SUCCESS` is skipped unless `--force-ingest` is given. DuckDB
uses at most 2 GB and 2 threads in the pipeline's own connection, spilling to `data/real/.tmp/` (the `scripts/` stages open their own connections). Serve a regional cube with
`FIRE_CUBE_PATH=data/real/regions/<region>/fire_cube.parquet`.

## Tests

```bash
python -m pytest pipeline/tests -q
sha256sum -c pipeline/tests/FROZEN_TESTS.sha256
```

The tests build the whole chain on the small FIRMS-format fixtures in `pipeline/tests/fixtures/` inside
a temporary folder, without network access.
