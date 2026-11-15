# Main integration — 2026-11-15

Integrated all remote branch tips not previously reachable from main:
`origin/front-end` (98cf4f8), `origin/pc-adam` (c635a27), and
`origin/pitch/slides-modis-viirs` (2d14f7b). Existing chatbot date/FRP fixes and
exact H3 area selection are retained. The only textual merge conflict was in
CAMBIOS.md; both sets of notes were preserved. No force push is used.

Validation on the consolidated tree: 710 backend tests passed, one skipped;
70 frontend tests passed; TypeScript and production build passed. Remote and
local branch inventories show no unmerged tips after integration. A fresh fetch
before publication confirmed that origin/main had not advanced.

Known real-data Risk AI history-window limitation remains documented in the
FRP totals verification report; passing fixture tests do not resolve it.
The pre-existing untracked `mis skillss/` folder is excluded from commits.
