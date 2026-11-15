# Held-pointer selection and perimeter Fill — 2026-11-15

## Behavior

In Select hexagons mode, hold the primary pointer and move to paint H3 R7 cells.
Starting on an unselected cell adds for the whole stroke; starting on a selected
cell erases. Revisiting cells is idempotent. Single clicks still toggle cells.
Intermediate screen samples prevent fast moves from selecting endpoints only.
Pointer capture and release/cancel/lost-capture/blur handling prevent stuck
painting, including release outside the map. Map drag-panning and double-click
zoom are disabled during cell selection. Wheel zoom is blocked during a stroke.
Painting does not open Copilot or change the applied area.

Fill is enabled only when a single connected selection encloses unselected cells.
It fills holes of the exact cell union, preserving the concave exterior. It does
not compute a rectangle or convex hull. Open/disconnected boundaries cannot fill;
oversized fills fail without changing the draft. The existing 256-cell selection,
16-ring/512-position polygon limits and exact R7 round-trip checks remain in force.
Fill only edits the draft. Apply commits it through the existing transactional
analysis and retains the selected day and scientific filters.

## Verification

- 78 frontend tests passed; TypeScript and production build passed.
- Unit coverage: closed/open perimeters in all four regions, concave multi-lobe
  exteriors, oversized and disconnected fills, idempotent add/erase, selection
  limits, intermediate cells on a fast pointer segment.
- Chromium on the actual local app with real data: ten checks passed. Paint a
  fast stroke, revisit it, erase, release outside the map, cancel on window blur,
  verify Fill is unavailable for an open boundary, close it, toggle one boundary
  cell, fill, apply and query Copilot. Wheel input during a stroke does not move
  the camera. No uncaught page errors recorded.
- A twelve-cell perimeter becomes exactly the expected nineteen-cell disk after
  Fill: seven interior cells added, no exterior cells added. Applied AOI and
  Copilot geometry are identical, with date 2021-08-16 retained.
- Independent Python API geometry reconstruction recovers precisely those 19
  cells. Direct accepted-center Parquet scans give 120 perimeter detections,
  plus 243 in the seven interior cells, totaling 363 and 8192.71 MW summed FRP.
  The live Copilot answer matches those totals. See independent.json.

Reusable browser check (real cube/API required; install the QA Playwright
package and Chromium first):

```sh
cd firms-harmonizer/qa
COPILOT_BROWSER_URL=http://127.0.0.1:5173 node browser_hex_paint.mjs
```

`CHROMIUM_PATH` and `HEX_PAINT_OUTPUT` optionally override the browser executable
and artifact directory. browser.json, perimeter.png and filled.png preserve the
actual run. Existing Risk AI history-window limitations are unrelated and unchanged.
