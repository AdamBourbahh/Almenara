# Backend Implementation Plan

**Goal** — Build and verify the offline FIRMS ETL pipeline and the on-demand API for harmonized daily fire radiative energy (FRE).

**Architecture** — Python, H3, DuckDB and PyArrow prepare the local Parquet cube. FastAPI queries it through DuckDB and delegates scientific analysis to the NumPy/SciPy core. The API delivers gzip-compressed JSON serialized with orjson.

**Source of truth** — [AGENTS.md](AGENTS.md) governs ownership and guardrails. [SPECS.md](SPECS.md) governs scientific methods and contracts. [ETL_SPEC.md](firms-harmonizer/data/ETL_SPEC.md) documents the ETL implementation. [CAMBIOS.md](firms-harmonizer/CAMBIOS.md) documents the approved contract updates, the API/core interface and known discrepancies.

**Status baseline** — 2026-11-14, `main` at `c159abb`. Check a task when its stated deliverable is present and supported by inspection or a passing check. Mark a phase **Complete** when all of its acceptance tasks are checked, **In progress** when implementation or integration is present, and **Pending** when implementation has yet to start. Record the date, command, result and data source as tasks close. Run backend commands from `firms-harmonizer/`.

| Block | Complete | In progress | Pending |
| --- | --- | --- | --- |
| Offline ETL | — | 1, 2, 3, 5, 6, 7 | 4 |
| Online API | 8 | 9, 10, 11, 12 | — |

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
- [ ] Complete Adam's footprint module and verify center-cell behavior, affected MODIS footprints and conservation of the discounted input power across distributed cells. Reuse the same scientific rule in ETL and the core.

### Phase 2 — Daily de-duplication and diurnal FRE · In progress

**Owner** — Germán. **Files** — `scripts/01_ingest_firms.py`, `scripts/02_detect_outages_clouds.py`, `scripts/04_build_master_cube.py`. **Specification** — [ETL_SPEC.md](firms-harmonizer/data/ETL_SPEC.md) stages 01, 02 and 04 and [SPECS.md](SPECS.md) §2(6), §3.4.

- [x] Deduplicate identical sensor/time/location records, aggregate by R7 cell and UTC day, use coincident Terra/Aqua diurnal ratios where available, and publish previous-day neighbor energy in `neighbor_fre_lag1`.
- [ ] Validate the daily Eulerian integration and diurnal weights on known inputs, including repeated acquisitions and lag alignment. The current conversion multiplies FRP by a one-hour integration proxy and divides by cell area. Document the proxy's limits and verify the approved daily FRE method before claiming validated energy estimates. The approved scope uses cell-day aggregation, with the proposed event graph and trapezoidal integration outside this phase.

### Phase 3 — Industrial entropy, infrared contrast and SAMA · In progress

**Owners** — Adam for `backend/core/industrial_filter.py`; Germán for `scripts/01_ingest_firms.py`; Moha for the query consumer. **Specification** — [ETL_SPEC.md](firms-harmonizer/data/ETL_SPEC.md) stage 01 and [SPECS.md](SPECS.md) §2(3), §3.2.

- [x] Compute R10 Shannon entropy normalized over 12 calendar months. Current staging uses a positional variance gate, a logistic industrial score and a local SAMA filter. The DB industrial inclusion/exclusion contract passes its fixture test.
- [ ] Complete the core industrial filter and verify its integration, including the `H_temp > 0.75` rule, infrared contrast, the positional variance gate, SAMA filtering and the pre-November 2000 cutoff. Use persistent flares and seasonal fires to verify the classification and the API's reported removal counts.

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
- [ ] Complete Adam's core module and verify upper-regime interpolation, pre-2012 sub-threshold compensation, sparse-stratum behavior and the LUT size limit of <150 KB. Record held-out results and which strata used real MCD12Q1 classes or nominal regional classes.

### Phase 7 — Master Parquet cube and publication · In progress

**Owner** — Germán, with Moha verifying API compatibility. **Files** — `scripts/00_bootstrap_synthetic_cube.py`, `scripts/04_build_master_cube.py`, `scripts/05_cli_benchmark.py`, `backend/tests/test_cube_schema.py`. **Specification** — [ETL_SPEC.md](firms-harmonizer/data/ETL_SPEC.md) stages 04–05 and [SPECS.md](SPECS.md) §5.1, subject to the real/synthetic rule in [AGENTS.md](AGENTS.md).

- [x] Build an atomic, ZSTD-compressed Parquet output with the 18-field layout and unique ascending `(h3_r4, epoch_day, h3_r7)` keys. The isolated synthetic bootstrap gate passed **11 tests**. The local master currently has 510,529 real rows and 199,836 fixture rows, with 32,768 rows in a full row group. ZSTD level 9 and 128,000-row groups are tuning candidates from the attachment.
- [ ] Publish the real-only master from verified FIRMS inputs and keep fixture generation on the separate synthetic path for API use. The current builder merges fixture coverage into the master and the engine rejects its hybrid metadata in default mode. Confirm that no fixture rows enter science or results labeled `real`, and report real temporal and regional coverage explicitly.
- [ ] Reconcile the cube conventions before publication. `SPECS.md` §5.1 says days since 1970-01-01, while the builder, consumer and fixture tests use 2000-01-01. Confirm the epoch across producers and consumers, NOAA-21's fifth mask bit, cloud fractions for real data versus legacy fixture percentages, and how missing ancillary inputs are distinguished from observed zero. Coordinate any schema or convention change through the owners and project references.
- [ ] Validate the real artifact separately for schema, nullability, order, unique keys, row source and coverage. Run `python scripts/05_cli_benchmark.py` against it and save the results. The current fixture gate reads `fire_cube.parquet`, so run it in a disposable checkout or copy when a local master is already present.

## Block II — On-demand API

### Phase 8 — Hierarchical H3 filter and DuckDB aggregation · Complete

**Owner** — Moha. **Files** — `backend/db/duckdb_engine.py`, `backend/db/queries.py`, `backend/tests/test_db_layer.py`. **Specification** — [AGENTS.md](AGENTS.md) guardrails 1, 3 and 4, [SPECS.md](SPECS.md) §3.1 and §5.1, and [CAMBIOS.md](firms-harmonizer/CAMBIOS.md).

- [x] Convert GeoJSON positions to H3 latitude/longitude order, polyfill R7, derive unique R4 parents, and register both cell lists as Arrow tables. Filter R4 then R7. The vectorized parent calculation is tested against H3 `cell_to_parent`; border cells and empty tiny AOIs have regression coverage. Reject AOIs above 250,000 R7 cells with HTTP 422.
- [x] Aggregate by UTC day and feed the API a dense calendar with NaN observations for missing measurements. Verify parallel cursor isolation, cursor closure on failure, industrial filtering and 15-character hex IDs. The DB suite passed as part of the 58-test gate. Real-data query performance remains an acceptance item in phases 7 and 12.

### Phase 9 — RTS Kalman smoother and historical guard · In progress

**Owners** — Adam for `backend/core/kalman_rts.py`; Moha for `backend/api/core_contract.py` and `backend/api/routes.py`. **Specification** — [SPECS.md](SPECS.md) §3.4, [AGENTS.md](AGENTS.md) guardrail 5, and [CAMBIOS.md](firms-harmonizer/CAMBIOS.md) core interface.

- [x] Wire `compute_cross_prior(doy, obs)` and `kalman_rts_smooth(obs, u_spatial, prior)` into the API using three observation channels and a dense daily input. The call and shape validation are covered by tests with a simulated core.
- [ ] Implement the 366-day circular historical prior and the linear-time forward/backward smoother. Skip NaN sensor updates, inject the historical guard on all-missing historical days with variance 40.0, use scalar Joseph covariance updates and add `1e-8` to forward and backward division denominators. Verify finite estimates and variances, robust dual-blackout recovery and ordered 95% intervals with a nonnegative lower bound. Both core functions are currently missing.

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
- [x] Verify the API contracts, cache and adapter error paths with tests. An empty AOI analysis returns HTTP 200 with empty lists and null audit, Chaos Monkey without data returns 404, invalid geometry returns 422 and missing scientific functions return 503 on requests that need them.
- [ ] Pass `python -m pytest backend/tests/test_math_core.py -v`, `python -m backend.check_core --synthetic`, and `python -m backend.validation_report --synthetic` using Adam's implementation. Then run `python -m backend.validation_report` and smoke-test the HTTP routes on real local data with networking disabled. Verify startup behavior and provenance in both source modes, including an uncached analysis, a repeated request and a Chaos Monkey run. Record timings by stage and compare them to the project query target.

## Verification baseline

| Check | Observed on 2026-11-14 |
| --- | --- |
| `python -m pytest backend/tests/test_db_layer.py backend/tests/test_api_contract.py backend/tests/test_core_validation.py -q` | **58 passed**. Scientific calls exercised by the HTTP tests use a simulated core. |
| `python scripts/00_bootstrap_synthetic_cube.py` followed by `python -m pytest backend/tests/test_cube_schema.py -q` | **11 passed** on a regenerated fixture in a temporary copy. Five fixture-specific assertions failed against the existing hybrid master. |
| `python -m pytest backend/tests/test_math_core.py --collect-only -q` | No tests collected. The science modules and test file are empty in this checkout. |
| `python -m backend.check_core --synthetic` | Eight required scientific callables reported missing. |
| Default and opted-in cube resolution | Default mode rejected the hybrid master. Explicit opt-in resolved the separate synthetic Parquet. |
| `python scripts/05_cli_benchmark.py` | Exit 1 on the hybrid master. Warmed query P95 ranged from **17.15 to 41.27 ms** across the five regions. Independent burned-area R² was unavailable for Chilecito and Iberia. The recovery column uses a seasonal-prior baseline. |

Close the backend when the real-only cube passes the publication checks, the actual science core passes its own and the API's contracts, real and explicit synthetic modes work offline, and the measured scientific and latency results are recorded against the project targets.
