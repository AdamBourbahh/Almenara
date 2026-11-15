# Scientific Fire Copilot verification — 2026-11-15

The Copilot now discovers a thermal episode without a calendar click, profiles its
±15-day progression window, and returns four scientific sections. All numbers are
calculated by the server. Ignition evidence, reported spread and assumed emissions
remain distinct. Existing endpoint and frontend field names remain compatible.

## Verified gates

- `pytest backend/tests/test_api_contract.py -v`: **20 passed**.
- `pytest backend/tests/ -v`: **451 passed**, including 21 investigator regressions
  and the integrated API accounting regressions. Full output: [backend-tests.txt](backend-tests.txt).
- `python3 scripts/test_copilot_e2e.py`: **12/12 cases passed** on the real local
  cube, including the five required scenarios and network failure, numeric
  cross-checks, invalid dates/locations, injection and schema validation.
  Full answers: [offline.json](offline.json).
- `python3 scripts/test_copilot_e2e.py --live`: **14/14 cases passed**, including
  actual search/model requests, article retrieval after simulated network failure,
  and the Madrid fire question dated 2026-07-24. Full answers: [live.json](live.json).
- Frontend: **24 tests passed**, `npx tsc --noEmit` and `npm run build` exited 0.
- Frozen-test SHA256 verification: all four unchanged test files passed.
- Chromium on `localhost:5173`: actual Copilot submission returned HTTP 200,
  all four dossier headings rendered, 9 references produced 17 clickable external
  links, lists were valid, and no page JavaScript errors were recorded.
  [Browser screenshot](browser.png).

Commands ran inside the existing `.venv`; no synthetic fallback was enabled in
E2E or browser checks. Backend unit/contract tests explicitly opt into the separate
synthetic fixture as required by their frozen setup.

## Numerical correction and limits

The integrated API accounting correction prevents multiplying every day's density
by the entire historical union of cells. GJ now integrates the footprint represented
on each day. This changes auto-discovery: the broad Madrid envelope's largest daily
GJ is **2026-07-24** in this archive, while the old density/constant-area ranking
selected August 2012. Earlier saved GJ/biomass snapshots use the former calculation
and are superseded by these reports.

For the broad Madrid selection, the statistical thermal episode is 2026-07-14 to
2026-07-29. This is **not** the official duration of one named fire; the envelope may
contain several incidents. Reconstruction and different sensor cell subsets affect
the modeled density. No burning footprint is invented on days without cube rows.
PM2.5 and CO2 use explicitly assumed factors and are not measured emissions, smoke
concentrations or validated ecological damage. Dashboard null emission fields remain
unchanged.

The retrieved official Madrid report discusses strong wind, high temperatures and
merging fronts. It does not establish the ignition cause. Citation IDs, dates and
excerpts are checked; scientific references explain methods and do not independently
confirm an incident.

Provider tests cover quotas, unavailable models, malformed/truncated responses,
network failures, all configured cascade branches and the 4,500-character / 900-token
bounds. Real Groq requests found the requested Llama model inaccessible (404), so
an available compatible Groq model is used. GitHub Models has retired; the optional
adapter requires an explicitly configured gateway, rather than sending a PAT to a
dead service. Actual Gemini/gateway accounts were not used; their protocol failures
and failover are tested with mocked HTTP responses.

These are finite acceptance cases, not proof of perfect answers to every possible
question or a guarantee about external quotas, latency or source accuracy. Network
requests have deadlines; the four-section local dossier works without providers.
