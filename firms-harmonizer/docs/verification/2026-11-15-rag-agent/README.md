# Groq RAG and read-only agent verification

The online endpoint now uses Groq native function calls. Its short system message
and five tools replace online question-keyword routing. SQLite FTS5/BM25 retrieves
versioned scientific notes plus current ETL documentation; it is lexical retrieval,
not neural embeddings, training or an exhaustive scientific literature collection.
The model can reformulate retrieval queries. Only relevant passages enter context.

## Verified evidence

- Backend: **475 passed**, including 15 agent/RAG/protocol tests.
  [Full log](backend-tests.txt).
- Frontend: **27 passed**, TypeScript and production build passed. Citation badges
  accept local document K/E IDs in addition to existing scientific/web IDs.
- Existing offline scientific E2E: **12/12 passed**, including simulated network
  failure. [Output](offline-e2e.txt), [responses](offline-e2e.json).
- Real Groq through TestClient `/api/explain-spike`: energy question caused the
  model to choose `query_energy`; its final answer cites the server calculation.
  [Live response and trace](live-api.json).
- Real Groq through the same endpoint: “What does FRP mean?” answered using the
  automatically retrieved K1 scientific note, without a web request.
  [Live RAG response](live-rag.json).
- Real Groq direct-agent checks also exercised the exact question “the reason of
  the fire is known?” and a Spanish FRP/FRE comparison. The former chose
  `search_incident_reports`; the latter cited the retrieved K1 note.
- Actual Chromium UI with a drawn Sierra Oeste area, selected 2026-07-24, and
  “Why did this fire happen?”: HTTP 200 / RETRIEVED_EVIDENCE, cited official spread
  conditions and no established ignition cause. No JS page errors. Drawer and
  chronology both meet at y=587 px. [Screenshot](browser.png).

The live iteration detected repeated tool requests, missing tool citation metadata,
Unicode citation markers and incorrect promotion of spread into ignition. These
were fixed and covered by tests. Each tool is available once per request, up to
three tool rounds; the final response can use ordinary model prose. Numeric tools
always display Python-calculated values. Unknown sources and unsupported numbers
are rejected. A source-based ignition guard prevents weather-only excerpts from
supporting a positive ignition claim.

On quota/network failure a request-local offline context uses the existing local
scientific calculation without retrying the failed network calls or changing other
requests' environment. Provider failures and free-tier rate limits remain possible;
passing finite cases does not establish universal factual accuracy. The index is
expandable and versioned; adding a document does not certify its scientific claims.

Reproduce real calls with `python scripts/09_validate_copilot_agent.py`; use
`--question` and `--output` for single cases when inspecting free-tier quotas.
The older dossier script's offline mode remains a scientific regression; its live
layout/classification assertions target the previous renderer. Use script 09 for
the new online agent, rather than interpreting old layout assertions as agent QA.
Gemini Google Search grounding is not implemented or activated in this revision.
