# Backend Implementation Plan

**Goal** — Build and verify the offline FIRMS ETL pipeline and the on-demand API for harmonized daily fire radiative energy (FRE).

**Architecture** — Python, H3, DuckDB and PyArrow prepare the local Parquet cube. FastAPI queries it through DuckDB and delegates scientific analysis to the NumPy/SciPy core. The API delivers gzip-compressed JSON serialized with orjson.

**Source of truth** — [AGENTS.md](AGENTS.md) governs ownership and guardrails. [SPECS.md](SPECS.md) governs scientific methods and contracts. [ETL_SPEC.md](firms-harmonizer/data/ETL_SPEC.md) documents the ETL implementation. [CAMBIOS.md](firms-harmonizer/CAMBIOS.md) documents the approved contract updates, the API/core interface and known discrepancies.

**Status baseline** — 2026-11-14, `main` at `35301bd` after the fast-forward pull from `4d0f6cb`. Check a task when its deliverable is present and supported by inspection or a passing check. Reopen a task when a regression invalidates that evidence. Mark a phase **Complete** when all of its acceptance tasks are checked, **In progress** when implementation or integration is present, and **Pending** when implementation has yet to start. Record the date, command, result and data source as tasks close. Run backend commands from `firms-harmonizer/`.

| Block | Complete | In progress | Pending |
| --- | --- | --- | --- |
| Offline ETL | — | 1, 2, 3, 5, 6, 7 | 4 |
| Online API | — | 8, 9, 10, 11, 12 | — |

## Pull review

- From `4d0f6cb` to `35301bd`, Git reports no deleted paths. Germán's `scripts/01_ingest_firms.py` through `scripts/05_cli_benchmark.py`, [ETL_SPEC.md](firms-harmonizer/data/ETL_SPEC.md), region definitions, download notes, LUT and mock JSON are unchanged. The local raw archives and staged Parquet are still present. These ignored inputs are outside Git's history.
- The scientific merge (`90f7f94`) rewrote Germán's generator and cube tests and added a synthetic Parquet at the master path. Before the pull, that path held the local hybrid artifact recorded in the previous baseline. The previous generator and tests are available at `4d0f6cb`. The rewritten suite dropped the mock/Python/TypeScript parity and request-validation checks. ETL now checks the mock provenance and request validation against Python. Phase 12 tracks restoring TypeScript parity with the frontend owner.

## Shared acceptance rules

- Germán owns `scripts/00` through `scripts/05` and `backend/tests/test_cube_schema.py`. Adam owns the science core, its tests and the backend schemas. Moha owns DuckDB, HTTP, the core adapter and their integration tests. Mohammed owns the frontend API mirror. Follow the full ownership table in [AGENTS.md](AGENTS.md).
- Preserve the frozen Python and TypeScript response contracts and the approved nullable fields. Keep `forecast_series`, `pm25_emitted_kg`, `total_pm25_emitted_tonnes` and `tooltip_narrative` nullable and return `null` for their deferred MVP capabilities. Keep user-facing output in English.
- Default startup requires a real-only local `data/processed/fire_cube.parquet`. Synthetic startup requires `USE_SYNTHETIC_CUBE=1` and serves `data/processed/fire_cube_synthetic.parquet`. Report the selected source as `data_source` and verify offline startup and requests in each mode.
- Keep H3 identifiers as unsigned integers inside DuckDB and Arrow. Use SQL `printf('%x', h3_r7)` for 15-character lowercase H3 identifiers in HTTP JSON. Use synchronous analytical routes and an isolated cursor per request, closed in `finally`. Keep FastAPI and DuckDB imports outside `backend/core/`.
- Keep the project query target of **<15 ms**. Record warmed SQL P95, uncached API processing, and cold and cached end-to-end HTTP timings with the AOI, date range, cube source, hardware and core implementation. The intermediate `execution_time_ms < 250 ms` budget in [CAMBIOS.md](firms-harmonizer/CAMBIOS.md) measures a different boundary. Treat the attachment's stage timings and pruning percentage as figures to measure.

## Block I — Offline ETL

### Phase 1 — Footprint geometry and H3 ingest · In progress

**Owners** — Germán for `scripts/01_ingest_firms.py`; Adam for `backend/core/footprint_h3.py`. **Specification** — [ETL_SPEC.md](firms-harmonizer/data/ETL_SPEC.md) stage 01 and [SPECS.md](SPECS.md) §2(5), §3.1.

- [x] Stage local FIRMS detections with H3 R4, R7 and R10 keys. The ETL script assigns VIIRS to the containing R7 cell and uses discrete, normalized, rotated Gaussian weights over the R7 center and its neighbors for deformed MODIS footprints, with the along-track bow-tie discount. This implements the approved footprint simplification.
- [x] Implement Adam's footprint module and verify center-cell behavior, Gaussian weighting for deformed MODIS footprints, and energy conservation and bow-tie weighting in the math tests.
- [ ] Verify parity between the ETL footprint calculations and Adam's core implementation on the same detections.

### Phase 2 — Daily de-duplication and diurnal FRE · In progress

**Owner** — Germán. **Files** — `scripts/01_ingest_firms.py`, `scripts/02_detect_outages_clouds.py`, `scripts/04_build_master_cube.py`. **Specification** — [ETL_SPEC.md](firms-harmonizer/data/ETL_SPEC.md) stages 01, 02 and 04 and [SPECS.md](SPECS.md) §2(6), §3.4.

- [x] Deduplicate identical sensor/time/location records, aggregate by R7 cell and UTC day, use coincident Terra/Aqua diurnal ratios where available, and publish previous-day neighbor energy in `neighbor_fre_lag1`.
- [ ] Validate the daily Eulerian integration and diurnal weights on known inputs, including repeated acquisitions and lag alignment. The current conversion multiplies FRP by a one-hour integration proxy and divides by cell area. Document the proxy's limits and verify the approved daily FRE method before claiming validated energy estimates. The approved scope uses cell-day aggregation, with the proposed event graph and trapezoidal integration outside this phase.

### Phase 3 — Industrial entropy, infrared contrast and SAMA · In progress

**Owners** — Adam for `backend/core/industrial_filter.py`; Germán for `scripts/01_ingest_firms.py`; Moha for the query consumer. **Specification** — [ETL_SPEC.md](firms-harmonizer/data/ETL_SPEC.md) stage 01 and [SPECS.md](SPECS.md) §2(3), §3.2.

- [x] Compute R10 Shannon entropy normalized over 12 calendar months. Current staging uses a positional variance gate, a logistic industrial score and a local SAMA filter.
- [x] Implement the core entropy, industrial score and SAMA filter. Unit tests cover the sigmoid, infrared contrast, SAMA boundaries and the Terra date cutoff.
- [ ] Align the ETL and core implementations and verify the classification and the API's removal counts with persistent flares and seasonal fires. ETL probes for `is_sama_artifact`, while the new core exposes `filter_sama_anomalies` and ETL still takes its local path. The DB industrial-filter integration test currently fails on the fixture epoch mismatch.

### Phase 4 — Orbital revisit weighting · Pending

**Owners** — Adam for the scientific rule and Germán for its application in `scripts/04_build_master_cube.py`. **Specification** — [SPECS.md](SPECS.md) §3.4(1).

- [ ] Resolve the equation in the specification before applying a weight. The revisit model gives `π_orb ∝ sec(latitude)`, while the weighting paragraph also calls `sec(latitude)` the inverse weight. For that revisit model, the mathematical inverse is proportional to `cos(latitude)`. Record the agreed expression, normalization and latitude domain in the authoritative specification.
- [ ] Apply the approved factor once to the offline energy calculation and verify its behavior across equatorial and high-latitude cells. Keep Terra diurnal scaling as a separate, existing correction.

### Phase 5 — Sensor outages and cloud gaps · In progress

**Owner** — Germán. **Files** — `scripts/02_detect_outages_clouds.py`, `scripts/04_build_master_cube.py`. **Specification** — [ETL_SPEC.md](firms-harmonizer/data/ETL_SPEC.md) stages 02 and 04 and [SPECS.md](SPECS.md) §3.4, §5.1.

- [x] Record Aqua Safe Mode (2022-07-31 through 2022-08-16). The current detector can also flag a drop below one-quarter of the mean of the preceding 15 complete global count days. The builder consumes local cloud ancillary data when supplied and sets the cloud bit above 80%.
- [ ] Verify the outage detector with actual global counts and document the evaluated rule. Validate the cloud, outage, swath gap and dual-blackout mask bits and their propagation into missing observations. Feed cloud reanalysis through a local, documented input for offline processing. The attachment's `−4σ` detector and Open-Meteo source are unverified proposals.

### Phase 6 — Censor-aware EQM and GPD lookup · In progress

**Owners** — Germán for `scripts/03_train_eqm_lut.py` and its ETL use; Adam for `backend/core/eqm_harmonizer.py`. **Specification** — [ETL_SPEC.md](firms-harmonizer/data/ETL_SPEC.md) stage 03 and [SPECS.md](SPECS.md) §3.3.

- [x] Train the current lookup on matched daytime Aqua/SNPP R7 cell-days in 2012–2025 using empirical quantiles and a bounded GPD tail. The trainer defines 17 IGBP classes and 10 angle bins, uses footprint width as an angle proxy, and falls back to broader strata when samples are sparse. A local `data/lookup/eqm_gpd_lut.json` was present at 9,553 bytes.
- [x] Implement Adam's `RadiometricHarmonizer`. Math tests cover linear interpolation, bounded GPD compensation, sparse or constant training inputs and invalid LUTs.
- [ ] Verify parity between the core and ETL lookup paths, including pre-2012 compensation on real samples. Record held-out results and which strata used real MCD12Q1 classes or nominal regional classes.

### Phase 7 — Master Parquet cube and publication · In progress

**Owner** — Germán, with Moha verifying API compatibility. **Files** — `scripts/00_bootstrap_synthetic_cube.py`, `scripts/04_build_master_cube.py`, `scripts/05_cli_benchmark.py`, `backend/tests/test_cube_schema.py`. **Specification** — [ETL_SPEC.md](firms-harmonizer/data/ETL_SPEC.md) stages 04–05 and [SPECS.md](SPECS.md) §5.1, subject to the real/synthetic rule in [AGENTS.md](AGENTS.md).

- [x] Implement the atomic, ZSTD-compressed master builder and verify the synthetic artifact's 18-field layout and unique ascending `(h3_r4, epoch_day, h3_r7)` keys. ZSTD level 9 and 128,000-row groups remain tuning candidates from the attachment.
- [x] Separate fixture and master publication. Script 00 and script 04 with `--bootstrap` default to `fire_cube_synthetic.parquet`. Script 04 builds a real-only master and preserves an existing output when staging is missing. The tracked synthetic master was removed. The local staged dataset produced **510,529** unique real cell-days, with zero fixture rows and consistent year and day-of-year values.
- [ ] Coordinate the 1970-01-01 epoch migration with Moha. Both generators now follow `SPECS.md` §5.1. DuckDB and the API still interpret the day index from 2000-01-01. Align the Cerrado AOI across the API tests and core checker, verify NOAA-21 masks and test both cube modes before replacing deployed cubes. Distinguish missing ancillary inputs from observed zero.
- [ ] Complete the real-data benchmark and scientific acceptance. The current artifact covers Chilecito and Iberia. Warmed query P95 was **17.64 ms** and **55.59 ms**, respectively, with no independent burned-area R². The three other benchmark regions have no real rows.

## Block II — On-demand API

### Phase 8 — Hierarchical H3 filter and DuckDB aggregation · In progress

**Owner** — Moha. **Files** — `backend/db/duckdb_engine.py`, `backend/db/queries.py`, `backend/tests/test_db_layer.py`. **Specification** — [AGENTS.md](AGENTS.md) guardrails 1, 3 and 4, [SPECS.md](SPECS.md) §3.1 and §5.1, and [CAMBIOS.md](firms-harmonizer/CAMBIOS.md).

- [x] Convert GeoJSON positions to H3 latitude/longitude order, polyfill R7, derive unique R4 parents, and register both cell lists as Arrow tables. Filter R4 then R7. The vectorized parent calculation is tested against H3 `cell_to_parent`; border cells and empty tiny AOIs have regression coverage. Reject AOIs above 250,000 R7 cells with HTTP 422.
- [x] Implement aggregation by UTC day, a dense calendar with NaN observations for missing measurements, cursor isolation and cursor closure on failure.
- [ ] Restore the DB regression gate with a freshly generated fixture after phase 7 aligns dates and regions. Verify populated Cerrado results, R7 filtering inside an R4 parent, industrial inclusion/exclusion, dense calendar length and 15-character H3 IDs. Five tests in `test_db_layer.py` failed after the pull, including a mask aggregation error from misaligned day indices.

### Phase 9 — RTS Kalman smoother and historical guard · In progress

**Owners** — Adam for `backend/core/kalman_rts.py`; Moha for `backend/api/core_contract.py` and `backend/api/routes.py`. **Specification** — [SPECS.md](SPECS.md) §3.4, [AGENTS.md](AGENTS.md) guardrail 5, and [CAMBIOS.md](firms-harmonizer/CAMBIOS.md) core interface.

- [x] Wire `compute_cross_prior(doy, obs)` and `kalman_rts_smooth(obs, u_spatial, prior)` into the API using three observation channels and a dense daily input. The call and shape validation are covered by tests with a simulated core.
- [x] Implement and unit-test the historical prior and guarded RTS routines in `kalman_rts.py`. The new functions are `build_cross_sensor_historical_prior` and `rts_kalman_smoother_with_cross_guard`, with tests for NaN observations, the dual blackout guard, Joseph covariance, and the forward/backward result against a batch posterior.
- [ ] Expose the API-compatible signatures `compute_cross_prior(doy, obs)` and `kalman_rts_smooth(obs, u_spatial, prior)` around those routines. Verify the finite 366-day prior and length-matched `x_smooth` and nonnegative `p_smooth` outputs on a populated AOI, including variance 40.0 on all-missing historical days, denominator jitter of `1e-8`, and ordered 95% intervals. The API checker still reports both required entry points missing when supplied a compatible fixture.

### Phase 10 — Circular phenology and decadal trends · In progress

**Owners** — Adam for `backend/core/von_mises.py`; Moha for API integration. **Specification** — [SPECS.md](SPECS.md) §3.6 and [CAMBIOS.md](firms-harmonizer/CAMBIOS.md) core interface.

- [x] Wire `fit_von_mises_year(doy, weights)` and `phenology_trend(years, peaks)` and validate the response shapes with a simulated core.
- [ ] Implement the 365.25-day circular fit, Best & Fisher concentration, season width, and Theil-Sen slope and Mann-Kendall p-value on unwrapped peaks. Verify leap days, peaks across the December/January boundary and zero-energy inputs. Both core functions are currently missing.

### Phase 11 — Scientific audit and Chaos Monkey · In progress

**Owners** — Adam for `backend/core/auditor_stats.py` and `backend/core/chaos_monkey.py`; Moha for HTTP integration and validation; Germán for the ETL benchmark and ancillary data pipeline. **Specification** — [SPECS.md](SPECS.md) §3.4(6), §3.5, §3.7 and §5.2, [CAMBIOS.md](firms-harmonizer/CAMBIOS.md), and [ETL_SPEC.md](firms-harmonizer/data/ETL_SPEC.md) stage 05.

- [x] Wire the audit calls and `POST /api/chaos-monkey`. The analysis route computes Wooster biomass with 0.368 kg/MJ. The CLI reports Chow, Wasserstein, burned-area cross-validation when available, and a seasonal-prior stress baseline.
- [ ] Implement and validate `chow_test`, `wasserstein_w1_normalized`, `descriptive_r2` and `run_chaos_monkey_simulation`. Use the January 2012 breakpoint, genuine annual MCD64A1 observations for independent validation, and null audit fields where the contract permits them and evidence is absent. Verify the actual audit against annual energy and burned area, including the effect of missing ancillary zero sentinels.
- [ ] Verify a seeded drop of VIIRS observations with the contract default of **25%**, and a 10-day dual blackout at peak season when enabled. Report naive and Kalman RMSE and recovered seasonal energy. Evaluate Chow `p > 0.10`, Wasserstein reduction, burned-area `R² > 0.90` and recovery `> 90%` as measured scientific targets; record the actual values and coverage.

### Phase 12 — HTTP, canonical cache and release verification · In progress

**Owner** — Moha, with Adam for core integration and Mohammed for the frontend contract mirror. **Files** — `backend/api/main.py`, `backend/api/routes.py`, `backend/api/cache.py`, `backend/api/core_contract.py`, `backend/check_core.py`, `backend/validation_report.py`. **Specification** — [AGENTS.md](AGENTS.md), [SPECS.md](SPECS.md) §2(7), §5.2, and [CAMBIOS.md](firms-harmonizer/CAMBIOS.md).

- [x] Expose synchronous `POST /api/analyze` and `POST /api/chaos-monkey`, plus `GET /api/health`. Serve orjson and GZipMiddleware for HTTP. Arrow stays internal to the query path; the proposed `/api/hexagons.arrow` endpoint and disk cache are outside this plan. The in-memory LRU uses BLAKE2b over sorted unique R7 cells, request parameters and cube modification time. `X-Cache` and `Server-Timing` expose cache and stage timings.
- [x] Retain HTTP tests for invalid geometry, empty AOIs, cache and core adapter error paths.
- [ ] Restore the HTTP and core validation gates with a newly generated fixture. Verify populated analysis and Chaos Monkey payloads, gzip and cache timing headers, and the 500 and 503 paths on a populated AOI. Eight tests in `test_api_contract.py` and `test_core_validation.py` failed after the pull.
- [ ] Restore the frozen TypeScript mirror and parity coverage against `backend/api/schemas.py` and the mock. The frontend merge removed `data_source` from both response types, removed `dates` from Chaos Monkey, and changed or removed other fields including daily `biomass_burned_tonnes` and approved nullability. Require explicit opt-in for synthetic fallback and propagate backend provenance into frontend state. The new client currently generates synthetic responses on connectivity or gateway errors and marks successful HTTP responses as non-synthetic, including responses from an opted-in synthetic backend.
- [ ] Pass `python -m pytest backend/tests/test_math_core.py -v`, `python -m backend.check_core --synthetic`, and `python -m backend.validation_report --synthetic` using Adam's implementation. Then run `python -m backend.validation_report` and smoke-test the HTTP routes on real local data with networking disabled. Verify startup behavior and provenance in both source modes, including an uncached analysis, a repeated request and a Chaos Monkey run. Record timings by stage and compare them to the project query target.

## Next backend step

Close phase 8 with Moha by aligning DuckDB, date serialization and the DB/API tests with the 1970 epoch and the agreed Cerrado AOI. Regenerate the fixture and require the DB and API suites to pass. Then verify a known UTC date on the real Chilecito cube and proceed with the phase 9 Kalman adapter.

## Verification after the pull

| Check | Observed on 2026-11-14 |
| --- | --- |
| `python -m pytest backend/tests -q --tb=short` | **86 passed, 13 failed** in a clean archive of `35301bd` with fresh synthetic API data. The failing tests are in the DB, HTTP and core validation suites. |
| `python -m pytest backend/tests/test_math_core.py backend/tests/test_cube_schema.py -q --tb=short` | **41 passed**. These tests cover the new math routines and the tracked fixture, while the DB and HTTP compatibility checks above exercise different contracts. |
| `python -m backend.check_core --synthetic` | The fresh fixture has no data for the checker's Cerrado AOI. With the previous local fixture copied into the test checkout, the checker runs and reports eight missing API callables, including the two Kalman entry points. |
| ETL publication branch | **43 passed** across cube and math tests. The full backend run recorded **88 passed, 13 failed** before the final test fixture isolation change. The staged real cube passed provenance, unique cell-day and UTC date checks. |
| Pre-pull ETL benchmark | **17.15–41.27 ms** warmed query P95 across five regions on the previous local hybrid master. Independent burned-area R² was unavailable for Chilecito and Iberia. Repeat after publishing the real-only master. |

Close the backend when the real-only cube passes the publication checks, the actual science core passes its own and the API's contracts, real and explicit synthetic modes work offline, and the measured scientific and latency results are recorded against the project targets.
