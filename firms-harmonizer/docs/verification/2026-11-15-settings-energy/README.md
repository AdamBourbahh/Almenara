# Settings and energy comparison verification

- 477 backend tests passed, including independent sparse-cell integration versus
  the map-period API and a test that the agent receives distinct observed/model
  objects. Frozen public API contracts were not changed.
- 27 frontend tests passed; TypeScript and production build passed.
- Actual Chromium verified Settings opens/closes, appearance toggles the root
  theme, keyboard shortcuts expand, and the display dropdown changes the actual
  map to raw counts and back to calibrated energy.
- For the same real-data polygon `[-67.55,-29.78]..[-66.25,-28.68]` and inclusive
  2026 selection, the browser map calculation and backend Copilot calculation
  independently matched to within 1e-6 GJ: mapped proxy **11,219.163298653 GJ**;
  regional model **16,633.632150052 GJ**. Mapped biomass is **4,128.652093904 t**;
  regional biomass **6,121.176631219 t**. Available series: 318 days through
  2026-11-14, with 142 days marked reconstructed. This verification polygon is an
  approximation of the user's selected area, not a recovery of its exact geometry.
- Mapped footprint **902.265627410 km²** and selected query area
  **15,429.234871915 km²** describe distinct areas; neither is burned hectares.

The difference is disclosed rather than hidden: per-cell observed integration and
regional sensor averaging / reconstruction are different estimators. Even without
reconstruction, different sensor cell subsets can yield different totals. These
remain model/proxy calculations, not independent measurements of combustion energy.

[Settings screenshot](settings.png), [comparison screenshot](comparison.png).
