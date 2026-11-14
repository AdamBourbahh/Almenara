# NASA FIRMS Raw Data Inventory — Chilecito & La Rioja (CONAE Study Region)

## 1. Overview & Geographic Bounding Box
This directory contains official raw satellite active fire observation CSVs acquired from **NASA LANCE / MODAPS FIRMS Archive Download** (`firms.modaps.eosdis.nasa.gov/download/`) covering the official CONAE Chilecito / La Rioja demonstration area.

- **Target Region:** Chilecito, La Rioja & NOA, Argentina
- **Bounding Box (`West, South, East, North`):** `-69.5, -31.0, -65.5, -27.5`
- **Temporal Coverage:** `2000-11-01` to `2026-11-14` (26 continuous years)
- **Total Validated Hotspots:** **108,072 detections**

---

## 2. File Inventory & Sensor Breakdown

| Filename | Satellite / Instrument | Product Tier | Temporal Span | Hotspot Count |
| :--- | :--- | :--- | :--- | :--- |
| `chilecito_modis_archive_2000_2026.csv` | Terra & Aqua (MODIS) | Standard Quality (`MCD14ML`) | 2000-11-05 – 2026-07-31 | 23,133 |
| `chilecito_modis_nrt_2026.csv` | Terra & Aqua (MODIS) | Near Real-Time (NRT) | 2026-08-01 – 2026-11-14 | 113 |
| `chilecito_viirs_snpp_archive_2012_2026.csv` | Suomi-NPP (VIIRS 375m) | Standard Quality (`VNP14IMGML`) | 2012-01-21 – 2026-07-31 | 47,473 |
| `chilecito_viirs_snpp_nrt_2026.csv` | Suomi-NPP (VIIRS 375m) | Near Real-Time (NRT) | 2026-08-01 – 2026-11-01 | 578 |
| `chilecito_viirs_noaa20_archive_2018_2026.csv` | NOAA-20 / JPSS-1 (VIIRS 375m) | Standard Quality (`VJ114IMGML`) | 2018-04-03 – 2026-07-31 | 26,644 |
| `chilecito_viirs_noaa20_nrt_2026.csv` | NOAA-20 / JPSS-1 (VIIRS 375m) | Near Real-Time (NRT) | 2026-08-01 – 2026-11-14 | 594 |
| `chilecito_viirs_noaa21_archive_2023_2026.csv` | NOAA-21 / JPSS-2 (VIIRS 375m) | Standard Quality (`VJ214IMGML`) | 2023-01-01 – 2026-07-31 | 9,020 |
| `chilecito_viirs_noaa21_nrt_2026.csv` | NOAA-21 / JPSS-2 (VIIRS 375m) | Near Real-Time (NRT) | 2026-08-01 – 2026-11-14 | 517 |

> [!NOTE]
> **Suomi-NPP Mission Operational End Note:**
> Suomi-NPP officially stopped transmitting science data on **November 2, 2026**. The NRT file `chilecito_viirs_snpp_nrt_2026.csv` captures observations up to `2026-11-01`. Continuity is seamlessly maintained through NOAA-20 and NOAA-21.

---

## 3. Raw Column Dictionary & Harmonization Mapping

| Raw CSV Column | Description & Units | MODIS Format | VIIRS 375m Format | Mapping in `scripts/01_ingest_firms.py` |
| :--- | :--- | :--- | :--- | :--- |
| `latitude`, `longitude` | Coordinates (WGS84) | Decimal degrees | Decimal degrees | Indexed to Uber H3 Res 4 and Res 7 |
| `scan`, `track` | Pixel footprint size (km) | $1.0 \times 1.0$ (nadir) to $4.8 \times 2.0$ | $0.375 \times 0.375$ (nadir) to $0.75 \times 0.75$ | Along-track bow-tie overlap correction $\eta = \min(1, 1/\text{track})$ |
| `acq_date`, `acq_time` | Acquisition date & UTC time | `YYYY-MM-DD`, `HHMM` | `YYYY-MM-DD`, `HHMM` | Mapped to `epoch_day` (days since 2000-01-01) |
| `frp` | Fire Radiative Power (MW) | Float (MW) | Float (MW) | Calibrated via EQM lookup table (`03_train_eqm_lut.py`) |
| `brightness` | Mid-Infrared brightness (K) | Channel 21/22 ($\sim 4\,\mu\text{m}$) | Channel I4 ($\sim 3.74\,\mu\text{m}$) | Brightness temperature $T_4$ |
| `bright_t31` | Thermal-Infrared brightness (K) | Channel 31 ($\sim 11\,\mu\text{m}$) | Channel I5 ($\sim 11.45\,\mu\text{m}$) | Thermal contrast $\Delta T_{4/11} = T_4 - T_{11}$ |
| `confidence` | Detection confidence | Integer `0..100` | Categorical `'l'`, `'n'`, `'h'` | Unified into `'low'`, `'nominal'`, `'high'` |
| `daynight` | Solar illumination | `'D'` (Day), `'N'` (Night) | `'D'` (Day), `'N'` (Night) | Diurnal cycle weighting $\kappa(\tau_s)$ |
| `type` | Presumed source type | `0` (veg), `1` (volcano), `2` (static), `3` (offshore) | `0` (veg), `1` (volcano), `2` (static), `3` (offshore) | Present in Archive SP; imputed as `0` in NRT |

---

## 4. Pipeline Ingestion & Validation Gate

To ingest these raw CSVs into the physical pipeline:

```bash
cd firms-harmonizer
# 1. Ingest raw CSVs -> staged Parquet (calculates H3 Res 4/7 and bow-tie weights)
python scripts/01_ingest_firms.py

# 2. Build or update the physical master cube
python scripts/04_build_master_cube.py

# 3. Verify schema regression gate
pytest backend/tests/test_cube_schema.py -v
```
