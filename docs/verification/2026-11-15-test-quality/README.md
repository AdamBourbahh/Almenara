# Test quality and performance review — 2026-11-15

## Executive summary

**Recommendation: conditional acceptance.** The requested removal/refactoring is
implemented without production changes or edits to frozen contracts. The full
backend passes **473 cases**, down from **494**, in **31.16 s** versus **43.94 s**
in the initial run. The frontend remains **30 passing tests** with a clean TypeScript
check. Eight core functions pass conformance. These are local sequential measurements,
not a statistically controlled performance benchmark or scientific model validation.

| Finding | Severity | Outcome |
| --- | --- | --- |
| Coverage selector could reject every forecast without a failing test | High | Positive acceptance and reserved-year rejection now asserted; mutation killed |
| Coverage area weighting could be uniform without a failing test | Medium | Exact independently recorded H3-area ratio now asserted; mutation killed |
| Redundant parameter products and repeated ETL process/setup work | Low | Removed/consolidated with invariant mapping below |
| Existing Starlette/httpx TestClient deprecation warning | Low | Still present and disclosed; no filter or dependency change |

## What changed

Baseline commit: `3168849`. Reviewed all four changed test files and their one-hop
dependencies; inventoried and executed all 21 backend test modules. Unchanged modules
were not independently re-audited line by line. Production code and frontend tests
are unchanged. History for the ETL/Copilot tests was checked against `03f2fae` and
`4b063bd`; no security regression test or production validation was removed.

The attached request used an older checkout path and older test counts. The actual
workspace is `Almenara/firms-harmonizer`; baseline counts and timings were measured
here before editing.

| Backend file | Before | After |
| --- | ---: | ---: |
| test_api_accounting.py | 12 | 12 |
| test_api_contract.py | 20 | 20 |
| test_audit_regressions.py | 16 | 16 |
| test_copilot_acceptance.py | 46 | 34 |
| test_copilot_agent.py | 16 | 16 |
| test_copilot_investigator.py | 21 | 21 |
| test_copilot_metrics.py | 17 | 17 |
| test_copilot_research.py | 38 | 38 |
| test_core_validation.py | 18 | 18 |
| test_coverage_policy.py | 2 | 2 |
| test_cube_schema.py | 105 | 97 |
| test_db_layer.py | 21 | 21 |
| test_explain_spike.py | 36 | 36 |
| test_map_period.py | 5 | 5 |
| test_math_core.py | 55 | 55 |
| test_nrt_poller.py | 23 | 23 |
| test_observations.py | 3 | 3 |
| test_real_cutover.py | 7 | 7 |
| test_risk_api.py | 4 | 4 |
| test_risk_predictor.py | 25 | 24 |
| test_science_integration.py | 4 | 4 |
| **Total** | **494** | **473** |

## Invariant preservation and blast radius

| Change | Removed work | Preserved evidence |
| --- | --- | --- |
| Numeric Copilot acceptance | Six phrases × three casing variants reduced from 18 executions to six | Every original phrase and all three languages remain; mixed-case `mAdRiD` exercises case normalization; exact counts, FRP, date scope and forbidden provider calls remain asserted |
| Feature-builder smoke test | One standalone shape-only case removed | Shape, finiteness and feature count move into the stronger causal-prefix test |
| Risk output checks | Five repeated model fits removed | All six distinctly named output tests remain, sharing one read-only fitted result; monotonicity, Fréchet bounds, weights, calibration, hazard classification and drivers remain asserted; full-history perturbation/sparse/NaN/Inf/zero/cloud tests retain independent data |
| Global-count outage windows | Nine CLI processes replaced by one | All nine original boundary histories/current values remain, isolated by 40 days in a single fixture; exact expected outage dates enforce both positive and negative cases; CLI formats, duplicate/missing days and idempotent publication stay separate |
| ETL base setup | Repeated lookup construction removed | Module-scoped immutable base files are copied into each function's temporary directory; no mutable lookup directory is shared |
| Forecast coverage | No case removed | Exact area weighting and successful threshold acceptance now complement existing water exclusion, sensor union, stale-index rejection and temporal separation assertions |

The ETL fixture has 15 test-function consumers (including parameterized cases), all
executed in the complete run. The risk fixture has six read-only consumers. Previously
different random seeds in those six structural checks are replaced by one common
2000-day seed-101 fit; this preserves their output invariants, not every former random
sample. Data perturbation and causal-history tests remain separate.

The synthetic cube schema/compression fixture was already module-scoped; it was
retained. Meaningful PSF, SAMA, orbital, cloud precision, EQM, MCD64 and region cases
were not removed to obtain a lower count. All 55 math-core cases and the seven named
scientific scenarios remain unchanged.

## Adversarial verification

The replacements used for mutation checks live only in an ignored scratch script,
within the test process. Production files were never changed to inject a bug.

| Deliberate wrong behavior | Before this refactor | After this refactor |
| --- | --- | --- |
| Always return `selected_threshold=None` | Both coverage tests passed | `test_threshold_selection_never_uses_reserved_year` fails |
| Return area 1 for every H3 cell | Both coverage tests passed | `test_union_of_sensors_excludes_measured_water_and_uses_previous_year` fails |

The real implementation passes both tests. The new expected area ratio uses recorded
areas 4.675232673770666 and 4.676643095626661 km² for the fixture cells, rather than
computing the expectation with the mutable production helper. The selector test now
requires a good case to accept 95%, then rejects a reserved year where the forecast
loses to persistence. Exact failing outputs are retained in the mutation logs.

## Guardrails and frozen integrity

No production changes affect H3 hex serialization, synchronous analytical endpoints,
isolated DuckDB cursors, hierarchical R7/R4 filtering, Joseph covariance, or rendering
context ownership. Their existing tests remain. The H3 count boundary and sparse
energy accounting tests were retained unchanged; the former 'huge polygon' bottleneck
was not present in the measured baseline. The near-limit exact polyfill takes about
0.34 s in the final run.

Source inspection still finds one DeckGL mount and one rendered calendar canvas.
This is structural review; this task did not independently measure live GPU context
creation in a browser. No claim of complete runtime/line/branch coverage is made.

The four hashed baseline files and `FROZEN_TESTS.sha256` are byte-for-byte identical
to the pre-edit snapshot. The exact requested raw-byte hash check reports:

```text
FROZEN_TESTS INTEGRITY: PASS (4/4 OK)
```

Snapshot checksums are recorded in [inventory.json](inventory.json).

## Verification and performance

| Check | Result |
| --- | --- |
| `python -m pytest backend/tests -q --durations=15` | 473 passed, 1 warning, 31.16 s |
| `python -m backend.check_core --synthetic` | Eight PASS; exit 0 |
| `npx tsc --noEmit` | Exit 0, no diagnostic output |
| `node --test tests/*.test.mjs` | 30 pass, zero failures |
| Raw frozen-file SHA-256 check | PASS (4/4 OK); checksum file also unchanged |

The whole-suite elapsed time fell by **29.1%** in these runs and meets the requested
<35 s target. ETL-only time fell from **11.58 s to 8.94 s (22.8%)**: the requested
35–50% ETL improvement was **not reached**. The zero-warning target was also **not
reached**: the pre-existing TestClient deprecation remains. It was not hidden.

Full captured outputs: [backend before](backend-before.txt), [backend after](backend-after.txt),
[ETL before](cube-before.txt), [ETL after](cube-after.txt), [core](core-conformance.txt),
[frontend](frontend.txt), [typecheck](typecheck.txt), [hashes](frozen-integrity.txt).

## Method and remaining limits

Applied the supplied context-mode, code-review, code-simplifier, test-driven-development,
verification-before-completion and differential-review skills from `mis skillss/`.
The context-mode server tools are unavailable in this session; full outputs were
captured locally and summarized instead. No production implementation was introduced;
the strengthened tests were checked green with the actual code and red against the
known deliberate mutations. Frozen tests were not bypassed or rehashed.

These changes improve regression quality and reduce redundant work. They do not
make the synthetic fixture an independent scientific reference, validate operational
forecast skill, or close every coverage gap identified in the earlier audit.
The user-provided untracked `mis skillss/` directory is preserved untouched.
