# FIRMS Copilot audit ? 2026-11-15

The assistant is named FIRMS Copilot in the navigation, drawer, accessible labels,
map help and model identity. API contracts and internal component filenames are stable.

## Findings and fixes

1. The retrieval index contained 139 records, including historical ETL claims,
   fixture arithmetic and pytest summaries. Nested headings bypassed the old section
   filter. Retrieval now has one explicitly approved source: `science.json`.
   Tests plant canaries in another JSON, ETL documentation, a log and `.env` and
   confirm none reaches search results.
2. No production Copilot code reads QA conversation logs, verification reports or
   arbitrary repository files. The curated incident index contains discovery URLs;
   incident facts still require independently fetched article evidence. It can bias
   discovery toward indexed incidents, but is not a stored answer transcript.
3. Scanning 414 tracked text files found no matches for the checked Google,
   Hugging Face or Groq credential formats. This is a bounded scan, not proof that
   arbitrary sensitive data cannot exist. Provider-failure tests also check that
   credentials and untrusted error bodies do not enter logs or responses.
4. The old 925,721-row cube was inconsistent with current staging and confidence
   semantics. Its original checksums and failing numerical audit are retained in
   `archive-before.json`. The current ETL rebuilt all three confidence cubes from
   actual local FIRMS CSVs. The old local files remain in an ignored backup directory.
5. Missing ancillary data is preserved as null; measured MCD64A1 values are checked
   against their actual input table. No unavailable forecast, fire identity or
   ignition cause is made available to satisfy a test.

## Local validation

- Full backend: 691 passing tests; four frozen contract hashes unchanged.
- Copilot subset: 306 passing tests, including transport faults and evidence integrity.
- Frontend: 55 passing tests; TypeScript and production build pass.
- Independent real-archive oracle: 36 passing checks against raw CSVs, staging,
  cube cell areas, confidence filters, inclusive dates, energy and biomass.
- Browser offline: 10 passing flows, including date edits, year boundaries, context
  removal, new area, actual hex selection and clearing conversation history.
- Initial real-provider HTTP matrix: 25 passing cases, 21 Gemini answers, one
  explicitly labelled local fallback for emissions; invalid dates and domain
  refusals intentionally do not require the model.
- Additional filters and emissions retry: five passing cases; four Gemini answers
  and one labelled local fallback for low confidence. The emissions retry used Gemini.
- Local online browser: actual Gemini request with exact selected geometry and day.

A passing HTTP case means the recorded assertions passed. The live tests do not
prove every arbitrary natural-language claim is correct. Model fallbacks are
recorded separately and are never counted as Gemini answers. The 16 backend warnings
concern pre-existing NumPy timedelta deprecations.

## Reproduction

From `firms-harmonizer`, run `python -m pytest backend/tests -q`,
`python -m pytest qa/test_copilot_archive.py -q`, and
`python scripts/verify_frozen_tests.py`. The browser scripts in `qa` support
`CHROMIUM_PATH`, `COPILOT_BROWSER_URL` and `COPILOT_BROWSER_OUTPUT`.

Run the same real-provider HTTP matrix against either environment:

```sh
python qa/copilot_http_audit.py --base http://127.0.0.1:18500 --delay 0 --output local.json
python qa/copilot_http_audit.py --base https://firms-harmonizer-612652227111.europe-west1.run.app --output deployed.json
```

The deployed command preserves public request limits. Local tests use isolated
ports, a real cube, NRT disabled and the provider key only in process memory.
Production evidence will be recorded after the verified release completes.
