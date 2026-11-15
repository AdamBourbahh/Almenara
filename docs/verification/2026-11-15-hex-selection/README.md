# Exact H3 area selection — 2026-11-15

The map now offers **Select hexagons**, alongside the existing area controls.
Click H3 R7 cells to add/remove them, inspect their IDs and total cell area, then
apply or cancel. Cells without observations are selectable. Grid work is bounded
before polyfilling (6000 visible cells); interactive selection allows up to 256
cells within the existing 16-ring/512-position polygon limits.

A connected selection becomes the union of its actual cell boundaries, with
unselected holes preserved. A polygon-to-R7 round trip must recover exactly the
selected set before the API request is sent. Disconnected groups are rejected
with an explicit message; no rectangle, bridge or hole fill is substituted.
Supporting disconnected groups would require extending the current Polygon API.
These are query cells, not an official incident perimeter or measured burned area.

Apply reuses the existing transactional AOI flow: the new geometry is committed
only after analysis succeeds. The selected dates and scientific filters remain
in force, and map/calendar/observations/risk/exports/Copilot reuse that same AOI.
A failed apply preserves the draft and previously applied AOI for retry.
Selection reuses the existing DeckGL instance with additional H3 layers and
turns off double-click zoom while selecting.

## Verification

- Frontend: 62 tests pass; TypeScript and production build pass.
- Backend geometry/DB/contracts: 45 tests pass.
- Frontend-generated polygon fixtures for Chilecito, Iberia, Orlando and Manaus
  recover exactly the same R7 sets in Python and retain an unselected central hole;
  R4 parents are unique and derived from those R7 cells.
- Real Chromium workflow: select a six-cell ring, toggle membership, reject a
  separate group, force an HTTP 503 on Apply, retain the draft, retry successfully,
  and ask Copilot. The day 2021-08-16 and exact polygon with a hole remain intact.
- Independent Parquet scan: the six selected cells contain 167 accepted detections
  and 3940.82 MW summed FRP. The central excluded cell contains 76 detections and
  2078.06 MW, excluded from both the selected scope and the chat answer. The
  returned map cells are a subset of the selected six cells. No page errors recorded.

See browser.json, independent.json, frontend-tests.log and backend-tests.log.
Screenshots are available locally at /tmp/almenara-hex-selection/draft.png and
/tmp/almenara-hex-selection/applied.png. Public contracts and backend polygon
limits are unchanged. Subsequent fast-forward pull to 9d21e64 changed deployment
files only; local functionality was preserved without conflicts. No push made.
