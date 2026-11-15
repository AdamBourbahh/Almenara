# Gemini deployment verification

Date: 2026-11-15. Local API uses the real 927,542-row cube.

The supplied Google credential successfully accessed the models endpoint. Both
native and compatibility calls to Gemini 2.5 Flash returned HTTP 404: the project
could not access that model as a new user. The user explicitly approved Gemini
3.8 Flash. A direct compatibility request and native Google Search request then
returned HTTP 200 for `gemini-3.8-flash`.

## Validation

- Backend: **499 passed**, using isolated provider credentials and explicit offline
  settings except tests with mocked Google transports. Existing dependency
  deprecation warnings remain.
- Frontend: **29 passed**. TypeScript and Vite production build passed.
- New regression tests exercised Google selection, tool-result continuity, two-call
  batches including large result histories, retained opaque metadata, grouped and
  doubled citations, provider outage, offline isolation, trusted grounding URLs and
  unsafe redirect rejection. A further test retains valid incident prose when the
  ignition cause is unknown. Each regression was observed failing before its fix.
- Five live cases passed through the real selected provider; a local fallback was
  treated as failure: `is this a fire?`, `Why did this happen?`, `the reason of the
  fire is known?`, `How much energy in GJ was released here?`, `What does FRP mean?`.
  See [live tool traces](live-cases.log). The incident cases used Google source
  discovery. The energy case used server calculations; the unit case used the local
  scientific index. A report lead is not necessarily retrievable article evidence.
- Chromium sent a question through the actual web form. The response used
  `gemini-agent/gemini-3.8-flash`, `data_source=real`, and a linked scientific source;
  no uncaught page errors occurred. [Screenshot](browser-response.png).
- Verified the real credential is absent from the tracked diff and frontend JS
  bundles. `.env` is ignored and has mode 0600. Public contract files are unchanged.

## Scope and limits

The short prompt incorporates practical vocabulary, direct answers, exact tool
values, source relevance, domain focus and distinctions between observed burning,
incident identity, ignition and spread. It does not implement every proposed metric
or the reference document's new deterministic pre-execution topic gate.

Google source discovery repeatedly timed out at four seconds. Native Google
inference plus redirect discovery now shares twelve seconds; individual redirect
and publisher reads retain a four-second cap, inside the agent's 35-second overall
budget. A live source-discovery check completed in 9.51 seconds and returned three
approved source URLs. Source metadata supplies URLs; generated search summaries
are not copied as verified report quotes. Some publisher bodies remain unavailable,
so neither a source lead nor an empty search proves an incident's identity or cause.

External quota and source availability can still require the local fallback. These
finite tests demonstrate the observed cases, not universal answer correctness.

## Implementation references

- [Google OpenAI compatibility API](https://ai.google.dev/gemini-api/docs/openai)
- [Google Search grounding metadata](https://ai.google.dev/gemini-api/docs/google-search)
- [Gemini 3.8 Flash capabilities and thinking levels](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)
