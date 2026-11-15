# Copilot differential review

## Assessment

Baseline: `39c8a9c`; production changes through `136da46` on `pc-adam`.
Risk: medium (answer availability, scientific evidence and geographic context).
Recommendation: accept the scoped changes subject to the documented validation
limits. No new security vulnerability was found in the reviewed diff.

| New security severity | Count |
|---|---|
| Critical | 0 |
| High | 0 |
| Medium | 0 |
| Low | 0 |

## Changes reviewed

- `copilot_agent.py`: explicit online errors instead of investigator substitution;
  selected location label preserved; scientific-audit tool advertised; evidence
  rules for nulls, zero energy and metric scope. Explicit offline use remains.
- `copilot_providers.py`: the auxiliary completion limit increases from 10 to
  15 seconds. The main agent already allowed 15 seconds per model read and a
  55-second multi-tool workflow deadline. These are not a promise of a 15-second
  end-to-end API response, which also includes local scientific work.
- `copilot_metrics.py`: selected-period mapped FRE and gap counts, full-archive
  Chow/W1, latest supported directional von Mises fit, and verbatim structured
  results. A zero-energy annual display sentinel is not reported as a fitted
  burning peak. Forecast work is unnecessary for this historical audit.
- Three regression files: expected online failure behavior changes explicitly;
  numerical-unit, source-evidence and identity rejection assertions remain.
  Original date-retention cases still exercise the explicit offline investigator.
- `14_certify_copilot.py` and evidence files: real ASGI routes, real Parquet,
  real Gemini calls, independent SQL and statistical arithmetic, recorded failed
  attempts, and a semantic-review gate before a new held-out case.

## Boundaries and regression checks

One online catch path previously invoked the local investigator after provider,
tool or evidence errors. It now returns insufficient context with a provider
error identifier and retained map dates. Missing credentials and invalid scope
also cannot trigger the investigator. The remaining investigator call requires
explicit offline mode. Public response schemas are unchanged.

The new read-only tool uses existing polygon validation, isolated DuckDB cursors,
confidence selection and industrial filters. No model-generated SQL, new network
destination, credential storage, validation bypass or write capability is added.
The new statistics use the dashboard pipeline rather than language-model math.

Behavioral regressions reproduced online substitution, unsupported annual peak
sentinels and broad pilot envelopes replacing selected locations before their
fixes. Fresh verification after the last production change: 684 backend tests
pass. Frontend passes 55 tests and builds; all four frozen hashes match.

## Findings and limits

An initial held-out answer incorrectly called a northern-African selection an
Iberian area. The pilot collection envelope overrode the selected label in model
context. The failed answer is retained; the corrected label transfer has a
dedicated regression and requires rerunning all six cases before a fresh holdout.

Earlier prose invented a reason for a null diagnostic; the model context now
restricts explanations to supplied evidence. An earlier live timeout remains a
failed case, never a successful model answer. No claim is made that a numerical
match alone proves absence of hallucinations.

This is a focused review, not a repository-wide security audit or universal
chatbot certification. Measured cloud cover is unavailable in the selected cube;
the mask oracle checks qualified observed zeros and unknown days. The selected
cells contain no independently evidenced missing-energy days eligible for RTS
reconstruction. Positive reconstruction, measured cloudy weather, independently
confirmed gas-flare identity, every conversational intent and frontend browser
behavior are outside this certificate. A private repository does not change
credential handling: only process-environment credentials were used.
