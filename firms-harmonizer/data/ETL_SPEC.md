# Offline FIRMS ETL specification

## Scope and acceptance

Build a real-only local FIRMS cube for regions with staged observations and declared coverage. The deterministic pilot fixture is generated separately at `data/processed/fire_cube_synthetic.parquet` by script 00 or by script 04 with `--bootstrap`. Run the five scripts in numeric order from the project directory. The build uses no network or API credentials.

```powershell
python scripts/01_ingest_firms.py
python scripts/02_detect_outages_clouds.py
python scripts/03_train_eqm_lut.py
python scripts/04_build_master_cube.py
python scripts/05_cli_benchmark.py
```

The cube must contain the 18 Arrow fields defined by the executable bootstrap contract, with its original types and nullability. The physical key is `(h3_r4, epoch_day, h3_r7)` with ascending order, unique cell-days and ZSTD compression. Both cubes store UTC days since 1970-01-01, as specified in `SPECS.md`. NOAA-21 uses the fifth sensor bit in real data. The fixture uses a grouped VIIRS bit. Both cubes store cloud cover as a fraction. Regenerate older cubes before adopting the 1970 epoch in the API.

## Inputs and new regions

1. Add the new key to `data/regions.json` with `bounds` in west, south, east, north order, `nominal_biome` in 1–17 and inclusive `coverage` date intervals matching the FIRMS requests. Put specific regions before broader overlapping regions. Current contracts limit the cube to 2026.
2. Place the downloaded MODIS and VIIRS CSVs directly under `data/raw/`. Preserve archive and NRT labels in the file names so standard detections win exact identity conflicts. Original Chilecito files and download notes are preserved in a nested directory outside the ingest glob.
3. Run scripts 01–05. Regions with real observations become queryable from their ingested records. Adding a regional frontend preset is a separate team change.

Use local auxiliary Parquet files when available.

| Location | Columns |
|---|---|
| `data/lookup/igbp_cells.parquet` | Unique unsigned `h3_r7`, `igbp_biome` from MCD12Q1 |
| `data/lookup/cell_day_ancillary.parquet` | Unique unsigned `h3_r7` and `acq_date`, with `cloud_cover_pct` in 0–1 and `burned_area_ha_mcd64` in hectares |
| Path passed to script 02 with `--global-counts` | `satellite`, `acq_date`, `detection_count`. Supply one row per instrument per calendar day, including observed zero counts. |

## Stage behavior

- **01** uses DuckDB to read local CSVs. It normalizes sensors, UTC date and time, thermal channels and confidence. It deduplicates exact sensor/time/location matches, filters SAMA candidates, computes H3 resolutions 4, 7 and 10, and stages both center counts and Gaussian MODIS footprint contributions. The footprint weights sum to one per detection. Entropy is normalized over twelve calendar months and the industrial score includes a positional variance gate. The ETL currently uses its local SAMA rule.
- **02** records the Aqua safe-mode interval and optionally flags fourfold drops relative to the previous 15 complete days of global counts. Local detection counts cannot establish global outages. Diurnal ratios use coincident daytime Aqua and Terra FRP by H3 r4 and month.
- **03** uses coincident daytime Aqua and SNPP r7 cell-days in 2012–2025. It fits empirical quantiles above 8 MW and fits a bounded sub-threshold contribution from VIIRS samples. Bins derive from footprint width, which is an angle proxy. Sparse strata fall back to biome then pooled fits. Unsupported models are omitted, with uncalibrated FRP as the build fallback.
- **04** aggregates per cell-day, applies available lookup corrections, uses a one-hour FRP integration proxy for FRE density and computes prior-day neighbor energy. Only staged FIRMS detections contribute rows to the real master. Missing staging stops the build before replacement. Coverage is declared independently of detection density. Real FIRMS rows are sparse detections, and days without detections have no real row. For real rows without auxiliary data, biome uses the configured nominal class and cloud and burned area use zero sentinels. Parquet metadata records these limitations. The final replacement is atomic.
- **05** measures warmed regional queries against the physical Parquet, reports Chow p-values and Wasserstein distance, computes leave-one-year-out burned-area R2 where defined, and exercises a seasonal-prior recovery baseline. A missing audit result fails the gate. Fixture metrics are diagnostics. Full Chaos Monkey validation depends on the backend RTS implementation.

### Stage 02 outage evidence contract

`data/lookup/sensor_outages.parquet` has exactly these columns, in order:

| Column | DuckDB / Arrow type | Meaning |
| --- | --- | --- |
| `acq_date` | `DATE` / `date32[day]` | UTC calendar day |
| `satellite` | `VARCHAR` / `string` | Canonical instrument: `Terra`, `Aqua`, `SNPP`, `N20`, `N21` |
| `evidence` | `VARCHAR` / `string` | `known_safe_mode` or `global_count_drop` |

Rows are unique and sorted by `(acq_date, satellite, evidence)`. With no `--global-counts`, all three columns are non-null and the output is exactly 17 `Aqua` / `known_safe_mode` rows, inclusive from **2022-07-31 to 2022-08-16**. Staged regional detections are never used to infer global outages. Known and dynamic evidence can coexist for the same instrument-day; stage 04 consumes their distinct instrument-day pairs.

The optional local Parquet supplied with `--global-counts` must use the canonical instrument names above and unique `(satellite, acq_date)` keys. Dates are cast to `DATE`; `detection_count` is cast to `DOUBLE`. Counts represent nonnegative global daily totals, including explicit observed zeros. For each instrument and target day `t`, the detector evaluates:

```text
baseline = mean(counts on the 15 calendar days t-15 through t-1)
outage = all 15 preceding days have non-null counts
         AND baseline > 0
         AND detection_count(t) < 0.25 * baseline
```

The current day is excluded from the baseline. Equality at one-quarter does not trigger. Observed zero counts participate in the mean and a zero target triggers against a positive complete baseline. A missing calendar day, null preceding count, null target count, or all-zero baseline does not trigger. Older observations cannot fill a missing day in the 15-day window. Duplicate instrument-days raise `ValueError` before replacing the existing outage lookup, so repeated rows cannot fake a complete window. Count-source provenance remains the input provider's responsibility; synthetic count fixtures are confined to temporary test directories.

Stage 02 also writes `diurnal_ratios.parquet`: `h3_r4: UBIGINT/uint64`, `month: UTINYINT/uint8`, `ratio: DOUBLE/float64`, `matched_days: BIGINT/int64`, sorted by `(h3_r4, month)`. It aggregates coincident positive daytime Terra/Aqua FRP. Missing staging produces a correctly typed empty ratio table. Serial DuckDB aggregation and explicit output ordering make both files byte-reproducible for identical inputs and software versions.

### Stage 04 observation and gap semantics

`sensor_obs_mask` is an unsigned byte: Terra `1`, Aqua `2`, SNPP `4`, NOAA-20 (`N20`) `8`, NOAA-21 (`N21`) `16`. It describes usable observations after masking. A known or dynamic instrument outage removes only that instrument's observation and bit. The grouped `obs_viirs_fre` averages the surviving VIIRS instruments and is null only when none survives.

`gap_status_mask` is an unsigned byte whose flags combine with bitwise OR:

| Value | Meaning and offline evidence |
| --- | --- |
| `0` | No supported gap evidence on the staged cell-day |
| `1` | At least one instrument has an outage lookup entry on that date |
| `2` | Local ancillary cloud fraction is strictly greater than `0.80` |
| `4` | Reserved for a swath gap supported by coverage evidence; current inputs cannot establish it |
| `8` | All three observation channels are missing after outage/cloud masking |

Cell-day cloud occlusion applies to all instruments: the three FRE observations become Parquet nulls and `sensor_obs_mask` becomes zero. Therefore cloud-only blackout is `10` and cloud plus outage blackout is `11`; outage-only total blackout is `9`. Raw detection counts and raw FRP remain available for audit. Exactly `0.80` remains below the occlusion rule for both FLOAT and DOUBLE ancillary columns. Neighbor lag energy is calculated **after** masking, so occluded measurements cannot contribute to the next day's neighbor energy.

The builder still emits only staged cell-days. Neither an absent sensor detection nor an absent cell-day proves a swath gap; it does not invent a dense calendar or set bit `4`. Positive swath-gap validation requires an additional documented coverage source and remains open.

The optional ancillary file uses unique `(h3_r7, acq_date)` keys, cloud fractions in `[0, 1]`, and finite nonnegative burned area in hectares. Missing rows or null values retain the frozen non-null columns' zero sentinel. The JSON Parquet metadata key `ancillary_coverage` records `input_present` and, for each of `cloud_cover_pct` and `burned_area_ha_mcd64`, `observed_rows`, `missing_rows`, and `observed_zero_rows` over published cell-days. An observed zero counts as observed, never missing. These are aggregate provenance counts: an individual zero in a partially covered cube still requires the original ancillary join to distinguish its provenance. Do not treat all zero sentinels as measured clear sky or measured zero burned area.

### Phase 5 local verification — 2026-11-14

Inspection of every CSV header and Parquet schema under `data/raw/` and `data/lookup/` found **no global daily count table** and **no `cell_day_ancillary.parquet`**. The existing `cloud_outages.parquet` has 9,496 rows with `date`, `epoch_day`, `cloud_cover_pct`, and `gap_status_mask`, but no H3 key or provenance metadata. It is not the required cell-day reanalysis input and is not consumed as one.

Two consecutive runs of `python scripts/02_detect_outages_clouds.py` from `firms-harmonizer/` produced identical bytes:

| Output | Rows | SHA-256 |
| --- | ---: | --- |
| `sensor_outages.parquet` | 17 | `6ac6b1bec13f35cac06a39135b7386fa69367c788dbcd2faf1bea2038feb9d98` |
| `diurnal_ratios.parquet` | 2,075 | `5d884f0523f349b5c39907b292b6722648bd9560fe80a84061910e31e48945bb` |

The outage dates exactly match the 17-day interval in `SPECS.md` §3.4. Evidence is the specification's known interval; diurnal ratios come from the existing local staged FIRMS file. The test suite checks repeated CLI execution, strict dynamic threshold boundaries, observed zeros, incomplete calendar windows, per-instrument partitioning, duplicate rejection, all five sensor bits, Aqua null propagation, surviving VIIRS instruments, combined blackout bits, cloud FLOAT/DOUBLE boundaries, neighbor lag exclusion, and ancillary metadata. All synthetic global counts and cloud inputs used for those checks are temporary fixtures, not production lookups. Actual global-count and cloud-reanalysis validation remain open.

### Differential review — Phase 5, 2026-11-14

**Baseline and scope:** working tree against `9a25bc1`; focused review of scripts 02 and 04, the cube schema tests, and the two authorized documentation files. The initial working tree was clean. Logic changes carry medium correctness risk; tests and documentation carry low risk. No new security finding was identified (critical/high/medium/low: 0/0/0/0); this is a scoped assessment, not a repository-wide security audit.

**Historical context:** `git log` and `git blame` trace the affected detector and ancillary logic to `da497a6`; real-only atomic publication safeguards were introduced by `c2b3ed6` and remain intact. No authentication, network, API, core, database-service, or frontend code was changed, and no validation was removed.

**Changes and regression evidence:** tests first reproduced non-reproducible outage ordering, duplicate counts faking a complete window, cloud observations surviving masking, missing blackout flags, absent ancillary provenance counts, and FLOAT `0.80` crossing the boundary after conversion to Python double. The implementation now sorts evidence, serializes stage 02 aggregation, rejects duplicate count keys, masks clouds before neighbor aggregation, marks total blackouts, and records ancillary coverage. The new tests exercise actual CLI processes and local Parquet publication; they do not call HTTP or the Kalman adapter.

**Blast radius:** `build_outages_table` has one production caller (script 02 CLI); `real_rows` has one (the master builder); `build_master_cube` has one (script 04 CLI). Their outputs feed offline lookup/cube consumers. The 18-column cube contract, raw observation counts, real/synthetic separation, and atomic master replacement are preserved. No changed production function lacks focused regression coverage; no numerical coverage percentage is claimed.

**Recommendation:** accept the offline fixes subject to the remaining real-data validation tasks. Positive swath inference, actual global counts, and cloud reanalysis are not validated. Aggregate ancillary metadata does not provide per-row provenance. Existing published real cubes require an explicit stage 04 rebuild to acquire these changes; this verification does not replace the current real master. Confidence is high for the tested local behavior and limited for unavailable external evidence. No network requests were made.

## Verification

Run `python scripts/00_bootstrap_synthetic_cube.py` followed by `python -m pytest backend/tests/test_cube_schema.py -q` for the synthetic gate. The schema suite generates its own temporary fixture. Run script 04 to publish the real cube. For the real output, check the 18 field types and nullability, ZSTD compression, ordering, unique keys, real row counts and footprint energy conservation. Script 05 exits nonzero when the measured project thresholds are unmet.

<details>
<summary>Exact Phase 5 acceptance output — 2026-11-14</summary>

Commands run from `firms-harmonizer/`; both exited with code 0:

```powershell
python scripts/02_detect_outages_clouds.py
python scripts/00_bootstrap_synthetic_cube.py && python -m pytest backend/tests/test_cube_schema.py -v
```

```text
Wrote sensor_outages.parquet and diurnal_ratios.parquet.
Synthetic cube: C:\vscode\proyectos\Almenara\firms-harmonizer\data\processed\fire_cube_synthetic.parquet (0.982s)
============================= test session starts =============================
platform win32 -- Python 3.12.6, pytest-9.1.1, pluggy-1.6.0 -- C:\Users\germa\AppData\Local\Programs\Python\Python312\python.exe
cachedir: .pytest_cache
rootdir: C:\vscode\proyectos\Almenara\firms-harmonizer\backend
configfile: pyproject.toml
plugins: anyio-4.15.1, platformdirs-4.12.4, cov-7.1.0, time-machine-2.16.0
collecting ... collected 37 items

backend\tests\test_cube_schema.py::test_stage02_known_aqua_interval_is_exact_and_reproducible PASSED [  2%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history0-24.0-True] PASSED [  5%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history1-25.0-False] PASSED [  8%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history2-0.0-True] PASSED [ 10%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history3-24.0-False] PASSED [ 13%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history4-23.0-True] PASSED [ 16%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history5-0.0-False] PASSED [ 18%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history6-0.0-False] PASSED [ 21%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history7-0.0-False] PASSED [ 24%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history8-None-False] PASSED [ 27%]
backend\tests\test_cube_schema.py::test_stage02_missing_calendar_day_does_not_trigger PASSED [ 29%]
backend\tests\test_cube_schema.py::test_stage02_duplicate_days_cannot_fake_a_complete_window PASSED [ 32%]
backend\tests\test_cube_schema.py::test_stage04_aqua_outage_and_five_instrument_bits PASSED [ 35%]
backend\tests\test_cube_schema.py::test_stage04_viirs_outages_preserve_remaining_instrument PASSED [ 37%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type0-0.0-0-False] PASSED [ 40%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type0-0.8-0-False] PASSED [ 43%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type0-0.8001-10-True] PASSED [ 45%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type0-1.0-10-True] PASSED [ 48%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type1-0.0-0-False] PASSED [ 51%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type1-0.8-0-False] PASSED [ 54%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type1-0.8001-10-True] PASSED [ 56%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type1-1.0-10-True] PASSED [ 59%]
backend\tests\test_cube_schema.py::test_stage04_ancillary_metadata_distinguishes_missing_and_observed_zero PASSED [ 62%]
backend\tests\test_cube_schema.py::test_missing_staging_preserves_existing_master PASSED [ 64%]
backend\tests\test_cube_schema.py::test_mock_and_request_contract PASSED [ 67%]
backend\tests\test_cube_schema.py::test_exact_schema_and_compression PASSED [ 70%]
backend\tests\test_cube_schema.py::test_sorted_and_unique PASSED         [ 72%]
backend\tests\test_cube_schema.py::test_four_regions_and_daily_coverage PASSED [ 75%]
backend\tests\test_cube_schema.py::test_calendar_keys_and_value_ranges PASSED [ 78%]
backend\tests\test_cube_schema.py::test_outages_and_sensor_masks PASSED  [ 81%]
backend\tests\test_cube_schema.py::test_required_outage_dates_in_duckdb[2022-08-10-sensors0] PASSED [ 83%]
backend\tests\test_cube_schema.py::test_required_outage_dates_in_duckdb[2022-08-24-sensors1] PASSED [ 86%]
backend\tests\test_cube_schema.py::test_instrumental_jump_and_physical_stability PASSED [ 89%]
backend\tests\test_cube_schema.py::test_industrial_and_climate_scenarios PASSED [ 91%]
backend\tests\test_cube_schema.py::test_generator_repeatability_performance_and_alternate_path PASSED [ 94%]
backend\tests\test_cube_schema.py::test_h3_compatibility_adapters[3] PASSED [ 97%]
backend\tests\test_cube_schema.py::test_h3_compatibility_adapters[4] PASSED [100%]

============================= 37 passed in 11.13s =============================
```

</details>

## Iberia FIRMS archive

The `iberia_med` ingest region uses west/south/east/north bounds `[-9.5, 36, 4, 44]` and the declared request window 2000-11-01 through 2026-11-01. The archive includes land outside Spain. A country-only study needs an explicit administrative polygon. The original frontend preset covers a smaller area.

Eight files named `spain_fire_*.csv` are staged directly under `data/raw/`. FIRMS request IDs are 847720 (MODIS), 847721 (NOAA-20), 847722 (NOAA-21) and 847723 (Suomi-NPP). Download notes are under `data/raw/spain_download_notes/`.
