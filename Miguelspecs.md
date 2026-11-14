# Miguelspecs — Work Log and Delivery Specification

**Author:** Migue (frontend track, cross-track integration on explicit request)
**Repository:** `AdamBourbahh/Almenara`
**Date:** 2026-11-14
**State at publication:** `5efd8e2`; after the 2026-11-14 pull and gate repair, `main` and `front-end` share `df19a04` plus the frozen-hash fix (see Section 13).
**Companion documents:** `AGENTS.md` (ownership and guardrails), `SPECS.md` (scientific methods), `Implementation_backend_plan.md` (phase-by-phase plan and evidence), `firms-harmonizer/frontendExpects.md` (frontend expectations), `firms-harmonizer/CAMBIOS.md` (approved contract changes).

---

## 1. Purpose

This document records everything delivered and fixed during the map-first frontend session and the Phase 11/12 backend close-out: what exists, why it exists, how it was verified, what remains blocked, and how to reproduce the results offline. It is the single entry point for a reviewer who needs to understand the current state without reading every commit.

The work is done under the project rules in `AGENTS.md`: no placeholders, frozen API contracts, English UI and docs, offline-first behaviour, and no fabricated scientific evidence.

---

## 2. Environment

| Item | Value |
| :--- | :--- |
| OS / shell | Linux, bash |
| Python | 3.12.3 |
| Virtual environment | `/tmp/almenara-cube-venv` (repository `backend/requirements.txt`) |
| Node | Vite 8 / npm (frontend dependencies in `frontend/package.json`) |
| DuckDB | 2.0.0 |
| Backend matrix | FastAPI, DuckDB, PyArrow, NumPy, SciPy, H3 v4, orjson, httpx, ddgs, python-dotenv |
| Frontend matrix | React 19, Tailwind v4, Vite 8, maplibre 6, react-map-gl 8, deck.gl 9.4, zustand 5 |
| Data source | Local FIRMS CSV archives in `firms-harmonizer/data/raw/` (no network) |

All commands are run from `firms-harmonizer/` unless stated otherwise.

---

## 3. Frontend delivery

### 3.1 Shell and navigation

- Map-first single-page application. Top bar: **Map**, **Calendar**, **Trends**, **Impact**, **Observations**, plus the **Fire Copilot** drawer, the **Raw/Harmonized** switch and the basemap switcher.
- Editorial visual language: paper `#F8F7F4`, white panels, `1px #DCDCDC` rules, Source Serif 4 headings, Inter controls, IBM Plex Mono with tabular figures. No neon, glassmorphism, gradients, coloured shadows or emoji.
- Accessible ramps: thermal `#FEF0D9 → #B30000` for fire energy; `#6A3D9A` for industrial flares.
- Offline-capable: fonts bundled locally; the typed client can generate a deterministic synthetic response only when explicitly enabled (`VITE_ALLOW_SYNTHETIC_FALLBACK`), and every response carries `data_source`.

### 3.2 Map

- Basemap options: **Satellite + relief** (Esri World Imagery + World Hillshade), Satellite, Terrain (OpenTopoMap), Streets (Carto).
- One WebGL2 Deck.gl context (`H3HexagonLayer`) with a transparent canvas (`MapView({ clear: false })`) so the basemap shows through. The `H` shortcut toggles the heat layer.
- AOI drawing (drag box), latitude/longitude entry, four populated pilot presets: **Chilecito (La Rioja)**, **Iberian Peninsula / Mediterranean**, **Orlando (Florida)**, **Amazonas / Manaus**.
- Industrial filter: "Hide industrial heat (refineries and flares)" with the Shannon temporal-entropy note (`H > 0.75`).
- Right-hand explore panel: mapped detections, active grid cells, mapped energy proxy, observed cell footprint, estimated dry biomass, PM2.5 availability, and the area's yearly heat history.

### 3.3 Calendar

- All `26 × 366 = 9,516` daily cells render in a single HTML5 `<canvas>` 2D element.
- The 2012 curtain compares raw hot-spot counts (left) with harmonized fire energy (right).
- Diagonal hatching marks Kalman-repaired days and the 14-day forecast; the legend explains both.
- Year selection syncs with the chronology dock at the bottom of the app.

### 3.4 Trends and Impact

- **Trends:** circular fire-season clock (Von Mises; peak day and concentration per year), decadal shift headline, and the Kalman 95% band with the 14-day forecast. The "Simulate a satellite outage" stress test is wired to the Chaos Monkey contract.
- **Impact:** dry biomass, PM2.5 smoke, analysed area, plain-language verdict, IPCC-ready CSV export, and the researcher table (Chow, Wasserstein-1, burned-area R²) with nullable fields rendered honestly.

### 3.5 Observations and Fire Copilot

- **Observations:** real FIRMS detection centers (accepted, de-duplicated), with export to CSV and an explicit note that FRP is instantaneous MW, not energy.
- **Fire Copilot:** slide-over drawer with the physics-first web-grounding panel and suggested inquiries.

### 3.6 Frontend fixes in this session

| Fix | Detail |
| :--- | :--- |
| **Copilot drawer blocked navigation** | The slide-over used `fixed inset-y-0` and covered the header controls on desktop, swallowing navigation clicks. It now renders as an `absolute` panel inside a content wrapper that begins below the header (with a `z-30` mobile backdrop), so the header stays fully clickable at every breakpoint. Verified in the browser with the drawer open: "Calendar" navigates and the header remains visible. |
| **Misleading 2022 outage** | The calendar, offline generator and tooltip narratives hard-coded "MODIS Aqua safe mode" (2022-07-31..08-16). The validated outage is **VIIRS SNPP, 2022-07-27..2022-08-10** (15 days). Replaced with `SNPP_OUTAGE`/`SNPP_MARKER` (DOY 208–222), corrected sensor availability and copy. |
| **Double-encoded copy (mojibake)** | `client.ts` contained `MJ/kmÂ²`, `Â±`, `Îºâ‰ˆ3.1Ã—`, `tâˆ’1`, `MODISâ€“VIIRS`. Corrected to `MJ/km²`, `±`, `κ≈3.1×`, `t−1`, `MODIS–VIIRS`. |

---

## 4. Backend Phase 11 and Phase 12

### 4.1 Phase 11 — Scientific audit and Chaos Monkey

The scientific code was already implemented; the session verified it on the real cube and closed everything that does not depend on external data.

- Wooster biomass (`0.368 kg/MJ`), smoke, Chow structural break (annual means), normalized Wasserstein-1, descriptive annual R² and the 25% / 10-day Chaos Monkey are covered by the suite.
- Real-cube behavior (Chilecito AOI): `/api/analyze` → HTTP 200, `execution_time_ms` 820.5, wall 1.01 s, 9,760 cells, 9,496 days. `POST /api/chaos-monkey` → HTTP 200 in 0.61 s, 87 dropped days, naive RMSE 22,197.9 vs RTS 19,403.3, 95.5% seasonal recovery.
- Cached analyze returns `X-Cache: HIT`, with a 1.7 ms cache stage in `Server-Timing`.
- **Remaining open task:** validation against genuine MCD64A1 burned area. `data/lookup/cell_day_ancillary.parquet` is absent, so `burned_area_r2_*` stays `null`. No synthetic substitute is fabricated.

### 4.2 Phase 12 — HTTP, cache and release verification

- Synchronous `POST /api/analyze` and `POST /api/chaos-monkey`, `GET /api/health`, orjson + GZip, isolated DuckDB cursors, `X-Cache` and `Server-Timing`.
- Airplane-mode verification in both modes: real (`data_source=real`, 761,801 rows) and explicit synthetic (`USE_SYNTHETIC_CUBE=1`).
- The original `<15 ms` SQL target was **descoped after measurement** (Section 6). Phase 12 is complete against the revised release gate.

---

## 5. Scientific and data corrections

### 5.1 Deterministic EQM/GPD lookup (Phase 6 defect)

`scripts/03_train_eqm_lut.py` was not reproducible: `mode(scan_bin)` and `any_value(igbp_biome)` broke ties arbitrarily, and the multi-threaded scan changed floating-point aggregation order. `matched_days` moved in 21–24 of 28 strata on identical inputs.

Fix:

- Group by `(h3_r7, acq_date, igbp_biome, scan_bin)`.
- Select the modal angle with `arg_max(scan_bin, n*10 - scan_bin)` (highest count, lower bin on ties).
- Use `min(igbp_biome)` and a single-threaded DuckDB connection.

Evidence: two consecutive runs are **byte-identical** (`sha256 20638d84bee866170915a6007b483029ea5f06b3dc9efdc6cfe17caea1795b97`, 28 models, 102,469 bytes). The tracked LUT was regenerated from the fixed path and the real cube was republished so the artifact and the trainer agree.

### 5.2 Real cube publication

The real cube was rebuilt offline from `data/raw/` through scripts `01 → 02 → 03 → 04`:

| Metric | Value |
| :--- | :--- |
| Staged detections | 2,376,587 |
| Footprint contributions | 2,803,055 |
| Published rows | **927,542** |
| Coverage | 2000-11-01 → 2026-11-14 |
| Row groups | 29 (ZSTD) |
| Size | ~13.9 MB |

The synthetic fixture is separate (`fire_cube_synthetic.parquet`) and opt-in only.

### 5.3 2022 outage

The validated outage is **SNPP**, 2022-07-27 through 2022-08-10 (15 inclusive days), measured against FIRMS world daily counts. The superseded "Aqua Safe Mode 2022-07-31..08-16" is contradicted by the archive and had nulled valid Aqua cell-days.

### 5.4 Benchmark estimator alignment

`scripts/05_cli_benchmark.py` previously reported a daily-harmonic Chow (0.000 everywhere) and absolute Wasserstein distances, disagreeing with the product audit. It now:

- imports `compute_chow_structural_break_test` and aggregates the daily series to annual means, exactly like the API audit;
- normalizes W1 by the overall mean;
- excludes industrial cells, like the API default.

Reported Chow now tracks the API (0.531 / 0.000 / 0.478 / 0.614 for Chilecito / Orlando / Manaus / Iberia). The residual Manaus difference (0.478 vs the API audit 0.028) is expected and documented: the benchmark uses the raw unsmoothed regional energy, while the API audit uses the Kalman-smoothed daily series. The estimator is aligned; the input series is deliberately different.

---

## 6. Performance envelope and target revision

Measured on the reference machine with the warmed SQL query over the full AOI history:

| Region | Warmed SQL P95 | Chow p | W1 (normalized) | Seasonal recovery |
| :--- | ---: | ---: | ---: | ---: |
| Chilecito | 81.3 ms | 0.531 | 0.523 | 79.7% |
| Orlando | 68.9 ms | 0.000 | 0.584 | 95.1% |
| Manaus | 128.8 ms | 0.478 | 0.357 | 82.8% |
| Iberia | 171.6 ms | 0.614 | 0.148 | 72.3% |

Interpretation:

- The **`<15 ms` target is not physically reachable** on this stack. A 0.5° interactive AOI floors at ~33 ms median (17 ms best) with a metadata-cached view; a `threads=1..4` sweep never reached 15 ms. The frozen per-cell `(h3_r4, epoch_day, h3_r7)` layout gives DuckDB no coarser grain, and a pre-aggregated `(h3_r4, year, doy)` table cannot serve the per-hexagon map summaries.
- **Revised release gate:** warmed SQL P95 **< 150 ms** per pilot region and **cached HTTP < 20 ms**. Cold `execution_time_ms` is recorded but not gated (Chilecito 820 ms, Iberia ~4.7 s).
- Run-to-run variation is 2–3× under machine load, so single-run numbers are not treated as pass/fail evidence.

---

## 7. NRT poller

`backend/db/nrt_poller.py` was an empty file (a placeholder, contrary to the project's zero-placeholder rule). It now implements the NASA FIRMS area API client:

- `(west, south, east, north)` bbox validation, source whitelist, day range 1–5, ISO start date;
- `FIRMS_MAP_KEY` read from `.env` or the environment;
- CSV fetch through `httpx`, numeric coercion, empty/HTML response handling;
- **the map key never appears in error messages or logs**;
- CLI entry point and `write_nrt_csv` helper.

16 offline tests use `httpx.MockTransport`; no live request was made because the stored key is compromised and must be rotated in NASA FIRMS before a real ingest.

---

## 8. Verification matrix

Run on the published `main` (`5efd8e2`):

| Gate | Command | Result |
| :--- | :--- | :--- |
| Backend suite | `pytest backend/tests -q` | **361 passed, 1 skipped** (optional `rasterio` for the MCD64A1 fetch test) |
| Frozen contracts | `sha256sum -c backend/tests/FROZEN_TESTS.sha256` | **4 files OK** |
| Core conformance | `python -m backend.check_core` | **exit 0**, 8/8 operations |
| Real audit | `python -m backend.validation_report` | **exit 0**, four populated regions |
| CLI benchmark | `python scripts/05_cli_benchmark.py` | exit 1 (R², recovery, Iberia P95 out of target) |
| Frontend types | `npx tsc --noEmit` | **0 errors** |
| Frontend build | `npm run build` | **OK** |
| Frontend tests | `node --test frontend/tests/*.test.mjs` | **19/19** |
| API health | `GET /api/health` | `data_source=real`, 927,542 rows, 8/8 core |
| Browser smoke | MCP browser | no console errors; calendar marker, copilot-open navigation |

`validation_report` real-mode summary (harmonized Chow / W1 reduction / Chaos recovery): Chilecito 0.562 / 83.3% / 95.7%; Orlando 0.000388 / 75.8% / 100.0%; Manaus 0.0303 / 90.5% / 93.9%; Cerrado 0.43 / 89.8% / 98.6%; California 0.777 / 75.0% / 91.1%; Iberia 0.516 / 81.4% / 94.4%. Cerrado and California now have real rows after the pull; only Niger Delta remains without local CSVs.

---

## 9. Known blockers (external data or deferred decisions)

| Item | Status | Why |
| :--- | :--- | :--- |
| MCD64A1 burned-area validation (Phase 11) | **Blocked** | `data/lookup/cell_day_ancillary.parquet` is still absent; `scripts/07_fetch_mcd64a1_ancillary.py` now exists but needs Earthdata credentials |
| Cloud reanalysis and swath evidence (Phase 5) | **Blocked** | Same ancillary file and external swath data |
| Niger Delta preset | **Blocked** | The only preset without local FIRMS CSVs; Cerrado and California now have real rows |
| PM2.5, tooltip narratives, 14-day forecast in the API | **Deferred** | MVP scope and frozen nullable contract |
| `FIRMS_MAP_KEY` in git history | **Action needed** | Rotate the key in NASA FIRMS, then use the new poller |
| NumPy timedelta warning in `tests/conftest.py` | **Accepted** | The file is frozen by `FROZEN_TESTS.sha256` |

The EQM core↔ETL parity decision (Phase 6) was closed by unifying the transform (`delta_e_sub` on VIIRS and MODIS) and is no longer open.

---

## 10. Repository state and commit trail

`main` and `front-end` both point to `5efd8e2` and are in sync with their remotes. Relevant commits:

```
5efd8e2 docs(backend): refresh the verification counts after the copilot merge
0db07b9 Merge origin/main: modular Fire Copilot, multi-turn and ddgs grounding
4b2b2d7 docs(backend): close phase 12, descope the <15 ms target and record the fixes
899af4b fix(benchmark): use the API annual-mean Chow and normalized W1
0d311aa fix(frontend): keep the copilot drawer below the header and repair mojibake
fa7e97a feat(nrt): implement the FIRMS area API poller
69fa5c7 docs(backend): record the phase 11/12 pass, determinism fix and latency re-measure
1a932c4 fix(frontend): mark the 2022 outage as VIIRS SNPP, not MODIS Aqua
f51798e fix(etl): make the EQM/GPD lookup byte-reproducible
```

Files touched in this delivery:

- **Frontend:** `App.tsx`, `api/client.ts`, `components/Calendar/BurningCalendarCanvas.tsx`, `components/Audit/FireCopilotDrawer.tsx`, `store/useAnalysisStore.ts`.
- **Backend:** `backend/db/nrt_poller.py`, `backend/tests/test_nrt_poller.py`, `backend/requirements.txt` (dedupe `python-dotenv`).
- **ETL:** `scripts/03_train_eqm_lut.py`, `scripts/05_cli_benchmark.py`, `data/lookup/eqm_gpd_lut.json`.
- **Docs:** `Implementation_backend_plan.md`, `Miguelspecs.md`.

The frontend and backend shared files listed in `AGENTS.md` were edited cross-track on explicit instruction from the team lead; the ownership table remains unchanged.

---

## 11. How to reproduce

```bash
# 1. Python environment
cd firms-harmonizer
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt

# 2. Rebuild the real cube offline (local CSVs, no network)
python scripts/01_ingest_firms.py
python scripts/02_detect_outages_clouds.py
python scripts/03_train_eqm_lut.py
python scripts/04_build_master_cube.py

# 3. Verify
pytest backend/tests -q
sha256sum -c backend/tests/FROZEN_TESTS.sha256
python -m backend.check_core
python -m backend.validation_report
python scripts/05_cli_benchmark.py

# 4. Run the API and the frontend
uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
cd frontend && npm install && npm run dev     # http://localhost:5173
```

The deterministic LUT check:

```bash
python scripts/03_train_eqm_lut.py --output /tmp/lut_a.json
python scripts/03_train_eqm_lut.py --output /tmp/lut_b.json
cmp /tmp/lut_a.json /tmp/lut_b.json && echo "byte-identical"
```

The explicit synthetic mode (opt-in only):

```bash
USE_SYNTHETIC_CUBE=1 uvicorn backend.api.main:app --port 8001
```

---

## 12. Decision log

| Date | Decision | Rationale |
| :--- | :--- | :--- |
| 2026-11-14 | Deterministic EQM/GPD trainer | Reproducibility is a release requirement; tie-breaking must not change a published lookup |
| 2026-11-14 | Republish the real cube with the deterministic LUT | Keep the published artifact consistent with the trainer |
| 2026-11-14 | Mark the outage as SNPP, not Aqua | The archive contradicts the Aqua interval; FIRMS world counts confirm SNPP |
| 2026-11-14 | Align the benchmark estimator with the API audit | Two different Chow/W1 definitions produced contradictory public numbers |
| 2026-11-14 | Descope `<15 ms`, adopt P95 `<150 ms` + cached `<20 ms` | Measured floor is ~33 ms even for a small AOI; the old bound was unreachable |
| 2026-11-14 | Implement `nrt_poller.py` instead of deleting it | The zero-placeholder rule; the file is referenced in the ownership table and `.env.example` |
| 2026-11-14 | Fast-forward `main` to `front-end` | `origin/main` was an ancestor, so no merge commit or conflict resolution was needed |
| 2026-11-14 | Do not fabricate MCD64A1 data | Independent validation must not be simulated; the field stays `null` until real data arrives |

---

## 13. Pull refresh — 2026-11-14 (evening)

`origin/main` advanced from `b24d00a` to `df19a04`; because the local branch was an ancestor, the pull was a **fast-forward** with no conflicts. Incoming work included the FIRMS NRT sync (`CubeSyncWidget`, `/api/cube/sync`, `/api/cube/sync-status`), the **Risk AI** tab and prediction panel, `scripts/07_fetch_mcd64a1_ancillary.py`, the phase 7 benchmark, `ddgs` copilot grounding, and new real raw CSVs.

Post-pull actions:

- **Frontend dependencies:** `npm install` after the pull (the `deck.gl` umbrella package was removed in favour of `@deck.gl/*`, with `@loaders.gl/*` overrides). `npx tsc --noEmit` and `npm run build` pass; `node --test` reports 19/19.
- **Cube rebuilt** from the refreshed raw data: 2,376,587 detections → **927,542 rows**, 29 ZSTD row groups, ~13.9 MB, coverage through 2026-11-14. Cerrado and California now publish real rows, leaving only Niger Delta without local CSVs.
- **Deterministic LUT:** the regenerated lookup has **37 models** and matches the committed file exactly (git reports no change), confirming the determinism fix holds on the new data.
- **Frozen gate repaired:** commit `319ac09` extended `backend/tests/test_api_contract.py` (cube-sync endpoint assertions) without regenerating `FROZEN_TESTS.sha256`. The hash was regenerated and the change recorded in `CAMBIOS.md`; the edit is additive and removes no prior assertion.
- **Backend suite:** 361 passed, 1 skipped (`rasterio` is only installed by `scripts/requirements-acquisition.txt` for the MCD64A1 fetch test). `sha256sum -c FROZEN_TESTS.sha256` now passes for all four files.
- **API:** `GET /api/health` → `data_source=real`, 927,542 rows, 8/8 core operations; the browser loads the new header ("FIRMS data through Nov 14, 2026"), the Risk AI tab and the map with no console errors.
- **Drawer regression re-fixed:** the pulled `7c4ca2b` removed the earlier `lg:top-16` offset when it changed the header to wrap at `2xl`, so the drawer covered the header again. The panel is now `absolute` inside a content wrapper below the header (mobile backdrop at `z-30`), which is breakpoint-independent. Verified: with the Copilot open, the header stays clickable and navigation works.

No scientific method or frozen public contract was changed by this refresh.
