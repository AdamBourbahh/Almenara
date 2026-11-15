# Bejís follow-up period regression

Verified on Windows, 2026-11-15, against main `a2dc209` plus the accompanying
uncommitted correction. The original failing live run used `c5b4031`; the three
intervening upstream commits changed branding only.

## Cause and correction

The request retained `2022-08-15` through `2022-08-28`. When Gemini rejected an
unsupported answer, the local investigator resolved these dates correctly but
passed only dates written in the latest question to the episode profiler.
The undated follow-up therefore searched the entire archive and selected the
stronger episode peaking on `2012-06-30`. The investigator then overwrote the
conversation context with that episode's June/July 2012 window.

The profiler now receives the resolved period, regardless of whether it came
from the latest question, map, previous context or conversation history. Only
discovery without any period establishes a new context. No incident-specific
rules, reference answers or changes to the archive were introduced.

## Real-archive replay of the failing follow-up

[offline-follow-up.json](offline-follow-up.json) contains the original request,
the original response's context/profile, and the new complete response. The new
run used the real archive with offline mode explicitly enabled; it is not a
simulated Gemini answer.

| Result | Before | After |
|---|---|---|
| Requested period | 2022-08-15 to 2022-08-28 | Identical request |
| Selected episode peak | 2012-06-30 | 2022-08-17 |
| Returned conversation period | 2012-06-15 to 2012-07-15 | 2022-08-15 to 2022-08-28 |

The corrected replay returned HTTP 200 in 21,960 ms. The thermal episode is a
statistical profile within the selected rectangle, not independent confirmation
that every detection belongs to the named incident.

## Authenticated Gemini conversation

[conversation.json](conversation.json) records the same three Spanish questions,
complete requests and responses, actual providers, tool selections and timings.
Gemini was called with its configured model and a process-only credential; no
answers, tool results or citations were mocked. The probe's wrapper recorded
calls without replacing their behavior.

| Turn | Actual response provider | HTTP | Time | Returned period |
|---|---|---|---|---|
| Initial incident investigation | Local fallback after invented source ID | 200 | 27,287 ms | Unresolved area |
| Undated ignition follow-up | Gemini agent / gemini-3.8-flash | 200 | 31,627 ms | 2022-08-15 to 2022-08-28 |
| Detections and energy | Local fallback after read timeout | 200 | 55,316 ms | 2022-08-15 to 2022-08-28 |

The first response still exposes a separate location-resolution problem: the
Spanish initial question loses the attached AOI. That issue is not corrected by
this date-propagation change. Provider reliability and incident-source retrieval
also remain imperfect; HTTP 200 alone is not a successful model answer.

[independent-numbers.json](independent-numbers.json) checks the last response
against direct Parquet SQL and independent within-cell sensor-mean integration
with exact H3 areas: 1,723 detections and 59,515.93752268897 GJ. Both displayed
quantities match. These are sparse observations and a one-hour energy proxy,
not distinct fire counts or continuously measured heat release.

## Automated verification

Five new regression cases failed before the correction: map dates, previous
context and conversation history each selected the stronger wrong-year episode;
explicit replacement dates were overwritten; an empty period substituted another
year. Only the external provider call is replaced in endpoint failure cases.
Scope resolution, DuckDB, calibration and dossier generation execute normally.
Existing unrestricted episode discovery remains covered.

Commands run from `firms-harmonizer`:

```text
.venv/Scripts/python.exe -m pytest backend/tests/test_copilot_investigator.py backend/tests/test_copilot_agent.py backend/tests/test_copilot_gemini.py -q
# 79 passed
.venv/Scripts/python.exe -m pytest backend/tests -q
# 680 passed, 17 warnings
.venv/Scripts/python.exe scripts/verify_frozen_tests.py
# All four hashes match
npm.cmd test --prefix frontend
# 55 passed
npm.cmd run build --prefix frontend
# TypeScript and production build passed
```

The first full backend run exposed a Windows CP1252 decoding error in the core
import test. Its file read now specifies UTF-8; import restrictions and all
assertions are unchanged. No frozen tests, schemas or credentials were changed.

This verifies the period-propagation fix and the recorded conversation, not
every location, provider outcome or incident claim. See the
[diff review](DIFFERENTIAL_REVIEW.md) for the reviewed boundaries.
