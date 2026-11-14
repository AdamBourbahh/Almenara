# Backend Implementation Plan

**Goal** — Build and verify the offline FIRMS ETL pipeline and the on-demand API for harmonized daily fire radiative energy (FRE).

**Architecture** — Python, H3, DuckDB and PyArrow prepare the local Parquet cube. FastAPI queries it through DuckDB and delegates scientific analysis to the NumPy/SciPy core. The API delivers gzip-compressed JSON serialized with orjson.

**Source of truth** — [AGENTS.md](AGENTS.md) governs ownership and guardrails. [SPECS.md](SPECS.md) governs scientific methods and contracts. [ETL_SPEC.md](firms-harmonizer/data/ETL_SPEC.md) documents the ETL implementation. [CAMBIOS.md](firms-harmonizer/CAMBIOS.md) documents the approved contract updates, the API/core interface and known discrepancies.

**Status baseline** — 2026-11-14, scientific integration merge `920d3d3` on `main`, combining the fetched `origin/main` at `5424d74` with scientific work at `b589a86`. The merge retained both histories without Git conflicts. The full backend gate passes **144 tests**; the real scientific API adapter remains incomplete. Check a task when its deliverable is present and supported by inspection or a passing check. Reopen a task when a regression invalidates that evidence. A phase is **Complete** only when all its acceptance tasks are checked. Record the date, command, result and data source as tasks close. Run backend commands from `firms-harmonizer/`.

| Block | Complete | In progress | Pending |
| --- | --- | --- | --- |
| Offline ETL | 2 | 1, 3, 5, 6, 7 | 4 |
| Online API | — | 8, 9, 10, 11, 12 | — |

## Earlier pull review (historical context)

- From `4d0f6cb` to `35301bd`, Git reports no deleted paths. Germán's `scripts/01_ingest_firms.py` through `scripts/05_cli_benchmark.py`, [ETL_SPEC.md](firms-harmonizer/data/ETL_SPEC.md), region definitions, download notes, LUT and mock JSON are unchanged. The local raw archives and staged Parquet are still present. These ignored inputs are outside Git's history.
- The scientific merge (`90f7f94`) rewrote Germán's generator and cube tests and added a synthetic Parquet at the master path. Before the pull, that path held the local hybrid artifact recorded in the previous baseline. The previous generator and tests are available at `4d0f6cb`. The rewritten suite dropped the mock/Python/TypeScript parity and request-validation checks. ETL now checks the mock provenance and request validation against Python. Phase 12 tracks restoring TypeScript parity with the frontend owner.

## Scientific integration review — 2026-11-14

- Integrated all pending scientific work through `science-core-integration-20261114`, then merged it into the updated `main`. Preserved incoming ETL publication, UTC epoch alignment, frontend changes and Phase 5 evidence. Public Python/TypeScript schemas and the four frozen DB/API test files were not changed by this integration; their SHA-256 checks pass.
- All seven science modules now have implementations. The 49 mathematical cases include the seven named acceptance tests, a 1,460-day seasonal record with a ten-day blackout, a fourteen-day forecast, a fifteen-year +1.5 days/year peak shift, a raw 4.5x sensor jump, and deterministic Chaos Monkey recovery. Models returned by phenology, audit and Chaos Monkey are the exact frozen Pydantic classes.
- The science functions requested in the implementation prompts differ from the callable names and argument/result shapes in `backend/api/core_contract.py`. This is an integration gap, not a Git conflict. Keep the tested scientific interfaces and adapt the API boundary deliberately; do not rename working functions or report simulated-core HTTP tests as actual scientific API validation.

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

### Phase 2 — Daily de-duplication and diurnal FRE · Complete

**Owner** — Germán. **Files** — `scripts/01_ingest_firms.py`, `scripts/02_detect_outages_clouds.py`, `scripts/04_build_master_cube.py`. **Specification** — [ETL_SPEC.md](firms-harmonizer/data/ETL_SPEC.md) stages 01, 02 and 04 and [SPECS.md](SPECS.md) §2(6), §3.4.

- [x] Deduplicate identical sensor/time/location records, aggregate by R7 cell and UTC day, use coincident Terra/Aqua diurnal ratios where available, and publish previous-day neighbor energy in `neighbor_fre_lag1`.
- [x] Validate the daily Eulerian integration and diurnal weights on known inputs, including repeated acquisitions and lag alignment — **2026-11-14**. Command from `firms-harmonizer/`: `python -m pytest backend/tests/test_cube_schema.py -v`. Result: **47 passed in 13.60s**, exit 0, including 10 new Phase 2 cases. Data source: **deterministic temporary fixtures + ETL_SPEC.md contract**. Tests verify exact-record deduplication with archive priority, per-instrument multi-pass energy, `FRP_calibrated * 3600 / exact_H3_area`, the daytime ratio of sums, the three-day support threshold and neutral fallback, and strict previous-day active-neighbor averaging. Fixed zero-energy neighbors diluting the mean; measured zeros remain valid observations. Production `data/processed/` file hashes, sizes and modification timestamps are unchanged. The [Eulerian integration contract](firms-harmonizer/data/ETL_SPEC.md#stage-04-diurnal-scaling-and-eulerian-integration-contract) documents the one-hour proxy and its physical limits. Completion validates implementation arithmetic, not independent real-fire energy accuracy; event graphs and continuous trapezoidal integration remain outside Phase 2.

### Phase 3 — Industrial entropy, infrared contrast and SAMA · In progress

**Owners** — Adam for `backend/core/industrial_filter.py`; Germán for `scripts/01_ingest_firms.py`; Moha for the query consumer. **Specification** — [ETL_SPEC.md](firms-harmonizer/data/ETL_SPEC.md) stage 01 and [SPECS.md](SPECS.md) §2(3), §3.2.

- [x] Compute R10 Shannon entropy normalized over 12 calendar months. Current staging uses a positional variance gate, a logistic industrial score and a local SAMA filter.
- [x] Implement the core entropy, industrial score and SAMA filter. Unit tests cover the sigmoid, infrared contrast, SAMA boundaries and the Terra date cutoff.
- [ ] Align the ETL and core implementations and verify the classification and the API's removal counts with persistent flares and seasonal fires. ETL probes for `is_sama_artifact`, while the new core exposes `filter_sama_anomalies` and ETL still takes its local path. The DB industrial-filter integration test passes with the aligned fixture.

### Phase 4 — Orbital revisit weighting · Pending

**Owners** — Adam for the scientific rule and Germán for its application in `scripts/04_build_master_cube.py`. **Specification** — [SPECS.md](SPECS.md) §3.4(1).

- [ ] Resolve the equation in the specification before applying a weight. The revisit model gives `π_orb ∝ sec(latitude)`, while the weighting paragraph also calls `sec(latitude)` the inverse weight. For that revisit model, the mathematical inverse is proportional to `cos(latitude)`. Record the agreed expression, normalization and latitude domain in the authoritative specification.
- [ ] Apply the approved factor once to the offline energy calculation and verify its behavior across equatorial and high-latitude cells. Keep Terra diurnal scaling as a separate, existing correction.

### Phase 5 — Sensor outages and cloud gaps · In progress

**Owner** — Germán. **Files** — `scripts/02_detect_outages_clouds.py`, `scripts/04_build_master_cube.py`. **Specification** — [ETL_SPEC.md](firms-harmonizer/data/ETL_SPEC.md) stages 02 and 04 and [SPECS.md](SPECS.md) §3.4, §5.1.

- [x] Verify the known Aqua Safe Mode interval and reproducible output — **2026-11-14**. Command from `firms-harmonizer/`: `python scripts/02_detect_outages_clouds.py` (run twice). Result: exit 0, exactly **17 inclusive days, 2022-07-31 through 2022-08-16**, and byte-identical outage and diurnal Parquet files. Data sources: the known interval in `SPECS.md` §3.4 and local staged FIRMS detections for 2,075 diurnal-ratio rows. Exact schemas, hashes, and reproduction checks are documented in [ETL_SPEC.md](firms-harmonizer/data/ETL_SPEC.md).
- [x] Verify the dynamic rule and observation propagation with deterministic temporary fixtures — **2026-11-14**. Command: `python scripts/00_bootstrap_synthetic_cube.py && python -m pytest backend/tests/test_cube_schema.py -v`. Result: exit 0, **37 passed in 11.13s**. The suite covers the strict `< 0.25 * mean(t-15..t-1)` rule, observed zeros, missing/null days, duplicate-day rejection, per-instrument windows, all five sensor bits, Aqua nulls, surviving VIIRS instruments, cloud thresholds, combined blackout bits, neighbor lag exclusion, and aggregate ancillary provenance. Fixture data never populate production global-count or ancillary files. See the Phase 5 verification and differential-review sections in `ETL_SPEC.md` for evidence and limitations.
- [ ] Validate the detector against **actual global daily counts**. None were found under local `data/raw/` or `data/lookup/` on 2026-11-14. Regional detection counts cannot establish global outages; the attachment's `−4σ` detector remains an unverified proposal.
- [ ] Validate cloud masking against **actual local cloud reanalysis** in `data/lookup/cell_day_ancillary.parquet`. This file is absent as of 2026-11-14. The legacy `cloud_outages.parquet` lacks H3 keys and provenance metadata and cannot substitute for it. No Open-Meteo or other HTTP request was made.
- [ ] Supply documented swath coverage evidence and verify positive bit `4` propagation. Sparse detections alone cannot establish swath gaps; current stage 04 leaves this bit unset. Tests cover the existing outage/cloud/blackout encoding without claiming swath validation.

### Phase 6 — Censor-aware EQM and GPD lookup · In progress

**Owners** — Germán for `scripts/03_train_eqm_lut.py` and its ETL use; Adam for `backend/core/eqm_harmonizer.py`. **Specification** — [ETL_SPEC.md](firms-harmonizer/data/ETL_SPEC.md) stage 03 and [SPECS.md](SPECS.md) §3.3.

- [x] Train the current lookup on matched daytime Aqua/SNPP R7 cell-days in 2012–2025 using empirical quantiles and a bounded GPD tail. The trainer defines 17 IGBP classes and 10 angle bins, uses footprint width as an angle proxy, and falls back to broader strata when samples are sparse. A local `data/lookup/eqm_gpd_lut.json` was present at 9,553 bytes.
- [x] Implement Adam's `RadiometricHarmonizer`. Math tests cover linear interpolation, bounded GPD compensation, sparse or constant training inputs and invalid LUTs.
- [ ] Verify parity between the core and ETL lookup paths, including pre-2012 compensation on real samples. Record held-out results and which strata used real MCD12Q1 classes or nominal regional classes.

### Phase 7 — Master Parquet cube and publication · In progress

**Owner** — Germán, with Moha verifying API compatibility. **Files** — `scripts/00_bootstrap_synthetic_cube.py`, `scripts/04_build_master_cube.py`, `scripts/05_cli_benchmark.py`, `backend/tests/test_cube_schema.py`. **Specification** — [ETL_SPEC.md](firms-harmonizer/data/ETL_SPEC.md) stages 04–05 and [SPECS.md](SPECS.md) §5.1, subject to the real/synthetic rule in [AGENTS.md](AGENTS.md).

- [x] Implement the atomic, ZSTD-compressed master builder and verify the synthetic artifact's 18-field layout and unique ascending `(h3_r4, epoch_day, h3_r7)` keys. ZSTD level 9 and 128,000-row groups remain tuning candidates from the attachment.
- [x] Separate fixture and master publication. Script 00 and script 04 with `--bootstrap` default to `fire_cube_synthetic.parquet`. Script 04 builds a real-only master and preserves an existing output when staging is missing. The tracked synthetic master was removed. The local staged dataset produced **510,529** unique real cell-days, with zero fixture rows and consistent year and day-of-year values.
- [ ] Coordinate the 1970-01-01 epoch migration with Moha. Both generators, DuckDB and the API now follow `SPECS.md` §5.1. The API tests and core checker use the aligned Cerrado AOI. Verify NOAA-21 masks and smoke-test both cube modes before replacing deployed cubes. Distinguish missing ancillary inputs from observed zero.
- [ ] Complete the real-data benchmark and scientific acceptance. The current artifact covers Chilecito and Iberia. Warmed query P95 was **17.64 ms** and **55.59 ms**, respectively, with no independent burned-area R². The three other benchmark regions have no real rows.

## Block II — On-demand API

### Phase 8 — Hierarchical H3 filter and DuckDB aggregation · In progress

**Owner** — Moha. **Files** — `backend/db/duckdb_engine.py`, `backend/db/queries.py`, `backend/tests/test_db_layer.py`. **Specification** — [AGENTS.md](AGENTS.md) guardrails 1, 3 and 4, [SPECS.md](SPECS.md) §3.1 and §5.1, and [CAMBIOS.md](firms-harmonizer/CAMBIOS.md).

- [x] Convert GeoJSON positions to H3 latitude/longitude order, polyfill R7, derive unique R4 parents, and register both cell lists as Arrow tables. Filter R4 then R7. The vectorized parent calculation is tested against H3 `cell_to_parent`; border cells and empty tiny AOIs have regression coverage. Reject AOIs above 250,000 R7 cells with HTTP 422.
- [x] Implement aggregation by UTC day, a dense calendar with NaN observations for missing measurements, cursor isolation and cursor closure on failure.
- [ ] Restore the DB regression gate with a freshly generated fixture after phase 7 aligns dates and regions. Verify populated Cerrado results, R7 filtering inside an R4 parent, industrial inclusion/exclusion, dense calendar length and 15-character H3 IDs. All DB integration tests pass after merging the epoch and Cerrado fixes. Confirm the API date against a known UTC observation in the real Chilecito cube.

### Phase 9 — RTS Kalman smoother and historical guard · In progress

**Owners** — Adam for `backend/core/kalman_rts.py`; Moha for `backend/api/core_contract.py` and `backend/api/routes.py`. **Specification** — [SPECS.md](SPECS.md) §3.4, [AGENTS.md](AGENTS.md) guardrail 5, and [CAMBIOS.md](firms-harmonizer/CAMBIOS.md) core interface.

- [x] Wire `compute_cross_prior(doy, obs)` and `kalman_rts_smooth(obs, u_spatial, prior)` into the API using three observation channels and a dense daily input. The call and shape validation are covered by tests with a simulated core.
- [x] Implement and unit-test `build_cross_sensor_historical_prior` and `rts_kalman_smoother_with_cross_guard`. The 366-bin circular prior calibrates overlapping sensors; Joseph updates, forward/backward jitter, missing observations, finite/nonnegative outputs and the covariance floor are tested. RTS estimates agree with an independent batch Gaussian posterior. The 1,460-day seasonal acceptance case preserves more than 35% of peak FRE throughout a ten-day total blackout.
- [x] Implement the requested extended-timeline RTS forecast and exact thirteen-key result contract: fourteen forecast steps, modulo-365 forecast DOY, cloud fraction 0.25, state-dependent spatial forcing, ordered 95% bands and uncertainty clipped to 1–99.9%. This is a core capability; API forecast fields remain deferred until the adapter and HTTP integration are completed.
- [ ] Expose the API-compatible signatures `compute_cross_prior(doy, obs)` and `kalman_rts_smooth(obs, u_spatial, prior)` around those routines. Verify the finite 366-day prior and length-matched `x_smooth` and nonnegative `p_smooth` outputs on a populated AOI, including variance 40.0 on all-missing historical days, denominator jitter of `1e-8`, and ordered 95% intervals. The API checker still reports both required entry points missing when supplied a compatible fixture.

### Phase 10 — Circular phenology and decadal trends · In progress

**Owners** — Adam for `backend/core/von_mises.py`; Moha for API integration. **Specification** — [SPECS.md](SPECS.md) §3.6 and [CAMBIOS.md](firms-harmonizer/CAMBIOS.md) core interface.

- [x] Wire `fit_von_mises_year(doy, weights)` and `phenology_trend(years, peaks)` and validate the response shapes with a simulated core.
- [x] Implement `best_fisher_kappa`, `doy_to_date_label` and `compute_circular_phenology`. Tests cover the Best & Fisher branches, English leap-calendar labels, annual energy in GJ, zero-energy cases and December/January unwrapping. A fifteen-year synthetic +1.5 days/year shift is recovered within 0.2 days/decade of 15, with Kendall p < 1e-6. Results are `VonMisesPhenologyYear` instances.
- [ ] Adapt the API's `fit_von_mises_year` and `phenology_trend` calls to the implemented science interface. The checker still reports those two legacy names missing. Keep undefined zero-energy directions out of trend fitting; label conventions use leap-year 2000 and are not acquisition dates.

### Phase 11 — Scientific audit and Chaos Monkey · In progress

**Owners** — Adam for `backend/core/auditor_stats.py` and `backend/core/chaos_monkey.py`; Moha for HTTP integration and validation; Germán for the ETL benchmark and ancillary data pipeline. **Specification** — [SPECS.md](SPECS.md) §3.4(6), §3.5, §3.7 and §5.2, [CAMBIOS.md](firms-harmonizer/CAMBIOS.md), and [ETL_SPEC.md](firms-harmonizer/data/ETL_SPEC.md) stage 05.

- [x] Wire the audit calls and `POST /api/chaos-monkey`. The analysis route computes Wooster biomass with 0.368 kg/MJ. The CLI reports Chow, Wasserstein, burned-area cross-validation when available, and a seasonal-prior stress baseline.
- [x] Implement `compute_wooster_biomass_and_smoke`, `compute_chow_structural_break_test` and `compute_scientific_audit_metrics`. Tests verify exact biomass/PM2.5 units, Chow against an independent nested-regression calculation, a raw 4.5x jump with p < 1e-4 and a continuous harmonized series with p > 0.10. The audit returns `ScientificAuditMetrics`; missing or constant burned-area data produce nullable R2, not fabricated validation.
- [x] Implement seeded **25%** VIIRS removal and a bounded ten-day peak blackout in `run_chaos_monkey_simulation`. Tests verify reproducibility, no input mutation, boundary/short-series behavior, fixed external historical priors, lower Kalman RMSE than naive RMSE, and seasonal energy recovery above 90% on the deterministic acceptance fixture. Chaos Monkey reuses the same RTS filter through an internal fixed-prior helper; the public smoother signature and output contract are preserved.
- [ ] Adapt API audit calls (`chow_test`, `wasserstein_w1_normalized`, `descriptive_r2`) and the legacy Chaos Monkey `(daily, target_year, ...) -> dict` interface to the implemented functions and Pydantic result. The prompt-specific Chaos Monkey signature accepts dates and observation arrays and labels its experiment `synthetic` because input provenance is not supplied. Source provenance must be coordinated at the API boundary.
- [ ] Validate the actual audit against genuine annual MCD64A1 data and evaluate the scientific targets on independent observations. Current R2 is descriptive squared annual correlation; W1 normalizes each complete daily record by its overall mean. Chow uses annual means and requires sufficient annual data across 2012. Seasonal recovery is reconstructed/reference energy and can exceed 100% when overestimated. The intact smoother is the stress-test reference, not observed physical truth. None of the synthetic acceptance results establishes real-world independent validation.

### Phase 12 — HTTP, canonical cache and release verification · In progress

**Owner** — Moha, with Adam for core integration and Mohammed for the frontend contract mirror. **Files** — `backend/api/main.py`, `backend/api/routes.py`, `backend/api/cache.py`, `backend/api/core_contract.py`, `backend/check_core.py`, `backend/validation_report.py`. **Specification** — [AGENTS.md](AGENTS.md), [SPECS.md](SPECS.md) §2(7), §5.2, and [CAMBIOS.md](firms-harmonizer/CAMBIOS.md).

- [x] Expose synchronous `POST /api/analyze` and `POST /api/chaos-monkey`, plus `GET /api/health`. Serve orjson and GZipMiddleware for HTTP. Arrow stays internal to the query path; the proposed `/api/hexagons.arrow` endpoint and disk cache are outside this plan. The in-memory LRU uses BLAKE2b over sorted unique R7 cells, request parameters and cube modification time. `X-Cache` and `Server-Timing` expose cache and stage timings.
- [x] Retain HTTP tests for invalid geometry, empty AOIs, cache and core adapter error paths.
- [x] Restore the DB, HTTP and core validation regression gates using the aligned synthetic fixture. The full 144-test backend run passes, including populated analysis and Chaos Monkey payloads and cache/error paths. The HTTP scientific calls in these tests use the existing simulated core; this does not close actual science integration.
- [ ] Restore the frozen TypeScript mirror and parity coverage against `backend/api/schemas.py` and the mock. The frontend merge removed `data_source` from both response types, removed `dates` from Chaos Monkey, and changed or removed other fields including daily `biomass_burned_tonnes` and approved nullability. Require explicit opt-in for synthetic fallback and propagate backend provenance into frontend state. The new client currently generates synthetic responses on connectivity or gateway errors and marks successful HTTP responses as non-synthetic, including responses from an opted-in synthetic backend.
- [x] Pass the 49-case `pytest backend/tests/test_math_core.py -v` gate, including all seven named scientific acceptance tests. This integration also passes the full backend regression gate.
- [ ] Pass `python -m backend.check_core --synthetic` and `python -m backend.validation_report --synthetic` using the actual adapted core. Then run `python -m backend.validation_report` and smoke-test the HTTP routes on real local data with networking disabled. Verify startup behavior and provenance in both source modes, including an uncached analysis, a repeated request and a Chaos Monkey run. Record timings by stage and compare them to the project query target.

## Next backend step

### Independent ETL task for Germán — Phase 2

**Execution plan — 2026-11-14:** native execution in this session, using `SPECS.md` §2(6), §3.4(1), §5.1 and `ETL_SPEC.md`. All new regression cases live in `backend/tests/test_cube_schema.py`; script changes are limited to failures demonstrated by those cases. Temporary CSV, lookup and Parquet fixtures use Python, DuckDB, H3 and PyArrow. Preserve the existing production artifacts and the scientific/API integration work below.

- [x] Isolate the existing bootstrap subprocess test under `tmp_path`, including its default output, then record production artifact hashes before running tests.
- [x] Add `test_stage01_deduplication_exact_records`: normalized sensor/time keys, five-decimal coordinates, archive preference over NRT, and distinct acquisitions retained.
- [x] Add `test_stage04_eulerian_fre_conversion_and_units` and an end-to-end case: known 10 + 20 MW acquisitions produce `30 * 3600 / exact_H3_area`, with independent sensor counts and UTC dates preserved.
- [x] Add stage 02 ratio-generation and `test_stage04_diurnal_scaling_terra_to_aqua` cases: positive coincident daytime sums, night/unmatched/zero exclusions, ratio 2.5 at three or five matched days, and factor 1.0 at two days or a missing bucket. Aqua remains unscaled.
- [x] Add `test_stage04_neighbor_lag1_alignment`: adjacent cells on three UTC days, exclusion of self/current/two-day-old observations, and mean over positive-energy neighbors only. Run focused tests before any necessary production fix and after it.
- [x] Document the Eulerian proxy, exact equations, complexity limits and physical uncertainty; run `python -m pytest backend/tests/test_cube_schema.py -v`, review the diff, and compare production artifact hashes. Mark Phase 2 complete only after these checks pass.

Merge `920d3d3` changed `kalman_rts.py`, `von_mises.py`, `auditor_stats.py`, `chaos_monkey.py`, and the math suite. It advanced the scientific core of phases 9–11. Phase 2 ETL acceptance is now complete with the 2026-11-14 evidence above. Commit `5424d74` already verified the phase 5 outage rule and previous-day lag exclusion with fixtures. The remaining phase 5 validation needs global counts, cloud reanalysis, and swath evidence.

- [x] Verify daily FRE end to end with a small local fixture. Include an exact duplicate and a distinct repeat acquisition, concurrent Terra and Aqua observations, a supported diurnal ratio and a cell with no ratio. Assert daily counts and expected per-sensor FRE in MJ/km² against a hand calculation using H3 cell area.
- [x] Verify `neighbor_fre_lag1` with adjacent H3 cells across a UTC day boundary. Check that only the previous day's eligible neighbor observations contribute. Reuse the phase 5 outage and cloud cases for missing observations.
- [x] Run the cube schema suite and record the inputs, expected values, and results in [ETL_SPEC.md](firms-harmonizer/data/ETL_SPEC.md). Document where the fixed one-hour FRP-to-FRE proxy limits physical interpretation. This ETL check requires only local fixtures and the files owned by Germán.

### Science and API integration

Implement the science/API adapter for phases 9–11 while preserving both the frozen response schemas and tested scientific entry points. Then rerun actual-core conformance and the validation report, and verify a known UTC date through the API on the real Chilecito cube to close phase 8. Keep frontend provenance/parity and real-data scientific/performance acceptance open until independently verified.

## Verification after scientific integration — 2026-11-14

Checks used Python 3.12.3 and the temporary `/tmp/almenara-cube-venv` environment with the repository's requirements installed. The full suite ran outside the restricted process sandbox: inside that sandbox, TestClient stalled before the first HTTP test. No application or frozen test changes were made to bypass this environment behavior.

| Check | Observed result and scope |
| --- | --- |
| `pytest backend/tests/test_math_core.py -v` | **49 passed in 0.76s** before integration. Scientific acceptance and regression tests; seven explicitly named Prompt 6 scenarios are present. |
| `pytest backend/tests -q --tb=short` | **144 passed in 6.71s** after merge with `5424d74`. Includes 49 math, 37 cube/ETL and 58 DB/API/core-validation cases. Test artifacts are synthetic or temporary fixtures; HTTP scientific calls use the simulated core. The 1,501 warnings concern the TestClient/httpx dependency and generic NumPy timedeltas in the frozen test helper. |
| `sha256sum -c backend/tests/FROZEN_TESTS.sha256` | **4 files OK**; frozen DB/API/core-validation tests and setup are unchanged. |
| `python -m backend.check_core --synthetic` | **Exit 2** on a populated, aligned Cerrado fixture: seven legacy API callables missing; Chaos Monkey exists but fails under the legacy arguments with `ValueError: Expected doy (T,) and y_obs (T, 3).` This is the next integration task. |
| `git diff --check` and merge review | No whitespace errors or unresolved Git conflicts. Merge `920d3d3` retains the fetched remote changes and all scientific work from `b589a86`. |
| Real-data validation and performance | Not rerun during this merge. Earlier Phase 5 evidence and real-cube publication/coverage records remain above; they are separate from synthetic scientific acceptance. |

Earlier reports of 101 backend tests and missing/empty science modules belong to previous revisions. The current results above supersede those test counts and implementation status; real-data acceptance and API conformance remain separate gates.

Close the backend when the real-only cube passes the publication checks, the actual science core passes its own and the API's contracts, real and explicit synthetic modes work offline, and the measured scientific and latency results are recorded against the project targets.
