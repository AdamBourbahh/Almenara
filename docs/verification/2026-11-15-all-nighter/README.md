# all-nighter audit closure — 2026-11-15

The coverage gate described in the original closure below has now been superseded. See [coverage-policy.json](coverage-policy.json) for the new threshold comparison and SPECS.md for its methodology. The previous results below remain the audit baseline.

The implementation addresses the supplied audit on branch `all-nighter`. This
delivery follows the user's selected scope: complete acquisition of the public
MODIS historical catalogue for the four registered regions, measured annual land
cover for PM2.5, and a verified VIIRS stage with the remaining archive resumable.
Catalogue gaps remain unknown. Scientific diagnostic failures remain visible.

The machine-readable evidence is [report.json](report.json),
[acquisition.json](acquisition.json) and [checks.json](checks.json). Derived cubes,
packed masks and raster caches remain local, ignored artifacts. Their fingerprints,
row counts, product metadata and acquisition status are recorded in acquisition.json.
No local credential is included.

## Verification

Local Python 3.12 / Node 24 verification:

- Canonical offline ETL publishes all three confidence cubes: 729,742 nominal,
  763,627 all-confidence and 126,695 high-confidence cell-days.
- **433 backend tests pass**, including sparse-cube physics, coverage, five sensor
  bits, forecast causality, uncertainty correlation, request bounds and concurrent
  engine reload regressions.
- **20 frontend tests pass**, including spatial period selection, stale-response
  protection, explicit synthetic opt-in and CSV BOM/unknown-value handling.
- TypeScript checking and the production build pass.
- All four coordinated frozen-test hashes pass.
- The installed Python dependency set passes `uv pip check` (102 distributions).
- Real HTTP analyses agree with independent exact-cell-area integration and biomass
  conversion for all four regions; concurrent cached requests agree.

One non-failing Starlette/httpx TestClient deprecation warning is present. The new
Windows/Linux GitHub Actions workflow has been added; remote CI has not been run
from this session.

Reproduce from `firms-harmonizer` with the local Python environment:

```powershell
python scripts/run_pipeline.py etl
python scripts/run_pipeline.py test
python scripts/12_audit_report.py
```

The real acceptance report requires locally acquired ancillary products to reproduce
these exact figures. A fresh offline ETL still works without them and reports their
absence explicitly. It never substitutes synthetic evidence.

## Real-data measurements

Observed energy is a one-hour FRP integration proxy with within-cell sensor fusion,
not a continuous daily fire-energy measurement. Biomass uses 0.368 kg/MJ. The API
integrates each cell against its own exact area; density uses the WGS84 polygon area.
The map selects cells by centre and does not clip their footprint at polygon edges.

| Region | Biomass (kt) | Positive PM2.5 days with complete fuel support | Harmonized Chow p | W1 reduction | Industrial records removed |
| --- | ---: | ---: | ---: | ---: | ---: |
| Chilecito | 1,139.052 | 746 | 0.3101 | 84.1% | 0 |
| Iberia | 14,191.156 | 570 | 0.5559 | 85.7% | 73 |
| Orlando | 698.452 | 2,633 | 0.00546 | 72.2% | 0 |
| Amazonas/Manaus | 5,081.319 | 1,785 | 0.4694 | 43.2% | 0 |

No region passes both original diagnostic gates (Chow p >0.1 and W1 reduction
>88%). Orlando fails both. Improvements or failures are reported without changing
the thresholds or manufacturing a passing verdict. Partial calendar years are
excluded from the annual Chow/phenology and era-comparison diagnostics.

Orlando has 409 mask-supported observed-zero days after the detection veto. The
other large study envelopes have no days that satisfy the conservative whole-AOI
zero screen. Their missing detections remain unknown. Unknown days do not acquire
energy from a climatological fill. These are sampled totals, not complete inventories.

All four full-period PM2.5 totals remain null because some emitting days lack a
supported annual fuel class. Supported individual days carry estimates and factor
SD. This SD covers common fuel-factor spread and biomass-factor uncertainty; it
excludes observation/integration bias. Unknown and reconstructed emissions remain
unavailable. Calendar exports leave unsupported physical values blank.

All four full-period FRE forecasts remain null because the last two years do not
have the required >=95% complete daily mask support. The causal seasonal/AR model
and rolling-origin baseline/interval checks are implemented and tested. Forecast
availability is conditional on those checks, distinct from the thermal-event risk
model. Risk labels remain conditional on that model's evidence and validation.

## Acquisition actually completed

- MODIS Terra/Aqua public FireMask acquisition was requested for every registered
  region from 2000-11-01 through 2026-11-14, with no acquisition failures. The
  catalogue does not provide uninterrupted support on every requested day. Actual
  NASA per-band dates are retained, including partial composites.
- Measured MCD12Q1.061 LC_Type1 classes cover 2001–2025: **6,717,325 unique
  cell-years**. Tile-edge class counts are merged before selecting a modal class;
  unknown sample pixels count against its dominant fraction. Missing years and
  unsupported/mixed fuels are not extrapolated for emissions.
- QA-filtered MCD64A1 contributes 129,667 burned cell-days (8,298,877 ha). Complete
  monthly inventories cover 2001–2022 for these regions. Incomplete later years
  are excluded from annual comparisons. Burned cells without FIRMS detections
  still contribute to the independent burned-area series.
- VIIRS SNPP, NOAA-20 and NOAA-21 acquisition was verified for **2024-01-01 through
  2024-01-07**, across all four regions, without failures (231 regional granules).
  These daily 14A1 products summarize 750 m inputs on a 1 km grid; they do not
  establish availability of the 375 m FIRMS detector. The remaining VIIRS archive
  is deliberately deferred and can be resumed without repeating completed shards.
- The regional EOG MYC25Q4 v1.0 subset contains 26 active site-years. Its upstream
  checksum, source and licence are retained. Positional/persistence matching is
  evidence for a filter, not a calibrated classifier of all industrial heat.

Resume VIIRS by selecting a manageable date window; completed matching shards are reused:

```powershell
python scripts/09_fetch_observation_coverage.py --sensor SNPP --sensor NOAA-20 --sensor NOAA-21 --start 2024-01-08 --end 2024-12-31
```

Credentials are read from local environment configuration. The former short global
count lookup remains a scoped outage evidence source, not a full historical global
coverage record. Independent masks supply positive observation support; missing
mask/count evidence is never interpreted as an outage or observed zero.

## Remediation matrix

| Audit finding | Implemented behavior / evidence |
| --- | --- |
| Inflated energy/biomass and inconsistent benchmark | Exact per-cell integrals; API and CLI share the canonical series; independent real-data checks pass for all four presets. |
| Sparse missing rows filled as fire | Explicit detected/observed-zero/reconstructed/unknown/forecast states; measured coverage gates reconstruction and zero support. |
| Inert industrial filter | Published site-year match, realistic positional screen, persistence; real Iberia matches; no-match controls hidden. |
| False validation claims | Backend verdict and unchanged gates displayed; R-squared described as a descriptive correlation; missing PM2.5 shown unavailable. |
| Future repaired history / ignored options | Archive/current-date bounds; forecast_days is honored subject to skill gates; confidence selects separately published cubes. |
| Sensor labels and area | All five bits retained; geodesic polygon area including holes; sensor evidence is never fabricated from another platform's mask. |
| Missing cloud/burned area encoded as zero | Nullable inputs; QA-filtered independent burned-area aggregation; no invented cloud values. |
| Chaos leakage and scoring | Target-year exclusion from prior/gain fitting; affected spatial forcing removed; affected-day metrics and intact-input reference labels. |
| Expensive/unbounded requests | Early geometry limits, body/question/history bounds, rate/concurrency limits, explicit CORS and byte-bounded cache. |
| Oversized annual map requests | Spatial-only /map-period path, request cancellation/cache, gzip for full responses; full analysis still carries the requested history. |
| CSV, presets and observations | Correct UTF-8 BOM, blank unknown values, one region registry, virtualized paginated observations and complete paginated CSV export. |
| Dead synthetic client backend / offline waits | Separate dynamically imported explicit fixture; archive-only Copilot defaults; provider failure cache. |
| NRT table without canonical publication | Validated raw download followed by canonical ETL, publication, safe engine reload and cache invalidation before success. Corrupt historical sync files are quarantined. |
| Bootstrap, rules and tests | Portable ETL/full verification, exact dependency locks, copied Windows-readable agent rules, coordinated contracts/hashes and CI matrix. |
| Obsolete raw/mock assets | Unused large mock and exclusive retired-region files removed; four-region raw observations retained as requested. Historical docs marked superseded. |

The remaining limits above concern observation support, model validation and the
explicitly staged VIIRS acquisition. They are not hidden behind a passing build.
