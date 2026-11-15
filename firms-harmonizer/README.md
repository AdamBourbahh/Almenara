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
| PM2.5 smoke emissions | **Not computed in the dashboard.** Copilot episode dossiers provide explicitly assumed-factor scenario estimates only. `total_pm25_emitted_tonnes` and `pm25_emitted_kg` are `null`; the Impact panel shows "Not computed", not `0 t`. |
| Industrial flaring filter | **Currently inert on real data.** The ETL entropy gate does not flag any real cell (`industrial_prob` max ≈ 0.0022), so the toggle and the purple flare layer remove nothing. The panel reports the real removed count and says so when it is zero. |
| Burned-area validation (R²) | **Pending.** Requires MCD64A1 ancillary data (`data/lookup/cell_day_ancillary.parquet`); until then R² is `null`. `scripts/07_fetch_mcd64a1_ancillary.py` exists for that ingest. |
| Forecast / PM2.5 / tooltips in the frozen contract | Kept nullable by design; returning `null` is the honest state. |

Known correctness issues identified by the 2026-11-14 audit and being fixed by their owners: zero-detection days entering the Kalman smoother as gaps and sensor means using different cell subsets. The daily-area inflation, NOAA-20/21 labels and AOI area reporting have been corrected. Biomass and emissions remain model-derived estimates.

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

Open **Fire Copilot** and ask about a place and date, in English, Spanish or Portuguese.
Answers and UI text are in English. For example:

- “What happened near Madrid on 24 July 2026?”
- “Investigate Careiro, Amazonas on 13 September 2024.”
- “Which days had the most detections near Manaus in September 2024?”
- “And on the next day?” (after a dated question)
- “How much energy in GJ and how many detections are in this area?”
- “Show energy by year for this area from 2020 to 2025.”
- “Tell me everything about the main wildfire in this region: cause, progression, duration and consequences.”

Selecting a map area, hexagon or timeline day automatically adds **Area and day
added as context** above the chat input. Month/year selections are labeled as periods,
including **full year** where appropriate. The notice shows location and dates and
has a single **×** to remove the attachment. Drawing an area preserves the selected
day. There are no separate pinning or date controls inside the chat. Removing context
also prevents earlier attached geometry or dates from leaking into the next question.

A compatible reference such as “that fire in Madrid” keeps the drawn polygon; it does
not expand a small selection to the whole Madrid envelope. A different named place or
explicit date can change the scope. Answers show their actual queried scope.

For “why did this fire happen?”, responses start with what can be established, then
show concise local evidence and distinguish incident reports from scientific context.
A broad first-time investigation discovers the highest-energy thermal episode in the
available local history without needing a calendar click. Explicit question dates take
precedence. Its four-section dossier explains ignition evidence, progression, physical
estimates and sensor verification. The ±15-day activity window and any censored bounds
are disclosed; this is a statistical thermal episode, not an official fire duration.
Biomass uses integrated FRE; PM2.5 and CO2 are clearly labeled scenario estimates with
assumed emission factors, not measured pollution or a replacement for null dashboard
emissions. A whole-year selection is not treated as a single incident. Ignition causes are never
inferred from detection counts, power, weather theory or the busiest day.

The assistant searches official agencies and reputable news, reads a bounded number of
official pages, and checks related scientific publication metadata using Crossref.
Reported explanations must be grounded in retrieved official or reputable-news text,
retain uncertainty and match the requested date/locality. Ignition, spread conditions
and incident context are treated separately. Search
snippets remain leads. DOI metadata and general scientific papers do not establish the
cause of a particular fire. Useful sources are cited, without inflating source counts.
This is retrieval and evidence checking, not model training. Source details can be
expanded below each response.

GJ answers use the same full-history scientific calculation as the dashboard, with
the attached reconstruction and industrial-source filters. They integrate daily FRE
over the cube cells represented on each day, then select the requested dates; they never convert a sum of
instantaneous MW samples into GJ. The full polygon area is not multiplied across every day; missing daily footprints
do not receive invented energy. Responses include biomass estimates, reconstructed
day counts, the highest-energy day and annual energy totals for multiyear requests.
Reconstructed regional totals may differ from the map's observed-only period energy.
Numerical queries need no model credentials or internet access. Missing data are
reported explicitly, and synthetic results remain visibly labeled.

The assistant queries accepted local FIRMS detections for the question's geography and
exact inclusive dates. It reports counts, summed instantaneous power and busiest days
without treating detections as distinct fires or converting MW into burned hectares.
Madrid, Sierra Oeste, Careiro and Autazes use explicit study envelopes; the four project
regions and custom drawn AOIs are also supported. Other named places can use web reports,
but local counts require a supported envelope or a drawn AOI. Amazonas/Manaus coverage
is a limited study area, not the whole Amazon basin.

For natural-language interpretation and prose, configure `GROQ_API_KEY` in a local `.env`.
Legacy concise answers default to `openai/gpt-oss-120b`; dossier extraction first tries
`llama-3.3-70b-versatile`. Set `GROQ_MODEL` to override either. If the account returns
404 for a model, `GROQ_FALLBACK_MODEL` (default `openai/gpt-oss-120b`) is tried within
the same deadline. The current local account cannot access the requested Llama model.
Optional `GEMINI_API_KEY` enables the subsequent Gemini provider.
[GitHub Models retired on 30 July 2026](https://github.blog/changelog/2026-07-01-github-models-is-being-fully-retired-on-July-30-2026/),
so a `GITHUB_TOKEN` alone does not trigger a request to a dead endpoint. The GitHub
compatibility adapter requires an explicitly configured `GITHUB_MODELS_ENDPOINT`
pointing to an operator-provided compatible gateway; it is optional and not a claim
that GitHub's former hosted service is available.
Requests are bounded to 4,500 content characters, 900 output tokens and a 10-second
provider deadline. These reduce request size; they cannot guarantee free-tier quota
availability or sub-second network latency. Optional `TAVILY_API_KEY` enables Tavily search; otherwise the assistant
uses public search through `ddgs`. Search results are contextual leads, not automatic
confirmation of a matching fire. Inline source markers open the actual cited pages.
Provider availability and model permissions depend on the configured account.

Set `COPILOT_OFFLINE=1` for deterministic answers from the local archive with no model or
search requests. These answers still report observations, distinguish missing evidence,
and explain basic sensor methods. A functioning local backend is required; a disconnected
frontend displays a connection error. Synthetic mode explicitly cannot verify real events.
The assistant never silently substitutes synthetic answers or invents an undocumented fire
when no reports are found.

Run the chatbot checks from `firms-harmonizer/`:

```bash
python -m pytest backend/tests/test_explain_spike.py backend/tests/test_copilot_metrics.py backend/tests/test_copilot_research.py backend/tests/test_copilot_acceptance.py -q
python scripts/06_validate_copilot.py --output data/processed/copilot_validation_offline.json
python scripts/06_validate_copilot.py --live --output data/processed/copilot_validation_live.json
python scripts/08_validate_copilot_acceptance.py
python scripts/08_validate_copilot_acceptance.py --live
python -m pytest backend/tests/ -v
python scripts/test_copilot_e2e.py
python scripts/09_validate_copilot_agent.py
cd frontend && node --test tests/*.test.mjs && npm run build
```

The validation script requires a real cube and staging file, cross-checks numerical answers
against separate SQL aggregates, and saves full answers for review. Its automated PASS
checks numerical accuracy and contracts; it does not independently certify the narrative
or prove a match between a detection and a news-reported incident.

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

### Map search and drawn-context repair (2026-11-15)

Location search returns places only inside the four UI study envelopes: Iberia,
Chilecito, Orlando and Amazonas/Manaus. Photon queries use a bounding box for each
envelope and results are checked locally against those bounds. Coordinates outside
all four envelopes are rejected; selected location boxes are clipped at the edge.
Place-name search needs a connection; region shortcuts and coordinates work offline.
The Explore panel no longer duplicates region shortcuts. Satellite and Terrain are
the available basemaps. The Copilot drawer ends at the top of the chronology bar.

A drawn Sierra Oeste selection now recognizes a matching Madrid regional report
when its body uses Madrid as the regional name. The source date still has to match,
and reported spread conditions remain distinct from an established ignition cause.

Causal paraphrases such as “the reason of the fire is known?” use the checked-report
path. Questions about whether ignition is known start with the available ignition
evidence, rather than substituting spread conditions. Relevant complete source
sentences are packed before applying the provider context limit, so the serialized
evidence is not truncated mid-JSON. This is a routing/context repair; the configured
model remains GPT-OSS 120B on Groq, without a claim that it is the best free model.

### Groq RAG and read-only tools

The online Copilot now uses Groq native tool calling with a short instruction
message. It chooses between local document retrieval, observations, energy,
episode profiling and incident research, rather than a question-keyword router.
SQLite FTS5/BM25 indexes the versioned science notes in `data/copilot_knowledge/`
and current ETL documentation. This is lexical RAG, not embeddings or fine-tuning;
the model can reformulate searches. Add reviewed documents to the corpus to expand
coverage. Scientific quantities remain database calculations, displayed by Python.

With `GROQ_API_KEY` configured the default agent model is `openai/gpt-oss-120b`.
`COPILOT_OFFLINE=1`, missing credentials, provider errors and invalid answers use
the existing local scientific fallback. A request-local offline override prevents
repeating failed network calls without changing other users' requests. Rate limits
can still cause fallback; no free-tier availability guarantee is made.

`python scripts/09_validate_copilot_agent.py` exercises actual Groq calls and records
which tools the model chose. Use `--question` and `--output` for individual cases.
`pytest backend/tests/test_copilot_agent.py -q` covers orchestration and failures
without using a provider account. Retrieved notes are not automatically certified
incident evidence; answers retain source and uncertainty labels.
