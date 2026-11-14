# Annual map inspection — 2026-11-14

The heat-history hover previously updated only its local label. The slider updated selectedYear, but the Deck.gl layer read map_hexagons from the all-years analysis and never subscribed to the selected year. Raw mode also used energy rather than raw detection count.

The store now requests the existing frozen analyze contract with start_year=end_year=selectedYear for a separate annual map. Full-range calendar, phenology and audit data remain intact. A 120 ms debounce coalesces pointer movement, a 32-entry cache reuses visited years, and abort plus sequence checks prevent stale responses overwriting the current year. AOI/filter reanalysis invalidates the cache. Loading and failures clear old annual cells and show an explicit status. Missing-year cells are absent; no synthetic measurements are fabricated.

The existing single DeckGL component receives annual data and updated accessor triggers. Color/elevation use annual calibrated energy or raw detections. The fixed cross-year reference is the all-range maximum mean annual energy, or maximum mean annual raw count; values above that reference saturate and the legend marks the upper bound with a plus sign. Both legend palettes match their layer ramps. Tooltips give the loaded year and annual values; single-year summaries no longer claim a multi-year trend. Map energy is the calibrated observation proxy from the existing API summary, not a per-cell RTS reconstruction.

Verification:

- node --test frontend/tests/real-data.test.mjs: 5 passed. Cases cover annual request bounds, distinct values, preserved full history, cache reuse, late responses, errors and prior provenance/opt-in behavior.
- npm --prefix frontend run build: TypeScript and Vite pass.
- Playwright CLI, http://127.0.0.1:5174: actual history-bar hover loads real annual HTTP responses. Chilecito 2022: 1687 cells; 2005: 532 cells; 2023: 1442 cells. Comparing 2005 and 2023, 159 shared cells have different values and different normalized color intensities with the same reference (238712.6496769832 MJ/km²). The Deck.gl canvas screenshot changes. Console: zero errors/warnings.
- git diff --check passes. No API/schema, core or database changes. Changes are local and have not been pushed in this task.

## Energy/panel audit update

The prior regional Kalman GJ total is not the sum of the observed/calibrated cells. The map footer now integrates visible cell densities with exact H3 areas, and the right-hand panel uses the same helper. The history bar heights now show annual satellite detection counts, explicitly labeled, instead of mixing the modeled regional annual energy with mapped energy. The fixed color reference is now the all-years maximum cell total (not the maximum mean annual total); logarithmic normalization avoids the previous widespread red saturation.

Independent DuckDB/Parquet checks for Chilecito, years 2001–2026: 107,739 raw detections match the API. The old full-record modeled biomass matches the API arithmetic but is not a direct measurement; it has been replaced in this map panel by biomass estimated from mapped energy (GJ × 0.000368 kt/GJ). PM2.5 is shown as not computed. The full-record panel labels counts and peak detection year explicitly; the selected-year panel labels observed cell footprint rather than burned area. Region descriptions now match the four actual region IDs.

Independent cell-by-cell integration versus annual API summaries: 2005 = 532 cells, 635 detections, 56,393.57945140203 GJ, 2,477.4517845871646 km² cell footprint; 2023 = 1,442 cells, 8,409 detections, 113,671.62722680724 GJ, 6,724.553949057719 km². Browser footer and panel agree after rounding (56,394 / 113,672 GJ); 2023 biomass proxy = 41.83 kt. These are examples for the full registered Chilecito AOI, not identified years from the cropped user screenshots, whose year labels and bounds are not visible. Six node regression cases pass; frontend build passes; browser console has zero errors/warnings. The underlying calibration remains a one-hour observation proxy and requires scientific validation. No backend scientific transformation or frozen contract was changed.
