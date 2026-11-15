# Copilot latency diagnosis — 2026-11-15

The reported question was `what has happened here?`, with selected center
40.355 N, -4.514 E and day 2026-07-24. The original polygon was not supplied;
reproduction uses a 0.4-degree box around that center. Counts in these artifacts
apply to that reproduction geometry, not necessarily the user's original cells.

## Findings

- Gemini was available: a simple FRP/energy definition on the running API returned
  `gemini-agent/gemini-3.8-flash` in 7.589 seconds. Credentials were checked only
  for presence and were never printed or included in these artifacts.
- The API process had started at 14:32 Madrid time, before later source merges,
  and had no reloader. It still ran the older offline-fallback implementation.
  The reported question reproduced an unverified-incident-identity rejection and
  returned a deterministic local substitute in 13.839 seconds (`exact-before.json`).
- A profiled incident question on current source took 48.686 seconds: three source
  discoveries took 11.371, 10.250 and 8.927 seconds, plus multiple Gemini turns.
  Removing the search tool from the advertised list did not prevent an extra
  provider request from executing it. A separate native Google grounding probe
  hit a 12.075-second read timeout; this does not imply chat completions failed.
- Current source also failed to recognize `what has happened here?` as event
  intent. The model requested incident research, but it was denied by the gate.
  A profiled 10.183-second response therefore did not execute source discovery.

## Changes and validation

The agent now enforces the existing two-search budget at execution time, including
batched/repeated tool requests. A third attempt receives a limit result, preserving
previous evidence without another remote call. Add English auxiliary/contraction
and Spanish event-question variants. Success/failure logs include elapsed time.
No credential/model changes or evidence-check bypasses were made.

153 related regression tests pass, including adversarial repeated and batched
third searches and event-question recognition. The existing two-search refinement
and numeric-question web-exclusion regressions also pass.

Restarted the live local API with `--reload --reload-dir backend`, preserving its
environment. The same reproduction question/area/day returned HTTP 200, real data,
`gemini-agent/gemini-3.8-flash` and retrieved sources in 27.397 seconds, with its
selected dates/geometry retained (`exact-after.json`). This successful researched
answer is not a like-for-like speedup over the previous local substitute or the
source run that denied research. Remote source discovery and evidence review can
still take tens of seconds; no universal latency improvement or SLA is claimed.

The measurements used real provider and archive responses. Wrappers in the source
profile only measured actual operations; they did not replace service responses.
