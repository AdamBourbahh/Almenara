# Offline FIRMS ETL specification

## Scope and acceptance

Build a local FIRMS cube for Chilecito and retain deterministic fixture coverage for the four pilot regions until their observations arrive. Run the five scripts in numeric order from the project directory. The build uses no network or API credentials.

```powershell
python scripts/01_ingest_firms.py
python scripts/02_detect_outages_clouds.py
python scripts/03_train_eqm_lut.py
python scripts/04_build_master_cube.py
python scripts/05_cli_benchmark.py
```

The cube must contain the 18 Arrow fields defined by the executable bootstrap contract, with its original types and nullability. The physical key is `(h3_r4, epoch_day, h3_r7)` with ascending order, unique cell-days and ZSTD compression. The executable fixture and its tests use days since 2000-01-01, despite the 1970 date in the project spec. The builder follows the tested convention. NOAA-21 uses the fifth sensor bit. The synthetic fixture keeps its existing grouped VIIRS bit and percentage cloud convention. Real rows store cloud as a fraction.

## Inputs and new regions

1. Add the new key to `data/regions.json` with `bounds` in west, south, east, north order, `nominal_biome` in 1–17 and inclusive `coverage` date intervals matching the FIRMS requests. Put specific regions before broader overlapping regions. Current contracts limit the cube to 2026.
2. Place the downloaded MODIS and VIIRS CSVs directly under `data/raw/`. Preserve archive and NRT labels in the file names so standard detections win exact identity conflicts. Original Chilecito files and download notes are preserved in a nested directory outside the ingest glob.
3. Run scripts 01–05. The four built-in regions use the project bootstrap's existing fixture centers. New regions become queryable from their ingested records. Adding a regional frontend preset is a separate team change.

Use local auxiliary Parquet files when available.

| Location | Columns |
|---|---|
| `data/lookup/igbp_cells.parquet` | Unique unsigned `h3_r7`, `igbp_biome` from MCD12Q1 |
| `data/lookup/cell_day_ancillary.parquet` | Unique unsigned `h3_r7` and `acq_date`, with `cloud_cover_pct` in 0–1 and `burned_area_ha_mcd64` in hectares |
| Path passed to script 02 with `--global-counts` | `satellite`, `acq_date`, `detection_count`. Supply one row per instrument per calendar day, including observed zero counts. |

## Stage behavior

- **01** uses DuckDB to read local CSVs. It normalizes sensors, UTC date and time, thermal channels and confidence. It deduplicates exact sensor/time/location matches, filters SAMA candidates, computes H3 resolutions 4, 7 and 10, and stages both center counts and Gaussian MODIS footprint contributions. The footprint weights sum to one per detection. Entropy is normalized over twelve calendar months and the industrial score includes a positional variance gate. The local SAMA rule runs while the backend module has no callable implementation.
- **02** records the Aqua safe-mode interval and optionally flags fourfold drops relative to the previous 15 complete days of global counts. Local detection counts cannot establish global outages. Diurnal ratios use coincident daytime Aqua and Terra FRP by H3 r4 and month.
- **03** uses coincident daytime Aqua and SNPP r7 cell-days in 2012–2025. It fits empirical quantiles above 8 MW and fits a bounded sub-threshold contribution from VIIRS samples. Bins derive from footprint width, which is an angle proxy. Sparse strata fall back to biome then pooled fits. Unsupported models are omitted, with uncalibrated FRP as the build fallback.
- **04** aggregates per cell-day, applies available lookup corrections, uses a one-hour FRP integration proxy for FRE density and computes prior-day neighbor energy. The bootstrap fixture fills uncovered days for its four original pilot regions. Coverage is declared independently of detection density. Real FIRMS rows are sparse detections, and days without detections have no real row. For real rows without auxiliary data, biome uses the configured nominal class and cloud and burned area use zero sentinels. Parquet metadata records these limitations. The final replacement is atomic.
- **05** measures warmed regional queries against the physical Parquet, reports Chow p-values and Wasserstein distance, computes leave-one-year-out burned-area R2 where defined, and exercises a seasonal-prior recovery baseline. A missing audit result fails the gate. Fixture metrics are diagnostics. Full Chaos Monkey validation depends on the backend RTS implementation.

## Verification

Run `python scripts/00_bootstrap_synthetic_cube.py` followed by `python -m pytest backend/tests/test_cube_schema.py -q` for the original synthetic gate. Run script 04 again to publish the hybrid cube after that gate. For the hybrid output, check the 18 field types and nullability, ZSTD compression, ordering, unique keys, real row counts and footprint energy conservation. Script 05 exits nonzero when the measured project thresholds are unmet.

## Iberia FIRMS archive

The `iberia_med` ingest region uses west/south/east/north bounds `[-9.5, 36, 4, 44]` and the declared request window 2000-11-01 through 2026-11-01. The archive includes land outside Spain. A country-only study needs an explicit administrative polygon. The original frontend preset covers a smaller area.

Eight files named `spain_fire_*.csv` are staged directly under `data/raw/`. FIRMS request IDs are 847720 (MODIS), 847721 (NOAA-20), 847722 (NOAA-21) and 847723 (Suomi-NPP). Download notes are under `data/raw/spain_download_notes/`.
