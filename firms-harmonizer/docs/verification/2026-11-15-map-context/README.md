# Map and drawn-context verification

- Frontend: 27 tests passed; TypeScript and production build passed.
- Backend research and acceptance regressions: 76 tests passed.
- New regression uses a drawn polygon centered near 40.393, -4.478 with
  2026-07-24 and an official Madrid report whose relevant paragraph contains no
  Sierra Oeste place name. It answers reported spread conditions without a model,
  preserves the selected geometry and rejects a source from the wrong year.
- Search tests reject Paris/out-of-bounds results even when a mocked provider
  ignores bbox, reject malformed coordinates, deduplicate results, clip selections
  to the four envelopes and handle network failure and aborted searches.
- Chromium, 1228 × 648, actual services: searched Madrid through Photon, then
  selected a drawn Sierra Oeste area and 2026-07-24 and submitted “Why did this fire
  happen?”. HTTP 200, REPORTED_INCIDENT_CONTEXT, with heat, strong wind and merging
  fronts attributed to the official report. No JavaScript page errors.
- Drawer bottom and chronology top both measured 587 px. Basemap options were
  exactly Satellite and Terrain. Explore contained no duplicate case-study tabs.
- Search no longer uses a full-screen pointer-blocking backdrop; clicking the
  header after searching works normally.

[Browser evidence](browser.png). This verifies the reported case and named behaviors;
source availability and geocoding depend on external services. Reported weather
conditions do not establish ignition cause or prove that one cell belongs to an incident.
