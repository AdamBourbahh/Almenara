# Real FIRMS cutover verification — 2026-11-14

Real default startup uses `data/processed/fire_cube.parquet`, 761,801 unique real cell-days, 18 frozen Arrow fields, epoch 1970-01-01, zero synthetic rows. The cube was rebuilt with the current orbital-weighting implementation; source staging and lookups already contained the four imports. No fixture was published as real. All 32 direct raw CSVs are now tracked by preceding commits.

## Verification

- Requested five-file gate: `python -m pytest backend/tests/test_cube_schema.py backend/tests/test_math_core.py backend/tests/test_db_layer.py backend/tests/test_api_contract.py backend/tests/test_core_validation.py -v`: 193 passed in 23.76s. Exact output is in `cutover_tests_2026-11-14.log`.
- Final entire backend gate: `python -m pytest backend/tests -q --tb=short`: 204 passed in 20.45s, including seven source/TypeScript parity cases.
- `python -m backend.check_core --synthetic`: exit 0; all eight operations PASS. Real-mode conformance also passes in `python -m backend.validation_report` (exit 0); full report is attached.
- `node --test frontend/tests/real-data.test.mjs`: three passing cases, exercising the real compiled client and store. Network/gateway failures are surfaced by default; generated responses require `VITE_ALLOW_SYNTHETIC_FALLBACK=1`. Backend synthetic responses retain their provenance.
- `cd frontend && npx tsc --noEmit && npm run build`: exit 0. Wire interfaces and Python schemas were preserved; obsolete fixture preset constants were removed from the wire-types file so the store owns the populated-region list.
- Live backend: `USE_SYNTHETIC_CUBE=0 python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8001`; frontend: `VITE_API_URL=http://127.0.0.1:8001/api npm run dev -- --host 127.0.0.1 --port 5174`. Default ports 8000/5173 were occupied and left running.
- Live health returns real, 761801 rows, no missing columns and all core functions available. Analyze and Chaos Monkey returned HTTP 200 / real for all four full registered rectangles. Every map ID matches 15 lowercase hexadecimal characters. Every dense calendar has 9,496 daily entries; phenology and audit are populated. Known Chilecito UTC 2022-08-10 has nine raw detections, matching the DB daily aggregation; Aqua is absent during Safe Mode.
- Playwright CLI selected Chilecito (9,760 cells), Iberia (71,439), Orlando (3,123) and Amazonas (13,104), opened Calendar and Trends, and observed real HTTP 200 payloads and no page errors. Final console: zero errors and zero warnings. Screenshot: `real-cutover.png`. A favicon 404 found initially was fixed with an embedded icon.

## Coverage and timings

Measurements use Windows/Python 3.12.6 on this local workstation, real cube, years 2001–2026, industrial filter enabled. SQL P95 uses 12 warmed samples of `query_daily_rows`, separate from H3 construction, full API aggregation, serialization and HTTP transfer. Browser/server processes were active, so these are diagnostic workstation measurements. Chilecito uncached HTTP uses confidence high to ensure a fresh cache key; other entries use nominal. Server-Timing details and source-coordinate extrema are in `real_cutover_metrics.json`.

| Region | Cell-days | R4 / R7 staged | R7 polygon cells | SQL P95 ms | API processing ms | HTTP MISS / HIT ms | Recovery % |
| --- | ---: | --- | ---: | ---: | ---: | --- | ---: |
| chilecito_la_rioja | 48,246 | 115 / 9879 | 32,349 | 33.22 | 302.18 | 532.16 / 120.23 | 95.30 |
| orlando_florida | 30,381 | 20 / 3261 | 3,891 | 22.69 | 187.53 | 309.99 / 71.33 | 99.86 |
| amazonas_manaus | 220,891 | 126 / 13176 | 36,927 | 31.42 | 500.42 | 671.71 / 102.17 | 93.47 |
| iberia_med | 462,283 | 450 / 71567 | 193,839 | 100.19 | 1826.38 | 2328.84 / 291.93 | 94.18 |

Cell-day counts sum to 761,801. Staged H3 coverage includes footprint contributions near rectangle borders; API counts include only R7 polygon centers and requested dates. See JSON for exact per-region observed date ranges and raw bounding extrema.

## Differential review and remaining acceptance

Focused review against `12100f0`: client/store provenance, default region, explicit fixture flag, validation-region selection, embedded icon, tests and documentation. No core math, SQL filtering, threadpool, DuckDB cursor, WebGL ownership, canvas layout or frozen response field was changed. Three production entry paths consume the client/store changes; validation changes affect only diagnostic CLI tools. Tests first demonstrated wrong presets, lost backend provenance and silent fallback, then passed after the implementation. Six frozen response interfaces now have type/field parity checks against Pydantic. No remaining security finding was identified in this scoped review; dependencies and the whole repository were not security-audited.

The project SQL target below 15 ms is unmet for all four full AOIs here. Some API processing also exceeds the separate 250 ms reference budget. Burned-area R2 remains null: no MCD64A1 ancillary observations are available. Chow passes for Chilecito/Iberia and fails for Orlando/Amazonas; W1 reduction passes the existing 88% gate only for Amazonas. Chaos recovery is relative to the intact smoother, not independent physical truth. No scientific threshold was weakened to make the cutover pass. Clouds/global counts/swath, independent calibration and scientific acceptance remain open. The online basemap uses external tiles; this browser check does not certify airplane-mode tiles. Data/API processing itself uses local files.

The earlier stage 03 rebuild emitted a SciPy numerical integration warning; supported lookup parameters were checked finite/monotone/bounded, but calibration accuracy still requires independent validation. Recommendation: accept functional real-data cutover; continue performance and scientific validation.

## Concurrent merge verification

Merged `038a557` during final synchronization. Preserved the four-region publication checks, refreshed EQM LUT, failed ETL/core calibration-parity evidence and independent benchmark results. Resolved the plan conflict by retaining the publication detail and labeling the old empty-Cerrado diagnostic failure as historical. `python -m backend.validation_report` was rerun after the merge with real data: exit 0; all eight callables pass and all four real regions complete analysis and Chaos Monkey. Exact updated diagnostics are in `post-merge-validation.log`; earlier timing tables describe their capture snapshot and should not be substituted for these later scientific measurements.
