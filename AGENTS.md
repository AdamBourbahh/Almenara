# AGENT.MD — Multi-Agent Vibe-Coding Rules, Team Ownership & Guardrails

- **Project:** `firms-harmonizer` (NASA Space Apps Challenge 2026)
- **Primary Reference:** Always read `SPECS.md` before creating or editing any file.

## Active integration authorization (2026-11-15)

The user approved the complete all-nighter remediation plan and authorized one integrating agent to edit all ownership tracks on branch `all-nighter`. This authorization supersedes track-only editing for this task. Coordinated contract and frozen-test changes are recorded in `firms-harmonizer/CAMBIOS.md` and the current scientific specification. Do not restore obsolete forecasts/PM2.5/CORS assertions or retired regions merely to preserve historical fixtures.

New modules: API request limits belong to the API track; energy forecasting/emission factors to the science track; burned-area, emissions-input and packed observation adapters to the DB track; acquisition scripts 09–13 and run_pipeline/verify_frozen_tests to ETL/shared infrastructure; browser synthetic fixtures to frontend; requirements.lock and root GitHub CI to shared infrastructure. The audit regression suite is shared.

---

## 1. GOLDEN RULES FOR ALL AI CODING AGENTS
1. **ZERO PLACEHOLDERS:** Never leave `# TODO`, `pass`, `...`, or stubbed functions. Every file must be 100% complete and production-ready.
2. **FROZEN CONTRACTS:** Never rename, delete, or change types in `backend/api/schemas.py` or `frontend/src/api/types.ts`. The only sanctioned exceptions are the additive/nullable changes of 2026-11-14 recorded in `firms-harmonizer/CAMBIOS.md` (`data_source` added; `forecast_series`, `pm25_emitted_kg`, `tooltip_narrative`, `audit_metrics`, `total_pm25_emitted_tonnes` and `burned_area_r2_*` nullable). The coordinated 2026-11-15 additions and semantic changes in CAMBIOS.md are also approved. Any further change must be coordinated across both files, `SPECS.md` and `CAMBIOS.md`.
3. **100% ENGLISH UI & DOCS:** All UI text, tooltips, chart labels, audit verdicts, and `README.md` must be in **English** per NASA Space Apps Global Judging eligibility rules.
4. **OFFLINE-FIRST RESILIENCE:** Both backend and frontend must work with Wi-Fi turned off (Airplane Mode). The synthetic fixture cube is **opt-in only**: with `USE_SYNTHETIC_CUBE=1` the API serves `data/processed/fire_cube_synthetic.parquet` (generated via `scripts/00_bootstrap_synthetic_cube.py` if missing). Without it, the API refuses to start if the real `data/processed/fire_cube.parquet` is missing or is itself synthetic. Every response carries `data_source: "real" | "synthetic"`. Never fall back to synthetic data silently.

---

## 2. STRICT 5-PERSON FILE OWNERSHIP (ZERO GIT MERGE CONFLICTS)

Each developer owns an isolated set of files. Only modify files belonging to the active developer's track:

| Developer | Role | Exclusive File Ownership | Automated Test Gate |
| :--- | :--- | :--- | :--- |
| **1. ADAM** *(Team Lead)* | **Math & Physics Core** *(RTS Kalman + Cross Guard, Shannon Entropy, EQM, Von Mises, Chow/Wasserstein, risk model)* | `backend/api/schemas.py`<br>`backend/core/` (all modules, incl. `risk_predictor.py`)<br>`backend/tests/test_math_core.py`<br>`backend/tests/test_risk_predictor.py` | `pytest backend/tests/test_math_core.py -v`<br>*(0% FastAPI/DuckDB imports inside `backend/core/`)* |
| **2. MOHAMMED** | **Frontend GPU Map, Store, 2D Canvas Calendar & Views** | `frontend/src/api/types.ts`<br>`frontend/src/api/client.ts`<br>`frontend/src/store/useAnalysisStore.ts`<br>`frontend/src/components/Map/` (HexagonMap, AoiDrawControl, HeatHistoryCard, MapInfo, DateRiskPrompt, mapMetrics)<br>`frontend/src/components/Calendar/` (HatchPatternDefs, BurningCalendarCanvas, CalendarTooltip)<br>`frontend/src/components/Risk/RiskPredictionPanel.tsx`<br>`frontend/src/components/Sync/CubeSyncWidget.tsx`<br>`frontend/src/views/` (MapPage, CalendarPage, TrendsPage, ImpactPage, ObservationsPage, PageShell)<br>`frontend/tests/`<br>`frontend/package.json`, `frontend/package-lock.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html` | `cd frontend && npx tsc --noEmit && npm test` |
| **3. MOHA** | **DuckDB, Hierarchical H3 Queries, FastAPI HTTP & Copilot backend** | `backend/db/` (duckdb_engine, queries, nrt_poller)<br>`backend/api/` (routes, main, cache, core_contract, science_adapter, fire_copilot, copilot_answers, copilot_metrics, copilot_research)<br>`backend/check_core.py`<br>`backend/validation_report.py`<br>`backend/tests/` (conftest, test_api_contract, test_db_layer, test_core_validation, test_observations, test_explain_spike, test_nrt_poller, test_science_integration, test_map_period, test_real_cutover, test_copilot_metrics, test_copilot_research, test_risk_api) | `pytest backend/tests/test_db_layer.py backend/tests/test_api_contract.py backend/tests/test_core_validation.py -v` |
| **4. GERMÁN** | **Offline ETL, Cube Publication & Data Acquisition** | `scripts/` (00–07, incl. `07_fetch_mcd64a1_ancillary.py`, `07_risk_blackout_benchmark.py`, `requirements-acquisition.txt`)<br>`backend/tests/test_cube_schema.py`<br>`data/regions.json`<br>`data/ETL_SPEC.md`<br>`data/lookup/`<br>`data/raw/` | `python3 scripts/00_bootstrap_synthetic_cube.py && pytest backend/tests/test_cube_schema.py -v` |
| **5. MIGUE** | **Charts, Audit Panel, Copilot drawer, Pitch & Documentation** | `frontend/src/components/Charts/`<br>`frontend/src/components/Audit/` (AuditMetricsPanel, FireCopilotDrawer, CopilotContextPanel)<br>`frontend/src/App.tsx`<br>`frontend/src/main.tsx`<br>`frontend/src/lib/theme.ts`<br>`README.md`<br>`firms-harmonizer/README.md`<br>`firms-harmonizer/frontendExpects.md`<br>`Miguelspecs.md`<br>`Implementation_backend_plan.md` | `cd frontend && npm run build` |
| **Shared** | **Contracts, docs and infrastructure** | `AGENTS.md`<br>`SPECS.md`<br>`CAMBIOS.md`<br>`Makefile`<br>`docs/` | Team review |

---

## 3. THE 6 MANDATORY TECHNICAL GUARDRAILS (NEVER VIOLATE)

### Guardrail 1: Never Send 64-Bit H3 Integers in JSON
JavaScript `Number.MAX_SAFE_INTEGER` is $2^{53}-1$, which silently truncates 64-bit `uint64` H3 indices. Always serialize H3 indices in DuckDB SQL as 15-character lowercase hex strings:
```sql
SELECT printf('%x', h3_r7) AS h3_index, ...
```

### Guardrail 2: Use Synchronous `def` for CPU-Bound FastAPI Endpoints
Never use `async def` on `/api/analyze` or `/api/chaos-monkey` in `backend/api/routes.py`. Declare them with standard `def` so FastAPI runs DuckDB and NumPy in its external threadpool without blocking the `asyncio` event loop.

### Guardrail 3: Isolated Thread-Safe DuckDB Cursors
Never share a single DuckDB connection directly across threads. In `backend/db/duckdb_engine.py`, use a context manager that yields `_MASTER_CONN.cursor()` per HTTP request and closes it in `finally`:
```python
@contextmanager
def get_db_cursor():
    cursor = _MASTER_CONN.cursor()
    try:
        yield cursor
    finally:
        cursor.close()
```

### Guardrail 4: Two-Level Hierarchical H3 Polygon Filtering (R7 first, then unique R4 parents)
Polyfill the polygon at `res=7` with `polygon_to_cells` (GeoJSON `[lon, lat]` converted explicitly to `(lat, lng)`, H3 v4 API), derive the **unique** `res=4` parents (`cell_to_parent`), and filter DuckDB first on `h3_r4` (Parquet Zone Map pruning) and then on `h3_r7`. **Never polyfill at `res=4` directly** — it only keeps cells whose centre lies inside the polygon and silently drops border cells — and **never use a centroid / `grid_disk` fallback** (a polygon with no R7 cell returns empty lists). Cell lists reach DuckDB as registered Arrow tables, never concatenated into SQL. Polygons above 250,000 R7 cells are rejected with HTTP 422.

### Guardrail 5: Numerical Stability in RTS Kalman Smoother
In `backend/core/kalman_rts.py`:
1. Skip sensor innovation when `np.isnan(y_obs[t, s])`.
2. When all sensors are `NaN` on day $t$, inject the **Cross-Sensor Historical Prior Guard** ($\mu_{\text{cross}}(d_t)$) with variance $R_{\text{guard}} = 40.0$ so the state never decays to zero.
3. Always use the **scalar Joseph form** for covariance updates:
   ```python
   P_p = ((1.0 - K * h) ** 2) * P_p + (K ** 2) * R_var[s]
   ```
4. Add `+ 1e-8` jitter to every division denominator in forward ($S_{\text{innov}}$) and backward ($G_t$) passes.

### Guardrail 6: Single WebGL2 Context in Deck.gl & Single 2D `<canvas>` in Calendar
1. Mount `<DeckGL>` once in `HexagonMap.tsx` and only update `data` and `updateTriggers` on `H3HexagonLayer` (avoids Chrome's 16 WebGL context limit).
2. Render all available calendar-year rows × 366 daily cells in a single HTML5 `<canvas>` 2D element using `OffscreenCanvas` / `ctx.createPattern` for diagonal hatching on `is_gap_filled === true` and `is_forecast === true`.
Coverage-policy follow-up: backend/core/coverage_policy.py belongs to science; backend/db/land_coverage.py to DB; script 13 to ETL; test_coverage_policy.py is shared. The user authorized this coordinated follow-up.
