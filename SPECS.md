# FIRMS-HARMONIZER: Technical, Physico-Mathematical & Interface Specification (36h War Plan)

- **Challenge:** NASA Space Apps Challenge 2026 — *Harmonization of MODIS and VIIRS Hot Spots*
- **Target Global Awards:** *Best Use of Science*, *Best Use of Data*, *Best Use of Technology*, *Galactic Impact*
- **Core Objective:** Analyze and harmonize sampled fire-energy observations from MODIS and VIIRS, with explicit observation coverage, physical unit checks and conditional scientific publication gates.

---

## 1. Current scope and acceptance (2026-11-15)

This section supersedes the original judging/pitch claims. The product analyses sampled fire-energy proxies for Chilecito, Iberia, Orlando and Amazonas/Manaus. It does not promise real-time incident prediction, full observation coverage, passing diagnostic thresholds, independently validated emissions, or a particular query latency without measured evidence.

The user-authorized `all-nighter` remediation coordinates changes across all ownership tracks. Public schema changes are recorded in `firms-harmonizer/CAMBIOS.md` and mirrored in TypeScript. Scientific correctness takes precedence over preserving obsolete frozen-test expectations; revised tests retain the original physical/robustness gates.

Canonical energy is `E(t) = sum_h(mean_available_s(FRE[h,t,s]) * exact_cell_area[h])`. Polygon-normalized density is `E(t) / WGS84_polygon_area`. Regional mean-active-cell density must never be multiplied by a historical union of burning-cell areas. The available-sensor fusion occurs inside each cell before summation.

Detection absence, clear observed zero, cloud/unprocessed coverage, confirmed outage and forecast are distinct. Unknown dates are not automatically reconstructed. Only explicit observation-gap evidence permits reconstruction. The actual archive range bounds history; future values belong only in the forecast series. November/December 2000 is queryable. Partial calendar years do not enter the Chow annual regression, Wasserstein era comparison or phenology trend.

Coverage policy update (2026-11-15): the fixed requirement of 95% complete whole-region days is replaced by temporal selection among 70/80/90/95% terrestrial support thresholds. Coverage is an exact-H3-area-weighted union of qualified cells across sensors, weighted by preceding-year measured land/water pixel fractions. Unknown land/water area remains potential unobserved land in the denominator; entirely missing land classifications remain unavailable. Legacy packed masks retain their >=95% valid-sample cell qualification and >=50% sampled-area screen. Consequently this is a sampled qualified-cell support proxy, not a pixel-exact measurement of observed terrestrial area. Historical observed-zero semantics remain conservative and unchanged.

The comparison computes coverage over the six most recent years, preserving at least three training years and two separate evaluation years. Tied selection scores prefer the higher coverage threshold. Selection uses the penultimate year of monthly rolling origins after at least three training years. The final year is reserved for validation of the single chosen threshold; failure does not trigger selection of a different candidate. All candidates use high-support (>=95%) origins and labels, never cloudy zeros. Reports include 1/7/14-day MAE, persistence/climatology baselines, signed bias, nominal-95% interval coverage and seasonal representation. Publication still requires >=12 cases per horizon, all four seasonal groups, MAE no worse than either baseline, and >=90% interval coverage in both selection and holdout. No qualifying candidate means null plus an explicit reason. These tests validate the sampled thermal proxy, not independently measured physical energy. No missing energy is upscaled by dividing by coverage.

Run `python scripts/13_validate_coverage.py` to atomically publish matching `land_*.npz` preset indexes and `coverage-policy.json`. Arbitrary AOIs without a matching published index retain an unavailable forecast. Incomplete support or a weak reserved-year result must keep publication blocked.


`confidence_level` means minimum detection confidence: low includes all accepted levels; nominal includes nominal/high; high includes high only. The ETL publishes separate confidence cubes and the API rejects an unavailable threshold explicitly.

PM2.5 requires measured annual MCD12Q1 classes and supported fuel-factor mappings. Andreae (2019) Table 1 field factors (g/kg dry matter) are savanna/grassland 6.7 (SD 3.3), tropical forest 8.3 (3.3), temperate forest 18.5 (14.4), boreal forest 18.7 (15.9), open agricultural residue 8.2 (4.4). IGBP 8–10 maps to savanna/grassland; 12 to agricultural residue; 1–5 to forest by latitude (tropical <=23.5°, boreal >=50°, otherwise temperate). Other fuels, mixed/unknown classes and missing years remain unsupported. This mapping is a fuel proxy, not direct fuel measurement. Daily factor SD preserves common fuel-factor correlation and includes the 0.015 kg/MJ biomass-factor SD, but excludes observation/integration bias. Reconstructed or unsupported emissions remain null.

Observation-mask summaries use each product's actual daily-band dates. Public MODIS 1 km masks cannot establish VIIRS coverage or absence of sub-threshold fire. An observed zero requires one sensor covering the entire requested R7 set, >=95% valid sampled pixels in each cell, >=50% cell-area-equivalent samples, no mask fire pixels, and no accepted FIRMS detection. Missing masks stay unknown. Summaries are bit-packed; complete preset indexes are atomically published.

Industrial filtering requires a published upstream flare site-year within 1 km and temporal persistence. The positional screen uses a 1 km dispersion scale instead of seven metres. Published-site matching is not an independently calibrated classifier, and no-match does not establish no industrial heat. EOG excludes refinery/LNG sources from this reference.

Chaos Monkey excludes the target year from historical calibration and prior fitting, removes spatial forcing contaminated by previously hidden observations, and scores only actually affected days against an intact-input model reference. Recovery may exceed 100%; no sabotage produces zero RMSE and the defined 100% control.

Request limits: 512 positions total, 16 rings, 1,250,000 km^2 geodesic preflight, 250,000 R7 cells, 6,000-character questions, ten conversation turns, 256 KiB request bodies, four analytical workers, 30 analytical requests/minute/client and ten Copilot requests/minute/client. Analysis cache: 64 entries and 128 MiB. Extra CORS origins require explicit configuration. Observations default to 366 dates/page, maximum 1,000.

Sources: [NASA MODIS Fire Guide](https://www.earthdata.nasa.gov/s3fs-public/2023-09/MODIS_C6_C6.1_Fire_User_Guide_1.0.pdf), [NASA VIIRS Fire Guide](https://www.earthdata.nasa.gov/s3fs-public/2024-07/VIIRS_C2_AF-375m_User_Guide_1.0.pdf), [MCD64A1 fields and QA](https://ladsweb.modaps.eosdis.nasa.gov/filespec/MODIS/61/MCD64A1), [Andreae 2019](https://doi.org/10.5194/acp-19-8523-2019), [EOG MYC25Q4](https://doi.org/10.5281/zenodo.23091822).

The remaining derivation records the original physics model; this current-scope section and executable contracts take precedence over historical performance/pitch claims below.

---

## 2. Firefighters & Tactical Brigades *(Bomberos y brigadas forestales de extinción: INFOCA en Andalucía, UME, Wildland Firefighters)*
- **Core Needs:** Clear operational view of active flame fronts without sensor duplication; resilient decision-support tools that function offline in remote mountainous areas.
- **How ALMENARA Solves It:**
  - **Bow-Tie De-duplication & Spatial Contagion:** Deformed off-nadir MODIS pixels ($4.8 \times 2.0\text{ km}$) are geometrically diffused across Uber H3 hexagons, preventing false double-counting of flame fronts.
  - **100% Airplane Mode Capability:** Entire backend and frontend run locally on field laptops without internet connectivity (<15 ms response time).
  - **Tactical Hotspot Feed (`/api/observations`):** Direct inspection of deduplicated active detection centers, sensor platforms, and raw FRP.
  - **One-Click Tactical CSV Export:** Standardized tabular export formatted for direct import into wildland fire simulation software.

#### 3. Scientists & Climate Researchers *(Científicos e investigadores: Climatología, Ciclo del Carbono, Ecología del Fuego)*
- **Core Needs:** Unbroken, statistically stationary multi-decadal time series without instrument artifacts; verifiable proof of cross-sensor calibration.
- **How ALMENARA Solves It:**
  - **Harmonized Climate Record (2000–2026):** Fuses MODIS Terra/Aqua ($1\text{ km}$) and VIIRS SNPP/NOAA-20/21 ($375\text{ m}$) into a continuous physical energy density metric ($\text{MJ}\cdot\text{km}^{-2}\cdot\text{day}^{-1}$).
  - **Elimination of the 2012 Discontinuity:** Proves stationarity via the **Chow Structural Break Test** ($p > 0.10$ vs. raw $p < 10^{-12}$) and $>88\%$ reduction in Wasserstein-1 distributional distance.
  - **Independent Ground Truth Validation:** Correlated against `MCD64A1` 500 m Burned Area scars ($R^2 > 0.90$).
  - **Rigorous Uncertainty Bounds:** $95\%$ analytical confidence intervals on daily energy estimates via Joseph-stabilized Kalman covariance.

#### 4. Land & Environmental Managers *(Gestores del territorio y medioambientales: Ingenieros forestales, responsables de parques naturales, gestión agrícola)*
- **Core Needs:** Understand how climate change is altering local fire seasons; separate industrial emissions (gas flaring, refineries) from genuine ecological fires.
- **How ALMENARA Solves It:**
  - **Circular von Mises Phenology Clock:** Tracks how the fire season peak ($\hat{\mu}_y$) and duration ($W_y$) are drifting over 26 years via the non-parametric Theil-Sen slope (measured in days shifted per decade).
  - **Shannon Temporal Entropy Industrial Filter ($H_{\text{temp}} > 0.75$):** Decouples year-round stationary industrial heat sources (oil gas flaring, power plants) from seasonal biomass fires.
  - **Biome-Specific Fuel Stratification:** Incorporates 17 IGBP land cover classes (`MCD12Q1`) for precise territorial accounting.

---

### 1.4 Pitch & Presentation Strategy (30s Video & 7-Slide Deck)

NASA Space Apps judging restricts web presentations to a **maximum of 7 slides** or a **30-second video demo**. FIRMS-Harmonizer provides ready-to-deliver blueprints for both formats:

#### A. 30-Second Elevator Pitch Video Script (Word-for-Word Storyboard)

| Timestamp | Visual Cue on Screen | Spoken Voiceover Script (English) | Focus Criterion |
| :---: | :--- | :--- | :--- |
| **00:00 – 00:07** | Camera zooms into the 2012 transition in the Burning Calendar: raw count jumps $+420\%$ in red. | *"In 2012, NASA upgraded satellite fire sensors from MODIS to VIIRS. The result? A fake 400% surge in raw detections that distorts 26 years of global fire records."* | **Relevance & Problem Hook** |
| **00:07 – 00:15** | User slides the **2012 Split-Screen Curtain**; the false jump flattens into continuous harmonized FRE. | *"Meet ALMENARA FIRMS-Harmonizer. We fuse 5 NASA products into a continuous physical energy metric, eliminating sensor bias with a stochastic RTS Kalman filter."* | **Creativity & Science** |
| **00:15 – 00:23** | User clicks **Chaos Monkey**: a 10-day satellite blackout is simulated, and the amber prior recovers 95% of energy. | *"Even during total satellite blackouts or cloud cover, our Cross-Sensor Historical Guard reconstructs lost observations with 95% accuracy in under 15 milliseconds."* | **Validity & Technology** |
| **00:23 – 00:30** | Transition to the **Circular Phenology Clock** showing +15 days/decade shift, followed by the 4 personas banner. | *"From Spanish INFOCA firefighters to IPCC climate scientists: 26 years of unified NASA data protecting our future. 100% offline. Mission ready."* | **Impact & Call to Action** |

---

#### B. 7-Slide Official Space Apps Presentation Deck Blueprint

```
┌────────────────────────────────────────────────────────────────────────┐
│ SLIDE 1: Title & Galactic Vision                                       │
│ • ALMENARA — FIRMS Harmonizer: 26 Years of NASA Fire Telemetry Unified │
│ • Mission: Turning noisy satellite hotspots into a continuous, audited │
│   physical energy record and 14-day early warning for planet Earth.    │
│ • Target Awards: Best Use of Science | Best Use of Data                │
├────────────────────────────────────────────────────────────────────────┤
│ SLIDE 2: The Core Challenge (The 2012 Sensor Discontinuity)            │
│ • The Dilemma: 1 km MODIS (2000) vs 375 m VIIRS (2012).                │
│ • The Illusion: Raw fire counts jump +420% in 2012, corrupting climate │
│   trends, firefighting resource planning, and emissions reporting.    │
│ • Visual: Graphic comparing raw pixel counts vs reality.               │
├────────────────────────────────────────────────────────────────────────┤
│ SLIDE 3: The Physico-Mathematical Solution                             │
│ • 5 NASA Products Unified: MCD14ML, VNP14IMG, VJ114IMG, MCD12Q1, MCD64A1│
│ • Core Innovation: Off-nadir elliptical PSF on H3, Empirical Quantile   │
│   Mapping (EQM) with Pareto tail, & RTS Kalman Smoother.               │
│ • The Guard: Climatological Cross-Sensor Prior prevents blackout decay.│
├────────────────────────────────────────────────────────────────────────┤
│ SLIDE 4: Interactive Mission Control Platform (Live Capabilities)      │
│ • 2D Canvas Burning Calendar: 9,516 days rendered at 60 FPS.           │
│ • Interactive 2012 Time-Machine Split Curtain.                         │
│ • Freehand AOI Drawing on GPU Hexagon Map (Uber H3 Res 7).             │
│ • Live Chaos Monkey Sabotage Stress-Test on stage.                     │
├────────────────────────────────────────────────────────────────────────┤
│ SLIDE 5: Four Stakeholders, One Source of Truth                        │
│ • Firefighters (INFOCA): Tactical flame front contagion & 1-click CSV. │
│ • Emergency Responders (112): PM2.5 smoke warnings & 14-day risk.      │
│ • Scientists (IPCC): Continuous 26-year time series & carbon metrics.  │
│ • Land Managers: Circular phenological season drift (days/decade).     │
├────────────────────────────────────────────────────────────────────────┤
│ SLIDE 6: Scientific Peer-Review & Real-Time Validation                 │
│ • Chow Structural Break F-Test: Passes 2012 gate (p > 0.10 vs raw 1e-12)│
│ • Wasserstein Distance: >88% reduction in cross-sensor divergence.     │
│ • Independent Validation: R² > 0.90 against MCD64A1 burned area scars. │
│ • Performance: <15 ms query latency, 100% offline (Airplane Mode).     │
├────────────────────────────────────────────────────────────────────────┤
│ SLIDE 7: Galactic Impact & Open Science Future                         │
│ • Global Scalability: Ready to process planet-wide FIRMS archives.     │
│ • Open Data & Standards: DuckDB + Parquet + OGC/GeoJSON compliance.    │
│ • Conclusion: Restoring 26 years of climate memory to protect lives.   │
└────────────────────────────────────────────────────────────────────────┘
```

---

---

## 2. 36-Hour Feasibility Architecture Decisions (Lead Chief Directives)

1. **[APPROVED IN FULL] RTS Kalman Smoother + Cross-Sensor Historical Guard + 14d Predictor:** Core scientific differentiator. Executes live in $1.4\text{ ms}$ in NumPy over the spatially aggregated Area of Interest (AOI) vector ($T \le 9,500$ days).
2. **[APPROVED IN FULL] Live Statistical Audit Engine (Chow Test 2012, Wasserstein $W_1$, $R^2$ vs. `MCD64A1`) & Circular von Mises Clock:** Direct vectorized NumPy/SciPy implementation guaranteeing *Best Use of Science*.
3. **[APPROVED IN FULL] Shannon Temporal Entropy Industrial Decoupling ($H_{\text{temp}} > 0.75$) & Infrared Contrast:** Precomputed in the offline ETL via a single DuckDB `GROUP BY h3_r10` aggregation and toggled live in the UI.
4. **[APPROVED & EXPANDED] Wooster Physical Biomass & Smoke Emissions Conversion:** Direct thermodynamic conversion ($\beta_{\text{comb}} = 0.368\text{ kg}\cdot\text{MJ}^{-1}$) stratified by `MCD12Q1` biome emission factors with zero extra latency.
5. **[SMART SIMPLIFICATION] Off-Nadir Elliptical PSF & Bow-Tie Overlap Suppression:** Since a VIIRS I-band pixel ($375\text{ m}$, $A \approx 0.14\text{ km}^2$) is $36\times$ smaller than an `H3_r7` hexagon ($5.161\text{ km}^2$), $100\%$ of its energy maps to its containing cell. Only off-nadir MODIS edge pixels ($\Delta S > 2.0\text{ km}$, where footprint grows to $4.8 \times 2.0\text{ km}$) undergo discrete Gaussian diffusion across the center `H3_r7` cell and its 1-ring `grid_disk(h, 1)` plus inter-scan overlap discounting.
6. **[SMART SIMPLIFICATION] Kinetic De-duplication & Diurnal Integration:** Eulerian daily integration per `H3_r7` cell weighted by the sensor diurnal curve $\kappa(\tau_s)$, capturing flame front spatial propagation via `neighbor_fre_lag1` ($\sum_{j \in \mathcal{N}(h)} w_{hj} x_{j,t-1}$) fed directly into the RTS Kalman Smoother.
7. **[DISCARDED & REPLACED] Manual Binary Apache Arrow IPC Web Worker Decoder:** Splitting 64-bit integers into `uint32` pairs in Web Workers is a high-risk debugging trap in a 36h hackathon. Replaced with `GZipMiddleware` + `orjson` responses serializing H3 indices as 15-character lowercase hexadecimal strings (`"872830828ffffff"`). A 5,000-hexagon payload is $< 90\text{ KB}$, transfers in $3\text{ ms}$, and binds directly to Deck.gl `H3HexagonLayer` at 60 FPS.

---

## 3. Physico-Mathematical Specification of the 7 System Modules

### 3.1 Module 1: Off-Nadir Spatial & Geometric Harmonization on Uber H3 (`footprint_h3.py`)
- **Physical Problem:** MODIS (`MCD14ML`) has a $1.0 \times 1.0\text{ km}$ nadir footprint that deforms at $\pm 55^\circ$ scan angles up to $\Delta S \approx 4.8\text{ km}$ (along-scan) by $\Delta T \approx 2.0\text{ km}$ (along-track), causing inter-scan *bow-tie* duplicate detections. VIIRS I-Band ($375\text{ m}$) uses on-board pixel aggregation across 3 scan zones ($3\times 1$ for $0^\circ \le \theta < 31.72^\circ$; $2\times 1$ for $31.72^\circ \le \theta < 44.86^\circ$; $1\times 1$ for $44.86^\circ \le \theta \le 56.28^\circ$), keeping footprints $\le 0.75\text{ km}$.
- **Equations Implemented:**
  1. **MODIS Inter-Scan Bow-Tie Overlap Correction:** For along-track pixel size $\Delta T > 1.35\text{ km}$:
     $$\eta_{\text{overlap}}(\Delta T) = \min\left(1.0,\, \frac{1.0}{\Delta T}\right)$$
  2. **Elliptical Gaussian PSF Diffusion on `H3_r7`:** Each detection $k$ at $(\phi_k, \lambda_k)$ with dimensions $(\Delta S_k, \Delta T_k)$ and orbital azimuth $\alpha \approx 98.2^\circ$ defines a 2D Gaussian $\mathcal{N}(\mu_k, \Sigma_k)$:
     $$\Sigma_k = R(\alpha)\begin{pmatrix} (\Delta S_k / 2.355)^2 & 0 \\ 0 & (\Delta T_k / 2.355)^2 \end{pmatrix} R(\alpha)^\top$$
     For deformed footprints ($A_k = \Delta S_k \cdot \Delta T_k > 3.5\text{ km}^2$), radiative power is distributed across the center cell $h_0 \in \mathcal{H}_7$ ($A_{\text{H3}_7} = 5.161\text{ km}^2$) and its 6 neighbors $h_j \in \text{grid\_disk}(h_0, 1)$ with normalized Gaussian weights $w_j \propto \exp\left(-\frac{1}{2}(x_j - \mu_k)^\top \Sigma_k^{-1}(x_j - \mu_k)\right)$.
  3. **Two-Level Hierarchical Indexing (`h3_r4` $\to$ `h3_r7`):** Every record stores its parent cell `h3_r4` ($\approx 1,770\text{ km}^2$). Sorting the Parquet file by `(h3_r4 ASC, epoch_day ASC, h3_r7 ASC)` enables DuckDB Zone Maps to skip $99.4\%$ of the file on disk.

### 3.2 Module 2: Shannon Entropic Industrial Filter, IR Contrast & SAMA Filter (`industrial_filter.py`)
- **Physical Problem:** VIIRS $375\text{ m}$ channel I4 ($3.74\text{ }\mu\text{m}$) detects thousands of stationary industrial heat sources (oil gas flaring, steel mills, refineries). Over South America and the South Atlantic, the **South Atlantic Magnetic Anomaly (SAMA)** bombards detectors with energetic protons, causing spurious nighttime false alarms.
- **Equations Implemented:**
  1. **Shannon Temporal Persistence Entropy ($H_{\text{temp}}$) at `H3_r10` ($\approx 15,000\text{ m}^2$):** Across $M = 12$ calendar months, let $p_m$ be the fraction of annual detections in month $m \in \{1,\dots,12\}$:
     $$H_{\text{temp}}(h_{10}) = -\frac{1}{\ln(12)} \sum_{m=1}^{12} p_m \ln(p_m + 10^{-12}) \in [0, 1]$$
     Vegetation fires consume fuel and extinguish ($H_{\text{temp}} < 0.25$); industrial gas flares emit year-round across wet and dry seasons ($H_{\text{temp}} > 0.75$).
  2. **Infrared Brightness Temperature Contrast ($\Delta T_{4/11}$):**
     $$\Delta T_{4/11} = T_4 - T_{11}$$
     Combining $H_{\text{temp}} > 0.75$ with low positional variance ($\sigma_{\text{pos}}^2 < 50\text{ m}^2$) produces `industrial_prob` $\in [0, 1]$ via a logistic sigmoid centered at $H_0 = 0.72$.
  3. **SAMA & Pre-Nov 2000 Filter:** Automatically discards isolated nighttime (`daynight == 'N'`) low-confidence detections inside $(15^\circ\text{S}\text{–}35^\circ\text{S},\, 30^\circ\text{W}\text{–}65^\circ\text{W})$ with background thermal contrast $\Delta T_{11} < 1.5\text{ K}$, as well as corrupted MODIS Terra records prior to `2000-11-01`.

### 3.3 Module 3: Censor-Aware Radiometric Harmonization (`eqm_harmonizer.py`)
- **Physical Problem:** MODIS minimum detection threshold is $\text{FRP}_{\min}^{\text{MODIS}} \approx 8.0\text{ MW}$, whereas VIIRS detects fires down to $\text{FRP}_{\min}^{\text{VIIRS}} \approx 0.5\text{ MW}$.
- **Equations Implemented:** Trained on the 2012–2025 overlap between afternoon MODIS Aqua and VIIRS SNPP ($\sim 13\text{:}30\text{ LT}$), stratified by 17 IGBP biomes ($c \in \{1,\dots,17\}$ from `MCD12Q1`) and 10 scan angle bins $\theta$:
  1. **Empirical Quantile Mapping (EQM) for Supra-Threshold Regime:**
     $$\hat{X}_{\text{harm}} = F_{\text{MODIS}|c,\theta}^{-1}\left(F_{\text{VIIRS}|c,\theta}(X_{\text{VIIRS}})\right)$$
  2. **Left-Tail Censorship Compensation via Generalized Pareto Distribution (GPD):** Compensates energy omitted by MODIS pre-2012 in the sub-threshold interval $[x_{\min}^V, \tau_M(\theta, c)]$:
     $$\Delta E_{\text{sub}}(\theta, c) = \pi_{\text{sub}}(X_M, \theta, c) \int_{x_{\min}^V}^{\tau_M(\theta, c)} x \, f_{\text{GPD}}(x; \xi_c, \sigma_c)\, dx$$
     Stored in `data/lookup/eqm_gpd_lut.json` ($< 150\text{ KB}$). Here $\pi_{\text{sub}}$ is the share of matched VIIRS cell-days in $[0.5, 8)\text{ MW}$ and the integral uses the GPD truncated to that interval, so $\Delta E_{\text{sub}} = \pi_{\text{sub}} \cdot \mathbb{E}_{\text{GPD}}[x \mid 0.5 \le x < 8]$.
  3. **Application rule (common scale):** Both channels are placed on the sub-threshold-compensated MODIS scale, using daily cell-day power sums before FRE scaling: $\hat{X}_{\text{VIIRS}} = F_{\text{MODIS}}^{-1}(F_{\text{VIIRS}}(X_{\text{VIIRS}})) + \Delta E_{\text{sub}}$ over the full VIIRS distribution (101 empirical knots, endpoint-clamped), and $\hat{X}_{\text{MODIS}} = X_{\text{MODIS}} + \Delta E_{\text{sub}}$ for every detected MODIS cell-day in every year (MODIS omits sub-threshold fires after 2012 too). Zeros and missing values are preserved. The ETL delegates training and application to `RadiometricHarmonizer` (`fit_biome_eqm_gpd`, `harmonize_viirs_to_modis`, `compensate_modis_censoring`); there is no second implementation.

### 3.4 Module 4: Multi-Satellite RTS Kalman Smoother + Cross-Sensor Historical Guard + 14-Day Predictor (`kalman_rts.py` & `chaos_monkey.py`)
- **Physical & Operational Problem:** Daily satellite series suffer from: (1) **Single-Sensor Outages** (e.g., the *Suomi NPP VIIRS* outage from July 27 to August 10, 2022: 15 days with zero global FIRMS detections, measured in `data/lookup/global_daily_counts.csv`, while Aqua, Terra and NOAA-20 stayed nominal. The earlier "MODIS Aqua Safe Mode, July 31 to August 16, 2022" is contradicted by the FIRMS archive and is not applied to real data); (2) **Dual-Sensor Blackouts / Total Cloud Occlusion** ($C_{\text{cloud}} > 80\%$), where standard autoregressive filters ($x_t = \phi x_{t-1}$) decay exponentially to zero ($\phi^k \to 0$); and (3) **Latitudinal Orbital Revisit Bias**: the daily revisit density grows toward the poles as $\pi_{\text{orb}}(\phi_h) \propto \sec(\phi_h) = 1/\cos(\phi_h)$.
- **Equations Implemented:**
  1. **Horvitz-Thompson Orbital Weighting & Diurnal Scaling:** Morning MODIS Terra observations ($10\text{:}30\text{ LT}$) are scaled to the afternoon thermal peak ($13\text{:}30\text{ LT}$ of Aqua/VIIRS) via $\kappa(\tau_s) = \text{FRP}_{13:30} / \text{FRP}_{10:30}$. All sensor energies are then weighted by the **inverse** of the relative orbital sampling probability (resolved 2026-11-14; the weight is $\cos(\phi_h)$, not $\sec(\phi_h)$):
     - *Revisit model.* For sun-synchronous polar orbiters ($i \approx 98.2^\circ$), swath convergence makes the daily revisit density at H3 R7 centroid latitude $\phi_h$
       $$\pi_{\text{orb}}(\phi_h) = \pi_{\text{orb}}(0^\circ) \cdot \sec(\phi_h) = \frac{\pi_{\text{orb}}(0^\circ)}{\cos(\phi_h)}$$
     - *Horvitz-Thompson inverse weight.* $\widehat{\text{FRE}}_{\text{HT}} = \text{FRE}_{\text{unweighted}} \,/\, \left(\pi_{\text{orb}}(\phi_h) / \pi_{\text{orb}}(0^\circ)\right)$, so the normalized weight is proportional to $\cos(\phi_h)$:
       $$w_{\text{orb}}(\phi_h) = \text{clip}\left(\cos(\phi_h),\ \cos(80^\circ),\ 1.0\right) \in [0.173648,\ 1.0]$$
     - *Normalization and domain.* $w_{\text{orb}}(0^\circ) = 1.0$ at the equator. The model applies over the sun-synchronous latitude domain $\phi_h \in [-81.8^\circ, +81.8^\circ]$; the lower clamp at $\cos(80^\circ) \approx 0.173648$ bounds the weight near the poles. $\phi_h$ is the centroid latitude `h3.cell_to_latlng(h3_r7)[0]`.
     - *Single application and orthogonality.* $w_{\text{orb}}$ is applied **exactly once**, offline in Stage 04 (`scripts/04_build_master_cube.py`), to `obs_terra_fre`, `obs_aqua_fre` and `obs_viirs_fre`; `neighbor_fre_lag1` inherits it from those channels and is not re-weighted. Query-time and core code never re-apply it. $\kappa$ remains a separate multiplicative factor on Terra only:
       $$\text{obs\_terra\_fre}(h,t) = \frac{\text{FRP}_{\text{Terra}}(h,t) \cdot 3600}{A_{\text{cell}}(h)} \cdot \kappa(\text{h3\_r4}, \text{month}) \cdot w_{\text{orb}}(\phi_h)$$
       $$\text{obs\_aqua\_fre}(h,t) = \frac{\text{FRP}_{\text{Aqua}}(h,t) \cdot 3600}{A_{\text{cell}}(h)} \cdot w_{\text{orb}}(\phi_h), \qquad \text{obs\_viirs\_fre}(h,t) = \frac{\text{FRP}_{\text{VIIRS,harm}}(h,t) \cdot 3600}{A_{\text{cell}}(h)} \cdot w_{\text{orb}}(\phi_h)$$
  2. **Cross-Sensor Historical Prior $\mu_{\text{cross}}(h, d)$:** Using all 26 years of inter-calibrated MODIS+VIIRS observations, for each Julian day $d \in [1, 366]$ we compute a circularly smoothed Gaussian kernel expectation ($\sigma_d = 5$ days over the ring $[1, 366]$):
     $$\mu_{\text{cross}}(d) = \frac{\sum_{y=2001}^{2026} \sum_{\tau=1}^{366} K_{\text{circ}}(d, \tau; \sigma_d)\, y_{\text{fused}}(y, \tau)}{\sum_{y=2001}^{2026} \sum_{\tau=1}^{366} K_{\text{circ}}(d, \tau; \sigma_d)\, \mathbb{I}(y_{\text{fused}}(y, \tau) \text{ observed})}$$
  3. **Forward Kalman Pass with Spatial Contagion & Dual-Sensor Blackout Guard:**
     $$x_{t|t-1} = \phi x_{t-1|t-1} + \gamma u_{\text{spatial}, t} + \omega_{\text{prior}} \mu_{\text{cross}}(d_t)$$
     $$P_{t|t-1} = \phi^2 P_{t-1|t-1} + Q_{\text{var}} \cdot (1 + 0.8 C_{\text{cloud}, t})$$
     where $\phi = 0.68$, $\gamma = 0.17$, $\omega_{\text{prior}} = 0.15$ ($\phi + \gamma + \omega_{\text{prior}} = 1.0$), and $Q_{\text{var}} = 12.0$.
     - **Case A (At least one active sensor $s \in \mathcal{S}_t$, `not np.isnan(y_obs[t, s])`):** Sequential update using the **scalar Joseph form** (guaranteeing $P_{t|t} > 0$ strictly):
       $$S_{t,s} = h_{t,s}^2 P_{t|t-1} + R_s + 10^{-8}, \quad K_{t,s} = \frac{P_{t|t-1} h_{t,s}}{S_{t,s}}$$
       $$x_{t|t} = x_{t|t-1} + K_{t,s}(y_{t,s} - h_{t,s} x_{t|t-1}), \quad P_{t|t} = (1 - K_{t,s} h_{t,s})^2 P_{t|t-1} + K_{t,s}^2 R_s$$
     - **Case B (Dual-Sensor Blackout / 100% Clouds, $\mathcal{S}_t = \emptyset$ on historical day $t$):** Activates the **Cross-Sensor Historical Guard** by injecting a pseudo-observation $y_{\text{guard}, t} = 0.55 \mu_{\text{cross}}(d_t) + 0.45 u_{\text{spatial}, t}$ with high instrumental variance $R_{\text{guard}} = 40.0$ via the Joseph form. The state never collapses to zero while uncertainty bands widen realistically.
  4. **Rauch-Tung-Striebel (RTS) Backward Smoother Pass ($t = T-1,\dots,0$):**
     $$G_t = \frac{P_{t|t} \phi}{P_{t+1|t} + 10^{-8}}$$
     $$\hat{x}_{t|T} = \max\left(0,\, x_{t|t} + G_t(\hat{x}_{t+1|T} - x_{t+1|t})\right)$$
     $$P_{t|T} = \max\left(10^{-4},\, P_{t|t} + G_t^2(P_{t+1|T} - P_{t+1|t})\right)$$
     $$\text{CI}_{95\%}(t) = \left[\max\left(0, \hat{x}_{t|T} - 1.96\sqrt{P_{t|T}}\right),\, \hat{x}_{t|T} + 1.96\sqrt{P_{t|T}}\right]$$
  5. **14-Day Operational Forecast Guard** *(out of the current MVP: the API returns `forecast_series: null` until it is implemented)*: Appending $H = 14$ future days with `y_obs = NaN` projects a 2-week probabilistic burning forecast anchored by $\mu_{\text{cross}}(d_{T+k})$ and $\pm 1.96\sqrt{P_{T+k|T}}$.
  6. **Interactive "Chaos Monkey" Stress Test (`POST /api/chaos-monkey`):** Randomly drops $25\%$ of VIIRS observations in the target year (e.g., 2022) and enforces a 10-day simultaneous blackout of all satellites at peak fire season, computing `naive_rmse`, `kalman_rmse`, and `seasonal_energy_recovered_pct` ($> 90\%$).

### 3.5 Module 5: Physical Conversion to Consumed Biomass & Smoke Emissions (`auditor_stats.py`)
- Based on Wooster et al. (2005) and GFAS ($\beta_{\text{comb}} = 0.368 \pm 0.015\text{ kg dry matter}\cdot\text{MJ}^{-1}$):
  $$M_{\text{biomass}}(t) = 0.368 \cdot \hat{x}_{t|T} \cdot A_{\text{AOI}} \quad [\text{kg dry biomass}\cdot\text{day}^{-1}]$$
  $$E_{\text{PM}_{2.5}}(t) = 10^{-3} \cdot \text{EF}_{\text{PM}_{2.5}}(c) \cdot M_{\text{biomass}}(t), \quad E_{\text{CO}_2}(t) = 10^{-3} \cdot \text{EF}_{\text{CO}_2}(c) \cdot M_{\text{biomass}}(t)$$
  with default $\text{EF}_{\text{PM}_{2.5}} \approx 9.5\text{ g}\cdot\text{kg}^{-1}$.

### 3.6 Module 6: Circular von Mises Phenology & Decadal Climate Shift (`von_mises.py`)
- Maps Julian day $d \in [1, 365.25]$ to angle $\psi_d = \frac{2\pi d}{365.25} \in [0, 2\pi)$ weighted by daily harmonized energy $w_{d,y} = \hat{x}_{d,y|T}$:
  $$\bar{C}_y = \frac{\sum_d w_{d,y} \cos\psi_d}{\sum_d w_{d,y} + 10^{-8}}, \quad \bar{S}_y = \frac{\sum_d w_{d,y} \sin\psi_d}{\sum_d w_{d,y} + 10^{-8}}, \quad \bar{R}_y = \sqrt{\bar{C}_y^2 + \bar{S}_y^2} \in [0, 1]$$
- **Peak Burning Day ($\hat{\mu}_y$):** $\hat{\mu}_y = (\text{atan2}(\bar{S}_y, \bar{C}_y) \bmod 2\pi) \cdot \frac{365.25}{2\pi}$.
- **Seasonal Concentration ($\hat{\kappa}_y$) via Best & Fisher (1981) Approximation:**
  $$\hat{\kappa}_y \approx \begin{cases} 2\bar{R}_y + \bar{R}_y^3 + \frac{5}{6}\bar{R}_y^5 & \text{if } \bar{R}_y < 0.53 \\ -0.4 + 1.39\bar{R}_y + \frac{0.43}{1 - \bar{R}_y} & \text{if } 0.53 \le \bar{R}_y < 0.85 \\ \frac{1}{\bar{R}_y^3 - 4\bar{R}_y^2 + 3\bar{R}_y} & \text{if } \bar{R}_y \ge 0.85 \end{cases}$$
- **Effective Fire Season Width:** $W_y = \min\left(365.0,\, \frac{365.25}{\sqrt{\max(0.15, \hat{\kappa}_y)}}\right)$ days.
- **Decadal Climate Shift:** Unwraps $\{\hat{\mu}_{2001},\dots,\hat{\mu}_{2026}\}$ via `np.unwrap` and computes the non-parametric **Theil-Sen slope** (`phenology_shift_days_per_decade`) and **Circular Mann-Kendall p-value**.

### 3.7 Module 7: Live Statistical Peer-Review Audit Engine (`auditor_stats.py`)
1. **Chow Structural Break F-Test at $t_0 = \text{Jan } 2012$:**
   $$F_{\text{Chow}} = \frac{(\text{RSS}_{\text{pooled}} - (\text{RSS}_1 + \text{RSS}_2)) / k}{(\text{RSS}_1 + \text{RSS}_2) / (N_1 + N_2 - 2k)} \sim F(k, N_1 + N_2 - 2k)$$
   with $k = 2$. Raw counts fail ($F > 50, p < 10^{-12}$); Harmonized FRE passes ($F < 2.0, p > 0.10$).
2. **Wasserstein-1 Earth Mover's Distance ($W_1$):**
   $$W_1(F_{\text{pre}}, F_{\text{post}}) = \int_0^\infty |F_{\text{pre}}(x) - F_{\text{post}}(x)|\, dx$$
   proving $> 88\%$ reduction in inter-sensor distributional divergence.
3. **Independent Burned Area Cross-Validation ($R^2$ vs. `MCD64A1`):** Coefficient of determination between annual integrated metric and `burned_area_ha_mcd64` ($R^2_{\text{raw}} \approx 0.51 \to R^2_{\text{harm}} > 0.90$).

---

## 4. 60 FPS Frontend Visual Architecture (5 Synchronized Components)

1. **GPU 3D/2D Hexagonal Map (`HexagonMap.tsx` + `AoiDrawControl.tsx`):** Deck.gl `H3HexagonLayer` + MapLibre GL JS (with offline fallback grid), 4 preset pilot region buttons, freehand bounding-box drawing tool, latency badge, and a **"Reveal Gas Flaring ($H_{\text{temp}} > 0.75$)"** toggle highlighting industrial cells in neon magenta `[255, 0, 200, 235]`.
2. **2D `<canvas>` Burning Calendar with "2012 Time-Machine Split Curtain" (`BurningCalendarCanvas.tsx` + `HatchPatternDefs.ts` + `CalendarTooltip.tsx`):** Renders $26\text{ years} \times 366\text{ days} = 9,516$ cells plus the 14-day forecast band in $< 1.5\text{ ms}$. Overlays a $45^\circ$ diagonal hatch pattern (`OffscreenCanvas`) on `is_gap_filled === true` and gold hatching on `is_forecast === true`. Includes a vertical split-screen slider comparing Raw Counts (left) vs. Harmonized FRE (right).
3. **Circular von Mises Phenology Clock (`PolarVonMisesClock.tsx`):** Polar SVG clock ($[0, 2\pi)$) plotting annual vectors $(\hat{\mu}_y, \hat{\kappa}_y)$ from 2001 (cyan) to 2026 (fiery orange/red) with Theil-Sen shift in days/decade.
4. **Kalman Uncertainty Band Chart & Chaos Monkey View (`KalmanUncertaintyBandChart.tsx` + `ChaosMonkeyButton.tsx`):** Plots daily series for `selectedYear` with shaded $95\%$ CI bands, amber dotted Cross-Sensor Historical Prior curve, cyan outage highlights (`gap_status_mask` bit 1; real data: the Jul 27 to Aug 10, 2022 SNPP outage; the synthetic fixture keeps an Aqua blackout stress scenario), 14-day forecast cone, and live Chaos Monkey reconstruction overlay.
5. **Live Scientific Audit & Climate Export Panel (`AuditMetricsPanel.tsx`):** Traffic-light cards for Chow F-Test, Wasserstein $W_1$, `MCD64A1` $R^2$, Shannon industrial filter count, Wooster biomass/$\text{PM}_{2.5}$ totals, English `executive_verdict_en` banner, and **"Export IPCC-Ready CSV"** button.

---

## 5. Master Data Contracts (Immutable Schemas)

### 5.1 Master Parquet Schema (`data/processed/fire_cube.parquet`)
Sorted physically by `ORDER BY h3_r4 ASC, epoch_day ASC, h3_r7 ASC` with `ZSTD` compression.

| Column | DuckDB / Arrow Type | Unit | Nullable | Role |
| :--- | :--- | :--- | :--- | :--- |
| `h3_r4` | `UBIGINT` (`uint64`) | H3 Res 4 | `NOT NULL` | Coarse partition key ($\sim 1,770\text{ km}^2$) for Zone Map pruning. |
| `h3_r7` | `UBIGINT` (`uint64`) | H3 Res 7 | `NOT NULL` | Native cell ($5.161\text{ km}^2$). Exported as 15-char hex string in JSON. |
| `epoch_day` | `USMALLINT` (`uint16`) | Days since 1970-01-01 | `NOT NULL` | Continuous UTC day index. |
| `year` | `USMALLINT` (`uint16`) | Year [2000..2026] | `NOT NULL` | Annual aggregation key. |
| `doy` | `USMALLINT` (`uint16`) | DOY [1..366] | `NOT NULL` | Julian day for von Mises & historical cross-prior. |
| `igbp_biome` | `UTINYINT` (`uint8`) | Class [1..17] | `NOT NULL` | `MCD12Q1` biome class. |
| `sensor_obs_mask` | `UTINYINT` (`uint8`) | Bitmask [0..31] | `NOT NULL` | Bit 0: Terra, Bit 1: Aqua, Bit 2: SNPP, Bit 3: NOAA-20. |
| `gap_status_mask` | `UTINYINT` (`uint8`) | Bitmask [0..15] | `NOT NULL` | `0`: Clean; `1`: Sensor Outage; `2`: Cloud $>80\%$; `4`: Swath Gap; `8`: Dual Blackout. |
| `cloud_cover_pct` | `FLOAT` (`float32`) | $[0.0, 1.0]$ | `NOT NULL` | Cloud cover fraction scaling $Q_{\text{var}}$. |
| `raw_modis_cnt` | `USMALLINT` (`uint16`) | Pixels | `NOT NULL` | Uncorrected MODIS count. |
| `raw_viirs_cnt` | `USMALLINT` (`uint16`) | Pixels | `NOT NULL` | Uncorrected VIIRS 375 m count ($+420\%$ jump in 2012). |
| `raw_frp_mw` | `FLOAT` (`float32`) | MW | `NOT NULL` | Uncorrected raw FRP sum. |
| `obs_terra_fre` | `FLOAT` (`float32`) | $\text{MJ}\cdot\text{km}^{-2}\cdot\text{d}^{-1}$ | `NULLABLE` | Diurnally scaled Terra FRE (`NaN` if outage/cloud). |
| `obs_aqua_fre` | `FLOAT` (`float32`) | $\text{MJ}\cdot\text{km}^{-2}\cdot\text{d}^{-1}$ | `NULLABLE` | Reference Aqua FRE (`NaN` on Aqua outage days; none are documented in the real archive, while the synthetic fixture blanks Aqua on 2022-07-31..08-16 as a stress scenario). |
| `obs_viirs_fre` | `FLOAT` (`float32`) | $\text{MJ}\cdot\text{km}^{-2}\cdot\text{d}^{-1}$ | `NULLABLE` | EQM + GPD harmonized VIIRS FRE. |
| `neighbor_fre_lag1` | `FLOAT` (`float32`) | $\text{MJ}\cdot\text{km}^{-2}\cdot\text{d}^{-1}$ | `NOT NULL` | Spatial contagion $u_{\text{spatial}, t}$ at $t-1$. |
| `industrial_prob` | `FLOAT` (`float32`) | $[0.0, 1.0]$ | `NOT NULL` | Shannon entropy industrial score ($H_{\text{temp}} > 0.75$). |
| `burned_area_ha_mcd64`| `FLOAT` (`float32`) | Hectares | `NOT NULL` | Independent `MCD64A1` burned area ground truth. |

### 5.2 Pydantic v2 Contract (`backend/api/schemas.py`)

**Authoritative source: `firms-harmonizer/backend/api/schemas.py`** (mirrored by `frontend/src/api/types.ts`). The block below is a verbatim copy as of 2026-11-15; changes are logged in `firms-harmonizer/CAMBIOS.md`. Nullable fields are `null` when their required inputs or scientific publication gates are unavailable. Forecast and PM2.5 support is conditional, as specified in section 1.

```python
"""Frozen, JSON-safe public API contracts; mirrored in frontend/src/api/types.ts."""

from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class GeoJSONPolygon(ContractModel):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[list[float]]]

    @field_validator("coordinates")
    @classmethod
    def validate_rings(cls, rings: list[list[list[float]]]) -> list[list[list[float]]]:
        if not rings:
            raise ValueError("A polygon requires an exterior ring.")
        if len(rings) > 16 or sum(map(len, rings)) > 512:
            raise ValueError("A polygon supports at most 16 rings and 512 positions.")
        for ring in rings:
            if len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("Polygon rings must be closed with at least four positions.")
            for point in ring:
                if len(point) != 2 or not (-180 <= point[0] <= 180 and -90 <= point[1] <= 90):
                    raise ValueError("Positions must contain valid longitude and latitude.")
        return rings


class AnalyzeRequest(ContractModel):
    aoi: GeoJSONPolygon
    start_year: int = Field(default=2001, ge=2000, le=2026)
    end_year: int = Field(default=2026, ge=2000, le=2026)
    exclude_industrial_flaring: bool = True
    enable_kalman_gap_filling: bool = True
    forecast_days: int = Field(default=14, ge=0, le=14)
    confidence_level: Literal["low", "nominal", "high"] = "nominal"

    @model_validator(mode="after")
    def validate_year_order(self) -> "AnalyzeRequest":
        if self.start_year > self.end_year:
            raise ValueError("start_year must not exceed end_year.")
        return self


class RiskPredictionRequest(ContractModel):
    aoi: GeoJSONPolygon
    start_year: int = Field(default=2001, ge=2000, le=2026)
    end_year: int = Field(default=2026, ge=2000, le=2026)
    as_of_date: date | None = None

    @model_validator(mode="after")
    def validate_period(self) -> "RiskPredictionRequest":
        if self.start_year > self.end_year:
            raise ValueError("start_year must not exceed end_year.")
        if self.as_of_date and not self.start_year <= self.as_of_date.year <= self.end_year:
            raise ValueError("as_of_date must fall inside the requested years.")
        if self.as_of_date and self.as_of_date > datetime.now(timezone.utc).date():
            raise ValueError('Forecast origin cannot be in the future.')
        return self


class RiskReliabilityBin(ContractModel):
    samples: int = Field(ge=1)
    mean_predicted_pct: float = Field(ge=0, le=100)
    observed_pct: float = Field(ge=0, le=100)


class RiskValidation(ContractModel):
    samples: int = Field(ge=0)
    positives: int = Field(ge=0)
    brier_score: float | None = Field(ge=0, le=1)
    roc_auc: float | None = Field(ge=0, le=1)
    reliability: list[RiskReliabilityBin]


class RiskModelMetrics(RiskValidation):
    model_weights: dict[str, float]


class RiskDailyProbability(ContractModel):
    date: date
    wildfire_prob_pct: float | None = Field(ge=0, le=100)
    accident_prob_pct: float | None = Field(ge=0, le=100)


class RiskHorizon(ContractModel):
    days: Literal[1, 7, 14]
    wildfire_prob_pct: float | None = Field(ge=0, le=100)
    accident_prob_pct: float | None = Field(ge=0, le=100)
    combined_risk_pct: float | None = Field(ge=0, le=100)
    wildfire_validation: RiskValidation
    accident_validation: RiskValidation
    combined_validation: RiskValidation
    prior_targets: list[Literal["wildfire", "accident", "combined"]] = Field(default_factory=list)


class RiskFactor(ContractModel):
    feature: str
    impact_pct: float = Field(ge=0, le=100)
    direction: Literal["raises", "lowers"]
    description: str


class AIRiskAssessment(ContractModel):
    as_of_date: date
    last_observation_date: date | None = None
    validation_start_date: date
    wildfire_prob_24h_pct: float | None = Field(ge=0, le=100)
    wildfire_prob_7d_pct: float | None = Field(ge=0, le=100)
    industrial_accident_prob_pct: float | None = Field(ge=0, le=100)
    combined_risk_pct: float | None = Field(ge=0, le=100)
    overall_hazard_level: Literal["LOW", "MODERATE", "HIGH", "CRITICAL"] | None
    vegetation_event_threshold_mw: float = Field(gt=0)
    horizons: list[RiskHorizon]
    model_metrics: RiskModelMetrics
    top_risk_factors: list[RiskFactor]
    industrial_risk_factors: list[RiskFactor]
    daily_probability_series: list[RiskDailyProbability]


class RiskPredictionResponse(ContractModel):
    data_source: Literal["real", "synthetic"]
    target: Literal["satellite_thermal_event_proxy"] = "satellite_thermal_event_proxy"
    assessment: AIRiskAssessment | None
    unavailable_reason: str | None = None
    model_time_ms: float = Field(ge=0)
    execution_time_ms: float = Field(ge=0)


class DailyCalendarCell(ContractModel):
    date: str
    year: int
    doy: int
    raw_hotspot_count: int
    raw_frp_mw: float
    harmonized_fre_mj_km2: float
    historical_cross_prior_fre: float
    ci_95_lower: float
    ci_95_upper: float
    uncertainty_pct: float
    biomass_burned_tonnes: float
    pm25_emitted_kg: float | None
    z_score_anomaly: float
    is_gap_filled: bool
    is_forecast: bool
    gap_reason: str | None
    active_sensors: list[str]
    tooltip_narrative: str | None
    observation_status: Literal['detected', 'observed_zero', 'reconstructed', 'unknown', 'forecast'] = 'unknown'
    pm25_factor_sd_kg: float | None = None


class VonMisesPhenologyYear(ContractModel):
    year: int
    peak_doy_mu: float
    peak_date_label: str
    concentration_kappa: float
    season_width_days: float
    total_annual_fre_gj: float


class ScientificAuditMetrics(ContractModel):
    chow_test_f_stat_raw: float
    chow_test_p_val_raw: float
    chow_test_f_stat_harm: float
    chow_test_p_val_harm: float
    wasserstein_w1_raw: float
    wasserstein_w1_harm: float
    burned_area_r2_raw: float | None
    burned_area_r2_harm: float | None
    phenology_shift_days_per_decade: float
    mann_kendall_p_value: float
    industrial_false_positives_removed: int
    total_biomass_burned_kt: float
    total_pm25_emitted_tonnes: float | None
    executive_verdict_en: str


class H3MapSummaryHex(ContractModel):
    h3_index: str = Field(pattern=r"^[0-9a-f]{15}$")
    mean_annual_fre: float
    raw_pixel_count: int
    trend_slope: float
    is_industrial_site: bool
    shannon_entropy: float


class EnergyForecastValidation(ContractModel):
    horizon_days: int
    samples: int
    mae: float
    persistence_mae: float
    climatology_mae: float
    interval_coverage_pct: float


class AnalyzeResponse(ContractModel):
    data_source: Literal["real", "synthetic"]
    query_hash: str
    execution_time_ms: float
    aoi_area_km2: float
    total_h3_cells: int
    calendar_series: list[DailyCalendarCell]
    forecast_series: list[DailyCalendarCell] | None
    phenology_by_year: list[VonMisesPhenologyYear]
    audit_metrics: ScientificAuditMetrics | None
    map_hexagons: list[H3MapSummaryHex]
    coverage_note: str = 'Sparse detections do not establish complete observation coverage.'
    forecast_validation: list[EnergyForecastValidation] = Field(default_factory=list)
    forecast_unavailable_reason: str | None = None


class ChaosMonkeyRequest(ContractModel):
    aoi: GeoJSONPolygon
    target_year: int = Field(default=2022, ge=2000, le=2026)
    drop_fraction: float = Field(default=0.25, ge=0, le=1)
    simulate_dual_blackout: bool = True
    random_seed: int = Field(default=42, ge=0)


class ChaosMonkeyResponse(ContractModel):
    data_source: Literal["real", "synthetic"]
    dropped_days_count: int
    dropped_dates: list[str]
    dates: list[str]
    true_harmonized_fre: list[float]
    corrupted_naive_fre: list[float]
    historical_cross_guard_fre: list[float]
    kalman_reconstructed_fre: list[float]
    reconstructed_ci_lower: list[float]
    reconstructed_ci_upper: list[float]
    naive_rmse: float
    kalman_rmse: float
    seasonal_energy_recovered_pct: float


class CitationReference(ContractModel):
    id: str
    source_type: Literal["NASA_DATASET", "PEER_REVIEWED", "WEB_NEWS_REPORT"] = "PEER_REVIEWED"
    title: str
    authors_or_agency: str
    year: int
    dataset_or_doi: str
    url: str | None = None
    relevance_note: str


class CopilotTurn(ContractModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=6000)


class CopilotMapContext(ContractModel):
    label: str
    aoi: GeoJSONPolygon
    period_start: str
    period_end: str
    h3_index: str | None = None


class ExplainSpikeRequest(ContractModel):
    region_name: str = Field(default="Unknown Region", max_length=200)
    selected_day: DailyCalendarCell | None = None
    selected_hex: H3MapSummaryHex | None = None
    user_question: str = Field(default="", max_length=6000)
    aoi: GeoJSONPolygon | None = None
    confidence_level: Literal["low", "nominal", "high"] = "nominal"
    conversation: list[CopilotTurn] = Field(default_factory=list, max_length=10)
    period_start: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    period_end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    prefer_map_context: bool = False
    exclude_industrial_flaring: bool = True
    enable_kalman_gap_filling: bool = True
    previous_context: CopilotMapContext | None = None
    audit_metrics: ScientificAuditMetrics | None = None
    chat_history: list[CopilotTurn] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def compatible_history(self) -> "ExplainSpikeRequest":
        if self.chat_history and not self.conversation:
            self.conversation = self.chat_history
        return self


class ExplainSpikeResponse(ContractModel):
    physical_classification: str
    explanation_markdown: str
    citations: list[CitationReference] = Field(default_factory=list)
    web_search_used: bool = False
    search_query_executed: str | None = None
    model_used: str = "deterministic-fallback"
    data_source: Literal["real", "synthetic"] = "synthetic"
    map_context: CopilotMapContext | None = None
    answer_markdown: str = ""
    provider_used: str = ""
    episode_summary: dict | None = None

    @model_validator(mode="after")
    def compatible_answer(self) -> "ExplainSpikeResponse":
        self.answer_markdown = self.explanation_markdown
        self.provider_used = self.model_used
        return self


class CubeSyncRequest(ContractModel):
    days: int | None = Field(default=None, ge=1, le=30)
    sync_full_month: bool = False
    regions: list[str] | None = None


class CubeSyncStatusResponse(ContractModel):
    status: Literal["idle", "in_progress", "success", "error"]
    last_synced_utc: str | None = None
    new_detections_count: int = 0
    date_coverage_start: str | None = None
    date_coverage_end: str | None = None
    regions_updated: list[str] = Field(default_factory=list)
    message: str | None = None
    data_source: Literal["real", "synthetic"] = "real"
    error: str | None = None




class MapPeriodResponse(ContractModel):
    """Spatial observations only; legacy hex energy field is summed over these dates."""

    data_source: Literal["real", "synthetic"]
    start_date: date
    end_date: date
    map_hexagons: list[H3MapSummaryHex]
    execution_time_ms: float
```

### 5.3 Official study regions

- **chilecito_la_rioja** ? Chilecito, La Rioja (Argentina); bounds `[west,south,east,north] = [-69.5, -31, -65.5, -27.5]`.
- **iberia_med** ? Iberian Peninsula / Mediterranean (Spain); bounds `[west,south,east,north] = [-9.5, 36, 4, 44]`.
- **orlando_florida** ? Orlando, Florida (USA); bounds `[west,south,east,north] = [-82.0, 28.0, -80.7, 29.3]`.
- **amazonas_manaus** ? Amazonas / Manaus (Brazil); bounds `[west,south,east,north] = [-62.0, -5.0, -58.0, -1.0]`.

### 5.4 Exact spatial map periods (2026-11-14 integration)

`POST /api/map-period?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` accepts the existing
`AnalyzeRequest` body without changing the frozen analysis contracts. Dates are inclusive,
must belong to the same year, and must lie inside the body's requested year range.
The response contains `data_source`, `start_date`, `end_date`, `map_hexagons` and
`execution_time_ms`. Each hexagon retains the existing `H3MapSummaryHex` shape; on this
endpoint, the legacy field `mean_annual_fre` is the integrated observed energy density
over the requested dates, in MJ/km², with no annual extrapolation or regional Kalman
gap filling. `raw_pixel_count` counts detections within those dates only.

The query uses the same R7 polygon fill and unique R4 parents, registered Arrow cell
tables, bound year and epoch-day parameters, request-local DuckDB cursors, and hexadecimal
H3 serialization as annual analysis. Industrial observations are filtered before temporal
aggregation when requested. Empty periods return an empty map, never an annual substitute.
Responses are cached by geometry, exact dates, industrial filter and cube modification time.

The chronology's selected day takes precedence over month, which takes precedence over
year. Changing any of them reloads spatial observations with cancellation and stale-response
protection. Map colors use one fixed reference across dates; tooltips and visible-map totals
describe that same selected period. Missing observations do not establish absence of fire;
the first satellite detection does not establish the actual ignition time.

### 5.5 Observations viewer (current scope, 2026-11-14)

The current UI displays accepted, deduplicated FIRMS detection centers from the real staging dataset. `POST /api/observations` accepts a `GeoJSONPolygon` directly and returns real provenance, daily counts, summed instantaneous FRP in MW, all five instrument labels, per-R7 counts/FRP, first/last detection dates and the aggregation method. It never calls the scientific core, fills missing dates, estimates emissions or forecasts. No detections on a date does not establish zero fire activity or complete observation coverage. Counts are detections, not distinct fire events. Staging retains the ingestion quality and SAMA/date filters; raw FRP is not footprint-corrected or EQM-adjusted.

The active region catalogue is `firms-harmonizer/data/regions.json`: entries with declared `coverage` are offered by the frontend. Current regions are Orlando, Manaus, Chilecito and the full Iberia study rectangle. Rectangles are study envelopes, not administrative boundaries. Section 5.3 uses this same registry; the duplicate TypeScript preset helper has been removed. Existing `/api/analyze` and `/api/chaos-monkey` contracts remain unchanged and are not used by the observations UI.

### 5.6 Offline satellite thermal event predictor

`POST /api/predict-risk` accepts an AOI polygon, optional `start_year` and `end_year`
(default 2001–2026), and an optional UTC `as_of_date` inside those years. An explicit
date is the forecast origin. The API excludes later records and treats any days after
the last available record through that origin as unknown. Without a date the origin
is the latest local cube row within the requested period. The frontend sends the selected
day or the final UTC day of the selected month or year. The optional
`assessment.last_observation_date` identifies the final cube record used. Horizons 1, 7 and 14 cover the
following UTC days. The response includes `data_source`, the target identifier
`satellite_thermal_event_proxy`, nullable `assessment` and `unavailable_reason`,
`model_time_ms` and `execution_time_ms`. Existing analysis contracts remain compatible.

The cube has no confirmed ignition, spread or industrial accident labels. Fields named
`wildfire_prob_*` estimate high **non-persistent satellite heat** and fields named
`accident_prob_*` estimate a **persistent-source thermal excursion**. The combined
target is the occurrence of either event within the horizon. These are observation
probabilities after the stated origin, and are conditioned on the local record and its
sensor coverage. The vegetation event threshold is the 90th percentile of positive
summed FRP in the first fifth of the record. A persistent cell has observations on at
least 12 days and across nine calendar months within its preceding 365 days, with a
log-FRP standard deviation at most 0.8. An excursion is at least 2.5 standard deviations
above that trailing log-FRP mean, with a 0.25 scale floor. Persistence is a thermal
pattern and cannot identify the physical source by itself.

The feature matrix uses raw daily FRP from the cube, same-AOI previous-day H3 neighbors,
trailing 3/7-day means and 14-day maximum, prior-years Gaussian-smoothed seasonal
climatology, circular phase and mean direction, anomaly, quiet-spell interaction,
persistent-source share/excursion and observation-gap features. Cloud enters only when
the cube confirms complete ancillary coverage. In the supplied real cube it is absent.
The full-history EQM/LUT, retrospective industrial entropy and RTS backward-smoothed
estimates would leak later information and are excluded. A day between recorded
observations without a cube row has no reported detection. This convention and changing
sensor coverage limit what the forecast can infer about real fire activity.

The first 60% supplies base-model fit data, the next 20% calibrates stacked logistic,
boosted-stump and Gaussian naive Bayes outputs, and the final 20% supplies held-out
forecasts and validation. Label windows may not cross those boundaries or extend past
the record; flagged or explicitly missing windows are excluded from scoring. Metrics
cover each target and horizon separately. The ensemble requires at least five events
and five non-events in both fitting and calibration, plus 365 days of history.
With less support, a causal prior shrinks the frequency in earlier complete windows
toward a declared 0.5% daily prior with the weight of 100 windows. Bounded spatial,
recent heat, seasonal and persistent-source terms adjust the prior log odds. A
missing positive FRP reference uses a declared 1 MW threshold. Each horizon lists
the targets using the prior in the additive `prior_targets` field. An AOI with
no records receives an unavailable status. Brier score requires complete held-out
windows and ROC-AUC also requires both classes. Reliability bins compare predicted
means to observed frequencies.
The combined estimate is trained on the union and constrained by its marginals.
During a run of missing observations the estimate is blended toward the earlier
event frequency, reaching that frequency after seven days when prior complete
windows exist. The blackout benchmark replays historical cutoffs with the last 1,
3 or 7 days hidden, then scores forecasts against intact later FIRMS reports.
The severity badge denotes the combined 24-hour proxy likelihood, with boundaries at
20%, 50% and 75%. Driver bars show shares of absolute model or prior log-odds contributions,
not causal effects or ensemble probability changes.

All computation runs locally. The geometry/date/cube-keyed LRU caches completed results.
Cold timings include database aggregation and new model fitting. The risk endpoint stays
separate from map, chronology and the existing nullable FRE forecast series.

### 5.7 Evidence-first Fire Copilot (2026-11-14)

`POST /api/explain-spike` retains its existing fields and response shape. Additive,
optional request fields `conversation` (at most 12 user/assistant turns, 6,000
characters each), `period_start` and `period_end` (ISO date strings or null) carry
follow-up context and the selected map period. Existing clients remain compatible.
The Python/TypeScript contracts and CAMBIOS.md record these additions together.

Explicit dates override the selected period. Compatible place names describe the
attached AOI without expanding it; disjoint named places resolve to documented study
envelopes. Arbitrary AOIs preserve their geometry. Madrid, Sierra Oeste, Careiro and
Autazes are geographic envelopes, not administrative polygons or known fire perimeters.
Unknown places can use web evidence but never model-generated coordinates or SQL.
Exact-day/date-range/year filtering of accepted staging detection centers uses R7
polygon filling, unique R4 parents, registered Arrow filters, bound parameters and
request-local DuckDB cursors. Synthetic mode never queries real staging for a real-event
claim. Observed counts, summed instantaneous FRP, individual maxima and busiest days
are calculated locally; counts do not identify distinct fires, severity or ignition.

Groq model selection is configurable. Offline operation (`COPILOT_OFFLINE=1`), provider
failure and invalid model output return useful deterministic local evidence. Quantitative
questions use local calculations. Search results are candidate contextual reports;
publication dates are not invented from the event date. `web_search_used` means relevant
web results were retrieved, not that an incident was confirmed. Only citations actually
used in an answer are returned, and the UI links their markers to the supplied sources.
The model cannot introduce links or cite unknown source IDs. Missing search results do
not establish a remote or undocumented fire. Entropy, reconstruction flags and a 2012
date alone cannot confirm gas flaring, an actual fire or a fixed sensor artifact.

`python scripts/06_validate_copilot.py` verifies real-data numerical answers offline;
`--live` additionally exercises configured model and search providers and saves full
answers for narrative/source review. Regression tests mock network services and cover
scope precedence, follow-ups, exact dates, provenance, concurrency and provider failures.

### 5.6 Automatic map context and question-led answers (2026-11-14)

An explicit area, hexagon or chronology selection automatically attaches location and
its exact day/month/year to Fire Copilot. The composer shows one removable “Area and
day/period added as context” notice, with location and date. It has only an X action;
there are no pin/follow-map controls or separate date inputs. Removing the attachment
clears geometry, dates and prior-scope inference from subsequent requests. Hovering
alone does not replace an attachment. Drawing a new area preserves the selected day.
Changing timeline precision actually selects the displayed day/month/year.

An attached polygon is retained when a user names a compatible containing locality
(e.g. “that fire in Madrid”). An explicitly different place can change geography;
explicit dates can change the period. Known study envelopes provide geographic search
labels, never invented incident names or fire perimeters. A full-year selection never
silently becomes the busiest day or a particular incident.

Existing optional request booleans `prefer_map_context`,
`exclude_industrial_flaring`, `enable_kalman_gap_filling` and nullable
`previous_context` remain compatible with existing clients. Nullable response
`map_context` records the geometry/dates actually queried. Structured prior scope
supports follow-ups after older conversation turns leave the bounded history.

Quantitative requests calculate accepted staging detection-center counts and FRP
locally. Energy requests reuse the dashboard's 2001–2026 `/api/analyze` series with
attached scientific filters and inclusive requested dates. GJ = sum of daily FRE
(MJ/km²) × represented H3 area / 1,000. Reconstruction is explicitly identified and
can differ from the map's observed-only energy. Missing data never become estimated
GJ from summed instantaneous MW, and synthetic data remain labeled.

Causal responses lead with an answer or explicit uncertainty, then concise local
evidence, incident-source status and separate scientific context. They do not dump
power statistics or busiest-day tables. Month/year selections cannot identify one
incident and request a precise day or incident name. Statistics and energy answers
use named sections; rankings and detailed tables appear when requested.

Research uses bounded parallel searches for official records and reputable news,
with exact host checks, deduplication, source diversity and location/date filtering.
Up to eight useful incident reports may be retained; source counts are never padded.
At most three official HTML pages are read without redirects or arbitrary hosts,
with time/body limits. A model may extract only complete, verbatim 5–25-word official
sentences about ignition or investigation. The server rejects excerpts absent from
retrieved text, stripped of a preceding negation, or lacking an explicit matching
event date and nearby locality. A source quote does not confirm that its incident
is identical to a selected satellite cluster; provisional status stays explicit.

Crossref supplies up to three related journal-article metadata records with valid
DOIs; obvious correction, retraction and withdrawn records are excluded. Registry
metadata identify publications, not the truth of every finding or an investigation
of this selected incident. Scientific background remains separate from event evidence.
Source cards distinguish official reports, news and scientific literature, and are
collapsed by default. The model is configured for grounded retrieval and extraction;
no model training or automatic confirmation of ignition causes is performed.

Offline mode skips all external providers while retaining local data and curated
scientific references. Source failures and insufficient context produce explicit,
useful limitations. The single DeckGL mount and calendar canvas are preserved.

### 5.7 Incident-answer acceptance and source extraction repair (2026-11-14)

This revision supersedes the research restrictions in section 5.6.

Incident research now reads both official reports and reputable news instead of
requiring a short official ignition quotation before it can explain anything. Search
queries separate place/date from provider syntax and use the supported automatic
backend, with a localized date fallback. The curated `data/copilot_sources.json`
contains source URLs and publication metadata, never ready-made event answers;
its Madrid 2026-07-24 reference is fetched and validated before use.

Up to four official/news articles are selected with publisher diversity. Every
redirect target must remain on an allowed source host. HTML retrieval is bounded
and honors character encodings. Article-body fields take precedence over navigation,
sharing links and related-story fragments. The model sees region-relevant verbatim
passages instead of an entire multi-incident liveblog. Reported ignition, spread
conditions, incident context and uncertainty are separate categories. Literal source
checks reject invented/truncated excerpts and unrelated liveblog incidents. Longer
passages (up to 80 words) may be checked internally; returned citations omit full
article bodies and displayed original excerpts are at most 25 words. Failure of model
extraction can fall back to validated report passages with conservative English text.
No source is equated automatically with a satellite cell or a known ignition cause.

Deterministic help, unit definitions and unsupported-metric explanations work without
providers. Unknown emissions/burned-area totals are not replaced by detection counts.
Numeric intent recognizes multilingual paraphrases such as “number of fires”; scientific
definitions such as “Qué significa GJ” are not routed as requests for an energy total.

`scripts/08_validate_copilot_acceptance.py` runs twelve real-data acceptance cases;
`--live` additionally exercises actual search/model providers. Assertions compare
counts with independent SQL, check dates/provenance/citations, and require a sourced
spread explanation for the user's Madrid 24 July case, rather than only HTTP success.
The automated suite also covers provider failures, malformed results, evidence checks,
encoding/navigation cleanup and multilingual scientific/data questions. These finite
checks do not imply universal correctness or independent certification of every report.

### 5.8 Autonomous scientific episode investigation (2026-11-15)

The synchronous `/api/explain-spike` route also supports first-time, broad fire
investigations through `backend/api/copilot_researcher.py`. An attached AOI without
a clicked day discovers the highest daily harmonized FRE in the available
2001–2026 cube history. Explicit question dates take precedence. A ±15-day window
estimates consecutive above-background thermal activity; it is not an official
ignition-to-extinction interval or an identified fire perimeter. Window and archive
censoring, reconstruction, industrial filtering and coverage are disclosed.

Coordinated additive contract fields: `ExplainSpikeRequest.audit_metrics` (nullable,
client context only), `chat_history` (bounded compatibility input, used only if
`conversation` is empty); `ExplainSpikeResponse.answer_markdown` and `provider_used`
mirror `explanation_markdown` and `model_used`; `episode_summary` is a nullable
JSON-safe scientific profile. Existing fields and types are retained in Python and
TypeScript. Client telemetry and audit verdicts never override server measurements.

Emission estimates use explicitly assumed factors (0.368 kg/MJ dry biomass,
9.5 g/kg PM2.5 and 1,580 g/kg CO2). They are scenario estimates, not measured
emissions or air concentrations, and do not replace null dashboard emissions.
Physics gates skip incident-news retrieval for industrial candidates, sensor
transition questions, reconstruction and forecasts. Entropy or client flags alone
do not establish an industrial facility; no universal 2012 count multiplier is
asserted. Geographic context comes from H3 or the AOI and a local catalogue,
without substituting a municipality for a study envelope.

Investigations combine bounded cause, progression and consequences searches with
Wikipedia context and scientific references; snippets and encyclopedic search
results are leads, not ignition evidence. LLM requests have at most 4,500 content
characters and 900 output tokens, provider timeouts and a deterministic four-section
offline dossier. Rate limits and latency depend on external providers and cannot
be guaranteed by a prompt length. Deprecated provider URLs must be replaced with
supported endpoints. `scripts/test_copilot_e2e.py` exercises the required five
scenarios and additional failure, scope, schema and numeric checks.

#### Episode energy footprint correction

The integrated Antonio API accounting changes use the cube cells represented on
**each day**, rather than the union of cells over 26 years. The Copilot obtains
per-day GJ from the corresponding scientific biomass field divided by the same
0.368 kg/MJ factor; this is an algebraic recovery of energy, not an independent
measurement. Auto-discovery ranks daily GJ, which can differ from ranking density.
`episode_summary.daily_series` includes `fre_gj`; `represented_area_km2` denotes the
selected polygon and `peak_represented_cell_area_km2` the peak-day footprint.
Temporal reconstruction on a day with no cube footprint does not invent a burning
area or an energy total. Sensor averaging still uses different cell subsets; these
are model-derived estimates, not a validated emission inventory.

The exact R7-first filtering guardrail remains in force; no R4 polyfill is used for
early rejection. Oversized polygons are rejected by their exact R7 count. Input
limits are 1,000 polygon positions, 6,000 question characters (matching the composer)
and 200 region-label characters. Frozen tests were retained unchanged.

GitHub's official retirement notice confirms that GitHub Models (including its
inference API) was retired on 2026-07-30. The requested legacy provider is therefore
skipped unless an operator supplies both `GITHUB_TOKEN` and an explicit
`GITHUB_MODELS_ENDPOINT` for a compatible gateway. Gemini remains the subsequent
provider. This avoids silently calling either retired GitHub inference URL.

### 5.9 Groq tool agent and local document retrieval (2026-11-15)

Online `/api/explain-spike` uses Groq native function calling instead of an intent
keyword classifier. A short system message and five read-only tools let the model
retrieve local knowledge (SQLite FTS5/BM25), query accepted observations, calculate
scientific energy, profile an episode and search incident reports. Geometry is
resolved by the server; tool arguments never contain SQL or arbitrary coordinates.
A model-selected tool is executed once per request; up to three tool rounds precede
a forced final response. Dates/arguments and citations are validated. Exact numeric
results are also rendered by Python, independently of model prose. Unsupported
numeric claims, malformed responses and provider failures return local evidence.

The versioned corpus under `data/copilot_knowledge/` contains scientific notes with
source links; ETL documentation is indexed in complete paragraphs, excluding test
logs and verification sections. Retrieval uses an offline lexical index, not neural
embeddings or model training. The model can reformulate retrieval queries. Prior
turns, source passages and tool results have explicit size limits. The existing
local scientific pipeline remains the offline/no-credentials fallback. Public
contracts remain unchanged; citation rendering additionally supports K/E document
markers. Groq quotas remain external constraints; fallback is reported explicitly.

### 5.10 Settings and comparable energy labels (2026-11-15)

The header Settings menu contains the map/calendar display choice, industrial
candidate exclusion/highlighting and a keyboard-shortcut disclosure. The adjacent
appearance button controls the existing persisted light/dark theme. The former
Raw/Harmonized choice remains functional as Detection count/Calibrated energy;
it changes visual encoding, not energy totals. Industrial settings display the
actual full-record candidate-cell count and explain when no visible change occurs.

Explore and Copilot distinguish the visible-map per-cell observed energy proxy
from the regional sensor-aggregation/model estimate. Copilot additionally executes
the same `fetch_map_period` calculation and exact H3 area sum as the frontend, with
identical dates and industrial filtering, to report mapped GJ and matching biomass.
The agent receives these estimators as separate nested tool results. Selected query
area, observed cell footprint, requested dates and actual archive cutoff remain
separate quantities. This adds internal tool fields only; frozen public schemas
and TypeScript API contracts remain unchanged.


### Chronology picker and inclusive ranges (2026-11-15)

The chronology dock retains a 56 px detection histogram. Clicking the date summary
opens Day, Month, Year and Date range controls with corresponding native fields;
Apply dates commits the draft, while Cancel and Escape preserve the current period.
Previous/next keep the selected granularity. Hovering bars does not change selection.
Daily bars cover the selected month, monthly bars the selected year, and annual bars
the full record. Date ranges use inclusive UTC bounds, including across years.

Internally, selectedRange overrides the single day/month/year for map requests,
regional totals and Copilot context; its end is the risk forecast origin. Selecting
any single period clears that range. Cross-year ranges split into same-year requests
to the existing map-period endpoint, with at most four concurrent requests, then sum
observed energy densities and detection counts per H3 cell. They preserve cancellation,
stale-response protection and real/synthetic provenance. No API contracts changed.
Appearance is available inside Settings as a persisted Dark mode switch.


### Activity answers and small histogram counts (2026-11-15)

Answering whether activity is consistent with burning is distinct from confirming
a wildfire identity or its ignition cause. Local answers state that distinction.
The agent excludes citation IDs from physical-number validation and can correct
an unsupported numerical answer once within its existing deadline; server-rendered
measurements remain exact. A failed provider still returns local evidence.
Histogram positive bins have a 5 px minimum and zero bins a 1 px baseline. Labels
state that detection bars are not incident duration; no observation does not
establish extinction. No observations are extended or fabricated to match reports.


### Google Gemini deployment and source discovery (2026-11-15)

The active local provider is `COPILOT_PROVIDER=gemini`, using `GEMINI_API_KEY` and
`GEMINI_MODEL=gemini-3.8-flash`. Google rejected `gemini-2.5-flash` for the project;
the user explicitly authorized the available replacement. `.env.example` documents
setup without credentials. `COPILOT_PROVIDER=groq` remains an explicit alternative.
Google-selected agent or auxiliary completion failures do not silently use Groq.

The concise domain prompt addresses practical land/fire questions, with exact local
measurements and relevance-based citations. It distinguishes thermal activity,
reported wildfire identity, ignition, spread, reconstructed estimates and missing
coverage. It is not a new deterministic pre-execution security gate or a claim that
all requested metrics in the reference methodology have been implemented.

The compatibility endpoint supports existing read-only tools. Gemini may return
multiple calls despite a no-parallel hint; batches of up to three are validated and
executed sequentially, with a complete result for each call ID before another model
turn. Opaque provider metadata is preserved. Context trimming retains whole tool
exchanges; numeric and source-ID checks still apply. Grouped/doubled citations are
normalized. Unknown ignition does not invalidate otherwise sourced incident prose.

Incident discovery uses native Google Search in a separate request, followed by the
existing approved-publisher article extraction. Only grounding metadata URLs are
accepted. A Google redirect can be inspected once without fetching an unapproved
target or forwarding credentials. Model-generated search summaries are not report
quotes. Search discovery shares a 12-second deadline; individual redirect/publisher
reads remain bounded to four seconds. This deliberately replaces the reference
methodology's four-second search suggestion after repeated live timeouts; the agent's
35-second overall deadline remains. Empty/failed searches do not prove no incident.

Public Pydantic and TypeScript API contracts are unchanged. Offline mode and provider
failure retain local archive responses and explicit real/synthetic provenance.

### Gemini-led incident evidence assessment (2026-11-15)

This update supersedes the previous provider cascade and the 35-second agent budget.
Gemini is the default for both the tool agent and auxiliary completion. Groq is an
explicit alternative (`COPILOT_PROVIDER=groq`), with no automatic cross-provider
fallback. Local retrieval, geometry, SQL and arithmetic are Python tools and do not
require Groq. Offline mode, missing credentials and unrecoverable provider/output
failures retain the deterministic local response.

Google discovery may be refined once with a model-selected candidate/locality query;
server-resolved coordinates and selected dates accompany each search. Retrieved
article text reaches Gemini without a veto requiring its county/town names to match
the map envelope label. Up to four sources are packed into a 5,500-character report
payload, keeping complete sentences and explicit lead/article status. Lead-only
sources cannot establish incident facts. Existing publisher and redirect restrictions
remain in force. The legacy excerpt matcher also recognizes English activity dates.

Gemini assesses geographic/date relevance and reviews the incident draft against the
retrieved articles before returning it. Reported identity, consequences and ignition
remain separate; a regional candidate is not a confirmed match to selected cells.
An article's missing ignition cause must not erase its documented incident context.
This review is model-based, not independent verification or a guarantee against error.
Selected dates and polygon centroids are valid context for numerical checks; exact
measurement results remain server-rendered. Episode profiling cannot replace an
explicitly selected map period with its wider analysis window.

The agent permits up to nine bounded processing steps, with a 55-second overall
budget and 15-second provider turns; the browser timeout remains 60 seconds. Google
discovery retains its 12-second budget and publisher reads their four-second cap.
Public Python and TypeScript API contracts are unchanged.
