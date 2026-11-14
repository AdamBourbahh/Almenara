# Fire Harmonizer — Team Engineering Rules

## Mission and architecture
Build the NASA Space Apps MODIS/VIIRS fire activity calendar with sensor-independent FRE density (MJ/km²/day). Use Python, NumPy/SciPy, DuckDB, Parquet ZSTD, FastAPI, React/TypeScript, Deck.gl and MapLibre with local PMTiles. No PostgreSQL/PostGIS. Bulk geospatial transport is Arrow IPC (`application/vnd.apache.arrow.stream`), consumed through typed arrays; JSON is only for bounded analysis summaries and mocks. All demonstration assets must work offline. Raw counts exist only for the before/after comparison. Never represent a detection as a dimensionless point: distribute its scan × track footprint over H3 R7.

## Golden rules
1. No placeholders, unfinished code, `TODO`, `pass`, or ellipsis stubs. Every implemented file must function completely.
2. `backend/api/schemas.py` and `frontend/src/api/types.ts` are frozen contracts. Never rename or delete fields. Coordinate any additive change across both languages and specs.md.
3. All visible UI text, tooltips, charts, audit verdicts and README.md must be entirely in English.
4. Read specs.md before writing mathematical code, SQL or visual components. Synthetic examples must be explicitly identified; never report invented scientific validation.

## Exclusive ownership — five developers
| Owner | Exclusive files |
|---|---|
| ADAM — Lead & Math Core | `backend/core/*`, `backend/tests/test_math_core.py`, `backend/api/schemas.py`. Only NumPy/SciPy and the standard library in core; no FastAPI or DuckDB imports. |
| MOHA — DuckDB & FastAPI | `backend/db/*`, `backend/api/main.py`, `backend/api/routes.py`, `backend/api/cache.py`, `backend/api/core_contract.py`, `backend/validation_report.py`, `backend/tests/test_api_contract.py`, `backend/tests/test_db_layer.py`, `backend/tests/conftest.py` |
| GERMÁN — Offline ETL | `scripts/*`, `data/*`, `backend/tests/test_cube_schema.py` |
| MOHAMMED — GPU map, store & calendar | `frontend/src/api/*`, `frontend/src/store/*`, `frontend/src/components/Map/*`, `frontend/src/components/Calendar/*` |
| MIGUE — Charts, audit & shell | `frontend/src/components/Charts/*`, `frontend/src/components/Audit/*`, `frontend/src/App.tsx`, `README.md` |

Bootstrap explicitly authorizes the shared rules, specs, Makefile, dependency/configuration files, both contracts, cube generator, cube tests and generated artifacts. After bootstrap, obey ownership above. Do not modify another developer's files to make a gate pass.

## Six mandatory technical shields
1. **H3 uint64 precision:** Parquet uses UBIGINT/uint64. Every SQL projection into JSON must use `SELECT printf('%x', h3_r7) AS h3_index`, yielding a 15-character hexadecimal string. Never convert H3 indices to JavaScript Number.
2. **FastAPI event loop:** CPU-bound `POST /api/analyze` and `POST /api/chaos-monkey` must use synchronous `def`, never `async def`, so FastAPI executes them in its thread pool.
3. **DuckDB concurrency:** In `backend/db/duckdb_engine.py` retain global `_MASTER_CONN`. Expose `@contextmanager def get_db_cursor():`, create `_MASTER_CONN.cursor()` per request, and close it in `finally`. Never share a cursor between threads.
4. **Hierarchical H3 filter:** In `backend/db/queries.py` polyfill R7 inside the polygon with `polygon_to_cells(..., 7)` (GeoJSON `[lon, lat]` converted explicitly to `(lat, lng)`), derive the unique R4 parents with `cell_to_parent`, and filter `h3_r4` first (zone map pruning) and then `h3_r7`. Never polyfill at R4 directly (it drops border cells) and never use a centroid/`grid_disk` fallback. Cell lists reach DuckDB as registered Arrow tables, never concatenated into SQL.
5. **Stable RTS Kalman:** Skip an observation whenever `np.isnan(y_obs[t, s])`. For a historical day with all sensors missing, inject the historical cross-sensor guard from specs.md with `R_guard = 40.0`; do not inject it into future forecast days. Use the scalar Joseph form `P_p = ((1.0 - K * h) ** 2) * P_p + (K ** 2) * R_var[s]` (the guard uses its own variance). Add `1e-8` to every forward/backward denominator. The detailed blackout guard is `0.55 * mu_cross + 0.45 * u_spatial`.
6. **WebGL and calendar:** Keep exactly one mounted singleton `<DeckGL>` in `HexagonMap.tsx`, updating data and updateTriggers. Render the 26 × 366 = 9516 calendar slots in one HTML5 2D `<canvas>`, with OffscreenCanvas / `ctx.createPattern` diagonal hatching for `is_gap_filled` and `is_forecast`; invalid leap-day slots remain blank.

## TDD gates — before every commit
```sh
python3 scripts/00_bootstrap_synthetic_cube.py && pytest backend/tests/test_cube_schema.py
pytest backend/tests/test_math_core.py -v
pytest backend/tests/test_api_contract.py -v
cd frontend && npx tsc --noEmit
```
Run `make sync-rules` after changing this file. These commands are required integration gates; empty teammate modules do not constitute successful verification. Scientific acceptance additionally requires Chow p > 0.10 at January 2012, Wasserstein-1 reduction >88%, and independent MCD64A1 cross-validation. Performance targets (<15 ms queries and 60 FPS) require measurement.
