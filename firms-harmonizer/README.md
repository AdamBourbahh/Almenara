# FIRMS Harmonizer

Local analysis of NASA MODIS/VIIRS fire detections and derived sampled fire radiative energy. The four study regions are **Chilecito / La Rioja**, **Iberia**, **Orlando / Florida**, and **Amazonas / Manaus**.

## Scientific meaning

The ETL deduplicates sensor/time/location identities, distributes MODIS footprints over H3 R7 cells, applies EQM calibration, and assigns an effective one-hour FRP integration window. This produces an **energy proxy**, not a measured continuous daily energy integral.

Sensors are fused within each cell before spatial aggregation. Energy is the sum of each cell's density times its exact H3 area. The regional density is that sum divided by the WGS84 polygon area. Biomass uses 0.368 kg dry matter/MJ. The map selects cells by their centres; energy is not clipped to sub-cell polygon intersections.

A missing detection row is not evidence of either no fire or a satellite outage. The calendar distinguishes detected energy, mask-supported observed zeros, reconstruction across evidenced gaps, unknown coverage, and forecasts. Unknown dates remain unfilled and their physical values are blank in CSV exports. Totals describe sampled/reconstructed support; they are not complete inventories of all fires.

## Available features

- Map, daily/monthly/yearly spatial queries, raw observations, a single-canvas calendar, seasonal trends and research CSV exports.
- Five instrument labels, true polygon area, explicit real/synthetic input provenance and bounded analytical requests/caches.
- Published EOG upstream flare-site evidence combined with temporal persistence. The catalogue does not cover every kind of industrial heat; the score is not a calibrated probability. Controls appear only when the analysis contains matches.
- Chaos Monkey with the target year excluded from the prior/calibration, affected spatial forcing removed, and errors/energy recovery measured on affected days. Its intact-input reference is not independently observed physical truth.
- A causal seasonal/AR FRE forecast with area-weighted multi-sensor land coverage and temporal selection of a coverage threshold (70/80/90/95%). A reserved final year must confirm baseline and interval skill; otherwise the forecast stays unavailable. Run script 13 to build coverage indexes and the comparison report. This is separate from the thermal-event risk model.
- Primary PM2.5 emission estimates where annual measured MCD12Q1 land classes and supported fuel factors exist. Daily factor SD includes published inter-study factor spread and biomass-factor uncertainty; it excludes sampling/integration bias and is not a full uncertainty interval. Unsupported inputs or reconstructed days return null.
- Descriptive burned-area R-squared from independent MCD64A1 cells, including cells without FIRMS detections, restricted to years with complete monthly tile inventories. Correlation is not out-of-sample validation.
- Fire Copilot defaults to immediate archive-only answers. Online research is explicit and retains evidence/date/location checks.

Chow p >0.1 and Wasserstein reduction >88% remain the original diagnostic gates. FAIL results are displayed unchanged. Passing them does not establish complete observation coverage or operational forecast accuracy.

## Local setup

Requires Python 3.12 and Node 24. From this directory, using PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python scripts/run_pipeline.py install
python scripts/run_pipeline.py etl
python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd frontend
npm run dev
```

With uv, the equivalent environment setup is `uv venv --python 3.12 .venv` followed by `uv pip sync --python .venv/Scripts/python.exe requirements.lock` and `npm ci --prefix frontend`.

The offline ETL uses retained CSVs and builds nominal/high/all-confidence cubes. It does not require downloaded ancillary products to start: missing coverage/land-class inputs stay explicitly unavailable. A prepared installation runs without a network connection; initial dependency and ancillary acquisition require one. Basemap imagery is optional network content.

No real cube means startup fails with instructions. Synthetic mode requires explicit `USE_SYNTHETIC_CUBE=1`; the browser fixture separately requires `VITE_ALLOW_SYNTHETIC_FALLBACK=1`. Neither is scientific evidence.

## Observation and ancillary acquisition

Public MODIS Terra/Aqua 1 km FireMask products can be acquired without an Earthdata account:

```powershell
python scripts/09_fetch_observation_coverage.py --public-modis --start 2000-11-01 --end 2026-11-14
python scripts/07_fetch_mcd64a1_ancillary.py --start 2000-11-01 --end 2026-11-14 --workers 4
python scripts/11_fetch_flare_reference.py
```

Acquisition is resumable. Mask summaries use bit-packed validity/fire flags, retain actual per-band NASA dates (including partial composites), and publish exact-preset daily indexes. A regional observed zero requires a single sensor to support all selected R7 cells, >=95% clear samples per cell, sufficient sampled area, no mask fire pixels, and no accepted FIRMS detection that day. It does not establish absence of sub-threshold fires. Cloud/unprocessed masks and unavailable catalogue dates remain unknown.

For Earthdata products, configure a free account token locally as `EARTHDATA_TOKEN` in `.env`, then run:

```powershell
python scripts/09_fetch_observation_coverage.py --sensor SNPP --sensor NOAA-20 --sensor NOAA-21 --start 2000-11-01 --end 2026-11-14
python scripts/10_fetch_land_cover.py --start-year 2001 --end-year 2025
python scripts/run_pipeline.py etl
```

For this delivery, MODIS acquisition spans 2000-11-01 through 2026-11-14; catalogue gaps remain unknown. VIIRS acquisition has been verified for all four regions and all three platforms on 2024-01-01 through 2024-01-07. The remaining VIIRS archive is intentionally resumable under the scope chosen by the user. The daily VNP/VJ1/VJ2 14A1 products summarize 750 m detection inputs on a 1 km grid; they do not establish availability of the 375 m FIRMS detector. Terra/Aqua masks do not establish VIIRS observation availability. No missing product or land-cover year is replaced by a fabricated value or an undocumented temporal extrapolation. Generated Parquet files, packed masks, and raster caches remain local; source/version information accompanies them.

Measured MCD12Q1 classes cover 2001–2025 (6,717,325 unique cell-years). Complete MCD64A1 monthly inventories cover 2001–2022 in these regions; later incomplete years are excluded from annual comparisons. MCD64A1 positive burn pixels require land/valid-data QA bits. Complete monthly inventories are reported separately from actual mapping quality. PM2.5 uses Andreae (2019), Table 1, field factors; fuels without an explicit mapping remain unsupported.

The EOG reference is MYC25Q4 v1.0 (Zhizhin et al., 2026), DOI 10.5281/zenodo.23091822, CC BY-NC 4.0. Its published checksum is verified before taking the regional subset. NASA fire-mask guides and emission references are linked in the scientific specification.

## Online services and synchronization

`COPILOT_OFFLINE=1` is the default. Set it to `0` and configure optional `GROQ_API_KEY` / `TAVILY_API_KEY` to use online research. Provider failures have a short negative-cache lifetime.

Live FIRMS sync requires a current local `FIRMS_MAP_KEY`. Sync returns an in-progress status and runs download, canonical deduplication/calibration, atomic cube publication, engine refresh and cache invalidation before reporting success. Previously exposed keys must be rotated; no historical credential is reused.

CORS defaults to localhost:5173 and 127.0.0.1:5173; `CORS_ORIGINS` configures other origins. Requests are bounded by body size, geometry size, analytical concurrency and per-client rate. Observation pages are paginated and virtualized; CSV export retrieves the complete daily result.

## Verification

```powershell
python scripts/run_pipeline.py test
python scripts/verify_frozen_tests.py
python scripts/12_audit_report.py
python scripts/05_cli_benchmark.py
```

The acceptance report compares HTTP energy against independent per-cell integrals, checks biomass units and concurrent results, and records actual diagnostic failures and availability reasons. CI runs backend tests, contract hashes, frontend tests and the production build on Windows and Linux. Network acquisition is separate from CI.

See `../docs/verification/2026-11-15-all-nighter/README.md` for the audit closure matrix and measured evidence. Earlier verification reports are historical and do not describe this branch's current calculations.
