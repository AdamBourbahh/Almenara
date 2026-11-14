# FIRMS Harmonizer — Frontend Contribution and Expectations

This document describes the frontend work delivered by **Migue** (scientific charts, audit panel, Chaos Monkey UI, dashboard shell and pitch presentation) and what the frontend is expected to do. It is written for the team and for reviewers who want to understand the interface without reading every file.

## 1. What was delivered

The frontend is a React 19 + Vite 8 single-page application built on the frozen API contract in `frontend/src/api/types.ts`. It renders the MODIS + VIIRS harmonized fire record as an interactive, map-first data product. The visual language is editorial and institutional, not a sci-fi dashboard: a paper background, thin rules, serif headings, and clean, accessible data colours.

Migue's owned files (per `AGENTS.md`):

| Area | Files |
| :--- | :--- |
| Dashboard shell | `frontend/src/App.tsx`, `frontend/src/main.tsx` |
| Charts | `frontend/src/components/Charts/PolarVonMisesClock.tsx`, `frontend/src/components/Charts/KalmanUncertaintyBandChart.tsx` |
| Audit | `frontend/src/components/Audit/AuditMetricsPanel.tsx` |
| Documentation | `README.md`, `frontendExpects.md` |

Migue also assembled and integrated the surrounding frontend: the section pages, the theme system, the map panel layout, and the adaptation of the map, calendar, store and client to the frozen contract.

## 2. Design system

- **Layout:** map-first landing. The map fills the screen; a collapsible panel on the left holds the area chooser, controls, key figures and history. The top bar carries the section menu, the Raw/Harmonized switch and the light/dark toggle.
- **Sections** (top-bar dropdown): **Map**, **Calendar**, **Trends**, **Impact**.
- **Palette:** `#F8F7F4` paper, white panels, `1px #DCDCDC` rules, 2–4 px radii. Fire energy uses a perceptual thermal ramp (`#FEF0D9 → #B30000`), industrial gas flaring uses sober purple (`#6A3D9A`), raw counts use a neutral grey ramp. No neon, glassmorphism, gradients, coloured shadows or emoji.
- **Dark mode:** follows the operating system by default; the toggle is in the top bar and the choice is remembered in `localStorage`. The maps, panels, calendar and charts all adapt.
- **Typography:** Source Serif 4 for headings, Inter for controls, IBM Plex Mono with `tabular-nums` for every figure. All fonts are bundled locally (`@fontsource`), so the app works offline.
- **Motion:** short, compositor-friendly transitions, `prefers-reduced-motion` respected, visible focus rings.

## 3. The map (Map section)

- **Satellite + relief by default:** open Esri World Imagery with a semi-transparent Esri World Hillshade overlay, so arid and vegetated terrain read at a glance. Basemap switcher: *Satellite + relief*, *Satellite*, *Terrain* (OpenTopoMap), *Streets* (Carto, theme-aware).
- **Heat layer toggle with a visible `H` shortcut:** the button shows the key, and `H` turns the harmonized heat grid on or off while the satellite/relief base stays visible.
- **Interaction:** drag to pan, scroll to zoom, hover a cell for its fire energy, trend and industrial flag. 2D by default for smoothness; 3D relief is opt-in.
- **Area of interest:** four case-study tabs (Cerrado & Pantanal, Sierra Nevada, Iberian Peninsula, Niger Delta), drag-to-draw a box, and latitude/longitude + radius entry.
- **Industrial filter:** "Hide industrial heat (refineries and flares)" with the discreet note `Shannon temporal entropy H > 0.75`.
- The deck.gl canvas is kept transparent (`MapView({ clear: false })`) so the satellite base shows through; one WebGL2 context is used.

## 4. Calendar section

- A single HTML5 `<canvas>` renders all 26 × 366 = 9,516 daily cells with a `ImageData` + `run-length` pipeline (60 FPS budget).
- The **2012 curtain** compares raw hot-spot counts (left, neutral grey) with harmonized fire energy (right, thermal ramp).
- Diagonal hatching marks **repaired days** (Kalman / cross-guard) and the **14-day forecast**; a clean legend explains both.
- Click a row to inspect a year; arrow keys move the selection; hovering a cell opens a detail card (energy, raw count, 95% range, anomaly, sensors, narrative).

## 5. Trends section

- **Fire-season clock:** each spoke is a year; its direction is the peak burning day and its length the seasonal concentration. The headline is a plain sentence — "The fire-season peak is moving +X.X days per decade" — with μ, κ, season width, the Mann–Kendall p-value and the Theil–Sen drift in a compact table for researchers.
- **Kalman band + 14-day forecast:** harmonized energy with its 95% interval, the historical baseline and the forecast cone. The **"Simulate a satellite outage (stress test)"** button removes 25% of the data and forces ten days of total cloud cover, then shows the ground truth, the naive collapse, the cross-sensor guard and the RTS Kalman reconstruction, plus the recovered energy percentage.

## 6. Impact section

- **Layer A (everyone):** dry biomass burned (kt), PM2.5 smoke emissions (t), analysed area (km²), a plain-language verdict and a **"Download harmonized series (IPCC-ready CSV)"** button.
- **Layer B (researchers):** a clean table comparing raw data against the harmonized series for the Chow structural break (Jan 2012), the Wasserstein-1 distance and the R² against burned area (MCD64A1), with quiet `[VALIDATED]` / `[BIAS DETECTED]` indicators.

## 7. Data, contracts and offline behaviour

- The frontend consumes the frozen `AnalyzeRequest`, `AnalyzeResponse`, `ChaosMonkeyRequest` and `ChaosMonkeyResponse` contracts. It does not rename or extend them; it mirrors the nullable fields and `data_source` defined in the backend schema.
- When the API is unreachable, the typed client falls back to a deterministic offline generator and labels the data as synthetic. This keeps the demo working in airplane mode, but real, varying maps require the backend running with the real `fire_cube.parquet` produced by the ETL pipeline.
- The side panel shows the area's yearly heat history and a year inspector. Animating the heat **per hexagon per year** on the map requires the backend to expose per-year hex data (the current contract only carries the period mean); the UI is ready for it.

## 8. Accessibility and performance

- Accessible, colour-blind-safe ramps; the raw/harmonized and anomaly encodings do not rely on red/green alone.
- Visible focus rings, semantic buttons and labels, keyboard navigation on the calendar.
- Reduced-motion support and no fixed animations.
- One WebGL2 context for the map, one 2D canvas for the calendar, imperative tooltips to avoid React re-renders on hover.

## 9. Running the frontend

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173
npm run build   # type-check + production build
```

## 10. Expected outcomes for reviewers

- A judge can open the app, see the whole map immediately, switch to satellite relief, hide the heat layer with `H`, pick a case study, draw an area or type coordinates, and read the area's figures and yearly history.
- The story is told in plain English: the 2012 sensor artefact, the fire-season shift, the gap-repair stress test, and the biomass/smoke impact with a defensible audit trail.
- The interface is honest: synthetic data is labelled, statistical verdicts are data-driven, and the technical parameters are available one level down for researchers.
