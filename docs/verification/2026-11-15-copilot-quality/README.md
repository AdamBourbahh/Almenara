# Fire AI Copilot quality audit — 15 November 2026

The implementation was developed in `/tmp/almenara-copilot-quality`, based on
`origin/main` at `8f16bc4`. Implementation commit: `3c070a4`. The original working directory had extensive unrelated
uncommitted changes; none were staged or overwritten. This audit uses one integrating
agent and preserves the public Python and TypeScript schemas.

The configured service is **Gemini, `gemini-3.8-flash`**. Credentials were read only
from the existing local environment. No provider was substituted. Saved traces omit
credentials, opaque provider signatures and hidden reasoning.

## Verified results

| Verification | Result | Evidence |
| --- | ---: | --- |
| Complete backend suite | 544 passed | `backend.log` |
| New controlled regressions within that suite | 49 passed | `test_copilot_quality.py`; red/green logs |
| Independent integration with actual CSV, staging and cubes | 36 passed | `archive.json`, `archive.log` |
| Unique real-provider conversations, two turns each | 15 passed / 30 turns | `live-final.json` |
| Chromium tests over the actual web app and real API | 10 passed | `browser.json`, `browser.log` |
| Existing frontend suite | 30 passed | `frontend.log` |
| TypeScript check and production build | Passed | `typecheck.log`, `build.log` |
| Frozen-test checksums and scientific core conformance | Passed | `frozen.log`, `core.log` |
| Independently downloaded first-party source contents | 5 passed | `source-review.json` |

There are **110 new, distinct cases**: 49 controlled regressions, 36 real-file checks,
15 conversations, and 10 browser flows. The 30 conversation turns, repeated live
runs, source reviews and six prompts inside the single network-denial check are
not counted again. Backend and real-file runs retain a Starlette/httpx deprecation
warning; it is not a failed check.

`before-live.json` came from the repository's previous acceptance script. Its `passed`
flags only checked transport, model identity and citations. Those flags are **not**
semantic acceptance results. Manual inspection identified incorrect context mutation,
an unverified cutoff premise and excessively repetitive answers despite those flags.
The intermediate live files preserve failures rather than relabeling retries as new
coverage. The final chronology record replaces the earlier version after an
additional source and wording review; the replaced record is retained separately.

## Reproduced defects and corrections

| Before | Correction and independent evidence |
| --- | --- |
| `July 23–24, 2026` selected all July; the Spanish shared-month range lost its first day. Reversed dates were silently sorted. | Preserve ordered inclusive endpoints and reject invalid/reversed dates. Literal calendar expectations and real HTTP checks cover both languages, leap days and cross-year dates. |
| Profiling changed the returned selected day from July 24 to July 10–August 9. Model-supplied tool dates could replace selected dates. | Keep episode/report comparison windows separate. Reject measurement-tool date overrides. Browser requests, tool arguments and response context retain the selected dates. |
| A date mentioned as a map cutoff became a new measurement selection. | Treat cutoff references as premises to investigate; the attached measurement day remains intact. A separately labeled local timeline checks later observations. |
| Detections ignored selected confidence and industrial filtering. Mapped GJ always used nominal confidence. Episode settings were hardcoded. | Propagate settings to staging filters, the corresponding confidence cube and episode calculations. Independent scans verify nominal, low and high outputs. |
| The auxiliary completion cascade could spend another service's quota. | Bind all completions to the configured provider. Quota, authentication, overload, malformed, timeout and truncation cases retain local evidence. The old cross-service regression now enforces that requirement. |
| A detection count could authorize the same numeric value in GJ. Valid decimal display rounding and sensor names could be rejected. | Validate typed quantities; preserve exact integers; check decimal rendering at its stated precision. Known NOAA sensor identifiers are not measurements. |
| Search leads could be cited as established incident evidence. Retrieved instructions could look like incident claims. | Require matched article passages for factual source IDs and exclude document commands from incident evidence. A real Gemini conversation also retrieves an adversarial temporary local document without following its instructions. |
| Regional reports were treated as proof that selected detections belonged to a named fire. | Reject explicit affirmative observation-to-incident matches and request a correction. There is no official perimeter-join tool; regional reporting remains contextual. Initial failures and subsequent actual-provider replies are retained. |
| An ambiguous “why” defaulted to ignition alone. Count and GJ answers buried quantities under long reports. | Expose spread/incident evidence separately, answer ambiguous questions without forcing ignition, and lead quantitative responses with exact server-calculated results. |
| A chronology response overstated that satellites observe flaming rather than smoldering. | Supply the correct sensor limitation: sufficiently hot smoldering is detectable, and counts alone do not establish why observations declined. The chronology conversation was repeated and manually reviewed. |

The accepted-center fixture now includes the confidence and industrial columns present
in production staging. Its expected counts and powers were retained. Frozen contracts,
frozen checksums, physical tolerances and scientific acceptance gates were not relaxed.

## Madrid / Sierra Oeste: observations and independently read reports

The exact selected polygon used for the historical cases is:

```json
[[[-4.8,40.2],[-4.15,40.2],[-4.15,40.58],[-4.8,40.58],[-4.8,40.2]]]
```

For **24 July 2026**, nominal/high detections with industrial candidates excluded:

- **1,860 accepted detection centers**, not 1,860 distinct fires.
- **84,971.666 GJ** mapped energy proxy; the temporal estimate matches for this
  selection without evidenced reconstruction. Independent per-cell integration
  uses the available-sensor mean times exact H3 area divided by 1,000.
- **31,269.573 tonnes** derived dry biomass, using 0.368 tonnes/GJ.
- **863.146 km²** observed cell footprint versus **2,328.742 km²** selected polygon.
  Neither quantity is measured burned area.

The independently scanned timeline contains detections after July 27, including
July 28, July 30, July 31, August 1 and August 7. The global archive extends through
November 14. The statistical episode's end is not the end of the archive or an
official extinction date; later detections are not automatically the same incident.

The content review is independent of the production source extractor. It downloads
the documents, checks actual text, saves SHA256 fingerprints and identifies which
claims each source supports:

- [Madrid, July 24](https://www.comunidad.madrid/noticias/2026/07/24/diaz-ayuso-es-peor-incendio-historia-comunidad-madrid-prioridad-es-salvar-vidas)
  describes high temperatures, strong wind and merging fronts. These are reported
  spread factors, not proof of an ignition mechanism for each selected observation.
- [Madrid, July 30](https://www.comunidad.madrid/noticias/2026/07/30/diaz-ayuso-comprueba-situacion-terreno-afectado-incendios-sierra-oeste)
  documents operational level 2 and continuing evacuations.
- [Order INT/788/2026](https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-16657)
  describes stabilization and continuing hot-spot/perimeter work on July 30.
  Stabilization and de-escalation do not establish extinction.
- [Madrid's forest information](https://www.comunidad.madrid/medio-ambiente/montes-comunidad-madrid)
  describes the regional incident formed by the July 24 merger.
- [The November restoration document](https://www.comunidad.madrid/docs/2026-11/plan_rest_forestal_sierra_oeste_divulgacion_03112026.pdf)
  retrospectively describes the main event during July 22–28. It does not supply a
  verified fourteen-day incident lifecycle or a final extinction timestamp.

**The fourteen-day claim remains unverified by the reviewed official material.**
This is not a claim that no closing report exists. Incident identity at a satellite
cell, ignition causes for separate fronts and final extinction require additional
matching evidence. Search leads, titles and publication metadata alone do not
establish them. The source-check harness initially expected a plural Spanish word;
inspection showed the actual phrase was singular, “strong wind.” The corrected check
requires that actual phrase; the initial failed source check is retained.

## Data reconstruction and independent oracles

The initial local artifacts were outdated: the real cube had 927,542 rows and lacked
the current confidence metadata; the synthetic fixture also predated current region
centers. The baseline suite reported 22 failures. Rebuilding in the isolated worktree
resolved the data-fixture failures; installing the acquisition dependency already
listed in `requirements.lock` resolved the missing `earthaccess` import.

The current ETL published 1,577,454 deduplicated detections and 1,874,100 spatial
footprint contributions, with 729,742 nominal, 763,627 low and 126,695 high-confidence
cube rows. The original directory's source and data files were not changed; its shared Python environment received the already-declared acquisition dependency. Generated cubes and the
learned calibration LUT are not part of the code commit. Their fingerprints are in
`data-manifest.json`; the rebuilt LUT is retained locally under `data/cache/` and is
regenerated by the documented pipeline.

The real-file tests do not compute expectations through the examined helper. They
select actual H3 centers with Shapely, execute separate Parquet scans, integrate
available sensor values in Python, check source CSV acquisition identities and FRP,
verify deduplication and PSF weight conservation, and compare center counts with the
confidence-filtered cube. Diffusion adds spatial contributions; confidence filters,
deduplication and calibration change different quantities legitimately. Raw FRP,
sensor-fused energy and detection counts are never required to be equal.

Each real-file record includes question/context, input files, actual tool/API results,
the independent expected value, criterion and passed/failed status. The live records
include exact requests, real model turns, executed local/search tools and responses.
Source contents and supported claims are recorded separately. No blocked case is
counted as passed; no external credential/quota/source blocker remained in the final
selected validation.

## Reproduction

Run from `firms-harmonizer` using the repository's Python environment:

```bash
python -m pip install -r requirements.lock
python scripts/00_bootstrap_synthetic_cube.py
python scripts/run_pipeline.py etl
python -m pytest backend/tests -q
python -m pytest qa/test_copilot_archive.py -q
python scripts/verify_frozen_tests.py
USE_SYNTHETIC_CUBE=1 python backend/check_core.py
python qa/review_sources.py
python qa/run_live_conversations.py --output ../docs/verification/2026-11-15-copilot-quality/live-reproduced.json
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix qa ci
```

The live runner requires the explicitly configured provider's credentials and quota.
It records fallbacks as failures or blocked validations, never successful model turns.
No credentials are required for the independent local-file and offline browser checks.

For the browser run, start the API with real data and `COPILOT_OFFLINE=1` on port
18000, permitting the explicit local CORS origin `http://127.0.0.1:15173`. Start Vite
with `VITE_API_URL=http://127.0.0.1:18000/api` on port 15173, then run:

```bash
CHROMIUM_PATH=/usr/bin/chromium npm --prefix qa test
```

The browser sets `navigator.onLine=false`, uses actual localhost HTTP responses and
records zero external requests. No selected-context API response is mocked. It tests
year drafts/cancellation, leap dates, inclusive cross-year requests, reversed ranges,
context removal/replacement, area changes, real GPU hex picking and chat clearing.
An additional online smoke run (`node qa/browser_online.mjs`; `browser-online.json`, `browser-online.png`) exercises the actual browser → HTTP API → Gemini path and independently checks its returned GJ; it is not counted again as a new case.
The separate offline real-file test blocks DNS and socket connections while running
all six historical prompts. Localhost HTTP is compatible with airplane mode.

## Limits

These results demonstrate the named cases on this local data snapshot and configured
model. They do not establish universal natural-language accuracy, complete satellite
coverage or permanent provider availability. The controlled failure tests complement
the live conversations; they do not replace them.

The energy is a calibrated one-hour integration proxy from sparse satellite samples,
not continuously measured physical heat release. Missing annual fuel/mask inputs
remain unavailable. Counts and footprint are not incident counts or burned area.
No observation is extended to match a claimed incident duration.

Typed numerical validation and the explicit incident-match guard catch specified
failure classes. They do not prove every free-form scientific sentence or citation
entails its source. Human review remains necessary for consequential claims; the
manual review here deliberately caught errors the initial automatic criteria missed.
Additional incident perimeters, investigation findings and closure reports would be
needed to settle the remaining incident-specific questions.
