# Publication verification — 2026-11-15

The QA reduction commit is `62060e3`. Before publication, main was fetched again
and the upstream commits `d36b7f0` and `be588f2` were integrated. They add numeric
recovery, fire-activity semantics and Gemini tool/source-discovery regressions.

Resolved README documentation overlap by preserving the audited scientific and
acquisition contract plus the new Gemini configuration. The provider regression
retains explicit online opt-in and explicitly selects Groq when checking Groq
failover. No frozen baseline file or hash was changed.

Fresh verification of the combined tree:

- Backend: **495 passed, one pre-existing TestClient deprecation warning**, 31.28 s.
- Frontend: **30 passed**, zero failures.
- TypeScript and production build: exit 0.
- Four frozen test hashes: all OK.
- Diff whitespace check and publication-content checks: pass.

The earlier 473-case QA result remains the pre-integration measurement. The
upstream additions account for the 22 additional cases; the QA pruning remains
intact. Local environment credentials and the user-provided `mis skillss/`
directory are excluded from publication. Remote CI status is separate from these
local checks.
