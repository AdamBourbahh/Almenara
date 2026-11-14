# FIRMS Harmonizer

A local, offline-first viewer and audit console for harmonized **MODIS + VIIRS** fire radiative energy (FRE). Built for the **NASA Space Apps Challenge 2026** — *Harmonization of MODIS and VIIRS Hot Spots*.

This README describes what the application actually does today (2026-11-14). It deliberately does not promise features that are not implemented.

---

## What the application does

- **Map** — satellite + relief basemap, H3 heat grid, drag-to-draw AOI, latitude/longitude entry, basemap switcher and the `H` shortcut.
- **Calendar** — a single 2D canvas with all 26 × 366 daily cells, a raw/harmonized curtain, hatching for repaired days and a per-day tooltip.
- **Trends** — circular fire-season clock (Von Mises) and the Kalman 95% band with the Chaos Monkey stress test.
- **Impact** — biomass, PM2.5 availability, IPCC-ready CSV export and the researcher validation table (Chow, Wasserstein-1, burned-area R²).
- **Risk AI** — local thermal-risk forecast for the selected AOI and date (classical model; probabilities are not incident records).
- **Observations** — accepted, de-duplicated FIRMS detection centres with CSV export. FRP is instantaneous MW, not energy.
- **Fire Copilot** — retrieval + evidence-checking assistant for local counts, energy and documented incidents.

Study regions with local real data: **Chilecito (La Rioja)**, **Iberian Peninsula**, **Orlando (Florida)**, **Amazonas / Manaus**, plus **Cerrado (Brazil)** and **California**. The UI presets are the first four; Cerrado and California are available through the API and the Copilot. **Niger Delta has no local CSVs yet.**

All UI copy and documentation are in English, per the NASA Space Apps global judging rules.

---

## What is deliberately not implemented

| Capability | Status |
| :--- | :--- |
| 14-day forecast | **Not available.** `forecast_series` is always `null`; the API accepts `forecast_days` but does not produce a forecast. The UI hides the forecast legend when there is no data. |
| PM2.5 smoke emissions | **Not computed.** `total_pm25_emitted_tonnes` and `pm25_emitted_kg` are `null`; the Impact panel shows "Not computed", not `0 t`. |
| Industrial flaring filter | **Currently inert on real data.** The ETL entropy gate does not flag any real cell (`industrial_prob` max ≈ 0.0022), so the toggle and the purple flare layer remove nothing. The panel reports the real removed count and says so when it is zero. |
| Burned-area validation (R²) | **Pending.** Requires MCD64A1 ancillary data (`data/lookup/cell_day_ancillary.parquet`); until then R² is `null`. `scripts/07_fetch_mcd64a1_ancillary.py` exists for that ingest. |
| Forecast / PM2.5 / tooltips in the frozen contract | Kept nullable by design; returning `null` is the honest state. |

Known correctness issues identified by the 2026-11-14 audit and being fixed by their owners: regional biomass/energy aggregation (currently inflated), zero-detection days entering the Kalman smoother as gaps, NOAA-20/21 sensor-bit decoding, and real AOI area reporting. Do not treat the current biomass numbers as final.

---

## Scientific method (summary)

1. **Footprint and H3.** MODIS footprints are distributed over the R7 centre and neighbours with normalized, rotated Gaussian weights and a bow-tie discount; VIIRS is assigned to the containing R7 cell.
2. **Daily energy.** Detections are de-duplicated per sensor/time/location, aggregated per H3 R7 cell and UTC day, and converted to energy density with `FRP × 3600 / cell_area`, plus the orbital revisit weight.
3. **Censor-aware harmonization.** A truncated-GPD EQM lookup maps VIIRS onto the Aqua reference; the correction is applied through `delta_e_sub` on VIIRS and detected MODIS cell-days.
4. **Gap reconstruction.** An RTS Kalman smoother with a cross-sensor 366-day prior and Joseph covariance updates reconstructs missing or flagged days.
5. **Audit.** Chow structural break at 2012, normalized Wasserstein-1, descriptive annual R², and a seeded Chaos Monkey (25% removal + 10-day blackout).

The core is implemented in `backend/core/` with no FastAPI or DuckDB imports, and is unit-tested against independent calculations.

---

## Measured diagnostics (2026-11-14, real cube)

`python -m backend.validation_report`, four-year-spanning real regions. These are **descriptive diagnostics**, not independent validation:

| Region | Chow p (harmonized) | W1 reduction | Chaos recovery |
| :--- | ---: | ---: | ---: |
| Chilecito | 0.562 | 83.3% | 95.7% |
| Orlando | 0.000388 | 75.8% | 100.0% |
| Manaus | 0.0303 | 90.5% | 93.9% |
| Cerrado | 0.430 | 89.8% | 98.6% |
| California | 0.777 | 75.0% | 91.1% |
| Iberia | 0.516 | 81.4% | 94.4% |

Gates: Chow p > 0.1 and W1 reduction > 88%. Some regions pass one gate and fail the other; the Impact panel shows the backend's verdict verbatim, including failures. Burned-area R² is `null` in every region until MCD64A1 data is ingested.

Warmed SQL P95 is 62–172 ms per pilot region on the reference machine; the original `<15 ms` target was measured as unattainable with the frozen per-cell layout and was replaced by a `P95 < 150 ms` + `cached HTTP < 20 ms` release gate. Cold `execution_time_ms` is 0.6–4.7 s.

---

## Architecture

- **ETL (offline).** `scripts/01` → `04` read the local FIRMS CSVs and publish a ZSTD Parquet cube keyed by `(h3_r4, epoch_day, h3_r7)` with 18 fields. The synthetic fixture is separate and opt-in.
- **API.** FastAPI + DuckDB. Hierarchical H3 filtering (R4 zone-map pruning, then R7), synchronous analytical routes, one cursor per request, orjson + GZip, an in-memory LRU keyed by a BLAKE2b digest, and `X-Cache` / `Server-Timing` headers.
- **Frontend.** React 19 + Vite 8 + Tailwind v4 + maplibre + deck.gl. One WebGL2 Deck.gl context, one 2D canvas calendar, Zustand store, local fonts. No network is required for the data path.
- **Provenance.** Every response carries `data_source: "real" | "synthetic"`. Synthetic results are opt-in and visibly labelled.

---

## Running it

From `firms-harmonizer/`:

```bash
python3 -m venv .venv
. .venv/bin/activate
make install PYTHON=python

# Rebuild the real cube from the tracked CSVs (no network)
python scripts/01_ingest_firms.py
python scripts/02_detect_outages_clouds.py
python scripts/03_train_eqm_lut.py
python scripts/04_build_master_cube.py

# API
env -u USE_SYNTHETIC_CUBE python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000

# Frontend (second terminal)
cd frontend && npm ci && npm run dev
```

Open the URL Vite prints (default <http://localhost:5173>). Vite proxies `/api` to port 8000; `VITE_API_URL` overrides it. The viewer needs the real master cube and `data/processed/staged_firms.parquet`, both rebuilt from the tracked raw CSVs.

Explicit synthetic mode (opt-in only):

```bash
USE_SYNTHETIC_CUBE=1 python -m uvicorn backend.api.main:app --port 8001
```

---

## Tests and checks

```bash
pytest backend/tests -q
sha256sum -c backend/tests/FROZEN_TESTS.sha256
python -m backend.check_core
python -m backend.validation_report
python scripts/05_cli_benchmark.py

cd frontend
npx tsc --noEmit
npm run build
npm test
```

The backend suite covers the math core, ETL schema, DB layer, HTTP contract, real-cutover provenance, observations, NRT polling and the Copilot. The frozen DB/API/core-validation tests are pinned by `FROZEN_TESTS.sha256`; any change to them must be agreed and the hash regenerated (see `CAMBIOS.md`).

---

## Fire Copilot

Open **Fire Copilot** and ask about a place and date, in English, Spanish or Portuguese; answers and UI text are in English. Examples:

- "What happened near Madrid on 24 July 2026?"
- "Investigate Careiro, Amazonas on 13 September 2024."
- "Which days had the most detections near Manaus in September 2024?"
- "And on the next day?"
- "How much energy in GJ and how many detections are in this area?"
- "Show energy by year for this area from 2020 to 2025."

Selecting an area, hexagon or timeline day attaches it as context above the input; removing the context prevents leaks into the next question. Numerical answers come from the same full-history calculation as the dashboard, with reconstructed and industrial flags. A whole-year selection is never treated as a single incident, and ignition causes are never inferred from detection counts.

For prose and live grounding, configure `GROQ_API_KEY` (and optionally `TAVILY_API_KEY`) in a local `.env`. Without credentials, set `COPILOT_OFFLINE=1` for deterministic archive-only answers. Search results are leads; only a causal excerpt in retrieved official text, with a matching date and locality, supports a cause. Missing evidence is stated explicitly; synthetic answers are labelled and never silently substituted.

Copilot checks:

```bash
python -m pytest backend/tests/test_explain_spike.py backend/tests/test_copilot_metrics.py backend/tests/test_copilot_research.py -q
python scripts/06_validate_copilot.py --output data/processed/copilot_validation_offline.json
cd frontend && node --test tests/*.test.mjs
```

The validation script cross-checks numerical answers against separate SQL aggregates. It checks accuracy and contracts, not whether a detection matches a news-reported incident.

---

## Data provenance and limits

- Raw inputs are the tracked FIRMS CSV exports under `data/raw/` (Terra/Aqua MODIS and SNPP/NOAA-20/NOAA-21 VIIRS). Study rectangles are envelopes, not administrative boundaries.
- Days with no detections may mean no fire **or** no observation; the cube stores only rows with detections, and the zero-vs-missing handling is an open backend issue (audit item 2).
- The 2022 outage marker is **VIIRS SNPP, 2022-07-27..2022-08-10** (15 days), validated against FIRMS world daily counts.
- The synthetic fixture (`fire_cube_synthetic.parquet`) is opt-in and clearly labelled; it is not evidence of real-world performance.
- `FIRMS_MAP_KEY` used for NRT ingest is compromised in the git history and must be rotated before live polling.

## Further documentation

- `../Miguelspecs.md` — delivery log, decisions and verification.
- `../Implementation_backend_plan.md` — phase-by-phase backend plan and evidence.
- `../SPECS.md` — scientific specification and frozen contracts.
- `../AGENTS.md` — ownership and technical guardrails.
- `CAMBIOS.md` — approved contract changes.
- `frontendExpects.md` — historical frontend expectations (superseded by `Miguelspecs.md`).
