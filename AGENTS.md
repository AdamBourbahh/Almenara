# AGENTS.md — NASA Space Apps 2026: MODIS & VIIRS Fire Harmonization Engine

## 1. Mission Context & Operational Purpose
This repository implements the solution for the **NASA Space Apps 2026 Challenge: "Harmonization of MODIS and VIIRS Hot Spots"**, authored by Marina Compagnucci (CONAE — Comisión Nacional de Actividades Espaciales, Argentina)[cite: 8].

* **The Core Problem:** MODIS and VIIRS have tracked active thermal anomalies for over two decades, but their datasets cannot be directly compared due to differences in spatial resolution ($1\text{ km}$ vs. $375\text{ m}$), radiometric sensitivity ($\sim 8\text{ MW}$ vs. $\sim 0.5\text{ MW}$), and orbital overpass times[cite: 1, 8, 11]. As MODIS reaches the end of its operational life and is replaced by VIIRS, failing to harmonize both records risks losing nearly 10 years of comparable baseline history[cite: 8, 11].
* **Operational Mandate:** Emergency response teams rely on two critical tools: (1) near-real-time active fire monitoring and spread projection, and (2) the **Burning / Fire Activity Calendar** to detect seasonal trends, regime shifts, and anomalies across years[cite: 8, 10].
* **Mission Deliverable:** Produce a sensor-agnostic, physically homogeneous 26-year time series (2000–2026) of **Spatial Fire Radiative Energy Density ($\text{FRE}$ in $\text{MJ}\cdot\text{km}^{-2}\cdot\text{day}^{-1}$)** mapped onto a hierarchical Uber H3 hexagonal grid, served inside a zero-bloat, 60 FPS interactive web application[cite: 1, 5, 6, 8, 9].

## 2. Architecture & Stack (Zero-Bloat)
* **Analytical & ETL Engine:** Python + DuckDB (compiled with `spatial`, `h3`, and `parquet` extensions) + Polars[cite: 5]. Do NOT use heavy transactional databases (PostgreSQL/PostGIS)[cite: 5].
* **Columnar Storage:** Apache Parquet with `ZSTD` compression, physically sorted on disk by `(h3_r4, year, day_of_year, h3_r7)` to maximize Row Group Pruning[cite: 5].
* **Backend API:** FastAPI + Uvicorn streaming pure binary buffers via **Apache Arrow IPC** (`application/vnd.apache.arrow.stream`)[cite: 5]. Target query latency: **< 15 ms**[cite: 5, 6].
* **Scientific Frontend (60 FPS):** React/TypeScript + Deck.gl (`H3HexagonLayer` + `DataFilterExtension` on GPU) + MapLibre GL JS + local PMTiles[cite: 5, 6]. Do NOT serialize/deserialize large JSON payloads on the client[cite: 5].

## 3. Strict Engineering Guardrails & Anti-Patterns
1. **NEVER treat hotspots as dimensionless `(lat, lon)` points:** Every detection must be projected using its off-nadir bivariate Gaussian footprint (`scan` × `track`) onto H3 Resolution 7 cells[cite: 1, 2].
2. **NEVER use raw detection counts (`COUNT(*)`) as the primary metric:** Raw counts are stored exclusively to power the *"Before: Broken Raw Data"* comparison toggle during the live pitch[cite: 1, 5, 6].
3. **Zero JSON for bulk geospatial transfers:** Backend responses must stream Apache Arrow binary buffers directly into WebGL `TypedArrays` (`Float32Array`)[cite: 5].
4. **Offline-First Resilience (Airplane Mode):** All map base tiles, IGBP biome geometries (`MCD12Q1`), the Parquet data cube, and demo region caches must run 100% locally without internet access[cite: 6].
5. **Empirical Validation Gate:** No harmonization module is complete unless it passes live statistical auditing: Chow Structural Break Test at Jan 2012 ($p > 0.10$), Wasserstein-1 distance reduction ($> 88\%$), and cross-validation ($R^2$) against independent `MCD64A1` burned area scars[cite: 1].

## 4. Data Contract: Master Cube Schema (`fire_cube.parquet`)
All offline ETL pipelines must output a single consolidated Parquet file sorted by `(h3_r4, epoch_day, h3_r7)` adhering strictly to this schema[cite: 5]:

| Column | Type | Description |
| :--- | :--- | :--- |
| `h3_r4` | `UINT64` | Uber H3 Resolution 4 index (primary spatial partition key)[cite: 5]. |
| `h3_r7` | `UINT64` | Uber H3 Resolution 7 index ($\sim 5.16\text{ km}^2$, native harmonization scale)[cite: 2, 5]. |
| `epoch_day` | `UINT16` | Days elapsed since `2000-01-01` (GPU time-window filter key)[cite: 5]. |
| `igbp_biome` | `UINT8` | Land cover class from `MCD12Q1` ($1..17$)[cite: 2, 5]. |
| `raw_modis_count` | `UINT16` | Uncalibrated MODIS detection count (for "Before" visual comparison)[cite: 5]. |
| `raw_viirs_count` | `UINT16` | Uncalibrated VIIRS detection count (for "Before" visual comparison)[cite: 5]. |
| `raw_frp_sum` | `FLOAT32` | Uncalibrated raw FRP sum in MW[cite: 5]. |
| `harm_fre_mj_km2` | `FLOAT32` | Harmonized Fire Radiative Energy density ($\text{MJ}\cdot\text{km}^{-2}\cdot\text{day}^{-1}$)[cite: 1, 5]. |
| `ci_lower_95` | `FLOAT32` | Lower 95% confidence bound (from RTS Kalman smoother gap-filling)[cite: 5]. |
| `ci_upper_95` | `FLOAT32` | Upper 95% confidence bound (from RTS Kalman smoother gap-filling)[cite: 5]. |
| `industrial_prob` | `FLOAT32` | Probability $[0, 1]$ of stationary anthropogenic heat source (Shannon entropy)[cite: 4, 5]. |