# SPECS.md — Technical Specification & Execution Phases

Aligned with CONAE's two-part mission architecture (**Part 1: Sensor-Agnostic Data Harmonization** & **Part 2: Interactive Fire Activity Calendar Web App**), the system is split into an Offline ETL Pipeline and an On-Demand Online Engine[cite: 9, 11].

---

## BLOCK 1: Data Preprocessing (Offline ETL Pipeline)
*Executed once over historical NASA FIRMS archives (2000–2026) for MODIS (`MCD14ML`), VIIRS (`VNP14IMGML`, `VJ114IMGML`), and Land Cover (`MCD12Q1`) across strategic benchmark regions (including **Chilecito, La Rioja, Argentina — July 2026**, Amazon/Cerrado, California/Western US, and Mediterranean/Iberia)[cite: 5, 6, 9].*

### Phase 1.1: H3 Ingestion & Off-Nadir Elliptical Footprint Reconstruction
* **Goal:** Eliminate the MODIS bow-tie distortion at scan edges ($\theta \to 55^\circ$, where pixels stretch from $1\times 1\text{ km}$ to $\sim 4.8\times 2.0\text{ km}$) and project physical energy onto H3 Resolution 7 cells[cite: 1, 2].
* **Algorithm:**
  1. Model each detection $k$ as a bivariate Gaussian $\mathcal{N}(\mu_k, \Sigma_k)$ rotated by orbital azimuth $\alpha$ ($i \approx 98.2^\circ$ sun-synchronous):[cite: 2]
     $$\Sigma_k = R(\alpha) \begin{pmatrix} (\Delta S_k / 2.355)^2 & 0 \\ 0 & (\Delta T_k / 2.355)^2 \end{pmatrix} R(\alpha)^\top$$
     using FIRMS `scan` ($\Delta S_k$) and `track` ($\Delta T_k$) dimensions[cite: 2].
  2. Query neighboring hexagons via `grid_disk(h3_r7, k)` and distribute $\text{FRP}_k$ proportionally using $\mathcal{O}(1)$ second-order barycentric quadrature[cite: 2].

### Phase 1.2: Kinetic De-duplication (ST-DAG) & FRE Integration
* **Goal:** Prevent multi-satellite over-counting (Terra, Aqua, SNPP, NOAA-20/21 observing the same fire 4–8 times/day) and integrate instantaneous power ($\text{MW}$) into total energy ($\text{MJ}$)[cite: 3].
* **Algorithm:**
  1. **ST-H3-DBSCAN Clustering:** Connect detections $(h_i, t_i)$ and $(h_j, t_j)$ via integer H3 ring hash-joins if $d_{H3}(h_i, h_j) \le k_{\max}$ and $0 \le t_j - t_i \le 18\text{ h}$[cite: 3].
  2. **Temporal DAG Integration:** Construct a Directed Acyclic Graph per connected component and integrate along the diurnal fire cycle modulated by `daynight` ($\omega_{\text{diurnal}}$):[cite: 3]
     $$\text{FRE}_{\text{event}} = \sum_{k=1}^{m-1} \frac{\text{FRP}_k + \text{FRP}_{k+1}}{2}(t_{k+1} - t_k)\cdot \omega_{\text{diurnal}}(t_k, t_k+1)$$[cite: 3]

### Phase 1.3: Anthropogenic & Industrial Filter (Shannon Entropy)
* **Goal:** Decouple stationary human heat sources (gas flaring, steel plants, solar farms present in unmasked VIIRS 375 m data) from wildland and agricultural fires[cite: 4, 10].
* **Algorithm:**
  1. Aggregate detections at high-resolution **H3-R10** ($\sim 15,000\text{ m}^2$) across $M$ historical months[cite: 4].
  2. Compute normalized temporal Shannon Entropy:[cite: 4]
     $$H_{\text{temp}}(h) = -\frac{1}{\log M} \sum_{m=1}^{M} p_m \log(p_m) \in [0, 1]$$[cite: 4]
  3. Store $H_{\text{temp}}(h)$ in `industrial_prob` (wildfires exhibit $H_{\text{temp}} \ll 0.25$; industrial flares exhibit $H_{\text{temp}} > 0.75$ and near-zero nocturnal spatial variance)[cite: 4]. Retain rows so users can toggle industrial sources on/off in the UI[cite: 4, 5].

### Phase 1.4: Censor-Aware Radiometric Harmonization (EQM + GPD)
* **Goal:** Align VIIRS and MODIS intensity scales and mathematically reconstruct sub-threshold cool fires ($0.5\text{ MW} - 8\text{ MW}$) missed by MODIS during the pre-VIIRS era (2000–2011)[cite: 1, 2].
* **Algorithm:**
  1. **Co-located Calibration (2012–2025):** Extract quasi-simultaneous overpasses ($|\Delta t| < 25\text{ min}$) between MODIS Aqua and VIIRS SNPP stratified by IGBP biome ($c \in \{1..17\}$) and scan zenith angle $\theta$[cite: 2, 3].
  2. **Suprathreshold Transfer:** Fit non-parametric Empirical Quantile Mapping: $\hat{X}_{\text{harm}} = F_{M|c,\theta}^{-1}(F_{V|c,\theta}(X_V))$, exported as a $< 150\text{ KB}$ lookup table (`lut_harmonization.json`)[cite: 2, 3].
  3. **Left-Censored Tail Extrapolation (2000–2011):** Fit a Generalized Pareto Distribution (GPD) over $[x_{\min}^V, \tau_M(\theta)]$ to analytically integrate and inject missing sub-threshold energy $\Delta E_{\text{sub}}(\theta, c)$ into historical MODIS records[cite: 2].

### Phase 1.5: Orbital Geometry Bias Correction (Horvitz-Thompson)
* **Goal:** Remove latitudinal sampling bias caused by polar-orbiting satellites converging near the poles[cite: 4].
* **Algorithm:**
  1. Re-weight energy by the inverse analytical orbital revisit probability $\pi_{\text{orb}}(\phi_h)$ at cell centroid latitude $\phi_h$:[cite: 4]
     $$\pi_{\text{orb}}(\phi_h) \propto \frac{W_{\text{swath}}}{2\pi R_E \cos(\phi_h)}, \quad \widehat{\text{FRE}}_{HT}(h, t) = \frac{\text{FRE}(h, t)}{\pi_{\text{orb}}(\phi_h)}$$[cite: 4]
  2. Write final sorted table to `fire_cube.parquet`[cite: 5, 6].

---

## BLOCK 2: Live Postprocessing & On-Demand Analysis (Online Engine)
*Executed in **< 15 ms** in the backend whenever a user selects a specific date, draws a custom Area of Interest (AOI), or inspects an emergency case study in the web app[cite: 6, 9, 11].*

### Phase 2.1: Spatial Filtering & DuckDB Aggregation
* **Input:** User GeoJSON polygon (AOI), date window, and industrial filter threshold[cite: 5, 6].
* **Execution:**
  1. Polyfill AOI to `h3_r4` cells (triggering Parquet Row Group Pruning) and filter exact `h3_r7` cells[cite: 5].
  2. Aggregate daily time series (`epoch_day`) in DuckDB and stream spatial tensors via **Apache Arrow IPC** directly to Deck.gl[cite: 5].

### Phase 2.2: Cloud & Outage Gap-Filling (RTS Kalman Smoother)
* **Goal:** Reconstruct blind days caused by dense cloud cover ($C_{\text{cloud}} \to 1$) or satellite outages (`NaN`) without hallucinating false fire spikes[cite: 4].
* **Execution:**
  1. Detect total occlusion gaps (`NaN`) in the AOI daily time series.
  2. Run a forward-backward **Rauch-Tung-Striebel (RTS) Kalman Smoother** over the latent daily energy state.
  3. Populate imputed `harm_fre_mj_km2` values alongside 95% uncertainty bands (`ci_lower_95`, `ci_upper_95`)[cite: 5].

### Phase 2.3: Circular Phenology Calendar & Live Statistical Audit
* **Goal:** Power the interactive **Fire Activity Calendar** (polar phenology clock + 26-year anomaly matrix) and prove sensor consistency live to the jury[cite: 1, 3, 6, 8].
* **Execution:**
  1. **von Mises Circular Calendar:** Map day-of-year $d \in [1, 365.25]$ to unit circle angle $\psi_d = \frac{2\pi d}{365.25}$ weighted by $w_d = \text{FRE}_d$[cite: 3]:
     * Compute trigonometric moments $\overline{C}_y, \overline{S}_y$ and mean resultant length $\overline{R}_y = \sqrt{\overline{C}_y^2 + \overline{S}_y^2}$[cite: 3].
     * Extract **Peak Burning Day** $\hat{\mu}_y = \text{atan2}(\overline{S}_y, \overline{C}_y) \cdot \frac{365.25}{2\pi}$ and **Seasonal Concentration** $\hat{\kappa}_y = A^{-1}(\overline{R}_y)$ (Best & Fisher rational approximation)[cite: 3].
     * Quantify decadal fire-season shift (days/decade) using **Circular Mann-Kendall** and **Theil-Sen slope**[cite: 3].
  2. **Operational Emergency Replay Mode:** Include a one-click preset for **Chilecito, La Rioja (July 2026)** demonstrating the 3-stage CONAE emergency workflow (initial hotspot detection $\to$ spread vector tracking $\to$ post-fire consolidation)[cite: 9].
  3. **Live Scientific Audit Panel:** Compute on-the-fly for any user-drawn AOI:
     * **Chow Structural Break Test ($t_0 = \text{Jan } 2012$):** Verify sensor continuity ($p > 0.10$)[cite: 1].
     * **Wasserstein-1 Distance ($W_1$):** Display real-time distribution convergence between MODIS and harmonized VIIRS[cite: 1].

---

## Acceptance Criteria (Pre-Pitch Checklist)
* [ ] **Backend Latency:** Spatial query + RTS Kalman smoothing + von Mises metrics across 26 years executes in **< 15 ms**[cite: 5, 6].
* [ ] **Frontend Frame Rate:** 9,131-day time slider runs at **60 FPS** with $> 500,000$ active hexagons in WebGL[cite: 5, 6].
* [ ] **Scientific Audit Metrics:** $W_1$ reduction $> 88\%$, Chow Test $p > 0.10$ at 2012 boundary, and $R^2 > 0.85$ against `MCD64A1` burned area[cite: 1, 7].
* [ ] **Mission Alignment:** Interactive Fire Activity Calendar supports custom region/date selection and includes the **Chilecito (July 2026)** operational case study[cite: 9, 11].
* [ ] **Offline Reliability:** 100% functional in Airplane Mode with RAM-cached demo views[cite: 6].