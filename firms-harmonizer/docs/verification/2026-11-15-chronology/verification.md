# Chronology and appearance verification

Validated on 2026-11-15 with the real local cube and running API/Vite application.

- `npm run build --prefix frontend`: TypeScript and production build passed.
- `npm test --prefix frontend`: 29 tests passed. New cases exercise inclusive cross-year partitioning, additive per-cell counts and observed energy, exact chat dates, invalid ranges, risk origin and stale responses.
- Chromium at 1440 × 1000: changed appearance using the switch inside Settings; selected July 2026, advanced to August without selecting a day, selected 24 July, and applied 28 December 2025 through 4 January 2026. The real map completed each request with no error. Chat context used the same inclusive range.
- Reversed dates disabled Apply. Cancel preserved the existing period. Merely hovering the histogram preserved selection. Histogram height measured 56 px.
- Changed from a range to 2024, advanced to 2025 and confirmed the selection remained a year.
- Chromium at 390 × 844: the date picker remained within viewport bounds. It remained clickable with Fire Copilot open after isolating the main workspace stacking context.
- No uncaught browser errors occurred during these checks.

Screenshots: [date range picker](date-range-picker.png), [mobile picker](mobile-picker.png).

The backend's existing same-year map-period contract is unchanged. Cross-year intervals are partitioned and merged by the frontend. The main analytical charts retain their existing annual presentation; exact intervals drive map observations, the map sidebar and chat context.
