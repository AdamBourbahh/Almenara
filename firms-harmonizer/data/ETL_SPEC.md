# Offline FIRMS ETL specification

## Scope and acceptance

Build a real-only local FIRMS cube for regions with staged observations and declared coverage. The deterministic pilot fixture is generated separately at `data/processed/fire_cube_synthetic.parquet` by script 00 or by script 04 with `--bootstrap`. Run the five scripts in numeric order from the project directory. The build uses no network or API credentials.

```powershell
python scripts/01_ingest_firms.py
python scripts/02_detect_outages_clouds.py
python scripts/03_train_eqm_lut.py
python scripts/04_build_master_cube.py
python scripts/05_cli_benchmark.py
```

The cube must contain the 18 Arrow fields defined by the executable bootstrap contract, with its original types and nullability. The physical key is `(h3_r4, epoch_day, h3_r7)` with ascending order, unique cell-days and ZSTD compression. Both cubes store UTC days since 1970-01-01, as specified in `SPECS.md`. NOAA-21 uses the fifth sensor bit in real data. The fixture uses a grouped VIIRS bit. Both cubes store cloud cover as a fraction. Regenerate older cubes before adopting the 1970 epoch in the API.

## Inputs and new regions

1. Add the new key to `data/regions.json` with `bounds` in west, south, east, north order, `nominal_biome` in 1–17 and inclusive `coverage` date intervals matching the FIRMS requests. Put specific regions before broader overlapping regions. Current contracts limit the cube to 2026.
2. Place the downloaded MODIS and VIIRS CSVs directly under `data/raw/`. Preserve archive and NRT labels in the file names so standard detections win exact identity conflicts. Original Chilecito files and download notes are preserved in a nested directory outside the ingest glob.
3. Run scripts 01–05. Regions with real observations become queryable from their ingested records. Adding a regional frontend preset is a separate team change.

Use local auxiliary Parquet files when available.

| Location | Columns |
|---|---|
| `data/lookup/igbp_cells.parquet` | Unique unsigned `h3_r7`, `igbp_biome` from MCD12Q1 |
| `data/lookup/cell_day_ancillary.parquet` | Unique unsigned `h3_r7` and `acq_date`, with `cloud_cover_pct` in 0–1 and `burned_area_ha_mcd64` in hectares |
| Path passed to script 02 with `--global-counts` | `satellite`, `acq_date`, `detection_count`. Supply one row per instrument per calendar day, including observed zero counts. |

## Stage behavior

- **01** uses DuckDB to read local CSVs. It normalizes sensors, UTC date and time, thermal channels and confidence. It deduplicates exact sensor/time/location matches, filters SAMA candidates, computes H3 resolutions 4, 7 and 10, and stages both center counts and Gaussian MODIS footprint contributions. The footprint weights sum to one per detection. Entropy is normalized over twelve calendar months and the industrial score includes a positional variance gate. The ETL delegates SAMA screening and Shannon industrial scoring to `backend/core/industrial_filter.py` (`filter_sama_anomalies` and `compute_industrial_probability`).
- **02** records the documented SNPP outage (2022-07-27..08-10) and flags fourfold drops relative to the previous 15 complete days of global counts, reading the tracked `data/lookup/global_daily_counts.csv` unless `--global-counts` names another CSV or Parquet file. Local detection counts cannot establish global outages. Diurnal ratios use coincident daytime Aqua and Terra FRP by H3 r4 and month.
- **03** uses coincident daytime Aqua and SNPP r7 cell-days in 2012–2025 and delegates every stratum fit to `backend/core/eqm_harmonizer.py::RadiometricHarmonizer.fit_biome_eqm_gpd` (101-knot EQM plus the bounded sub-threshold GPD term `delta_e_sub`). Bins derive from footprint width, which is an angle proxy. Strata with fewer than 20 matched cell-days are omitted; stage 04 then falls back to the biome and pooled fits, and to uncalibrated FRP when no model exists. See the [Stage 03/04 radiometric harmonization contract](#stage-0304-radiometric-harmonization-contract-phase-6).
- **04** aggregates per cell-day, applies available lookup corrections, uses a one-hour FRP integration proxy for FRE density and computes prior-day neighbor energy. Only staged FIRMS detections contribute rows to the real master. Missing staging stops the build before replacement. Coverage is declared independently of detection density. Real FIRMS rows are sparse detections, and days without detections have no real row. For real rows without auxiliary data, biome uses the configured nominal class and cloud and burned area use zero sentinels. Parquet metadata records these limitations. The final replacement is atomic.
- **05** measures warmed regional queries against the physical Parquet, reports Chow p-values and Wasserstein distance, computes leave-one-year-out burned-area R2 where defined, and exercises a seasonal-prior recovery baseline. A missing audit result fails the gate. Fixture metrics are diagnostics. Full Chaos Monkey validation depends on the backend RTS implementation.

### Stage 01 footprint geometry and bow-tie parity contract

**Mathematical formulation.** As defined in `SPECS.md` §2(5) and `backend/core/footprint_h3.py`:
- Detections with `scan * track <= 3.5 km²` (e.g., all nominal VIIRS at 0.375 km nadir and MODIS near nadir) are assigned wholly (`weight = 1.0`) to the containing H3 resolution 7 cell (`center = h3.latlng_to_cell(lat, lon, 7)`).
- Deformed MODIS footprints with `scan * track > 3.5 km²` allocate energy across the 1-ring neighborhood (the center cell plus its 6 adjacent neighbors, or 5 for H3 pentagons) via a discrete bivariate Gaussian PSF aligned with scan and track axes rotated by the nominal orbit inclination azimuth ($\alpha = 98.2^\circ$).
- Log-scale weight evaluation prevents numerical underflow for narrow ellipses:
  $$xy = R_{\text{earth}} \cdot \text{deg2rad}([\Delta \text{lon} \cdot \cos(\text{lat}), \Delta \text{lat}])$$
  $$\text{scaled} = (xy \cdot R(\alpha)) / ([\text{scan}, \text{track}] / 2.355)$$
  $$w_i \propto \exp(-0.5 \sum \text{scaled}_k^2)$$
- Energy conservation is strictly guaranteed by residual assignment: $w_{\text{largest}} = 1.0 - \sum_{i \neq \text{largest}} w_i$, ensuring $\sum_{i=1}^7 w_i = 1.0$ exactly down to floating-point precision ($\Delta < 10^{-12}$).
- Along-track bow-tie overlap suppression: For MODIS observations with `track > 1.35 km`, the discount weight is $w_{\text{bowtie}} = 1.0 / \text{track}$. For `track <= 1.35 km` or VIIRS observations, $w_{\text{bowtie}} = 1.0$.

**Parity verification.** `scripts/01_ingest_firms.py` delegates directly to `backend.core.footprint_h3` (`compute_elliptical_psf_weights` and `compute_modis_bowtie_overlap_weight`) and incorporates an identical mathematical fallback. Exact parity ($\Delta < 10^{-12}$) across all 4 production regions (Chilecito, Iberia, Orlando, Amazonas), polar and antimeridian extremes, boundary conditions, and staged Parquet output is verified by `backend/tests/test_cube_schema.py::test_phase1_*` (14 automated test cases).

### Stage 01 SAMA artifact and industrial persistence contract

**SAMA anomaly screening.** As defined in `SPECS.md` §3.2 and implemented in `backend/core/industrial_filter.py::filter_sama_anomalies`:
- Detections inside the South Atlantic Magnetic Anomaly bounding box ($15^\circ\text{S} \le \text{lat} \le 35^\circ\text{S}$, $30^\circ\text{W} \le \text{lon} \le 65^\circ\text{W}$) that occur at nighttime (`daynight == 'N'`), carry normalized `low` confidence, and have background thermal contrast $\Delta T_{11} = T_{\text{MIR}} - T_{\text{TIR}} < 1.5\text{ K}$ are discarded as energetic proton noise.
- Pre-November 2000 corrupted Terra MODIS records (`acq_year == 2000 and acq_month < 11`) are discarded.
- In `scripts/01_ingest_firms.py`, `sama_artifact` delegates directly to `filter_sama_anomalies` with scalar broadcasting and identical fallback logic.

**Shannon temporal entropy & industrial probability.**
- Monthly counts $c_m$ ($m=1,\dots,12$) at H3 resolution 10 evaluate temporal persistence:
  $$H_{\text{temp}} = -\frac{1}{\ln(12)} \sum_{m=1}^{12} p_m \ln(p_m + 10^{-12}) \in [0, 1]$$
- The logistic industrial score uses `compute_industrial_probability`:
  $$P_{\text{industrial}} = \text{expit}(22.0 \cdot (H_{\text{temp}} - 0.72))$$
  gated by spatial positional variance ($\sigma_{\text{pos}}^2 < 50\text{ m}^2$) to distinguish stationary industrial gas flaring ($H_{\text{temp}} > 0.75$) from dynamic seasonal wildfire events.
- Parity between ETL and core is verified by `backend/tests/test_cube_schema.py::test_phase3_*` (14 automated test cases).

### Stage 03/04 radiometric harmonization contract (Phase 6)

**One implementation.** `SPECS.md` §3.3 is implemented once, in `backend/core/eqm_harmonizer.py`. Stage 03 trains each stratum with `RadiometricHarmonizer.fit_biome_eqm_gpd(aqua_mw, snpp_mw)` on matched daytime cell-day MW sums; stage 04 applies `harmonize_viirs_to_modis` to SNPP/NOAA-20/NOAA-21 daily sums and `compensate_modis_censoring` to Terra and Aqua daily sums, in one vectorized call per (stratum, instrument family), before the FRE scale and the orbital weight. The LUT records `method`; the cube metadata records `radiometric_harmonization`.

**Common scale.** Both channels land on the sub-threshold-compensated MODIS scale:

```text
VIIRS_h = F_MODIS^-1(F_VIIRS(P_viirs)) + delta_E_sub       (101 empirical knots, endpoints clamped)
MODIS_h = P_modis + delta_E_sub                            (P_modis > 0; Terra then * kappa)
delta_E_sub = pi_sub * E_GPD[x | 0.5 <= x < 8 MW]          (pi_sub = share of SNPP cell-days in [0.5, 8) MW)
```

This is SPECS §3.3 equation 2 with the truncated GPD integral normalized to its conditional mean. MODIS omits sub-threshold fires in every year, so the compensation applies to all MODIS cell-days, not only pre-2012 ones; otherwise MODIS and VIIRS would sit on different scales after 2012. Zeros stay zero and missing values stay missing. Stratum selection is `biome:angle`, then `biome:all`, then `all:all`.

**Superseded ETL path.** The earlier stage 03/04 code mapped only VIIRS ≥ 8 MW with 21 knots and ratio extrapolation, and added `mean·f/(1−f)` to MODIS ≥ 8 MW. On real held-out data it inflated harmonized VIIRS energy (sum VIIRS/Aqua 1.433 versus 1.121 raw) and worsened the distributional match (KS 0.060 versus 0.053 raw). It was replaced on 2026-11-14.

**Real-data verification — 2026-11-14.** Inputs: 30,449 matched daytime Aqua/SNPP R7 cell-days from the four-region staging, trained on 2012–2022 (24,096) and evaluated on held-out 2023–2025 (6,353). The stage 03/04 path and direct core calls agree exactly (worst |ETL − core| = 0.0 MW in every stratum).

| Stratum | Train / held-out | delta_E_sub (MW) | Median log(V/A) raw → harmonized | Sum V/A raw → harmonized | KS raw → harmonized |
| --- | --- | --- | --- | --- | --- |
| `all:all` | 24,096 / 6,353 | 0.918 (pi_sub 0.199, mean 4.615) | +0.087 → −0.052 | 1.121 → 1.108 | 0.053 → 0.016 |
| `2:all` (Amazonas) | 6,631 / 2,507 | 1.132 | −0.053 → −0.048 | 1.142 → 1.134 | 0.055 → 0.020 |
| `8:all` (Iberia, Orlando) | 15,285 / 3,460 | 0.850 | +0.178 → −0.018 | 1.106 → 1.056 | 0.069 → 0.017 |
| `16:all` (Chilecito) | 2,180 / 386 | 0.716 | +0.270 → −0.029 | 1.510 → 1.042 | 0.142 → 0.075 |

Pre-2012 compensation adds +2.60% energy to 179,238 real MODIS cell-days (pooled model). **Strata provenance:** `data/lookup/igbp_cells.parquet` (MCD12Q1) is absent, so every biome stratum uses the nominal regional class from `data/regions.json`; only `all:all` is independent of that fallback. Regression tests: `test_stage03_lut_is_trained_by_the_core_harmonizer`, `test_stage04_eqm_gpd_parity_with_core_on_every_channel` (pooled and biome strata) and `test_math_core.py::test_eqm_modis_censoring_compensation_shares_viirs_scale`. Limits: EQM matches marginal distributions, not paired cell-days, and the residual 4–13% energy excess of VIIRS is not corrected; a MODIS cell-day that receives only a fraction of a spread footprint still receives the full `delta_E_sub`.

### Stage 04 diurnal scaling and Eulerian integration contract

**Architecture and scope.** `SPECS.md` §2(6) approves Eulerian aggregation on fixed H3 R7 cells and UTC calendar days. Stage 01 normalizes and deduplicates detections before footprint allocation. Stage 04 groups the staged contributions by `(h3_r4, h3_r7, acq_date, satellite, sensor_bit)`. Distinct acquisitions in the same cell-day add power within each instrument. The proposed spatio-temporal DAG event clustering (`ST-H3-DBSCAN`) and continuous trapezoidal integration are outside Phase 2: sparse polar-orbiting snapshots do not establish continuous event trajectories or burn duration.

The daily grouping uses DuckDB's vectorized hash aggregation, with expected O(N) aggregation work for N staged contributions; this is not a worst-case or whole-pipeline O(N) guarantee. Stage 01 also uses Python record processing, and explicit ordering of G groups or M published rows costs O(G log G) or O(M log M). Fixed keys and sorted Parquet output support hierarchical H3 Zone Map pruning and direct daily state-space input. The spatial term `neighbor_fre_lag1` couples those cell-day observations to the downstream RTS model without requiring an event graph. This validation exercises the offline values, not the Kalman implementation or its scientific performance.

**Exact record identity.** Stage 01 uses `(normalized_satellite, UTC_acq_date, four_digit_acq_time, round(latitude, 5), round(longitude, 5))`. Sensor aliases such as `T`/`Terra` and `A`/`Aqua` are normalized first; `930` and `0930` denote the same UTC acquisition time. Files whose names contain `nrt` (case-insensitive) are processed after standard/archive files, regardless of lexical filename order. The first accepted identity wins; ties within the same priority use sorted filenames and input row order. A later conflicting FRP does not replace the archive record. Different instruments, dates, times or five-decimal locations remain distinct, even when they occupy the same R7 cell-day. Footprint allocation follows deduplication, so one detection's distributed contributions are not independent duplicate acquisitions.

**Conversion and units.** For cell h, UTC day t and instrument s, let P(h,t,s) be the sum of `corrected_frp` over all retained staged contributions. Stage 04 applies the core radiometric harmonization (`harmonize(modis, P, model)`, Phase 6 contract below) to that daily instrument sum, using modal biome and scan bin; the Phase 2 arithmetic fixtures deliberately use an empty LUT (identity calibration). Let P_cal be the resulting power and A_h the exact `h3.cell_area(cell, unit="km^2")`, rather than a universal nominal 5.161 km². Then:

```text
FRP: 1 MW = 1 MJ/s
FRE_obs(h,t,s) = P_cal(h,t,s) * 3600 s / A_h * w_orb(h)      (Terra also * kappa; see below)
reported unit: MJ / km² / day (energy assigned to one UTC daily bin)
```

Multiplication by 3,600 seconds converts power to energy; it does not reconstruct a measured 24-hour integral. There is no additional factor of 24, division by 86,400, or averaging across repeated acquisitions within one instrument. With identity calibration, two distinct 10 MW and 20 MW passes yield `30 * 3600 / A_h`. The three output channels retain separate Terra and Aqua estimates and the arithmetic mean of available SNPP/NOAA-20/NOAA-21 estimates. Thus different VIIRS instruments are averaged, while repeated passes within each instrument are summed. `raw_modis_cnt`, `raw_viirs_cnt`, and `raw_frp_mw` count/sum deduplicated center detections, not extra footprint contributions. Outage/cloud masking precedes neighbor-energy calculation.

**Physical limits.** Polar-orbiting sensors measure instantaneous thermal snapshots, not continuous burn duration. The operational proxy assigns an effective one-hour window to the aggregated daily instrument power. Linearity makes each retained pass contribute one hour of its measured power, without estimating how much its time window overlaps another pass. This can overestimate brief agricultural flash burns lasting less than 30 minutes and underestimate multi-hour or overnight crown fires. Multiple passes can recover additional activity but can also count overlapping burning more than once; the temporal sampling remains incomplete. Terra-to-Aqua scaling adjusts sampled morning amplitude and does not recover duration. Independent MCD64A1 burned-area cross-validation is required to evaluate and, where justified, calibrate these biases. Neither multiple passes nor diurnal scaling guarantees accurate true daily energy. Passing Phase 2 validates the approved proxy's implementation, not physical accuracy on real fires or the separate Phase 6 calibration model.

**Diurnal lookup generation.** Stage 02 selects only `daynight == "D"` Terra/Aqua contributions, sums `corrected_frp` separately by `(h3_r4, UTC acq_date)`, and retains days where both sums are strictly positive. These are coincident coarse-cell days, not a requirement for identical R7 locations or acquisition times. For each `(h3_r4, calendar_month)` bucket, pooling available years:

```text
kappa = sum(Aqua daily power over matched days) / sum(Terra daily power over matched days)
matched_days = number of retained R4 calendar days
```

This is a ratio of sums, not the unweighted mean of individual daily ratios. Multiple passes on one date contribute power but count as one matched day. Nighttime, unpaired, and nonpositive pairs do not contribute. Lookup output is sorted by R4 and month.

**Diurnal application.** Stage 04 loads only lookup rows with `matched_days >= 3`. It multiplies Terra FRE by `kappa(h3_r4, month)` to represent the nominal morning Terra overpass (10:30 local time) on the afternoon Aqua amplitude scale (13:30 local time). A missing bucket or fewer than three matched days uses the neutral factor `1.0`. Aqua is not multiplied by kappa, nor are the VIIRS estimates. The grouping date remains UTC; local overpass times describe the physical rationale and do not shift the calendar key.

**Orbital revisit weighting (Phase 4, `SPECS.md` §3.4(1)).** Sun-synchronous polar orbiters (inclination ≈ 98.2°) revisit high latitudes more often because their swaths converge: the relative daily revisit density at R7 centroid latitude φ_h is `π_orb(φ_h) / π_orb(0°) = sec(φ_h)`. The Horvitz-Thompson estimator divides each observation by that relative sampling probability, so the weight is the inverse, `cos(φ_h)`, not `sec(φ_h)`:

```text
φ_h      = h3.cell_to_latlng(h3_r7)[0]                       (centroid latitude, degrees)
w_orb(h) = clip(cos(φ_h), cos(80°), 1.0)  ∈ [0.173648, 1.0]

obs_terra_fre = P_cal,Terra * 3600 / A_h * kappa(h3_r4, month) * w_orb(h)
obs_aqua_fre  = P_cal,Aqua  * 3600 / A_h * w_orb(h)
obs_viirs_fre = mean over surviving VIIRS instruments of (P_cal,VIIRS * 3600 / A_h * w_orb(h))
```

- **Normalization:** `w_orb = 1.0` at the equator. Weighted densities are therefore expressed on the equatorial sampling scale.
- **Domain and clamp:** the revisit model covers φ_h ∈ [−81.8°, +81.8°]. The lower clamp at `cos(80°) ≈ 0.173648` bounds the weight for cells poleward of ±80°.
- **Single application:** Stage 04 multiplies each channel by `w_orb` exactly once, at the point where calibrated power becomes FRE density. Because the weight is constant per cell, weighting each VIIRS instrument before averaging equals weighting the mean. `neighbor_fre_lag1` is derived from the already-weighted channels and is not weighted again. DuckDB queries, the API and `backend/core/` must not re-apply it.
- **Orthogonality:** `kappa` is the separate, existing Terra-only diurnal correction. Aqua and VIIRS receive `w_orb` without `kappa`.
- **Unchanged fields:** `raw_frp_mw`, raw counts, masks and null semantics are untouched. A channel that is missing, in outage or cloud-occluded stays null; the weight only scales observed values.
- **Provenance:** the published Parquet metadata records `orbital_weighting = "w_orb = clip(cos(centroid_lat_h3_r7), cos(80 deg), 1.0); applied once to obs_terra_fre, obs_aqua_fre, obs_viirs_fre"`.
- **Limits:** `cos(φ)` is a first-order swath-convergence model. It does not use actual per-day swath geometry, scan angle or orbit tracks, and published real cubes acquire the weight only after a Stage 04 rebuild.

**Spatial lag.** First form each source cell-day's mean across its non-null Terra, Aqua and grouped-VIIRS FRE channels. Let J(h,t-1) be the cells in `grid_disk(h, 1)`, excluding h itself, whose resulting mean on exactly `epoch_day - 1` is positive. An ordinary R7 cell has six neighbors (H3 pentagons can have five). Then:

```text
neighbor_fre_lag1(h,t) = mean(source_cell_mean(j,t-1) for j in J(h,t-1))
neighbor_fre_lag1(h,t) = 0.0 when J(h,t-1) is empty
```

The mean is over active burning neighbors, not over all six locations; zero-energy neighbors do not dilute it. A measured zero remains a valid observation and does not become a blackout. Missing or occluded channels cannot contribute. Self, contemporaneous t, and older t-2 observations are excluded; there is no forward fill. The tests use valid FIRMS dates 2024-01-10 through 2024-01-12 (`epoch_day` 19732–19734), rather than literal epoch day 100 in 1970, which is outside the data contract.

**Hand-checkable regression inputs.** All Phase 2 CSVs, region definitions, lookups and cubes are created under pytest temporary directories. Cell `87390c014ffffff` at 40° N, 4° W has an exact area of approximately 5.338061472892 km². Identity-calibrated 10, 30 and 75 MW give approximately 6,744.021249, 20,232.063746 and 50,580.159365 MJ/km²/day before orbital weighting, respectively; since Phase 4 the assertions multiply these by the cell's `w_orb = cos(centroid latitude)` (≈ 0.766 for this cell) and use `pytest.approx` to accommodate FLOAT storage. The end-to-end fixture has three daily groups of Terra 10 + 20 MW and Aqua 75 MW, plus archive/NRT conflicts and an exact duplicate. It retains nine detections, yields kappa `225 / 90 = 2.5` from three matched days, and publishes three daily rows with both channels at `75 * 3600 / A_h`. Independent cases cover insufficient/missing ratios, midnight boundaries, separate instrument means, and active-neighbor lag averaging.

### Stage 02 outage evidence contract

`data/lookup/sensor_outages.parquet` has exactly these columns, in order:

| Column | DuckDB / Arrow type | Meaning |
| --- | --- | --- |
| `acq_date` | `DATE` / `date32[day]` | UTC calendar day |
| `satellite` | `VARCHAR` / `string` | Canonical instrument: `Terra`, `Aqua`, `SNPP`, `N20`, `N21` |
| `evidence` | `VARCHAR` / `string` | `known_outage` or `global_count_drop` |

Rows are unique and sorted by `(acq_date, satellite, evidence)`. The known evidence is exactly 15 `SNPP` / `known_outage` rows, inclusive from **2022-07-27 to 2022-08-10** (`KNOWN_OUTAGES` in the script). With the tracked global counts, the detector independently yields the same 15 `SNPP` / `global_count_drop` rows and nothing else. Staged regional detections are never used to infer global outages. Known and dynamic evidence can coexist for the same instrument-day; stage 04 consumes their distinct instrument-day pairs.

**Correction — 2026-11-14.** The interval was previously hard-coded as "Aqua safe mode, 2022-07-31..08-16" (17 days). FIRMS world counts contradict it: MODIS Aqua reported 6,881–20,844 global detections on every one of those days, and the local Iberia, Chilecito and Orlando raw CSVs contain Aqua detections on 2022-07-31. The previous cube therefore nulled 843 valid Aqua cell-days. The measured outage is Suomi NPP VIIRS: zero global detections from 2022-07-27 through 2022-08-10, 65,996 on 07-26 and 85,776 on 08-11, while NOAA-20 stayed at 50,799–91,918 per day. The synthetic fixture (`scripts/00`) deliberately keeps its 2022-07-31..08-16 Aqua blackout as a reconstruction stress scenario; it is not a historical claim.

**Tracked global counts.** `data/lookup/global_daily_counts.csv` holds Terra, Aqua, SNPP and NOAA-20 world totals for 2022-07-06..2022-08-24 (200 instrument-days, unique keys, explicit zeros). It was produced from the FIRMS area API (`/api/area/csv/{MAP_KEY}/{MODIS_SP|VIIRS_SNPP_SP|VIIRS_NOAA20_SP}/world/{≤5}/{date}`): every row of each standard-processing response was counted by `satellite` and UTC `acq_date`; a successful header-only day is an observed zero, and any failed or non-CSV response aborts the download, so a missing day is never written as zero. The MAP_KEY lives only in the untracked root `.env`. Stage 02 reads this file without network access.

A global-counts file (`--global-counts`, CSV or Parquet) must use the canonical instrument names above and unique `(satellite, acq_date)` keys. Dates are cast to `DATE`; `detection_count` is cast to `DOUBLE`. Counts represent nonnegative global daily totals, including explicit observed zeros. For each instrument and target day `t`, the detector evaluates:

```text
baseline = mean(counts on the 15 calendar days t-15 through t-1)
outage = all 15 preceding days have non-null counts
         AND baseline > 0
         AND detection_count(t) < 0.25 * baseline
```

The current day is excluded from the baseline. Equality at one-quarter does not trigger. Observed zero counts participate in the mean and a zero target triggers against a positive complete baseline. A missing calendar day, null preceding count, null target count, or all-zero baseline does not trigger. Older observations cannot fill a missing day in the 15-day window. Duplicate instrument-days raise `ValueError` before replacing the existing outage lookup, so repeated rows cannot fake a complete window. Count-source provenance remains the input provider's responsibility; synthetic count fixtures are confined to temporary test directories.

Stage 02 also writes `diurnal_ratios.parquet`: `h3_r4: UBIGINT/uint64`, `month: UTINYINT/uint8`, `ratio: DOUBLE/float64`, `matched_days: BIGINT/int64`, sorted by `(h3_r4, month)`. It aggregates coincident positive daytime Terra/Aqua FRP. Missing staging produces a correctly typed empty ratio table. Serial DuckDB aggregation and explicit output ordering make both files byte-reproducible for identical inputs and software versions.

### Stage 04 observation and gap semantics

`sensor_obs_mask` is an unsigned byte: Terra `1`, Aqua `2`, SNPP `4`, NOAA-20 (`N20`) `8`, NOAA-21 (`N21`) `16`. It describes usable observations after masking. A known or dynamic instrument outage removes only that instrument's observation and bit. The grouped `obs_viirs_fre` averages the surviving VIIRS instruments and is null only when none survives.

`gap_status_mask` is an unsigned byte whose flags combine with bitwise OR:

| Value | Meaning and offline evidence |
| --- | --- |
| `0` | No supported gap evidence on the staged cell-day |
| `1` | At least one instrument has an outage lookup entry on that date |
| `2` | Local ancillary cloud fraction is strictly greater than `0.80` |
| `4` | Reserved for a swath gap supported by coverage evidence; current inputs cannot establish it |
| `8` | All three observation channels are missing after outage/cloud masking |

Cell-day cloud occlusion applies to all instruments: the three FRE observations become Parquet nulls and `sensor_obs_mask` becomes zero. Therefore cloud-only blackout is `10` and cloud plus outage blackout is `11`; outage-only total blackout is `9`. Raw detection counts and raw FRP remain available for audit. Exactly `0.80` remains below the occlusion rule for both FLOAT and DOUBLE ancillary columns. Neighbor lag energy is calculated **after** masking, so occluded measurements cannot contribute to the next day's neighbor energy.

The builder still emits only staged cell-days. Neither an absent sensor detection nor an absent cell-day proves a swath gap; it does not invent a dense calendar or set bit `4`. Positive swath-gap validation requires an additional documented coverage source and remains open.

The optional ancillary file uses unique `(h3_r7, acq_date)` keys, cloud fractions in `[0, 1]`, and finite nonnegative burned area in hectares. Missing rows or null values retain the frozen non-null columns' zero sentinel. The JSON Parquet metadata key `ancillary_coverage` records `input_present` and, for each of `cloud_cover_pct` and `burned_area_ha_mcd64`, `observed_rows`, `missing_rows`, and `observed_zero_rows` over published cell-days. An observed zero counts as observed, never missing. These are aggregate provenance counts: an individual zero in a partially covered cube still requires the original ancillary join to distinguish its provenance. Do not treat all zero sentinels as measured clear sky or measured zero burned area.

### Phase 5 local verification — 2026-11-14

Inspection of every CSV header and Parquet schema under `data/raw/` and `data/lookup/` found **no global daily count table** and **no `cell_day_ancillary.parquet`**. The existing `cloud_outages.parquet` has 9,496 rows with `date`, `epoch_day`, `cloud_cover_pct`, and `gap_status_mask`, but no H3 key or provenance metadata. It is not the required cell-day reanalysis input and is not consumed as one.

Two consecutive runs of `python scripts/02_detect_outages_clouds.py` from `firms-harmonizer/` produced identical bytes:

| Output | Rows | SHA-256 |
| --- | ---: | --- |
| `sensor_outages.parquet` | 17 | `6ac6b1bec13f35cac06a39135b7386fa69367c788dbcd2faf1bea2038feb9d98` |
| `diurnal_ratios.parquet` | 2,075 | `5d884f0523f349b5c39907b292b6722648bd9560fe80a84061910e31e48945bb` |

The outage dates exactly match the 17-day interval in `SPECS.md` §3.4. Evidence is the specification's known interval; diurnal ratios come from the existing local staged FIRMS file. The test suite checks repeated CLI execution, strict dynamic threshold boundaries, observed zeros, incomplete calendar windows, per-instrument partitioning, duplicate rejection, all five sensor bits, Aqua null propagation, surviving VIIRS instruments, combined blackout bits, cloud FLOAT/DOUBLE boundaries, neighbor lag exclusion, and ancillary metadata. All synthetic global counts and cloud inputs used for those checks are temporary fixtures, not production lookups. Actual global-count and cloud-reanalysis validation remain open.

### Differential review — Phase 5, 2026-11-14

**Baseline and scope:** working tree against `9a25bc1`; focused review of scripts 02 and 04, the cube schema tests, and the two authorized documentation files. The initial working tree was clean. Logic changes carry medium correctness risk; tests and documentation carry low risk. No new security finding was identified (critical/high/medium/low: 0/0/0/0); this is a scoped assessment, not a repository-wide security audit.

**Historical context:** `git log` and `git blame` trace the affected detector and ancillary logic to `da497a6`; real-only atomic publication safeguards were introduced by `c2b3ed6` and remain intact. No authentication, network, API, core, database-service, or frontend code was changed, and no validation was removed.

**Changes and regression evidence:** tests first reproduced non-reproducible outage ordering, duplicate counts faking a complete window, cloud observations surviving masking, missing blackout flags, absent ancillary provenance counts, and FLOAT `0.80` crossing the boundary after conversion to Python double. The implementation now sorts evidence, serializes stage 02 aggregation, rejects duplicate count keys, masks clouds before neighbor aggregation, marks total blackouts, and records ancillary coverage. The new tests exercise actual CLI processes and local Parquet publication; they do not call HTTP or the Kalman adapter.

**Blast radius:** `build_outages_table` has one production caller (script 02 CLI); `real_rows` has one (the master builder); `build_master_cube` has one (script 04 CLI). Their outputs feed offline lookup/cube consumers. The 18-column cube contract, raw observation counts, real/synthetic separation, and atomic master replacement are preserved. No changed production function lacks focused regression coverage; no numerical coverage percentage is claimed.

**Recommendation:** accept the offline fixes subject to the remaining real-data validation tasks. Positive swath inference, actual global counts, and cloud reanalysis are not validated. Aggregate ancillary metadata does not provide per-row provenance. Existing published real cubes require an explicit stage 04 rebuild to acquire these changes; this verification does not replace the current real master. Confidence is high for the tested local behavior and limited for unavailable external evidence. No network requests were made.

### Phase 2 verification and differential review — 2026-11-14

**Result:** `python -m pytest backend/tests/test_cube_schema.py -v` from `firms-harmonizer/` exited 0 with **47 passed in 13.60s** (37 existing cases plus 10 Phase 2 cases). Data source: deterministic temporary fixtures and the integration contract above. No network call or production cube publication was performed. The existing bootstrap CLI test now runs an unchanged copy of script 00 inside a temporary project, preserving the foreign-working-directory/default-path check while avoiding production output.

**Baseline and review scope:** focused review against `0a6d8e7`, with the pre-existing uncommitted Phase 2 planning addition retained and its checklist completed. Reviewed all four changed files: the master builder (medium correctness risk), cube schema tests, ETL specification, and implementation plan (low risk). Scripts 01 and 02 were inspected and exercised without requiring implementation changes. No frozen schema, API, DB, core, or frontend file was edited.

**Finding and fix:** the initial focused run had nine passes and one failure: a 10 MW burning neighbor plus a measured-zero neighbor yielded 3,372.644531 MJ/km²/day instead of 6,745.289150 for that source cell's exact area. `real_rows` now filters the lag's contributors to positive cell-mean energy. It still records a measured zero as an observation and does not add a blackout bit. The focused run then passed all ten cases; the final gate also checks the existing outage/cloud exclusions. No remaining security findings were identified in the changed code (critical/high/medium/low: 0/0/0/0); this is not a whole-repository security audit.

**Historical context and blast radius:** `git blame` traces the lag loop to the Phase 5 changes in `5424d74` and exact-record normalization to `da497a6`. `real_rows` has one production caller, `build_master_cube`, which has one production caller, the script 04 CLI. The only production change is the positive-energy predicate and its explanatory comment. No input validation, atomic publication safeguard, or observation field is removed. Expected output changes are confined to next-day neighbor means that previously included zero-energy cells.

**Coverage and limits:** new tests cover deduplication identity and priority, pass summation, separate instruments, exact H3 area, UTC midnight, daytime ratio generation, sufficient/insufficient/missing strata, self and temporal leakage, and one/two/no active neighbors. The changed branch has positive-and-zero, two-positive, and all-zero regression cases. No code-coverage percentage is claimed. The review confirms the proxy and identity-calibration arithmetic; it does not validate the nonlinear EQM model, true fire duration, scientific API integration, or real-data accuracy. No broader HTTP suite was run for this isolated offline task. Recommendation: accept Phase 2 implementation validation, keeping the other phases' scientific and real-input acceptance gates open.

**Production artifact preservation:** the file set, byte sizes, modification timestamps and SHA-256 hashes under `data/processed/` were identical before and after the tests:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `fire_cube_synthetic.parquet` | 6,997,103 | `828edce7f579ba5abac21aa3d3c20b0c13ceadcfba438f18af786edb0dea9254` |
| `staged_firms.parquet` | 38,476,797 | `7b8db663f562e44a98827f1dae26a081263d904d7860bf69e6bb135723b49f88` |

<details>
<summary>Exact Phase 2 pytest output — 2026-11-14</summary>

Command: `python -m pytest backend/tests/test_cube_schema.py -v`

```text
============================= test session starts =============================
platform win32 -- Python 3.12.6, pytest-9.1.1, pluggy-1.6.0 -- C:\Users\germa\AppData\Local\Programs\Python\Python312\python.exe
cachedir: .pytest_cache
rootdir: C:\vscode\proyectos\Almenara\firms-harmonizer\backend
configfile: pyproject.toml
plugins: anyio-4.15.1, platformdirs-4.12.4, cov-7.1.0, time-machine-2.16.0
collecting ... collected 47 items

backend\tests\test_cube_schema.py::test_stage01_deduplication_exact_records PASSED [  2%]
backend\tests\test_cube_schema.py::test_stage04_eulerian_fre_conversion_and_units PASSED [  4%]
backend\tests\test_cube_schema.py::test_stage02_diurnal_ratio_uses_positive_coincident_daytime_sums PASSED [  6%]
backend\tests\test_cube_schema.py::test_stage04_diurnal_scaling_terra_to_aqua[3] PASSED [  8%]
backend\tests\test_cube_schema.py::test_stage04_diurnal_scaling_terra_to_aqua[5] PASSED [ 10%]
backend\tests\test_cube_schema.py::test_stage04_neighbor_lag1_alignment PASSED [ 12%]
backend\tests\test_cube_schema.py::test_stage04_neighbor_lag_averages_only_active_burning_cells[powers0] PASSED [ 14%]
backend\tests\test_cube_schema.py::test_stage04_neighbor_lag_averages_only_active_burning_cells[powers1] PASSED [ 17%]
backend\tests\test_cube_schema.py::test_stage04_neighbor_lag_averages_only_active_burning_cells[powers2] PASSED [ 19%]
backend\tests\test_cube_schema.py::test_phase2_csv_to_cube_preserves_energy_and_empirical_scaling PASSED [ 21%]
backend\tests\test_cube_schema.py::test_stage02_known_aqua_interval_is_exact_and_reproducible PASSED [ 23%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history0-24.0-True] PASSED [ 25%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history1-25.0-False] PASSED [ 27%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history2-0.0-True] PASSED [ 29%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history3-24.0-False] PASSED [ 31%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history4-23.0-True] PASSED [ 34%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history5-0.0-False] PASSED [ 36%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history6-0.0-False] PASSED [ 38%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history7-0.0-False] PASSED [ 40%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history8-None-False] PASSED [ 42%]
backend\tests\test_cube_schema.py::test_stage02_missing_calendar_day_does_not_trigger PASSED [ 44%]
backend\tests\test_cube_schema.py::test_stage02_duplicate_days_cannot_fake_a_complete_window PASSED [ 46%]
backend\tests\test_cube_schema.py::test_stage04_aqua_outage_and_five_instrument_bits PASSED [ 48%]
backend\tests\test_cube_schema.py::test_stage04_viirs_outages_preserve_remaining_instrument PASSED [ 51%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type0-0.0-0-False] PASSED [ 53%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type0-0.8-0-False] PASSED [ 55%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type0-0.8001-10-True] PASSED [ 57%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type0-1.0-10-True] PASSED [ 59%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type1-0.0-0-False] PASSED [ 61%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type1-0.8-0-False] PASSED [ 63%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type1-0.8001-10-True] PASSED [ 65%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type1-1.0-10-True] PASSED [ 68%]
backend\tests\test_cube_schema.py::test_stage04_ancillary_metadata_distinguishes_missing_and_observed_zero PASSED [ 70%]
backend\tests\test_cube_schema.py::test_missing_staging_preserves_existing_master PASSED [ 72%]
backend\tests\test_cube_schema.py::test_mock_and_request_contract PASSED [ 74%]
backend\tests\test_cube_schema.py::test_exact_schema_and_compression PASSED [ 76%]
backend\tests\test_cube_schema.py::test_sorted_and_unique PASSED         [ 78%]
backend\tests\test_cube_schema.py::test_four_regions_and_daily_coverage PASSED [ 80%]
backend\tests\test_cube_schema.py::test_calendar_keys_and_value_ranges PASSED [ 82%]
backend\tests\test_cube_schema.py::test_outages_and_sensor_masks PASSED  [ 85%]
backend\tests\test_cube_schema.py::test_required_outage_dates_in_duckdb[2022-08-10-sensors0] PASSED [ 87%]
backend\tests\test_cube_schema.py::test_required_outage_dates_in_duckdb[2022-08-24-sensors1] PASSED [ 89%]
backend\tests\test_cube_schema.py::test_instrumental_jump_and_physical_stability PASSED [ 91%]
backend\tests\test_cube_schema.py::test_industrial_and_climate_scenarios PASSED [ 93%]
backend\tests\test_cube_schema.py::test_generator_repeatability_performance_and_alternate_path PASSED [ 95%]
backend\tests\test_cube_schema.py::test_h3_compatibility_adapters[3] PASSED [ 97%]
backend\tests\test_cube_schema.py::test_h3_compatibility_adapters[4] PASSED [100%]

============================= 47 passed in 13.60s =============================
```

</details>

## Verification

Run `python scripts/00_bootstrap_synthetic_cube.py` followed by `python -m pytest backend/tests/test_cube_schema.py -q` for the synthetic gate. The schema suite generates its own temporary fixture. Run script 04 to publish the real cube. For the real output, check the 18 field types and nullability, ZSTD compression, ordering, unique keys, real row counts and footprint energy conservation. Script 05 exits nonzero when the measured project thresholds are unmet.

<details>
<summary>Exact Phase 5 acceptance output — 2026-11-14</summary>

Commands run from `firms-harmonizer/`; both exited with code 0:

```powershell
python scripts/02_detect_outages_clouds.py
python scripts/00_bootstrap_synthetic_cube.py && python -m pytest backend/tests/test_cube_schema.py -v
```

```text
Wrote sensor_outages.parquet and diurnal_ratios.parquet.
Synthetic cube: C:\vscode\proyectos\Almenara\firms-harmonizer\data\processed\fire_cube_synthetic.parquet (0.982s)
============================= test session starts =============================
platform win32 -- Python 3.12.6, pytest-9.1.1, pluggy-1.6.0 -- C:\Users\germa\AppData\Local\Programs\Python\Python312\python.exe
cachedir: .pytest_cache
rootdir: C:\vscode\proyectos\Almenara\firms-harmonizer\backend
configfile: pyproject.toml
plugins: anyio-4.15.1, platformdirs-4.12.4, cov-7.1.0, time-machine-2.16.0
collecting ... collected 37 items

backend\tests\test_cube_schema.py::test_stage02_known_aqua_interval_is_exact_and_reproducible PASSED [  2%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history0-24.0-True] PASSED [  5%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history1-25.0-False] PASSED [  8%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history2-0.0-True] PASSED [ 10%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history3-24.0-False] PASSED [ 13%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history4-23.0-True] PASSED [ 16%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history5-0.0-False] PASSED [ 18%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history6-0.0-False] PASSED [ 21%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history7-0.0-False] PASSED [ 24%]
backend\tests\test_cube_schema.py::test_stage02_global_counts_complete_window[history8-None-False] PASSED [ 27%]
backend\tests\test_cube_schema.py::test_stage02_missing_calendar_day_does_not_trigger PASSED [ 29%]
backend\tests\test_cube_schema.py::test_stage02_duplicate_days_cannot_fake_a_complete_window PASSED [ 32%]
backend\tests\test_cube_schema.py::test_stage04_aqua_outage_and_five_instrument_bits PASSED [ 35%]
backend\tests\test_cube_schema.py::test_stage04_viirs_outages_preserve_remaining_instrument PASSED [ 37%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type0-0.0-0-False] PASSED [ 40%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type0-0.8-0-False] PASSED [ 43%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type0-0.8001-10-True] PASSED [ 45%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type0-1.0-10-True] PASSED [ 48%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type1-0.0-0-False] PASSED [ 51%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type1-0.8-0-False] PASSED [ 54%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type1-0.8001-10-True] PASSED [ 56%]
backend\tests\test_cube_schema.py::test_stage04_cloud_masks_observations_before_neighbor_lag[cloud_type1-1.0-10-True] PASSED [ 59%]
backend\tests\test_cube_schema.py::test_stage04_ancillary_metadata_distinguishes_missing_and_observed_zero PASSED [ 62%]
backend\tests\test_cube_schema.py::test_missing_staging_preserves_existing_master PASSED [ 64%]
backend\tests\test_cube_schema.py::test_mock_and_request_contract PASSED [ 67%]
backend\tests\test_cube_schema.py::test_exact_schema_and_compression PASSED [ 70%]
backend\tests\test_cube_schema.py::test_sorted_and_unique PASSED         [ 72%]
backend\tests\test_cube_schema.py::test_four_regions_and_daily_coverage PASSED [ 75%]
backend\tests\test_cube_schema.py::test_calendar_keys_and_value_ranges PASSED [ 78%]
backend\tests\test_cube_schema.py::test_outages_and_sensor_masks PASSED  [ 81%]
backend\tests\test_cube_schema.py::test_required_outage_dates_in_duckdb[2022-08-10-sensors0] PASSED [ 83%]
backend\tests\test_cube_schema.py::test_required_outage_dates_in_duckdb[2022-08-24-sensors1] PASSED [ 86%]
backend\tests\test_cube_schema.py::test_instrumental_jump_and_physical_stability PASSED [ 89%]
backend\tests\test_cube_schema.py::test_industrial_and_climate_scenarios PASSED [ 91%]
backend\tests\test_cube_schema.py::test_generator_repeatability_performance_and_alternate_path PASSED [ 94%]
backend\tests\test_cube_schema.py::test_h3_compatibility_adapters[3] PASSED [ 97%]
backend\tests\test_cube_schema.py::test_h3_compatibility_adapters[4] PASSED [100%]

============================= 37 passed in 11.13s =============================
```

</details>

## Iberia FIRMS archive

The `iberia_med` ingest region uses west/south/east/north bounds `[-9.5, 36, 4, 44]` and the declared request window 2000-11-01 through 2026-11-01. The archive includes land outside Spain. A country-only study needs an explicit administrative polygon. The original frontend preset covers a smaller area.

Eight files named `spain_fire_*.csv` are staged directly under `data/raw/`. FIRMS request IDs are 847720 (MODIS), 847721 (NOAA-20), 847722 (NOAA-21) and 847723 (Suomi-NPP). Download notes are under `data/raw/spain_download_notes/`.

## Orlando and Amazonas FIRMS archives — 2026-11-14

Two additional user-supplied packages are registered in `data/regions.json` and copied directly into `data/raw/` with region prefixes. Their full file inventory and original-byte SHA-256 hashes are recorded in `data/raw/orlando_amazonas_manifest.json`; the eight generic FIRMS notes are preserved under `data/raw/orlando_amazonas_download_notes/`. Original local uploads are retained outside the ingest glob.

| Region key | Bounds (west, south, east, north) | Configured date span | Raw files / rows | Nominal IGBP fallback |
| --- | --- | --- | --- | ---: |
| `orlando_florida` | `[-82, 28, -80.7, 29.3]` | 2000-11-01 to 2026-10-30 | 8 / 52,943 | 8 |
| `amazonas_manaus` | `[-62, -5, -58, -1]` | 2000-11-01 to 2026-11-01 | 8 / 390,954 | 2 |

These date spans are the first/last detections in the supplied packages. The generic download notes do not establish the original requested date interval or daily completeness. Bounds enclose the source coordinates; nominal biome classes are documented regional fallbacks, not observed MCD12Q1 classes. Amazonas here means the Manaus-area rectangle, distinct from the Cerrado/Pantanal demo AOI.

Each package includes archive and NRT observations from Terra/Aqua MODIS, SNPP, NOAA-20 and NOAA-21. FIRMS request IDs 848215–848218 identify Orlando and 848219–848222 identify Amazonas. Original `archive` and `nrt` labels are retained, so stage 01's deduplication priority is unchanged. Four temporary-fixture integration cases verify ingest and publication for Chilecito, Iberia, Orlando and Amazonas.

The 16 new CSVs are tracked explicitly in Git at the user's request; generated Parquet remains excluded and can be rebuilt with stages 01–04. Earlier Chilecito/Iberia raw packages remain local and are required to reproduce a four-region cube. The incoming frontend merge is retained; this ETL import does not change its preset list or API contracts.

## Four-region real cube publication — 2026-11-14

Stages 01–04 were run in order from `firms-harmonizer/` on the local FIRMS CSVs of `amazonas_manaus`, `chilecito_la_rioja`, `iberia_med` and `orlando_florida`, without network access or credentials. Staging held 1,574,092 deduplicated detections and 1,870,624 footprint contributions. The cube includes the Phase 4 orbital revisit weight.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `staged_firms.parquet` | 52,291,869 | `436bc71c1b1bc89b30741faf61add63c1a001b0b4c9ee6a48fad79082233be99` |
| `fire_cube.parquet` | 10,900,199 | `1ed635f787564376470c284c834bf4512e090c1a2b212c4c70542f9a31dd6f3a` |
| `sensor_outages.parquet` | 737 | `6ac6b1bec13f35cac06a39135b7386fa69367c788dbcd2faf1bea2038feb9d98` |
| `diurnal_ratios.parquet` | 27,558 | `2a66f7251cc170f11a66a25b26d5b8991602b18500becf567d989b0a25ac6656` |
| `eqm_gpd_lut.json` | 13,918 | `8ede60e41ca06a62f441d34e0f7339a82c53d0b449e32f2abcd69d5cc34a019c` |

The cube has 761,801 unique cell-days from 2000-11-01 to 2026-11-01 (center cell-days: Manaus 191,509; Chilecito 37,955; Iberia 384,226; Orlando 24,752). The publication checks above pass: 18-field schema and nullability, ZSTD, real-only provenance, unique ascending keys, 1970 UTC calendar consistency, raw FRP (34,804,483 MW) and detection-count conservation, unit footprint weights, NOAA-21 bit 16 on 86,348 rows, sensor bits matching non-null channels, no Aqua values in the 2022 Safe Mode interval, and finite non-negative FRE. No ancillary file was present, so metadata records all rows as missing cloud and burned-area input rather than observed zero.

Script 05 exits 1 on this cube. Warmed P95 is 17.92–60.10 ms against the 15 ms target, Chow p ≤ 0.010, burned-area R² is undefined without MCD64A1 input, recovery is 71.8–95.5%, and the `cerrado_brazil`, `california_usa` and `niger_delta_flaring` presets have no real rows. These are open acceptance results, not build failures.

## Phase 5/6 republication — 2026-11-14

Stages 02 and 04 were rerun on the unchanged staging (`436bc71c…`) after the Phase 6 harmonization unification and the Phase 5 outage correction; stage 03 regenerated the LUT from the same staging. No network access was used.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `fire_cube.parquet` | 10,950,174 | `dc0ce0b87ee50cf2adc7dc3f1457ccf57335c4ed85ff1c9cc6ab83cc6d5340ae` |
| `sensor_outages.parquet` | 788 | `3b3b000205daeca55dfe3876bd1b0148ee40faf72eb456ccf8cf6982bf9d64fc` |
| `eqm_gpd_lut.json` | 102,760 | `e34f78c8cb228b78d9e04d5e70503559ce79662dea6c6151d76a4f829aa26451` |
| `global_daily_counts.csv` (tracked input, LF) | 4,309 | `447b6c6754b0949da80fd0d7b14ac0d83da89fd17a868ba2d0d8ea15019e6735` |

The cube keeps 761,801 unique cell-days, 24 ZSTD row groups and a verified ascending `(h3_r4, epoch_day, h3_r7)` order (PyArrow lexsort). Publication checks pass: schema, ZSTD, real-only provenance, unique keys, calendar consistency, four populated regions, raw FRP (34,804,483 MW) and detection (1,574,092) conservation, footprint weights summing to 1, NOAA-21 bit 16 on 86,348 rows, sensor bits matching non-null channels, finite non-negative FRE, and the corrected outage: across 2,020 cell-days in 2022-07-27..08-10 no row carries SNPP bit 4, every row carries outage bit 1, and 618 keep Aqua values. Across 2022-07-31..08-16, 843 Aqua cell-days that the previous cube nulled are now published. Metadata records `radiometric_harmonization`. A live uvicorn smoke test served `data_source=real` and schema-valid `/api/analyze` (9,496 days, audit present, cache HIT on repeat) and `/api/chaos-monkey` responses for Chilecito, Iberia, Orlando and Manaus; `python -m backend.check_core` exits 0 on the real cube.
