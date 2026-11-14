# Fire Copilot acceptance review — 14 November 2026

The user-reported failure was a question about the Madrid fire on 24 July 2026.
Previously, relevant articles were discovered but discarded by an official-only,
short-ignition-quote gate. The bot consequently returned counts and a generic refusal.

The repaired response retrieves the official regional report and distinguishes its
explanation of spread conditions (wind, temperature and merging fronts) from the
unknown ignition cause. The answer does not equate an individual H3 cell with the
entire reported incident. The source index contains URLs, not a hardcoded answer;
article text must still be fetched and checked.

## Executed checks

| Check | Outcome |
| --- | --- |
| Complete backend suite | 419 passed |
| New behavioral/retrieval cases within that suite | 57 |
| Complete frontend suite | 19 passed |
| Production frontend build | Passed |
| Real-data acceptance scenarios, actual providers | 12/12 passed |
| Real-data acceptance scenarios, providers disabled | 12/12 passed |
| Python dependency consistency | Passed |

`live.json` and `offline.json` retain the questions, complete answers, source metadata,
latencies and per-case assertions. Counts are cross-checked against independent SQL;
Madrid causal answers must explain reported spread, not just return HTTP 200. Cases
cover Spanish/English/Portuguese numerical questions, unit definitions, unknown
emissions, malformed dates, model/provider failures, liveblog incident confusion,
article encodings, navigation removal and unrecognized source hosts.

## Reproduce

From `firms-harmonizer/` with the real cube and staged observations installed:

```bash
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python scripts/08_validate_copilot_acceptance.py --output data/processed/acceptance-offline.json
.venv/bin/python scripts/08_validate_copilot_acceptance.py --live --output data/processed/acceptance-live.json
cd frontend
npm test
npm run build
```

These are finite acceptance checks, not proof of universal correctness. Search results
and providers can change. A source-backed regional report is not proof that a selected
satellite cell belongs to that incident. Publication metadata do not certify a paper's
findings. No frozen test file was edited; the existing API-contract hash manifest is
already inconsistent with its tracked HEAD version and is not relabeled by this patch.
