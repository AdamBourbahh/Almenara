# AGENT.MD — Multi-Agent Vibe-Coding Rules, Team Ownership & Guardrails

- **Project:** `firms-harmonizer` (NASA Space Apps Challenge 2026)
- **Primary Reference:** Always read `@specs.md` before creating or editing any file.

---

## 1. GOLDEN RULES FOR ALL AI CODING AGENTS
1. **ZERO PLACEHOLDERS:** Never leave `# TODO`, `pass`, `...`, or stubbed functions. Every file must be 100% complete and production-ready.
2. **FROZEN CONTRACTS:** Never rename, delete, or change types in `backend/api/schemas.py` or `frontend/src/api/types.ts`.
3. **100% ENGLISH UI & DOCS:** All UI text, tooltips, chart labels, audit verdicts, and `README.md` must be in **English** per NASA Space Apps Global Judging eligibility rules.
4. **OFFLINE-FIRST RESILIENCE:** Both backend and frontend must work with Wi-Fi turned off (Airplane Mode). If `data/processed/fire_cube.parquet` is missing at startup, automatically invoke `scripts/00_bootstrap_synthetic_cube.py`.

---

## 2. STRICT 5-PERSON FILE OWNERSHIP (ZERO GIT MERGE CONFLICTS)

Each developer owns an isolated set of files. Only modify files belonging to the active developer's track:

| Developer | Role | Exclusive File Ownership | Automated Test Gate |
| :--- | :--- | :--- | :--- |
| **1. ADAM** *(Team Lead)* | **Math & Physics Core** *(RTS Kalman + Cross Guard, Shannon Entropy, EQM, Von Mises, Chow/Wasserstein)* | `backend/api/schemas.py`<br>`backend/core/footprint_h3.py`<br>`backend/core/industrial_filter.py`<br>`backend/core/eqm_harmonizer.py`<br>`backend/core/kalman_rts.py`<br>`backend/core/von_mises.py`<br>`backend/core/auditor_stats.py`<br>`backend/core/chaos_monkey.py`<br>`backend/tests/test_math_core.py` | `pytest backend/tests/test_math_core.py -v`<br>*(0% FastAPI/DuckDB imports inside `backend/core/`)* |
| **2. MOHAMMED** | **Frontend GPU Map, Store & 2D Canvas Calendar** | `frontend/src/api/types.ts`<br>`frontend/src/api/client.ts`<br>`frontend/src/store/useAnalysisStore.ts`<br>`frontend/src/components/Map/HexagonMap.tsx`<br>`frontend/src/components/Map/AoiDrawControl.tsx`<br>`frontend/src/components/Calendar/HatchPatternDefs.ts`<br>`frontend/src/components/Calendar/BurningCalendarCanvas.tsx`<br>`frontend/src/components/Calendar/CalendarTooltip.tsx` | `cd frontend && npx tsc --noEmit` |
| **3. ANTONIO** | **DuckDB Engine, Hierarchical H3 Queries & FastAPI** | `backend/db/duckdb_engine.py`<br>`backend/db/queries.py`<br>`backend/db/nrt_poller.py`<br>`backend/api/cache.py`<br>`backend/api/routes.py`<br>`backend/api/main.py`<br>`backend/tests/test_api_contract.py` | `pytest backend/tests/test_api_contract.py -v` |
| **4. GERMÁN** | **Offline ETL Pipeline & Master Parquet Cube** | `scripts/00_bootstrap_synthetic_cube.py`<br>`scripts/01_ingest_firms.py`<br>`scripts/02_detect_outages_clouds.py`<br>`scripts/03_train_eqm_lut.py`<br>`scripts/04_build_master_cube.py`<br>`scripts/05_cli_benchmark.py`<br>`backend/tests/test_cube_schema.py` | `python3 scripts/00_bootstrap_synthetic_cube.py && pytest backend/tests/test_cube_schema.py -v` |
| **5. MIGUE** | **Scientific Charts, Audit Panel, Chaos Monkey UI & Pitch** | `frontend/src/components/Charts/PolarVonMisesClock.tsx`<br>`frontend/src/components/Charts/KalmanUncertaintyBandChart.tsx`<br>`frontend/src/components/Audit/AuditMetricsPanel.tsx`<br>`frontend/src/components/Audit/ChaosMonkeyButton.tsx`<br>`frontend/src/App.tsx`<br>`frontend/src/main.tsx`<br>`README.md` | `cd frontend && npm run build` |

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

### Guardrail 4: Two-Level Hierarchical H3 Polygon Filtering
Never call `h3.polygon_to_cells(poly, res=7)` directly on large polygons. Always compute `res=4` cells first (`< 0.4 ms`) to filter `WHERE h3_r4 IN (...)` via Parquet Zone Maps, and only refine `res=7` when `len(cells_r4) < 80`. If `res=4` is empty on a tiny polygon, fallback to the centroid's `res=4` cell and its `grid_disk(c, 1)`.

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
2. Render all $26 \times 366 = 9,516$ calendar cells in a single HTML5 `<canvas>` 2D element using `OffscreenCanvas` / `ctx.createPattern` for diagonal hatching on `is_gap_filled === true` and `is_forecast === true`.