# Requested FRP totals and Risk AI diagnosis — 2026-11-15

## Chatbot change

The raw observation tool already returned `summed_frp_mw` for the entire selected
area and inclusive dates. The online count summary displayed only detection
counts; the model could then omit FRP or substitute the busiest day's value.
The server now renders the requested period total itself. Simple observation-total
answers use the trusted summary instead of a second model numerical summary.
Additional energy tool calls retain the observation total. Tool instructions
separate sampled FRP sums from peaks, simultaneous power and integrated energy.
No public schema changes were made.

Live Chromium-to-API-to-Gemini validation queried the area around 40.4 N, 4.5 W
for 2021-08-14 through 2021-08-22. English and Spanish questions both received
119 detections and **3,328.57 MW**. Neither replaced that total with the
**2,147.06 MW** daily peak. Both retained the exact selected dates and geometry.
Responses used `gemini-agent/gemini-3.8-flash`, real data, HTTP 200 (5.804 and
5.537 seconds). `browser.json` and `browser.png` contain the results.
The independent direct Parquet/H3 scan in `independent-numbers.json` gives the
same detection count and sum. The offline real-archive API check also returns
3,328.57 MW (`offline.json`). These sums accumulate instantaneous samples across
accepted detection centers; they are not time-integrated energy or simultaneous
power of the whole fire.

Regressions cover model omission, daily-peak substitution, English/Spanish
requests, zero observations and retaining FRP when an energy tool runs.

## Risk AI: diagnosis and proposal only

`risk-matrix.json` records calls through the real database adapter and risk route,
using the actual cube, start_year=2000 and end_year=2026. The same default region
can work or fail depending on its origin date:

| Selection | Origin | Model days | Result |
| --- | --- | ---: | --- |
| Full Chilecito region | 2026-11-14 | 9506 | ValueError / HTTP 500 in live app |
| Small Chilecito area | 2026-11-14 | 9094 | Assessment available |
| Full Chilecito region | 2026-07-24 | 9393 | Assessment available |
| Small Chilecito area | 2026-07-24 | 8981 | Assessment available |
| Full Chilecito region | 2021-08-22 | 7596 | Assessment available |
| Full Chilecito region, no explicit day | Latest record | 9505 | ValueError |

The daily arrays are consecutive in every case. The failure is the 9500-day
limit in `backend/core/risk_predictor.py`, not a requirement to select a single
cell or day. Smaller areas can have later first observations and therefore
shorter arrays. Earlier forecast dates also shorten the historical prefix.

Proposed fix: apply a bounded training window after extending the series to the
requested origin. Keep the latest MAX_DAYS samples in **every** aligned array,
without moving the origin or using observations after it. Retain causal feature
construction and validation on that bounded chronological history. Add route
regressions for histories above the limit, observation-gap extension and origin
preservation; report the available training window consistently. Do not merely
hide the error, silently change the selected date, or require a small AOI.

The proposal was tested separately on the failing real-region series. Keeping
9500 of 9506 aligned days produced an assessment at the unchanged origin
2026-11-14 (`risk-window-proposal.json`). This confirms that the proposed window
removes the input failure; it is not a fresh validation of forecast skill.
**No production risk files were changed**, as the request asked for diagnosis
and a proposed solution while authorizing the chatbot correction.
