# Fire Harmonizer — Single Source of Truth

## Scope and units
The bootstrap covers every real Gregorian day from 2001-01-01 through 2026-12-31 (26 years; epoch origin 2000-01-01). The broader mission may later ingest 2000. Canvas has 26 × 366 slots, including blank non-leap-year slots. FRE is daily energy density in MJ/km²/day; FRP is instantaneous MW, not interchangeable with FRE. One MW sustained for one second equals one MJ. Synthetic scenarios are integration fixtures, never evidence of real scientific performance. Future dates within the synthetic fixture are simulated observations, not operational observations.

## Physical cube contract
`data/processed/fire_cube.parquet` has exactly the following 18 columns, in this order. Sort physically by `ORDER BY h3_r4 ASC, epoch_day ASC, h3_r7 ASC`, use ZSTD compression and statistics for row-group pruning. No dataframe index or region column is stored. H3 parent-child hierarchy encodes location; region membership is determined from pilot polygons. All fields are non-null except the three observations; missing observations are Arrow NULL (NumPy NaN on extraction), never zero. Zero means observed absence of energy.

| Column | DuckDB | Arrow | Semantics |
|---|---|---|---|
| h3_r4 | UBIGINT | uint64 | R4 parent of h3_r7 |
| h3_r7 | UBIGINT | uint64 | R7 footprint cell |
| epoch_day | USMALLINT | uint16 | Days since 2000-01-01 |
| year | USMALLINT | uint16 | Gregorian year |
| doy | USMALLINT | uint16 | Gregorian ordinal day, 1..366 |
| igbp_biome | UTINYINT | uint8 | MCD12Q1 class, 1..17 |
| sensor_obs_mask | UTINYINT | uint8 | Available observations: Terra=1, Aqua=2, VIIRS=4; bit set iff finite |
| gap_status_mask | UTINYINT | uint8 | Bit flags: 0 clean, 1 sensor outage, 2 cloud >80%, 4 swath gap, 8 dual blackout |
| cloud_cover_pct | FLOAT | float32 | Cloud percentage, 0..100 |
| raw_modis_cnt | USMALLINT | uint16 | Unharmonized count, comparison only |
| raw_viirs_cnt | USMALLINT | uint16 | Unharmonized count, comparison only |
| raw_frp_mw | FLOAT | float32 | Raw aggregate FRP in MW |
| obs_terra_fre | FLOAT | float32 nullable | Terra daily FRE density |
| obs_aqua_fre | FLOAT | float32 nullable | Aqua daily FRE density |
| obs_viirs_fre | FLOAT | float32 nullable | VIIRS daily FRE density |
| neighbor_fre_lag1 | FLOAT | float32 | Previous-day neighboring energy, no future leakage |
| industrial_prob | FLOAT | float32 | Probability in [0,1] |
| burned_area_ha_mcd64 | FLOAT | float32 | Independent burned-area reference in ha in production; synthetic proxy in bootstrap |

VIIRS is unavailable before 2012-01-01; Aqua before 2002-07-04. Mission availability alone does not mark an outage. Bootstrap simulates a global Aqua outage 2022-07-31..2022-08-16 inclusive (`gap_status_mask=1`), and clouds 2022-08-22..2022-08-26 inclusive (all three NULL, `gap_status_mask=8`, cloud=100). Raw counts and power are zero during complete blackout. Gas flaring has constant underlying FRE and industrial_prob=0.92. Natural-fire peaks move +0.75 days/year. From 2012 VIIRS raw counts are 5.2 times the rounded MODIS-equivalent baseline (+420%, rather than 4.2 times). Counts remain a secondary diagnostic. Sensor energy observations keep the same physical scale.

## Module 1 — Off-nadir geometry and bow-tie overlap
Let ΔS and ΔT be scan and track dimensions in km, and α orbital azimuth. Use Σ = R(α) diag((ΔS/2.355)², (ΔT/2.355)²) R(α)ᵀ. At ΔT > 1.35 km apply η_overlap(ΔT)=min(1,1/ΔT); otherwise η=1 (ΔT numerically expressed in km). Integrate the elliptical Gaussian over `grid_disk(h3_r7, 1)`, normalize nonnegative weights to sum to one, then distribute corrected energy E_h=η E w_h. Density is E_h/A_h, using nominal A_h=5.161 km² in bootstrap and exact H3 cell area in production. Conserve total corrected energy. A synthetic latent cell field is not a replacement for production footprint ingestion.

## Module 2 — Industrial entropy and SAMA
At R10, let p_m be the fraction of annual detections in month m. H_temp=−Σ(m=1..12) p_m ln(p_m+10⁻¹²)/ln(12), clipped to [0,1]. Zero-total cells have H=0. Candidate industry has H_temp>0.75; preserve rows for the industrial toggle. Reject low-confidence nocturnal anomalies inside −35≤lat≤−15 and −65≤lon≤−30 when ΔT_11<1.5 K. Entropy alone is not independent proof of industry.

## Module 3 — Censor-aware EQM and GPD
Stratify by biome c and scan zenith θ; calibrate co-located overlap observations (|Δt|<25 minutes) without reusing validation years. X_harm=F_MODIS|c,θ⁻¹(F_VIIRS|c,θ(X_VIIRS))+ΔE_sub(θ,c). Fit GPD tails with CDF G(z)=1−(1+ξz/β)^(−1/ξ) on its valid support (ξ→0 exponential limit). Infer the missing 0.5..8 MW population before 2012 using censored likelihood, not a fit to detected-only samples. ΔE_sub is the integral of power times inferred population density over that interval, converted to daily energy and area units. Enforce monotonic quantile interpolation and nonnegative energy; report strata with insufficient overlap rather than fabricate calibration.

## Module 4 — RTS Kalman, cross-history guard and 14-day prediction
Build μ_cross(d) from available calibrated sensors for each ordinal day d in 1..366, averaging sensors within days before averaging across years so the advent of VIIRS cannot increase weight. Smooth circularly with Gaussian σ=5 days. Compute training priors without held-out target-year information for validation. Empty climatology bins require an explicitly documented finite neighbor/circular interpolation.

Forward state: x_pred=φ x_previous+γ u_spatial,t+ω_prior μ_cross(d_t), with φ=0.68, γ=0.17, ω_prior=0.15; P_pred=φ² P_previous+Q. Sensors use y_s=h_s x+ε_s, Var ε_s=R_s. Skip NaN observations. For each finite sensor K=P h/(h²P+R_s+10⁻⁸), x←x+K(y_s−h_s x), P←(1−Kh_s)²P+K²R_s (Joseph form). Historical complete blackout uses y_guard=0.55μ_cross(d_t)+0.45u_spatial,t, h=1, R_guard=40.0 with the same update. This precise blended guard resolves the shorthand historical μ_cross pseudo-observation rule.

RTS backward: J_t=φ P_filtered,t/(P_pred,t+1+10⁻⁸); x_smooth,t=x_filtered,t+J_t(x_smooth,t+1−x_pred,t+1); P_smooth,t=P_filtered,t+J_t²(P_smooth,t+1−P_pred,t+1). Require finite nonnegative covariance; clip only roundoff-size negatives and expose substantive instability. CI is x±1.96√P (physical lower display bound may clip at zero). Future H=14 days have NaN observations and prediction-only uncertainty propagation; never treat forecast absence as historical blackout. Chaos Monkey drops historical observations with a seeded RNG, optionally all sensors, and compares against withheld truth via RMSE and 100Σx_reconstructed/Σx_true. Do not use withheld truth for guards or reconstruction.

## Module 5 — Biomass and smoke
For area A_AOI in km², daily biomass kg=0.368 kg/MJ × x_smooth MJ/km²/day × A_AOI. Divide by 1000 for tonnes. PM2.5 kg=biomass_kg ×9.5 g/kg /1000. Report these as emission estimates; EF depends on biome. Annual FRE GJ=Σdaily FRE density × A_AOI/1000.

## Module 6 — Circular von Mises phenology
θ_d=2π(d−1)/365.25, weights w_d=FRE_d≥0. C̄=Σw cosθ/Σw, S̄=Σw sinθ/Σw, R̄=√(C̄²+S̄²), μ_doy=1+(atan2(S̄,C̄) mod 2π)365.25/(2π). Best & Fisher rational approximation: κ=2R+R³+5R⁵/6 for R<0.53; κ=−0.4+1.39R+0.43/(1−R) for 0.53≤R<0.85; κ=1/(R³−4R²+3R) otherwise. Handle R→1 with numerical clipping. W=365.25/√κ; a uniform or empty season is not an identifiable peak (use finite W=365.25 and κ=0 in JSON, explain in tooltip).

Unwrap annual circular peaks across the shortest arcs before fitting Theil-Sen median pairwise slopes; multiply by ten for days/decade. Circular Mann-Kendall here means Mann-Kendall applied to that unwrapped sequence: S=Σi<j sign(μ_j−μ_i), tie-correct Var(S)=[n(n−1)(2n+5)−Σt t(t−1)(2t+5)]/18, continuity-corrected Z=(S−sign(S))/√Var(S), two-sided normal p. State the unwrapping convention; do not treat this as a uniquely defined general circular rank test.

## Module 7 — Live statistical audit
Chow at 2012-01-01 compares pooled regression RSS_p to separate RSS_1+RSS_2 with the same k predictors (intercept, trend and annual sine/cosine controls): F=[(RSS_p−RSS_1−RSS_2)/k]/[(RSS_1+RSS_2)/(n_1+n_2−2k)], p=F survival probability. Report insufficient degrees of freedom or zero residual variance explicitly. Targets: raw p<10⁻¹² and harmonized p>0.10; do not force outcomes. Physical climate trends can themselves cause rejection.

W1(P,Q)=∫|F_P(x)−F_Q(x)|dx on consistent units and matched seasons; improvement=100(1−W1_harm/W1_raw), target >88%. Burned-area predictive R²=1−Σ(y−ŷ)²/Σ(y−ȳ)² must be evaluated out of sample against independent MCD64A1 (target >0.85); squared Pearson correlation is only a descriptive association and must be labeled as such. Bootstrap proxy correlation is not independent validation. All verdicts and tooltips are English. No module is scientifically complete until audited on real data.

## Frozen API and frontend conventions
Pydantic v2 models forbid unknown fields and NaN/Infinity in JSON. All listed fields are required unless an input default appears below. TypeScript `number` mirrors Python int/float; `Array<T>` mirrors list[T]. Defaulted input fields are optional in TypeScript and normalized by Pydantic. All response fields are required except those marked nullable (`| null`); nullable fields are null when out of MVP scope or when the source column/core output is unavailable. Every AnalyzeResponse and ChaosMonkeyResponse carries `data_source` (`real | synthetic`). The API uses the synthetic cube only when `USE_SYNTHETIC_CUBE=1` (file `data/processed/fire_cube_synthetic.parquet`); otherwise it refuses to start without a real cube. Dates are ISO YYYY-MM-DD strings; `gap_reason` is string or null; `active_sensors` is a string array (Terra, Aqua, VIIRS). Empty arrays are valid. H3 indices are lowercase hexadecimal strings of exactly 15 characters. Confidence is `low | nominal | high`. Request years are 2001..2026 with start≤end, forecast_days 0..14, drop_fraction 0..1 and random_seed≥0. Polygon positions are finite [longitude,latitude] pairs with closed rings of at least four positions. Full topology validation belongs to the spatial API layer.

`PRESET_REGIONS` is a keyed object with exactly cerrado_brazil, california_usa, iberia_med and niger_delta_flaring. Values contain `name` (English), `center` ([longitude,latitude]) and `aoi` (GeoJSONPolygon). Pilot centers are (−48,−16), (−121,39), (−5,39), (6,5), each with a closed ±1-degree rectangle. Synthetic cube samples an R7 center and its six neighbors in each polygon, rather than densely filling the entire region. R4 is derived from each R7, never guessed from the pilot center.

POST /api/analyze takes AnalyzeRequest and returns AnalyzeResponse; POST /api/chaos-monkey takes ChaosMonkeyRequest and returns ChaosMonkeyResponse. Use synchronous routes. Bounded analysis JSON is allowed; bulk map tensors use Arrow IPC and preserve uint64 until converted to hexadecimal for Deck.gl. These bootstrap contracts do not implement routes.

## Bootstrap module status
Bootstrap implementation verified: 11 cube/contract tests pass; strict standalone TypeScript compilation passes; all six rule mirrors match agent.md. The generated cube contains 265,888 rows (28 cells × 9,496 days), 18 correctly typed columns, and ZSTD compression. Measured generator runtime was 0.779 seconds on the development machine (generation and mock writing, excluding interpreter imports); this is not an API latency measurement. Dependencies were installed in `/tmp/firms-harmonizer-venv`, with standalone TypeScript in `/tmp/firms-harmonizer-ts`.

Math core, production ETL, API and visual components remain with their assigned owners. Their mathematical/API test files are empty (pytest exit 5: no tests collected). Frontend package.json and tsconfig.json are empty, so the full frontend `npx tsc --noEmit` integration gate remains pending. They were not modified by bootstrap. The mock uses known synthetic latent energy and climatology, not a claimed production Kalman implementation; its 95% bands are illustrative relative margins. Mock execution_time_ms measures fixture generation before mock serialization, not a query benchmark. Annual map energy is the annual sum of density, averaged over years; trend_slope is its Theil-Sen slope per year.

The fixture audit reports harmonized Chow p≈1.07×10⁻²³ under the documented intercept/trend/first-harmonic model, so it does NOT meet p>0.10. A moving nonlinear season is not fully modeled by that regression; this result must be retained, not replaced with a fabricated passing value. The measured synthetic peak shift is approximately 7.499 days/decade. The burned-area proxy is generated from latent energy and is not an independent MCD64A1 validation. No production scientific module or full integration gate is declared complete by this bootstrap.

### GeoJSONPolygon

| Field | TypeScript type | Default / constraints |
|---|---|---|
| `type` | `"Polygon"` | `'Polygon'` |
| `coordinates` | `Array<Array<Array<number>>>` | `required` |

### AnalyzeRequest

| Field | TypeScript type | Default / constraints |
|---|---|---|
| `aoi` | `GeoJSONPolygon` | `required` |
| `start_year` | `number` | `Field(default=2001, ge=2001, le=2026)` |
| `end_year` | `number` | `Field(default=2026, ge=2001, le=2026)` |
| `exclude_industrial_flaring` | `boolean` | `True` |
| `enable_kalman_gap_filling` | `boolean` | `True` |
| `forecast_days` | `number` | `Field(default=14, ge=0, le=14)` |
| `confidence_level` | `"low" | "nominal" | "high"` | `'nominal'` |

### DailyCalendarCell

| Field | TypeScript type | Default / constraints |
|---|---|---|
| `date` | `string` | `required` |
| `year` | `number` | `required` |
| `doy` | `number` | `required` |
| `raw_hotspot_count` | `number` | `required` |
| `raw_frp_mw` | `number` | `required` |
| `harmonized_fre_mj_km2` | `number` | `required` |
| `historical_cross_prior_fre` | `number` | `required` |
| `ci_95_lower` | `number` | `required` |
| `ci_95_upper` | `number` | `required` |
| `uncertainty_pct` | `number` | `required` |
| `biomass_burned_tonnes` | `number` | `required` |
| `pm25_emitted_kg` | `number \| null` | `required, nullable (null in MVP)` |
| `z_score_anomaly` | `number` | `required` |
| `is_gap_filled` | `boolean` | `required` |
| `is_forecast` | `boolean` | `required` |
| `gap_reason` | `string | null` | `required` |
| `active_sensors` | `Array<string>` | `required` |
| `tooltip_narrative` | `string \| null` | `required, nullable (null in MVP)` |

### VonMisesPhenologyYear

| Field | TypeScript type | Default / constraints |
|---|---|---|
| `year` | `number` | `required` |
| `peak_doy_mu` | `number` | `required` |
| `peak_date_label` | `string` | `required` |
| `concentration_kappa` | `number` | `required` |
| `season_width_days` | `number` | `required` |
| `total_annual_fre_gj` | `number` | `required` |

### ScientificAuditMetrics

| Field | TypeScript type | Default / constraints |
|---|---|---|
| `chow_test_f_stat_raw` | `number` | `required` |
| `chow_test_p_val_raw` | `number` | `required` |
| `chow_test_f_stat_harm` | `number` | `required` |
| `chow_test_p_val_harm` | `number` | `required` |
| `wasserstein_w1_raw` | `number` | `required` |
| `wasserstein_w1_harm` | `number` | `required` |
| `burned_area_r2_raw` | `number \| null` | `required, nullable` |
| `burned_area_r2_harm` | `number \| null` | `required, nullable` |
| `phenology_shift_days_per_decade` | `number` | `required` |
| `mann_kendall_p_value` | `number` | `required` |
| `industrial_false_positives_removed` | `number` | `required` |
| `total_biomass_burned_kt` | `number` | `required` |
| `total_pm25_emitted_tonnes` | `number \| null` | `required, nullable (null in MVP)` |
| `executive_verdict_en` | `string` | `required` |

### H3MapSummaryHex

| Field | TypeScript type | Default / constraints |
|---|---|---|
| `h3_index` | `string` | `Field(pattern='^[0-9a-f]{15}$')` |
| `mean_annual_fre` | `number` | `required` |
| `raw_pixel_count` | `number` | `required` |
| `trend_slope` | `number` | `required` |
| `is_industrial_site` | `boolean` | `required` |
| `shannon_entropy` | `number` | `required` |

### AnalyzeResponse

| Field | TypeScript type | Default / constraints |
|---|---|---|
| `data_source` | `"real" \| "synthetic"` | `required` |
| `query_hash` | `string` | `required` |
| `execution_time_ms` | `number` | `required` |
| `aoi_area_km2` | `number` | `required` |
| `total_h3_cells` | `number` | `required` |
| `calendar_series` | `Array<DailyCalendarCell>` | `required` |
| `forecast_series` | `Array<DailyCalendarCell> \| null` | `required, nullable (null in MVP)` |
| `phenology_by_year` | `Array<VonMisesPhenologyYear>` | `required` |
| `audit_metrics` | `ScientificAuditMetrics \| null` | `required, nullable (null when the AOI has no data)` |
| `map_hexagons` | `Array<H3MapSummaryHex>` | `required` |

### ChaosMonkeyRequest

| Field | TypeScript type | Default / constraints |
|---|---|---|
| `aoi` | `GeoJSONPolygon` | `required` |
| `target_year` | `number` | `Field(default=2022, ge=2001, le=2026)` |
| `drop_fraction` | `number` | `Field(default=0.25, ge=0, le=1)` |
| `simulate_dual_blackout` | `boolean` | `True` |
| `random_seed` | `number` | `Field(default=42, ge=0)` |

### ChaosMonkeyResponse

| Field | TypeScript type | Default / constraints |
|---|---|---|
| `data_source` | `"real" \| "synthetic"` | `required` |
| `dropped_days_count` | `number` | `required` |
| `dropped_dates` | `Array<string>` | `required` |
| `dates` | `Array<string>` | `required` |
| `true_harmonized_fre` | `Array<number>` | `required` |
| `corrupted_naive_fre` | `Array<number>` | `required` |
| `historical_cross_guard_fre` | `Array<number>` | `required` |
| `kalman_reconstructed_fre` | `Array<number>` | `required` |
| `reconstructed_ci_lower` | `Array<number>` | `required` |
| `reconstructed_ci_upper` | `Array<number>` | `required` |
| `naive_rmse` | `number` | `required` |
| `kalman_rmse` | `number` | `required` |
| `seasonal_energy_recovered_pct` | `number` | `required` |
