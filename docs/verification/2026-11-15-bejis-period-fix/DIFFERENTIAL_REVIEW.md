# Period propagation differential review

## Executive summary

Risk: medium, because the change affects scientific episode selection and
conversation state. Recommendation: approve the scoped correction. No new
security vulnerabilities were identified in the reviewed diff.

| New security finding severity | Count |
|---|---|
| Critical | 0 |
| High | 0 |
| Medium | 0 |
| Low | 0 |

## Changes and historical context

Baseline: `a2dc209`; reviewed the accompanying production change, both test
changes, change log and the five files in this evidence directory.

`git blame` attributes the explicit-question-only filter and unconditional
discovery context replacement to `4e720964`, in
`backend/api/copilot_researcher.py:537-554`. The change uses already validated,
resolved dates instead. It narrows discovery to the requested period and prevents
a discovered event from overwriting an existing period.

The test changes add five behavioral cases and make one source-code read
explicitly UTF-8. No existing assertions, import restrictions, frozen hashes,
public schemas, request limits or external tool permissions are weakened.

## Callers and boundaries

The investigator has three production call sites, all in `copilot_agent.py`:
offline/missing credentials, invalid scope, and caught provider/tool failure.
They share the `/api/explain-spike` route. The profiler also has a direct online
tool caller, whose code is unchanged. The production edit affects one caller of
the profiler and one context update in the investigator.

No SQL construction, geometry, authentication, network destination or secret
storage changes occur. The corrected path accepts only the scope resolver's
dates, preserving explicit question precedence. Out-of-period activity cannot
become an episode candidate merely because the provider failed.

## Evidence and adversarial cases

The endpoint regressions include an in-period weak event and a much stronger
event in a different year. Previously, provider failure selected the stronger
event; now it retains the intended period for map, previous-context and history
inputs. Other cases cover deliberate replacement dates and an empty selected
period. Existing tests cover unrestricted discovery and selected-day profiling.

All five new cases failed before the production correction. The full backend
suite passes 680 tests, frontend passes 55 tests and builds, and all four frozen
test hashes match. The real-archive offline replay changes the selected peak
from June 2012 to August 2022. A separate authenticated Gemini replay is recorded
without claiming local fallback responses are model responses.

## Limitations

This is a focused review of period propagation, not a repository-wide security
audit. Confidence in this regression fix is high given the reproduced failure,
real-data replay and behavioral tests. Initial Spanish place recognition,
provider timeouts, source retrieval completeness and all possible date-language
combinations are outside the verified correction. Thermal profiles remain
statistical episodes, not incident perimeter attribution.
