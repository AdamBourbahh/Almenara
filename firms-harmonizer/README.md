# Current application: real FIRMS observations

The default UI visualizes accepted observations from Orlando, Manaus, Chilecito and the Iberia study area. It shows satellite detection counts and summed instantaneous FRP (MW). It does not apply gap filling or prediction. Missing dates are not assumed to be observed zero-fire days. Study rectangles are not country boundaries.

From `firms-harmonizer/`, install `backend/requirements.txt` in your Python environment and run:

```bash
python scripts/01_ingest_firms.py
python scripts/02_detect_outages_clouds.py
python scripts/03_train_eqm_lut.py
python scripts/04_build_master_cube.py
env -u USE_SYNTHETIC_CUBE python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
```

In a second terminal, run `cd firms-harmonizer/frontend && npm ci && npm run dev` and open the displayed local URL. Vite proxies `/api` to port 8000; `VITE_API_URL` can override the API base URL. Preview uses the same proxy. Hosting a production build requires a reverse proxy for `/api` to the backend. The viewer requires the real master and `data/processed/staged_firms.parquet`, both rebuilt from the 32 tracked CSVs. No network is needed for the data API after installation; online basemap tiles have a local coordinate-grid fallback. API failures are shown explicitly and never produce simulated results.

## Fire Copilot

Open **Fire Copilot** and ask about a place and date, in English, Spanish or Portuguese.
Answers and UI text are in English. For example:

- “What happened near Madrid on 24 July 2026?”
- “Investigate Careiro, Amazonas on 13 September 2024.”
- “Which days had the most detections near Manaus in September 2024?”
- “And on the next day?” (after a dated question)
- “How much energy in GJ and how many detections are in this area?”
- “Show energy by year for this area from 2020 to 2025.”

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
A whole-year selection is not treated as a single incident. Ignition causes are never
inferred from detection counts, power, weather theory or the busiest day.

The assistant searches official agencies and reputable news, reads a bounded number of
official pages, and checks related scientific publication metadata using Crossref.
A causal excerpt must be present in retrieved official text, retain its complete
sentence and uncertainty, and match a nearby explicit event date and locality. Search
snippets remain leads. DOI metadata and general scientific papers do not establish the
cause of a particular fire. Useful sources are cited, without inflating source counts.
This is retrieval and evidence checking, not model training. Source details can be
expanded below each response.

GJ answers use the same full-history scientific calculation as the dashboard, with
the attached reconstruction and industrial-source filters. They integrate daily FRE
over represented H3 area, then select the requested dates; they never convert a sum of
instantaneous MW samples into GJ. Responses include biomass estimates, reconstructed
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
`GROQ_MODEL` defaults to `openai/gpt-oss-120b`; `GROQ_FALLBACK_MODEL` defaults to
`openai/gpt-oss-20b`. Optional `TAVILY_API_KEY` enables Tavily search; otherwise the assistant
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
python -m pytest backend/tests/test_explain_spike.py backend/tests/test_copilot_metrics.py backend/tests/test_copilot_research.py -q
python scripts/06_validate_copilot.py --output data/processed/copilot_validation_offline.json
python scripts/06_validate_copilot.py --live --output data/processed/copilot_validation_live.json
cd frontend && node --test tests/*.test.mjs && npm run build
```

The validation script requires a real cube and staging file, cross-checks numerical answers
against separate SQL aggregates, and saves full answers for review. Its automated PASS
checks numerical accuracy and contracts; it does not independently certify the narrative
or prove a match between a detection and a news-reported incident.

The scientific architecture and demonstration material below describe experimental modules retained in the repository, outside the current observations-only UI.

---

# FIRMS Harmonizer

**A statistically audited, offline-ready MODIS + VIIRS fire radiative energy mission-control dashboard and 14-day burning forecast.**

Built for the **NASA Space Apps Challenge 2026** — *Harmonization of MODIS and VIIRS Hot Spots*.

> **Honesty note for judges.** The repository ships a deterministic **synthetic integration fixture** (see `scripts/00_bootstrap_synthetic_cube.py`). Every number rendered from that fixture is illustrative, not a measured NASA result; the bundled `executive_verdict_en` states this explicitly. Replace the fixture with the real FIRMS cube to obtain measured statistics. No production Kalman or phenotype claims are made from synthetic data.

---

## 1. The problem

Two generations of NASA fire satellites observe the same planet with fundamentally different instruments:

| | MODIS (`MCD14ML`) | VIIRS (`VNP14IMG` / `VJ114IMG`) |
| :--- | :--- | :--- |
| Nadir pixel | ~1 km × 1 km | 375 m |
| Minimum detectable FRP | ~8 MW | ~0.5 MW |
| Archive begins | 2000 | 2012 |
| Scan deformation | bow-tie up to ~4.8 × 2.0 km at ±55° | on-board aggregation keeps footprint ≤ ~0.75 km |

If raw detections are concatenated naively, **January 2012 appears to be the year the planet started burning ~420 % more**. It is not a climate signal — it is a radiometric and geometric instrument artifact. A continuous, comparable, 26-year climate record therefore requires explicit **harmonization**, not counting.

The platform converts every observation into a physically comparable **Spatial Density of Fire Radiative Energy**

$$\text{FRE}\ [\mathrm{MJ}\,\mathrm{km^{-2}}\,\mathrm{d^{-1}}],$$

audits the harmonization against independent NASA products, and projects a **14-day operational burning forecast**.

---

## 2. System architecture

```
FIRMS CSV  ──►  Offline ETL (DuckDB + Arrow/Parquet)
                     │
                     ├─ H3 footprint / PSF diffusion        (backend/core/footprint_h3.py)
                     ├─ Shannon industrial entropy filter   (backend/core/industrial_filter.py)
                     ├─ EQM + GPD left-tail harmonization   (backend/core/eqm_harmonizer.py)
                     ├─ RTS Kalman + cross sensor guard     (backend/core/kalman_rts.py)
                     ├─ von Mises phenology                 (backend/core/von_mises.py)
                     └─ Chow / Wasserstein / R² audit       (backend/core/auditor_stats.py)
                     │
              data/processed/fire_cube.parquet  (≤ 15 ms DuckDB zone-map queries)
                     │
        FastAPI (offline-first, GZip + orjson)  ──►  React + Deck.gl + Canvas mission control
```

- **Storage:** a single ZSTD Parquet cube sorted by `(h3_r4, epoch_day, h3_r7)` so DuckDB Zone Maps skip ~99 % of the file.
- **Transport:** H3 64-bit integers are serialized as 15-character lowercase **hex strings** (`"872830828ffffff"`) because JavaScript `Number` silently truncates above 2⁵³.
- **Frontend:** one WebGL2 context (`Deck.gl` `H3HexagonLayer`) and one 2D `<canvas>` rendering all 26 × 366 = 9,516 calendar cells with `OffscreenCanvas` diagonal hatching.

### 2.1 Interface

The dashboard is a single guided, editorial article that reads top to bottom (no sci-fi cockpit, no sidebar):

- **Explorer** — a case-study tab row (Cerrado/Pantanal, Sierra Nevada, Iberia, Niger Delta) above a light MapLibre basemap with GPU H3 hexagons coloured by a perceptual thermal ramp, industrial gas flaring in sober purple, drag-to-draw AOI boxes, an offline graticule fallback and a 2D/3D toggle.
- **Section 1 — the 2012 problem** — the 26 × 366 burning calendar with a slider comparing raw pixel counts (neutral grey) against harmonized fire energy (thermal ramp), cobalt hatching for reconstructed days and terracotta hatching for the 14-day forecast.
- **Section 2 — season and reconstruction** — the circular von Mises fire-season clock (plain-language decadal drift plus a compact μ / κ / Mann–Kendall table for researchers) and the Kalman uncertainty band chart with a scripted satellite-blackout stress test.
- **Section 3 — impact and audit** — physical impact first (dry biomass, PM2.5, analysed area, a plain-language verdict and an IPCC-ready CSV) followed by a researcher validation table (Chow, Wasserstein, R²) with quiet `[VALIDATED]` / `[BIAS DETECTED]` indicators.

Design language: an institutional paper palette (`#F8F7F4` page, white panels, 1 px `#DCDCDC` rules, 2–4 px radii), **Source Serif 4** for headings, **Inter** for controls and **IBM Plex Mono** for every figure (`tabular-nums`), a ColorBrewer-style thermal ramp (`#FEF0D9 → #B30000`) for fire energy and `#6A3D9A` for industrial flaring. No neon, glassmorphism, gradients, coloured shadows or emoji.

---

## 3. Physics and equations

### 3.1 Off-nadir footprint and elliptical PSF on H3 (`footprint_h3.py`)

MODIS grows from ~1 km at nadir to a **bow-tie** footprint at large scan angles:

$$\eta_{\text{overlap}}(\Delta T)=\min\!\left(1.0,\ \frac{1.0}{\Delta T}\right).$$

Each deformed detection defines a 2D Gaussian with target dimensions $(\Delta S_k,\Delta T_k)$ and orbital azimuth $\alpha \approx 98.2^\circ$:

$$\Sigma_k = R(\alpha)\begin{pmatrix}(\Delta S_k/2.355)^2 & 0\\ 0 & (\Delta T_k/2.355)^2\end{pmatrix}R(\alpha)^\top .$$

Radiative power is distributed across the centre `H3_r7` cell ($A \approx 5.161\ \mathrm{km^2}$) and its 1-ring `grid_disk(h,1)` with normalized Gaussian weights $w_j \propto \exp\!\left(-\tfrac12 (x_j-\mu_k)^\top \Sigma_k^{-1}(x_j-\mu_k)\right)$. Because a VIIRS I-band pixel (≈0.14 km²) is ~36× smaller than an `H3_r7` cell, it maps entirely to its containing cell.

Two-level hierarchical indexing stores the parent `h3_r4` (~1,770 km²) so large polygons are pruned at resolution 4 before refining resolution 7.

### 3.2 Shannon temporal persistence entropy (`industrial_filter.py`)

Gas flares, refineries and steel mills emit year-round. For `H3_r10` cells, with $p_m$ the fraction of annual detections in month $m$:

$$H_{\text{temp}}(h_{10}) = -\frac{1}{\ln 12}\sum_{m=1}^{12} p_m \ln\!\left(p_m + 10^{-12}\right)\in[0,1].$$

Vegetation fires extinguish between seasons ($H_{\text{temp}} < 0.25$); stationary industry persists ($H_{\text{temp}} > 0.75$). Combined with low positional variance and infrared contrast $\Delta T_{4/11}=T_4-T_{11}$, a logistic score `industrial_prob` is produced. A dedicated SAMA / pre-November-2000 filter discards isolated nighttime false alarms over the South Atlantic Magnetic Anomaly.

### 3.3 Censor-aware radiometric harmonization (`eqm_harmonizer.py`)

**Empirical Quantile Mapping** aligns the supra-threshold distributions per biome $c$ and scan-angle bin $\theta$:

$$\hat X_{\text{harm}} = F_{\text{MODIS}|c,\theta}^{-1}\!\left(F_{\text{VIIRS}|c,\theta}(X_{\text{VIIRS}})\right).$$

The **left-tail censorship** caused by MODIS's higher detection threshold is compensated with a Generalized Pareto tail integrated over the sub-threshold interval:

$$\Delta E_{\text{sub}}(\theta,c)=\pi_{\text{sub}}(X_M,\theta,c)\int_{x_{\min}^{V}}^{\tau_M(\theta,c)} x\, f_{\text{GPD}}(x;\xi_c,\sigma_c)\,dx .$$

The lookup is stored in a compact `eqm_gpd_lut.json` (< 150 KB) for zero-latency runtime use.

### 3.4 RTS Kalman smoother + Cross-Sensor Historical Guard + 14-day predictor (`kalman_rts.py`)

Forward pass with spatial contagion and a cross-sensor climatological prior:

$$x_{t\mid t-1}=\phi x_{t-1\mid t-1}+\gamma u_{\text{spatial},t}+\omega_{\text{prior}}\,\mu_{\text{cross}}(d_t),\qquad P_{t\mid t-1}=\phi^2 P_{t-1\mid t-1}+Q_{\text{var}}\,(1+0.8\,C_{\text{cloud},t}),$$

with $\phi=0.68$, $\gamma=0.17$, $\omega_{\text{prior}}=0.15$ and $Q_{\text{var}}=12.0$. The **Cross-Sensor Historical Prior** is a circularly smoothed 26-year kernel expectation over Julian days:

$$\mu_{\text{cross}}(d)=\frac{\sum_{y}\sum_{\tau}K_{\text{circ}}(d,\tau;\sigma_d)\,y_{\text{fused}}(y,\tau)}{\sum_{y}\sum_{\tau}K_{\text{circ}}(d,\tau;\sigma_d)\,\mathbb{I}(\text{observed})}.$$

Updates use the **scalar Joseph form** so the covariance stays strictly positive:

$$S_{t,s}=h_{t,s}^2P_{t\mid t-1}+R_s+10^{-8},\quad K_{t,s}=\frac{P_{t\mid t-1}h_{t,s}}{S_{t,s}},\quad P_{t\mid t}=(1-K_{t,s}h_{t,s})^2P_{t\mid t-1}+K_{t,s}^2R_s .$$

On a **dual-sensor blackout** ($\mathcal{S}_t=\varnothing$, e.g. 100 % cloud) the guard injects a pseudo-observation $y_{\text{guard},t}=0.55\,\mu_{\text{cross}}(d_t)+0.45\,u_{\text{spatial},t}$ with $R_{\text{guard}}=40.0$, so the state never decays to zero.

The RTS backward smoother is

$$G_t=\frac{P_{t\mid t}\phi}{P_{t+1\mid t}+10^{-8}},\qquad \hat x_{t\mid T}=\max\!\left(0,\ x_{t\mid t}+G_t(\hat x_{t+1\mid T}-x_{t+1\mid t})\right),$$

with analytical 95 % intervals $\mathrm{CI}_{95\%}(t)=\hat x_{t\mid T}\pm 1.96\sqrt{P_{t\mid T}}$. Appending $H=14$ future days with `y_obs = NaN` yields the **operational forecast guard**.

The interactive **Chaos Monkey** (`POST /api/chaos-monkey`) drops 25 % of VIIRS and forces a 10-day simultaneous blackout, reporting `naive_rmse`, `kalman_rmse` and the recovered seasonal energy fraction.

### 3.5 Wooster biomass and smoke accounting (`auditor_stats.py`)

Following Wooster et al. (2005) and GFAS ($\beta_{\text{comb}}=0.368\pm0.015\ \mathrm{kg\ dry\ matter\,MJ^{-1}}$):

$$M_{\text{biomass}}(t)=0.368\cdot\hat x_{t\mid T}\cdot A_{\text{AOI}}\ [\mathrm{kg\,d^{-1}}],\qquad E_{\mathrm{PM}_{2.5}}(t)=10^{-3}\,\mathrm{EF}_{\mathrm{PM}_{2.5}}(c)\,M_{\text{biomass}}(t),$$

with $\mathrm{EF}_{\mathrm{PM}_{2.5}}\approx 9.5\ \mathrm{g\,kg^{-1}}$ by biome.

### 3.6 Circular von Mises phenology and decadal drift (`von_mises.py`)

Map Julian day $d$ to $\psi_d=2\pi d/365.25$ and weight by daily harmonized energy $w_{d,y}$:

$$\bar C_y=\frac{\sum_d w_{d,y}\cos\psi_d}{\sum_d w_{d,y}},\quad \bar S_y=\frac{\sum_d w_{d,y}\sin\psi_d}{\sum_d w_{d,y}},\quad \bar R_y=\sqrt{\bar C_y^2+\bar S_y^2}.$$

The peak burning angle is $\hat\mu_y=(\operatorname{atan2}(\bar S_y,\bar C_y)\bmod 2\pi)\cdot 365.25/2\pi$, and the concentration $\hat\kappa_y$ follows the Best & Fisher (1981) approximation. The effective season width is $W_y=\min(365,\ 365.25/\sqrt{\max(0.15,\hat\kappa_y)})$ days. Unwrapping $\{\hat\mu_y\}$ yields the non-parametric **Theil–Sen** decadal drift and the circular **Mann–Kendall** p-value.

### 3.7 Live statistical peer-review (`auditor_stats.py`)

1. **Chow structural-break F-test** at January 2012 — raw counts fail ($p\ll 10^{-3}$), harmonized FRE should not.
2. **Wasserstein-1 distance** $W_1(F_{\text{pre}},F_{\text{post}})=\int_0^\infty |F_{\text{pre}}-F_{\text{post}}|\,dx$ between inter-sensor distributions.
3. **Independent burned-area cross-validation** ($R^2$) against `MCD64A1`.

---

## 4. Data products used

| Product | Role |
| :--- | :--- |
| `MCD14ML` (Terra + Aqua) | 1 km active-fire detections, 2000 → present |
| `VNP14IMG` (Suomi-NPP) | 375 m active-fire detections, 2012 → present |
| `VJ114IMG` (NOAA-20 / NOAA-21) | 375 m gap coverage |
| `MCD12Q1` | 17 IGBP biome classes (EQM / emission factors) |
| `MCD64A1` | independent burned-area validation |

---

## 5. Quick start (one command)

```bash
# from the repository root
make bootstrap && make api        # terminal 1 — synthetic cube + FastAPI on :8000
make frontend                     # terminal 2 — Vite dashboard on :5173
```

`make bootstrap` runs `scripts/00_bootstrap_synthetic_cube.py`, which builds the deterministic
Parquet cube and the `data/mock/mock_analyze_response.json` fixture. No internet is required.

Manual equivalent:

```bash
python3 scripts/00_bootstrap_synthetic_cube.py
python3 -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
cd frontend && npm install && npm run dev
```

The frontend is **offline-first**: if the API is unreachable it falls back to a deterministic
local fixture, so the mission-control dashboard always renders during an airplane-mode demo.

---

## 6. Repository layout

```
backend/
  api/      schemas.py (frozen contract), routes.py, main.py, cache.py
  core/     footprint_h3, industrial_filter, eqm_harmonizer, kalman_rts,
            von_mises, auditor_stats, chaos_monkey
  db/       duckdb_engine, queries, nrt_poller
frontend/
  src/api/        types.ts (frozen contract), client.ts
  src/store/      useAnalysisStore.ts (zustand)
  src/components/ Map/ · Calendar/ · Charts/ · Audit/
  src/App.tsx     mission-control dashboard
scripts/          00_bootstrap_synthetic_cube.py … 05_cli_benchmark.py
data/             processed/fire_cube.parquet, mock/, lookup/
```

---

## 7. API contract

| Endpoint | Method | Purpose |
| :--- | :--- | :--- |
| `/api/analyze` | `POST` | AOI → calendar series, 14-day forecast, phenology, audit metrics, H3 hexagons |
| `/api/chaos-monkey` | `POST` | sabotage simulation → naive vs RTS reconstruction and recovered energy |
| `/api/health` | `GET` | liveness probe |

The Pydantic v2 models in `backend/api/schemas.py` and the TypeScript interfaces in
`frontend/src/api/types.ts` are **frozen** and mirrored one-to-one.

---

## 8. Validation and reproducibility

```bash
make test        # cube schema, math core and API contract suites
make check-all   # sync agent rules + tests + frontend type check
```

Honest reporting is a project requirement. The dashboard distinguishes measured statistics
from synthetic fixtures, and the audit panel renders the actual p-values rather than a
pre-baked verdict.

---

## 9. References

**NASA / science**

- Giglio, L., Schroeder, W., & Justice, C. O. (2016). *The Collection 6 MODIS active fire detection algorithm and fire products.* Remote Sensing of Environment, 178, 31–41.
- Schroeder, W., Oliva, P., Giglio, L., & Csiszar, I. A. (2014). *The New VIIRS 375 m active fire detection data product.* Remote Sensing of Environment, 143, 85–96.
- Wooster, M. J., Roberts, G., Perry, G. L. W., & Kaufman, Y. J. (2005). *Retrieval of biomass combustion rates and totals from fire radiative power observations.* Journal of Geophysical Research, 110, D24311.
- Kaiser, J. W., et al. (2012). *Biomass burning emissions estimated with a global fire assimilation system (GFAS).* Biogeosciences, 9, 527–554.
- Fisher, N. I. (1993). *Statistical Analysis of Circular Data.* Cambridge University Press.
- Mardia, K. V., & Jupp, P. E. (2000). *Directional Statistics.* Wiley.
- Best, D. J., & Fisher, N. I. (1981). *The bias of the maximum likelihood estimators of the von Mises–Fisher concentration parameters.* Communications in Statistics.
- Chow, G. C. (1960). *Tests of equality between sets of coefficients in two linear regressions.* Econometrica, 28(3), 591–605.
- Sen, P. K. (1968). *Estimates of the regression coefficient based on Kendall's tau.* JASA, 63, 1379–1389.
- Mann, H. B. (1945). *Nonparametric tests against trend.* Econometrica, 13, 245–259.
- NASA FIRMS — Fire Information for Resource Management System: <https://firms.modaps.eosdis.nasa.gov/>
- NASA Earthdata: <https://www.earthdata.nasa.gov/>
- Uber H3 geospatial indexing system: <https://h3geo.org/>

**Open-source libraries**

- DuckDB — in-process analytical SQL: <https://duckdb.org/>
- Apache Arrow / PyArrow — columnar memory format: <https://arrow.apache.org/>
- FastAPI — async Python API framework: <https://fastapi.tiangolo.com/>
- Pydantic v2 — data validation: <https://docs.pydantic.dev/>
- SciPy / NumPy — statistics and linear algebra: <https://scipy.org/>
- React — UI library: <https://react.dev/>
- Zustand — minimal state management: <https://zustand.docs.pmnd.rs/>
- Deck.gl — GPU geospatial visualization: <https://deck.gl/>
- MapLibre GL JS / react-map-gl — maps: <https://maplibre.org/>
- Vite — frontend build tool: <https://vitejs.dev/>
- Tailwind CSS — utility styling: <https://tailwindcss.com/>
- Lucide — icon set: <https://lucide.dev/>

---

## 10. Team and file ownership

| Role | Ownership |
| :--- | :--- |
| **Adam** — Math & Physics Core | `backend/api/schemas.py`, `backend/core/*`, `backend/tests/test_math_core.py` |
| **Mohammed** — Frontend map, store & calendar | `frontend/src/api/*`, `frontend/src/store/*`, `frontend/src/components/Map/*`, `frontend/src/components/Calendar/*` |
| **Antonio** — DuckDB engine & FastAPI | `backend/db/*`, `backend/api/routes.py`, `backend/api/main.py`, `backend/tests/test_api_contract.py` |
| **Germán** — Offline ETL | `scripts/*`, `backend/tests/test_cube_schema.py` |
| **Migue** — Scientific charts, audit & pitch | `frontend/src/components/Charts/*`, `frontend/src/components/Audit/*`, `frontend/src/App.tsx`, `frontend/src/main.tsx`, `README.md` |

All UI copy, audit verdicts and documentation are in **English** for global judging eligibility.

---

## 11. License

Released for the NASA Space Apps Challenge 2026 under the MIT License. NASA data products
remain subject to their respective NASA Earthdata terms of use.
