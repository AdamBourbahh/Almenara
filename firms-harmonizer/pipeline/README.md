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
