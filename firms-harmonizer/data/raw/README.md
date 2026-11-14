# NASA FIRMS raw data inventory

## Local regions

Inventory verified from the supplied CSVs on 2026-11-14. Counts are raw rows before exact-record deduplication, quality filtering and footprint allocation. Dates below describe observed detections, not proof of uninterrupted daily sensor coverage.

| Region key | CSV prefix | Files | Raw rows | First / last observed date | Configured bounds (west, south, east, north) |
| --- | --- | ---: | ---: | --- | --- |
| `chilecito_la_rioja` | `chilecito_` | 8 | 108,072 | 2000-11-05 / 2026-11-01 | `[-69.5, -31, -65.5, -27.5]` |
| `iberia_med` | `spain_` | 8 | 1,022,123 | 2000-11-01 / 2026-11-01 | `[-9.5, 36, 4, 44]` |
| `orlando_florida` | `orlando_` | 8 | 52,943 | 2000-11-01 / 2026-10-30 | `[-82, 28, -80.7, 29.3]` |
| `amazonas_manaus` | `amazonas_` | 8 | 390,954 | 2000-11-01 / 2026-11-01 | `[-62, -5, -58, -1]` |
| `cerrado_brazil` | `cerrado_` | 11 | 547,455 | 2000-11-04 / 2026-11-01 | `[-57.2, -17.8, -55.2, -16]` |
| `california_usa` | `california_` | 11 | 251,697 | 2000-11-01 / 2026-10-31 | `[-121.2, 38, -119.5, 40.2]` |

The Amazonas package covers the Manaus area, not the entire Amazon basin and not the separate Cerrado/Pantanal demo preset. Each package contains archive and NRT files for MODIS (Terra/Aqua), VIIRS SNPP, NOAA-20 and NOAA-21. The pipeline reads only CSVs directly in this directory; nested notes and original copies do not create duplicate inputs.

## Cerrado and California source provenance — 2026-11-14

Both presets were acquired programmatically, not from portal downloads, and each file name states its source span:

- `*_archive_2000_2025.csv` (MODIS), `*_viirs_snpp_archive_2012_2025.csv` and `*_viirs_noaa20_archive_2018_2025.csv`: FIRMS yearly country archives (`https://firms.modaps.eosdis.nasa.gov/data/country/{modis|viirs-snpp|viirs-jpss1}/{year}/..._{Brazil|United_States}.csv`), streamed and filtered to the region box (rows kept when `west <= lon <= east` and `south <= lat <= north`). All 2000/2012/2018–2025 yearly files were published; 2026 files and NOAA-21 files are not.
- `*_archive_2026.csv`, `*_viirs_noaa21_archive_2023_2026.csv` and `*_nrt_2026.csv`: FIRMS area API with the region box, in 5-day chunks (`MODIS_SP`/`VIIRS_*_SP` through their standard-processing end dates, then `*_NRT` through 2026-11-01), using the MAP_KEY in the untracked root `.env`. A failed or non-CSV response aborts; a header-only response is an empty chunk.

**Completeness check.** Country archives are clipped to national borders, so they were compared record by record — `(latitude, longitude, acq_date, acq_time, satellite, frp)` multisets — with independent area-API responses for the same box and 5-day window: every one of 622 Cerrado MODIS windows from 2000–2008, plus 8 seeded random windows per region and product. Cerrado and California matched exactly in every window. The same check showed that Nigeria's country files omit offshore Niger Delta gas flares (1–2 records missing per window near 4.6° N), so the country route was rejected for `niger_delta_flaring`; that preset was then dropped by decision of the project owner and has no coverage.

## Orlando and Amazonas source provenance

The user supplied 16 FIRMS CSVs in `orlandoyamazonas/`. Verified copies retain their original names with an `orlando_` or `amazonas_` prefix. The original upload remains local outside the ingest directory. The manifest [orlando_amazonas_manifest.json](orlando_amazonas_manifest.json) records each original and canonical filename, request ID, byte size, SHA-256, row count, satellite names, and observed coordinate/date extrema. All copied CSVs match the original bytes.

| Region | MODIS request | NOAA-20 request | NOAA-21 request | SNPP request |
| --- | --- | --- | --- | --- |
| Orlando | 848215 | 848216 | 848217 | 848218 |
| Amazonas / Manaus | 848219 | 848220 | 848221 | 848222 |

Eight original generic FIRMS download notes are preserved under `orlando_amazonas_download_notes/`. These notes do not include the request's original time interval or bounding box. New region bounds enclose the supplied coordinates, and configured date intervals use the package's observed first/last detection dates. Do not infer detection completeness from those intervals. Nominal IGBP class 8 for Orlando and class 2 for Amazonas are regional fallbacks, not measured cell-level MCD12Q1 classifications.

The 16 new CSVs are explicitly tracked in Git as requested (36,150,510 bytes in total; largest file 11,750,716 bytes). The general ignore rule for other raw downloads and generated Parquet files is unchanged. Existing Chilecito/Iberia CSVs remain local and are not added by this import. A clone therefore contains the two new packages; rebuilding all four regions also requires the earlier local downloads.

## Existing source packages

Chilecito archive/NRT filenames retain the `chilecito_modis_` and `chilecito_viirs_` naming scheme. Original downloads are preserved locally under `chilecito_original_download/`.

The Iberia package retains filenames prefixed `spain_fire_`, with FIRMS request IDs 847720 (MODIS), 847721 (NOAA-20), 847722 (NOAA-21) and 847723 (SNPP). Its geographic envelope includes areas outside Spain; country-only studies require an administrative polygon. Download notes remain under `spain_download_notes/`.

## Columns and processing

- `latitude`, `longitude`: WGS84 coordinates, indexed to unsigned H3 R4/R7/R10 keys internally.
- `acq_date`, `acq_time`: UTC date and HHMM acquisition time. Cube `epoch_day` is days since **1970-01-01**.
- `frp`: instantaneous power in MW. `scan` and `track` describe the footprint in kilometres; stage 01 applies the established MODIS bow-tie and spatial weights.
- `satellite`: Terra/Aqua/SNPP/N20/N21 or supported aliases. Preserve the source's instrument labels.
- `confidence`, `daynight`: normalized quality and day/night labels. Daytime coincident MODIS observations train the diurnal ratios.
- MODIS `brightness` / `bright_t31` and VIIRS `bright_ti4` / `bright_ti5`: thermal channels used by the ingest filters.

Archive/standard files take precedence over NRT for an identical normalized satellite, UTC date/time and five-decimal coordinate key. Distinct passes are retained. The cube uses the documented one-hour FRE proxy; see [ETL_SPEC.md](../ETL_SPEC.md) for units, caveats, outage/cloud masks and ancillary provenance.

## Rebuild from local inputs

Run from `firms-harmonizer/`:

```powershell
python scripts/01_ingest_firms.py
python scripts/02_detect_outages_clouds.py
python scripts/03_train_eqm_lut.py
python scripts/04_build_master_cube.py
python -m pytest backend/tests/test_cube_schema.py -v
python scripts/05_cli_benchmark.py
```

Stages 01–05 make no network calls. Stage 02 reads the tracked global counts in `data/lookup/global_daily_counts.csv`; stage 07 (`python scripts/07_fetch_mcd64a1_ancillary.py`, network, requires `scripts/requirements-acquisition.txt`) publishes MCD64A1 burned area to `data/lookup/cell_day_ancillary.parquet` and should run before stage 04. Missing cloud and burned-area inputs remain explicitly documented; they are not synthesized. Script 05 reports scientific/performance acceptance separately and can exit nonzero even when publication and schema checks pass. Generated cubes and lookup Parquet files remain local rebuildable artifacts.
