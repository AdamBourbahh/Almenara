# Change log — integration changes

## 2026-11-15 — Preserve episode dates during provider fallback

The local investigator now forwards the resolved map/conversation period to the
episode profiler, including follow-up questions without dates. A selected period
is retained in the returned map context; only discovery without a period creates
a new context around the detected peak. Explicit new dates still take precedence,
and an empty selected period cannot substitute an event from another year.

Regression cases exercise the actual fallback endpoint, scope resolver, DuckDB
and scientific profile against a stronger out-of-period episode. The core import
check reads UTF-8 explicitly on Windows without changing its assertions. Public
schemas and frozen tests are unchanged. Real Bejís before/after evidence is in
`../docs/verification/2026-11-15-bejis-period-fix/README.md`.

## 2026-11-15 — Fire Copilot context and evidence quality

Preserved inclusive date endpoints, selected geometry and scientific filters across
chat, measurements and episode tools. Added an explicitly labeled observation
timeline comparison, including local offline answers; profile/report windows no
longer replace attached dates. Fixed mapped energy using the nominal confidence
cube for low/high-confidence questions.

Provider selection is binding across services. Source leads cannot authorize event
citations without retrieved passages, document commands cannot become incident
facts, and explicit unverified links between thermal observations and named fires
must be corrected. Typed quantities replace unitless numeric matching; deterministic
decimal display rounding and known sensor identifiers are supported. Count and GJ
summaries lead quantitative answers. Scientific notes and map explanations now
describe canonical within-cell sensor fusion and conditional emissions correctly.

Added independent real-archive checks, selected-provider multi-turn conversations,
controlled failure regressions and Chromium UI coverage. The previous provider
cascade regression now enforces service selection; the accepted-center test fixture
adds the actual production confidence/industrial columns without changing expected
measurements. Public Python/TypeScript schemas and frozen checksums are unchanged.
See `../docs/verification/2026-11-15-copilot-quality/README.md` for evidence and limits.

## 2026-11-15 — Integration with updated origin/main

Preserved upstream inclusive chronology ranges, map search/scale, settings, local
document RAG, bounded investigation tools and request-local provider fallback.
Resolved overlapping accounting changes in favour of canonical within-cell fusion,
exact cell-area integrals and WGS84 polygon-normalized density. Migrated incoming
regression expectations to these physical units and actual archive bounds while
retaining their independent energy/concurrency/limit checks. Cache constructor
spellings are compatible and byte budgets remain bounded. The episode dossier now
uses the API's conditional annual-fuel PM2.5 instead of a generic 9.5 g/kg factor.
Region-name length is bounded at 200 characters in the shared schema. Forecast
coverage selection and its untouched final-year gate are retained.

## 2026-11-15 — Evidence-based coverage policy

Coverage policy update (2026-11-15): the fixed requirement of 95% complete whole-region days is replaced by temporal selection among 70/80/90/95% terrestrial support thresholds. Coverage is an exact-H3-area-weighted union of qualified cells across sensors, weighted by preceding-year measured land/water pixel fractions. Unknown land/water area remains potential unobserved land in the denominator; entirely missing land classifications remain unavailable. Legacy packed masks retain their >=95% valid-sample cell qualification and >=50% sampled-area screen. Consequently this is a sampled qualified-cell support proxy, not a pixel-exact measurement of observed terrestrial area. Historical observed-zero semantics remain conservative and unchanged.

Selection uses the penultimate year of monthly rolling origins after at least three training years. The final year is reserved for validation of the single chosen threshold; failure does not trigger selection of a different candidate. All candidates use high-support (>=95%) origins and labels, never cloudy zeros. Reports include 1/7/14-day MAE, persistence/climatology baselines, signed bias, nominal-95% interval coverage and seasonal representation. Publication still requires >=12 cases per horizon, all four seasonal groups, MAE no worse than either baseline, and >=90% interval coverage in both selection and holdout. No qualifying candidate means null plus an explicit reason. These tests validate the sampled thermal proxy, not independently measured physical energy. No missing energy is upscaled by dividing by coverage.

Run `python scripts/13_validate_coverage.py` to atomically publish matching `land_*.npz` preset indexes and `coverage-policy.json`. Arbitrary AOIs without a matching published index retain an unavailable forecast. Incomplete support or a weak reserved-year result must keep publication blocked.

## 2026-11-15 — all-nighter audit remediation

The user authorized coordinated changes across every ownership track. Energy now
integrates per-cell sensor fusion against each exact H3 area, then normalizes by
the WGS84 polygon area. Missing detections are unknown unless independent masks
support an observed zero or explicit gap evidence permits reconstruction. History
ends at actual archive/current-date limits and includes November/December 2000.
All five sensor bits are retained. Confidence thresholds select separately built
cubes; requests no longer silently ignore their selected threshold.

Coordinated additive contracts: DailyCalendarCell.observation_status and nullable
pm25_factor_sd_kg; AnalyzeResponse.coverage_note, forecast_validation and
forecast_unavailable_reason; EnergyForecastValidation; shared MapPeriodResponse
and sync request/status contracts. Python, TypeScript and SPECS.md are updated
together. PM2.5 uses measured annual classes and cited fuel factors; incomplete
support stays null. Causal FRE forecasts require rolling-origin baseline and
interval gates. No forecast is published merely because it was requested.

Chaos Monkey excludes the target year from prior/gain fitting, removes affected
spatial forcing and scores affected days against an intact-input model reference.
Annual diagnostics exclude partial years. UI verdicts preserve actual failures,
unknown emissions stay unavailable, and CSVs use a real UTF-8 BOM with blank
unknown physical estimates. Map periods use spatial-only queries. Observations
are virtualized and browser fixtures are isolated behind explicit opt-in.

Published EOG site-year evidence now constrains industrial scoring at a realistic
position scale. Acquisition scripts provide resumable MODIS/VIIRS masks, QA-filtered
MCD64A1 and measured annual MCD12Q1. Four official regions share one registry;
exclusive retired-region raw files and unused mocks are removed, while corrupt
historical sync files are quarantined. Raw files for the four regions are retained
as requested. Live synchronization uses canonical ETL and safe engine refresh.

Geometry/body/question/rate/concurrency bounds, explicit local CORS and a byte-bounded
cache protect analytical operations. Offline Copilot is the default. Dependency
locks, portable bootstrap/ETL/full verification, Windows/Linux CI and regular-file
agent rules support a fresh clone. Coordinated frozen tests were revised to remove
obsolete None/CORS-star assertions, with LF-normalized SHA-256 hashes regenerated.

Final evidence and remaining scientific availability limits are recorded in
`../docs/verification/2026-11-15-all-nighter/README.md` and `report.json`. The user
selected complete public MODIS acquisition plus staged, resumable VIIRS; the full
VIIRS historical archive is not claimed complete.

## 2026-11-14 — Incident explanation and acceptance tests

Reproduced the user's Madrid 24 July 2026 failure with live providers. Search found
relevant reports but the official-only short-quote gate discarded useful explanations.
Repaired provider selection and queries, article-body/encoding extraction, approved
redirect handling and diverse official/news retrieval. A source-URL index supplies a
verified official starting point for Madrid without embedding any incident answer.
Regional passage selection prevents multi-fire liveblogs from assigning another
incident's cause to Madrid. Explanations distinguish reported spread from ignition;
model failure can return validated reporting instead of only database counts.
Added deterministic scientific guidance, unavailable-metric handling and multilingual
numeric-intent fixes, plus a real-data acceptance runner with explicit answer-quality
checks and independent SQL counts. Full-text articles are not copied into public
citation records. Existing API contracts and map/calendar interactions are unchanged.

Validation: 419 backend tests (57 new acceptance/retrieval cases), 19 frontend tests
and the production build pass. Twelve real-data scenarios pass both with actual
search/model providers and with providers disabled. Numerical checks use independent
SQL. The Madrid 2026-07-24 case must contain a sourced spread explanation, rather than
only counts or a generic refusal. Reports are under root
`docs/verification/2026-11-14-copilot-acceptance/`. This finite matrix does not claim
perfect answers to every possible question or independently certify incident causes.

## 2026-11-14 — Dependency repair and synchronized integration

Completed the pending main rebase and resolved five accidentally committed conflict
blocks in the analysis store. Retained risk predictions, AOI prompts and live sync,
restored H3 coordinate imports, and preserved copilot attachments and selected dates.
Removed the unused deck.gl umbrella dependency. Aligned loaders.gl core/glTF/textures
on 4.5.4 and patched compression's fflate dependency to 0.7.5, removing the obsolete
texture-compressor/image-size chain without forcing a breaking image-size override.
Regenerated the npm lockfile from a clean dependency tree and corrected the Node engine
range to match Vite. Added npm test and make install/check-deps entry points; local
installation includes the optional Rasterio/STAC acquisition dependencies.

Rebuilt local real staging, outages, calibration and the master cube from the updated
tracked observations: 927,542 cube rows with coverage through 2026-11-14. Updated the
tracked calibration lookup. Fixed header controls overlapping after the sync widget
was integrated, including responsive navigation and a full-height copilot drawer.
Merged the incoming timeline-anchored risk prediction update, retaining both the
risk date prompt and automatic chatbot context. Final validation: 362 backend tests,
19 frontend tests, production build, pip check, npm ls --all and a zero-vulnerability
npm audit. Chromium exercised map loading, chat controls and mobile layout without
JavaScript errors or horizontal overflow.

## 2026-11-14 — Automatic removable context and causal evidence

Replaces the earlier pin/follow-map panel with one automatic location/date attachment
above the composer and a single remove X. Explicit AOI, hexagon and chronology
selections attach immediately; hover alone does not replace context. Area analysis
preserves the selected day, and timeline precision changes select the displayed unit.
Removal clears attached request geometry, dates and previous-scope inference while
retaining visible chat. Compatible locality names preserve the actual selected polygon.

Answers now use question-specific sections. Causal questions lead with the documented
status or uncertainty and concise local evidence, with no irrelevant FRP/ranking dump.
Annual selections request an incident day rather than guessing the busiest day.
Scientific mechanisms are distinguished from incident-specific ignition evidence.

Official and reputable-news searches run in parallel with domain, location/date and
source-diversity checks. Selected official articles are retrieved without redirects,
with bounded bodies/timeouts. Causal extraction accepts complete verbatim sentences
only, validates source text and nearby event date/locality, and rejects invented quotes
or excerpts that strip preceding negations. Crossref adds relevant DOI publication
metadata while excluding obvious retractions/corrections. Metadata and background
papers are not represented as verified incident causes. The model is not retrained.
All existing API contract fields remain compatible. Source cards are collapsed by
default and identify official reports, news and scientific literature.

Validation: 306 backend tests and 18 frontend tests pass, the production build passes,
and all frozen test hashes match. Chromium checks exercise an actual right-button AOI
drag, preservation of the selected 2026-07-24 date, the Madrid causal question without
polygon/date expansion, X removal with no stale context in the next request, and mobile
layout with no horizontal overflow or JavaScript errors. A live real-data research
check retrieves six references, including three DOI metadata records, while explicitly
leaving the selected incident's ignition cause unverified.

## 2026-11-14 — Exact daily and monthly map observations

User-authorized integration across API, DuckDB and frontend: added synchronous
`POST /api/map-period` with inclusive date bounds, source provenance, bounded caching,
industrial filtering and per-cell energy/count aggregation from the local cube.
The frozen `schemas.py` and `types.ts` contracts are unchanged. The new endpoint reuses
the existing hexagon shape: its legacy `mean_annual_fre` field contains the selected
period's integrated energy density, without annual extrapolation or regional gap filling.
See root `SPECS.md` §5.4 for the additional endpoint contract.

Day/month selection now reloads map cells with cancellation, stale-response protection
and period-aware caching. Map tooltips, the chronology dock and the right panel identify
the same period. Colors retain a shared reference; empty dates show no observations.
The first satellite detection must not be described as an exact ignition time.
Regression coverage includes leap days, month totals, empty periods, industrial filtering,
date validation, cache isolation and late responses.

Cada fila es un cambio hecho por Moha (dueño de `backend/db/` y `backend/api/`) sobre un archivo compartido o de otra persona. Motivo general: implementar la API sin datos falsos ni sustitutos silenciosos (plan v2).

| Fecha | Archivo | Dueño original | Cambio | Motivo | Afecta a |
|---|---|---|---|---|---|
| 2026-11-14 | `backend/db/nrt_poller.py` | Moha | Implementación 100% lista para producción del poller NRT (ADR-03) con soporte offline y test en `test_nrt_poller.py` | Eliminar archivo vacío (0 bytes); regla ZERO PLACEHOLDERS de AGENTS.md | Backend, DuckDB |
| 2026-11-14 | `backend/api/main.py` | Moha | Integrado `start_nrt_poller()` y `stop_nrt_poller()` en lifespan de FastAPI | Gestión del ciclo de vida del poller NRT en background | Backend |
| 2026-11-14 | `backend/db/queries.py` | Moha | Corregido f-string SQL en `fetch_risk_daily` y sustituido `.execute().to_arrow_table()` por `.sql().to_arrow_table()` | Cumplimiento del guardarraíl AST de SQL y eliminación de advertencias UserWarning por copia extra de filas | Backend, DuckDB |
| 2026-11-14 | `backend/api/routes.py` | Moha | Actualizado `duckduckgo_search` a `ddgs` e incluido estado de NRT en `/api/health` | Eliminar RuntimeWarning de paquete renombrado y enriquecer healthcheck | Backend, Health |
| 2026-11-14 | `backend/api/schemas.py` | Adam | Añadidos `CitationReference`, `ExplainSpikeRequest` y `ExplainSpikeResponse` | Contratos para endpoint `/api/explain-spike` (grounding web y citas científicas) | Frontend, Backend |
| 2026-11-14 | `frontend/src/api/types.ts` | Mohammed | Espejo de `CitationReference`, `ExplainSpikeRequest` y `ExplainSpikeResponse` | Tipos TypeScript sincronizados con backend | Frontend |
| 2026-11-14 | `backend/api/routes.py` | Moha | Implementado endpoint síncrono `POST /api/explain-spike` con triaje físico y grounding web en cascada | Explicación científica de anomalías con citas [1]..[5] y [W1]..[W3] | Frontend, Demo |
| 2026-11-14 | `backend/api/schemas.py` | Adam | `AnalyzeResponse.data_source` y `ChaosMonkeyResponse.data_source: Literal["real","synthetic"]` (nuevos, obligatorios) | Toda respuesta debe decir si los datos son reales o sintéticos | Frontend (Mohammed, Migue) |
| 2026-11-14 | `backend/api/schemas.py` | Adam | Pasan a nullable: `DailyCalendarCell.pm25_emitted_kg`, `DailyCalendarCell.tooltip_narrative`, `AnalyzeResponse.forecast_series`, `ScientificAuditMetrics.total_pm25_emitted_tonnes` | Forecast a 14 días, PM2.5 y tooltip quedan fuera del MVP y se devuelven como `null`. PM2.5 necesita un factor de emisión por bioma con fuente citada | Frontend: hay que gestionar `null` |
| 2026-11-14 | `backend/api/schemas.py` | Adam | Pasan a nullable: `ScientificAuditMetrics.burned_area_r2_raw/harm` y `AnalyzeResponse.audit_metrics` | `null` si falta la columna `burned_area_ha_mcd64` o si la AOI no tiene datos (respuesta 200 con listas vacías) | Frontend |
| 2026-11-14 | `frontend/src/api/types.ts` | Mohammed | Espejo exacto de los cambios anteriores (`\| null` y `data_source`) | `test_cube_schema.py` exige que `types.ts` y `schemas.py` coincidan | Frontend |
| 2026-11-14 | `specs.md` | Compartido | Tablas de la sección "Frozen API" actualizadas; regla "required except nullable"; documentado `USE_SYNTHETIC_CUBE` | Mantener una única fuente de verdad | Todos |
| 2026-11-14 | `scripts/00_bootstrap_synthetic_cube.py` | Germán | `_write_mock` añade `data_source="synthetic"`. Se regeneró `data/mock/mock_analyze_response.json` | El mock debe seguir validando contra el schema | Germán, Frontend |
| 2026-11-14 | `agent.md` (y copias vía `make sync-rules`) | Compartido | Propietario ANTONIO → MOHA, con los archivos nuevos `core_contract.py`, `validation_report.py`, `test_db_layer.py` y `conftest.py` | El responsable del módulo es Moha | Todos |
| 2026-11-14 | `agent.md` escudo 4 | Compartido | Ahora: polyfill R7 → padres R4 únicos → filtro `h3_r4` y después `h3_r7`. Sin polyfill R4 directo y sin fallback de centroide / `grid_disk` | `polygon_to_cells` en R4 solo incluye celdas cuyo centro cae dentro y pierde las celdas del borde (hay un test que lo demuestra) | Todos |
| 2026-11-14 | `Makefile` | Compartido | `make test` también ejecuta `test_db_layer.py` | Nuevos tests de contrato | Todos |
| 2026-11-14 | `agent.md` (y copias) | Compartido | La fila MOHA añade `backend/check_core.py` y `backend/tests/test_core_validation.py` | Archivos nuevos de este bloque | Todos |
| 2026-11-14 | `AGENTS.md` (raíz, nuevo en main) | Compartido (Tifu0) | Al fusionar main en `api`: regla de oro 2 (se citan las excepciones de contrato registradas aquí), regla 4 (cubo sintético solo con `USE_SYNTHETIC_CUBE=1`, nunca automático), fila 3 ANTONIO → MOHA con sus archivos, Guardrail 4 reescrito (R7 primero → padres R4 únicos, sin polyfill R4 ni fallback de centroide) | Decisiones de Moha para este PR; el AGENTS.md nuevo las contradecía | Todos |
| 2026-11-14 | `SPECS.md` (raíz, nuevo en main) | Compartido (Tifu0) | §5.2 sustituido por copia literal del `schemas.py` real (la versión de SPECS divergía: `gap_reason` como enum, `forecast_days` ≤ 30, años desde 2000, sin `data_source`). Forecast marcado como fuera del MVP | Una sola verdad: manda `backend/api/schemas.py` | Todos, sobre todo frontend |
| 2026-11-14 | `firms-harmonizer/{agent,AGENTS,CLAUDE,specs}.md` | Compartido | Se acepta su borrado (hecho en main) | Las reglas viven ahora en la raíz | Todos |
| 2026-11-14 | `.cursorrules`, `.windsurfrules`, `.clinerules` | Compartido | Enlaces simbólicos redirigidos de `agent.md` (borrado, quedaban rotos) a `../AGENTS.md`; `.github/copilot-instructions.md` sincronizado con la raíz | Los enlaces estaban rotos en main | Quien use Cursor, Windsurf, Cline o Copilot |
| 2026-11-14 | `Makefile` (`sync-rules`), `.aider.conf.yml` | Compartido | Ahora copian o leen `../AGENTS.md`, `../SPECS.md` y `CAMBIOS.md` | `agent.md` y `specs.md` ya no existen | Todos |
| 2026-11-14 | `.env` (raíz) | Tifu0 | Se deja de seguir en git (`git rm --cached`) y se añade un `.gitignore` en la raíz | Contenía `FIRMS_MAP_KEY`. **La clave sigue en el historial de main: hay que revocarla en NASA FIRMS y pedir una nueva** | Quien use la API de FIRMS |
| 2026-11-14 | `data/mock/mock_analyze_response.json` | Germán | Regenerado con el generador fusionado (`write_mock` de main + `data_source` de este PR) | Conflicto de fusión | Frontend |
| 2026-11-14 | Todo el repo (`.gitattributes` nuevo en la raíz) | Compartido (Tifu0) | El commit `4d0f6cb` pasó 39 archivos a CRLF sin cambiar su contenido. Se renormalizan a LF y `.gitattributes` fija `eol=lf` (git convierte en local en Windows) | Los hashes de `FROZEN_TESTS.sha256` fallaban y el Makefile y los shebangs se rompían con `\r` | Quien trabaje en Windows |
| 2026-11-14 | `frontend/src/api/types.ts` (fusión PR #2) | Mohammed / Antonio | Se mantiene el contrato (espejo de `schemas.py`). Se añaden los tipos solo de UI `ViewMode`, `ConfidenceLevel` y `GapReason` (códigos del generador offline). `H3MapSummaryHex.h3_index` pasa a obligatorio, como en `schemas.py` | El `types.ts` del PR #2 quitaba `data_source` y los `\| null`, convertía `gap_reason` en enum y renombraba campos (`total_biomass_burned_kt`), y la API no envía eso | Frontend |
| 2026-11-14 | `frontend/src/api/client.ts`, `CalendarTooltip.tsx`, `HatchPatternDefs.ts` (fusión PR #2) | Mohammed / Antonio | Ajustes mínimos para compilar contra el contrato. CSV y tooltip usan `biomass_burned_tonnes`. El tooltip acepta `gap_reason` como texto o `null` y `pm25_emitted_kg` como `null`. El generador offline añade `data_source: "synthetic"`, `is_forecast`, `dates`, `raw_pixel_count` y `shannon_entropy` y usa los valores por defecto del schema. Se añaden `getHatchPattern` y `hatchCss`, que `BurningCalendarCanvas` importaba pero no existían (la rama no compilaba sola) | `npx tsc --noEmit` y `npm run build` en verde | Frontend |
| 2026-11-14 | `backend/db/queries.py`, `backend/api/routes.py` | Moha | `EPOCH` pasa de 2000-01-01 a **1970-01-01** y queda en una sola constante (`queries.EPOCH`) | El cubo sintético nuevo (merge de `computo`) y `SPECS.md` §5.1 usan días desde 1970-01-01. Con la época vieja las fechas salían desplazadas 30 años | Todos los que lean `epoch_day` |
| 2026-11-14 | Tests congelados (`conftest.py`, `test_db_layer.py`, `test_api_contract.py`, `test_core_validation.py`) y `FROZEN_TESTS.sha256` | Moha | Solo constantes: el polígono del Cerrado pasa a los límites de `SPECS.md` §5.3 (lon −57,2..−55,2, lat −17,8..−16,0), la celda pequeña a (−16,9, −56,2) y la época a 1970. En `test_industrial_exclusion_contract`, «todo Níger es industrial» se sustituye por invariantes de contrato: cada hotspot se conserva o cuenta como eliminado, `removed > 0`, la exclusión no añade celdas y hay algún hexágono industrial. Hashes regenerados | El cubo nuevo ya no tiene celdas en el polígono antiguo y en Níger solo 6 de 10 celdas son industriales | Moha |
| 2026-11-14 | `frontend/src/api/types.ts` (`PRESET_REGIONS`), `backend/check_core.py`, `backend/validation_report.py` | Moha / Mohammed | Presets = límites de `SPECS.md` §5.3, con centro en el punto medio | Así coinciden con las celdas del cubo sintético nuevo | Frontend |

| 2026-11-14 | `backend/tests/test_api_contract.py` y `FROZEN_TESTS.sha256` | Compartido (Migue) | El commit `319ac09` añadió a un test congelado la comprobación de que `trigger_cube_sync` y `get_cube_sync_status` son síncronos, más un caso para `/api/cube/sync-status` y `/api/cube/sync`, pero no regeneró el hash. El cambio es aditivo: no elimina ni debilita ninguna aserción previa. Hash regenerado (`5fbe0389…6818b7`) | Mantener el gate `sha256sum -c FROZEN_TESTS.sha256` en verde | Moha / quien toque los tests congelados |

### Discrepancias abiertas tras la fusión (decidir en equipo)
- ~~**Polígono del Cerrado**~~ Resuelto: todo usa ya los límites de `SPECS.md` §5.3.
- **Columnas del cubo**: `SPECS.md` §5.1 marca `neighbor_fre_lag1`, `cloud_cover_pct` y `burned_area_ha_mcd64` como NOT NULL. La API las trata como opcionales: si faltan, las lee como NULL y lo avisa en `/api/health`.
- ~~**`cloud_cover_pct`**~~ Resuelto: el generador nuevo lo guarda como fracción [0, 1].
- **Presets del frontend (PR #2)**: `useAnalysisStore.PRESET_REGIONS` (Chilecito, Amazonas, California, Iberia) no coincide con `types.ts.PRESET_REGIONS` ni con el cubo sintético. Con `USE_SYNTHETIC_CUBE=1`, Chilecito y Amazonas devuelven 200 con listas vacías porque el cubo no tiene celdas allí.
- **`data/processed/fire_cube.parquet` está en git y es SINTÉTICO**: el merge de `computo` lo subió y ahora `scripts/00_bootstrap_synthetic_cube.py` escribe por defecto en esa ruta, la del cubo **real**. La API se niega a servirlo sin `USE_SYNTHETIC_CUBE=1` (lo detecta por los metadatos), pero ejecutar el generador sobrescribe un cubo real si existe. Propuesta: que el generador escriba por defecto en `fire_cube_synthetic.parquet` y dejar de versionar el parquet.
- **Interfaz del core de Adam**: `kalman_rts.py` expone `build_cross_sensor_historical_prior(doy, y_obs) -> (H_gain, prior_series, lut_366)` y `rts_kalman_smoother_with_cross_guard(y_obs, u_spatial, doy, cloud_cover, ...) -> dict`. La API espera `compute_cross_prior(doy, obs) -> float[366]` y `kalman_rts_smooth(obs, u_spatial, prior) -> .x_smooth/.p_smooth` (ver «Interfaz Core»). `von_mises.py`, `auditor_stats.py` y `chaos_monkey.py` siguen vacíos. `python -m backend.check_core --synthetic` → 8 MISSING (exit 2), y `/api/analyze` responde 503. Hay que acordar los nombres: o Adam añade alias con la firma acordada, o se adapta `core_contract.py` a sus funciones.
- **Generador offline del frontend**: `client.ts` inventa respuestas completas (incluidas Chow, W1 y R²) cuando el backend no responde (502/503/504, timeout o red). Avisa con `isSynthetic` y con el veredicto `[OFFLINE SYNTHETIC]`, pero `isSynthetic` vale `false` cuando el backend sirve el cubo sintético (habría que mirar `data.data_source`). Además, un 503 por falta del core de Adam dispara también este generador.

## Comportamiento nuevo de la API que conviene conocer
- **Cubo sintético solo con `USE_SYNTHETIC_CUBE=1`.**
  - Con esa variable se usa `data/processed/fire_cube_synthetic.parquet`, que se genera si no existe.
  - Sin ella, el servidor **no arranca** en dos casos: si falta `data/processed/fire_cube.parquet` o si ese archivo es sintético según sus metadatos.
  - Para la demo: `USE_SYNTHETIC_CUBE=1 make api`.
- **Columnas opcionales ausentes** del cubo: se leen como NULL y se listan en `GET /api/health` → `missing_columns`.
- **Zona sin datos**: `POST /api/analyze` responde 200 con listas vacías y `audit_metrics: null`. `POST /api/chaos-monkey` responde 404.
- **Entradas inválidas**: un polígono inválido (anillo abierto, menos de 4 posiciones, coordenadas fuera de rango o lados que se cruzan) o años fuera de rango responden 422.
- **Caché**: la cabecera `X-Cache: HIT|MISS` indica si la respuesta sale de la caché.
- **Si falta una función de `backend/core/`**: `/api/analyze` y `/api/chaos-monkey` responden **503** con el nombre y la firma esperada. `GET /api/health` → `core` muestra qué funciones existen.

## Pendiente de acordar con Adam — Interfaz Core
`backend/api/core_contract.py` busca exactamente estas funciones. No hay sustitutos: si falta alguna, la API devuelve 503.

```
backend.core.kalman_rts.compute_cross_prior(doy:int[n], obs:float[n,3] NaN=missing) -> float[366]
backend.core.kalman_rts.kalman_rts_smooth(obs:float[n,3], u_spatial:float[n] NaN allowed, prior:float[n])
                                          -> obj with .x_smooth float[n], .p_smooth float[n] (>=0)
backend.core.von_mises.fit_von_mises_year(doy:int[m], weights:float[m]) -> (mu_doy, kappa, width_days)
backend.core.von_mises.phenology_trend(years:int[k], peaks:float[k]) -> (slope_days_per_decade, mk_p)
backend.core.auditor_stats.chow_test(values:float[n], years:int[n], doy:int[n]) -> (F, p)
backend.core.auditor_stats.wasserstein_w1_normalized(values:float[n], years:int[n]) -> float
backend.core.auditor_stats.descriptive_r2(x:float[n], y:float[n]) -> float | None
backend.core.chaos_monkey.run_chaos_monkey_simulation(daily:dict[str,ndarray], target_year,
        drop_fraction, simulate_dual_blackout, random_seed) -> dict con los campos de ChaosMonkeyResponse salvo data_source
```
`daily` tiene 14 claves: `epoch_day, year, doy, raw_modis_cnt, raw_viirs_cnt, raw_frp_mw, obs_terra_fre, obs_aqua_fre, obs_viirs_fre, neighbor_fre_lag1, cloud_cover_pct, gap_status_mask, sensor_obs_mask, burned_area_ha_mcd64`. Es una rejilla diaria densa: las observaciones ausentes son NaN y una máscara cuya columna falta vale -1.

El chaos monkey, según lo definido, elimina al azar un X % de observaciones con semilla fija, aplica el suavizado y mide el % de energía estacional recuperada.

## Contrato de salida que valida la API (`backend/api/core_contract.py`)
Cada resultado de `backend/core` pasa por `core_contract.call()`. Si no cumple esta tabla, la API responde **500** con el nombre de la función (`backend.core.<módulo>.<función> violated the API contract: ...`). Si la función no existe, responde **503**.

| Función | Debe devolver |
|---|---|
| `compute_cross_prior` | array de floats con forma (366,), todo finito |
| `kalman_rts_smooth` | objeto con `.x_smooth` y `.p_smooth`, ambos con forma (n,), finitos, y `p_smooth ≥ 0` |
| `fit_von_mises_year` | tupla de 3 floats finitos `(mu, kappa, width)`, con `kappa ≥ 0` y `width > 0` |
| `phenology_trend` | tupla de 2 floats finitos `(slope, p)`, con `0 ≤ p ≤ 1` |
| `chow_test` | tupla de 2 floats finitos `(F, p)`, con `F ≥ 0` y `0 ≤ p ≤ 1` |
| `wasserstein_w1_normalized` | float finito `≥ 0` |
| `descriptive_r2` | `None` o un float en [0, 1] |
| `run_chaos_monkey_simulation` | dict con **exactamente** las claves de `ChaosMonkeyResponse` salvo `data_source`. Las 6 listas diarias deben tener la misma longitud que `dates` |

El número de argumentos posicionales también se comprueba (`/api/health` → `core_signatures`).

## Cómo comprobar tu código, Adam
```
python -m backend.check_core --synthetic
```
Ejecuta cada función con entradas deterministas del cubo (Cerrado, 2001–2026, n = 9496 días). Imprime PASS / FAIL / MISSING, el motivo y los ms por llamada. Termina con código 0 si todo cumple, 1 si hay alguna violación o fallo y 2 si falta alguna función. `python -m backend.validation_report --synthetic` lo ejecuta primero y después imprime los diagnósticos científicos tal como salen.

## Presupuesto de tiempo medido (2026-11-14; portátil WSL de 2 núcleos, cubo sintético, Cerrado, core FAKE)
| Etapa (`Server-Timing`) | ms |
|---|---|
| `h3` (filtro H3 en frío; con la geometría en caché ≈ 3 ms) | ≈ 20–24 |
| `db` (un solo escaneo + agregación) | ≈ 40–49 |
| `build` (calendario, fenología, auditoría) | ≈ 23 |
| `validate` (`AnalyzeResponse`, 9496 celdas) | ≈ 42 |
| `serialize` | ≈ 31 |
| **`execution_time_ms` sin core** (lo que la API mide antes de validar) | **≈ 97** |
| POST en frío completo / hit de caché (incluye gzip-1 y HTTP) | ≈ 224 / ≈ 42 |

Con el objetivo de `execution_time_ms < 250 ms`, quedan **unos 150 ms para todas las llamadas al core en una petición**: 1 prior, 1 Kalman con n = 9496, 26 von Mises, 1 tendencia, 2 Chow, 2 W1 y 2 R². `check_core` muestra cuánto tarda cada una.


## 2026-11-14 — Real scientific API adapter

`backend/api/science_adapter.py` translates the existing eight analysis operations to the implemented scientific core; no public Python/TypeScript schema or frozen test file changes. `core_contract` resolves and checks the actual underlying dependencies, so missing science still returns HTTP 503. Kalman receives explicit per-request DOY and cloud fractions through `KalmanInput`, and its state, covariance and uncertainty are preserved. Phenology uses the circular model and unwrapped trends. Chow uses annual means; descriptive R2 uses complete annual totals. Requests with insufficient years across 2012 return nullable audit metrics instead of invented significance.

Chaos Monkey extracts the requested year, supplies the full retrospective calibration history and converts the core Pydantic result to the HTTP shape. The HTTP response uses the selected cube's provenance. Its reference is the intact smoother; full-history use is retrospective and is not held-out independent validation. Forecast, PM2.5 and tooltip HTTP fields retain their deferred nullable behavior.

Verification: 148 backend tests passed (including four new actual-core HTTP integration cases); all four frozen test hashes match; `python -m backend.check_core --synthetic` passes all eight operations; `python -m backend.validation_report --synthetic` completes all four pilot regions. The artifact is synthetic: real-data scientific validation and latency targets remain separate acceptance gates.

## 2026-11-14 — Real observations viewer

The default frontend now uses additive `POST /api/observations` with a GeoJSON polygon body. Responses contain `data_source: "real"`, `daily` (UTC date/year/DOY, detection_count, raw_frp_mw, sensors), `map_hexagons` (15-character H3 hex, detection_count, raw_frp_mw), total detections, first/last observed dates, execution time and a method description. Values come exclusively from accepted staging detection centers, without calibration or imputation. Missing staging or synthetic backend mode returns 503. The endpoint uses hierarchical R4/R7 filtering, request-local cursors, Arrow cell tables and bound SQL parameters. Counts and FRP are additive across map cells and days; no scientific validation or energy interpretation is implied.

The UI reads its four study envelopes from data/regions.json, displays observed counts, raw FRP, all five instruments and explicit missing-day semantics, and exports an observations CSV. It has no automatic synthetic fallback, gap-filling control, forecast or emissions/audit claims. Calendar gaps remain blank. Map colors summarize the full observed period; the history year control only selects the inspected annual count. The map stays mounted across tabs. Legacy scientific API contracts and their TypeScript mirror are unchanged.

## 2026-11-14 — Database metrics and pinned map context

Fire Copilot now answers quantitative energy, biomass and detection questions directly
from server data. `copilot_metrics.py` reuses the dashboard's `/api/analyze` calculation
over the 2001–2026 history and selects inclusive query dates. It preserves reconstruction
and industrial-source filters, reports GJ integration, reconstructed days, biomass,
peak-energy day and per-year totals, and identifies the derived local cube separately
from accepted raw detection counts. It does not interpret detections as unique fires.
Local metric requests call neither model nor search providers. Missing cube columns,
unsupported dates and absent spatial data return explicit limitations.

The user-requested chatbot/map integration coordinates changes across the backend and
frontend ownership tracks. Existing contract fields are retained. Optional request
booleans `prefer_map_context=false`, `exclude_industrial_flaring=true` and
`enable_kalman_gap_filling=true`, nullable request `previous_context=null`, and
nullable response `map_context=null` are mirrored
in `backend/api/schemas.py`, `frontend/src/api/types.ts` and root `SPECS.md`.
`CopilotMapContext` carries the resolved label, polygon, dates and optional R7 cell ID.

Follow-ups echo the structured resolved scope so dates, custom AOIs and hexagons
survive bounded history; new attachments discard that prior scope.

The drawer follows the map selection, supports pinned geometry and filter snapshots,
click-to-attach hexagons, removable hexagons and arbitrary date attachments. Context
changes preserve visible chat but reset scope inference for subsequent requests.
Messages show their attachment snapshots; answers show the actual queried area/dates.
The existing single DeckGL mount is preserved. The attached chatbot methodology
informs grounding and fallback behavior; project UI and documentation stay in English.

Validation: 287 backend tests and 16 frontend tests pass; the production frontend
build passes and all four frozen test hashes match. A real-data offline check against
independent staging SQL and the scientific dashboard returns 8 detections and 15.811 GJ
for R7 cell `87390cac0ffffff` on 2026-07-24 through 2026-07-25. Chromium checks cover
pinned dates, a real Madrid energy query, desktop/mobile layouts, actual GPU cell
picking and attachment removal, with no JavaScript errors or horizontal mobile overflow.

## 2026-11-14 — Main integration conflict resolution

Merged upstream observations, ETL updates and Physics-First Fire Copilot while retaining
the integrated chronology dock and exact daily/monthly energy maps. The Observations
section exposes accepted FIRMS records and CSV export separately from calibrated energy.
The upstream observations and explanation endpoints and their additive contracts are retained.
Validation: 73 backend tests, 8 frontend tests and the production build passed.

## 2026-11-14 — Evidence-first Fire Copilot (`computo`)

The chatbot now queries accepted FIRMS detection centers for the question's place and
exact dates, instead of explaining whichever region happened to be selected in the UI.
`backend/api/fire_copilot.py` separates scope resolution, parameterized observation
retrieval, candidate web reports, bounded model calls and deterministic local answers.
Local numerical summaries remain available without network access. Model failure no
longer becomes an invented extreme fire or a remote/undocumented burn. Counts are not
fire events; power is not energy; high entropy is not proof of gas flaring; a date in
2012 is not proof of an instrumentation artifact.

Coordinated contract addition: `CopilotTurn` and optional `conversation` (default empty,
at most 12 turns, each at most 6,000 characters), `period_start` and `period_end` (default
null) are mirrored in `backend/api/schemas.py`, `frontend/src/api/types.ts` and the
frozen-contract excerpt in root `SPECS.md`. Existing fields and types are unchanged.
The user's instruction granting full freedom for chatbot improvements authorizes the
backend/frontend integration across the usual file-ownership tracks.

The frontend supplies geometry, chronology and bounded conversation history, prevents
concurrent duplicate sends, cancels cleared requests and ignores stale responses.
Citation markers open their actual sources. Source labels distinguish retrieved web
results from verified incident matches, and synthetic provenance remains visible.
Backend outages surface errors instead of fabricated client-side explanations.

Groq defaults to `openai/gpt-oss-120b` with `openai/gpt-oss-20b` as fallback; both can be
overridden. The previously preferred Llama model returned HTTP 404 for the configured
account. Authentication and quota failures are not retried across models. The retired
`duckduckgo-search` dependency is replaced by `ddgs`, with bounded search fallback and
10-minute in-memory caching of successful queries. Optional Tavily remains supported.
`COPILOT_OFFLINE=1` prevents all assistant provider requests.

`backend/tests/test_explain_spike.py` now tests grounded behavior without network access.
It no longer requires scientifically unsupported classifications or unmeasured biomass
claims. The four files listed in `FROZEN_TESTS.sha256` are unchanged. Frontend copilot
regressions cover context transmission, provenance, cancellation and unavailable backend
behavior. `scripts/06_validate_copilot.py` exercises Madrid/Sierra Oeste (2026-07-24),
Careiro (2024-09-13), Autazes (2023-10-09), monthly Manaus observations and a next-day
follow-up against the real local archive, saving complete responses and source links.

Validation completed on 2026-11-14: 255 backend tests passed (35 copilot regressions),
12 frontend tests passed, and the production frontend build passed. All four frozen
test hashes match. Real-data offline and live numerical checks passed for all five
cases and the next-day follow-up; full snapshots are in
`data/processed/copilot_validation_{offline,live}.json`. Live model prose was also
checked against retrieved reports; free search availability and provider quotas varied,
so the snapshots explicitly record whether each response used a model or local fallback.
These automated checks establish numerical consistency, not independent certification
of every generated narrative. The missing real cube was rebuilt locally from existing
staging and lookup files; generated Parquet remains ignored by git.

## 2026-11-14 — Main integration

Retained the offline predictor and date-specific map alongside the upstream modular
Fire Copilot. The FIRMS NRT CLI and background ingestion share the validated area
client. Background polling requires `NRT_POLLING=1`, stays idle in offline or synthetic
mode, and writes to a separate in-memory table through an isolated DuckDB cursor.
The health endpoint exposes polling status. Offline and mocked tests cover the path;
live FIRMS ingestion was not exercised during the merge.

## 2026-11-14 — Risk AI completeness and map shortcut

The Python and TypeScript risk horizon contracts add optional `prior_targets` for
backward compatibility. Forecasts for sparse observed areas use the causal prior
documented in SPECS. The panel omits undefined diagnostics and marks each prior
estimate. Selecting an area opens a dismissible shortcut to Risk AI and computes
the new forecast on demand, without mounting an additional map.

## Cambios de contrato pendientes (auditoría 2026-11-14)

Estos puntos están congelados hoy por `FROZEN_TESTS.sha256`. Solo pueden cambiar
por acuerdo del equipo, modificando la aserción afectada y regenerando el hash:

| Punto | Test que lo fija | Cuándo cambiarlo |
| :--- | :--- | :--- |
| `forecast_series` siempre `null` | `test_api_contract.py:63` | Si se implementa el pronóstico de 14 días |
| `pm25_emitted_kg` / `tooltip_narrative` `null` y `total_pm25_emitted_tonnes` `null` | `test_api_contract.py:64-65` | Si se implementa PM2.5 con factor de emisión citado y narrativas |
| CORS `allow_origins == ["*"]` | `test_api_contract.py:140` | Si se restringe CORS por seguridad |

Procedimiento: (1) acordar el cambio con el dueño del test y de `schemas.py`;
(2) modificar solo la aserción afectada, sin debilitar el resto; (3) regenerar
`sha256sum backend/tests/<fichero>` en `FROZEN_TESTS.sha256`; (4) registrar el
cambio en esta tabla con fecha, autor y motivo. El hash regenerado el 2026-11-14
tras los tests de sincronización del cubo es el último cambio aprobado.

## Historical forecast origins and blackout validation

Risk AI and Impact share the timeline cutoff. The additive assessment field
`last_observation_date` distinguishes the last cube record from the requested UTC
origin. Forecasts after a gap blend toward historical event frequency as the gap
grows. `python -m scripts.07_risk_blackout_benchmark` replays Chilecito and Iberia
with hidden input blocks and scores the next 1, 7 and 14 days against later reports.

## 2026-11-15 — Autonomous scientific episode investigations

Coordinated additive Python/TypeScript contract update, documented in SPECS §5.8:
optional request `audit_metrics` and bounded `chat_history`; response
`answer_markdown`/`provider_used` compatibility mirrors and nullable
`episode_summary`. Existing names and types remain valid. The episode pipeline
profiles local measurements independently of model prose and exposes assumptions,
coverage limits and censored duration. Assumed PM2.5/CO2 estimates are confined to
this dossier and do not change the dashboard's unavailable measured emissions.
## 2026-11-14 — API energy accounting, calendar bounds and limits (Antonio)

No field was added, removed or retyped; `schemas.py`, `types.ts` and the four frozen tests are
unchanged. Several fields now carry their documented meaning:

- `biomass_burned_tonnes`, `total_biomass_burned_kt`, `total_annual_fre_gj`: daily energy is the
  cell-mean density times the km² of the cube cells present that day
  (`AoiAggregate.daily_area_km2`). It used to be multiplied by the area of every cell that burned at
  any time in 2001-2026, inflating totals 500-1,900x on the real cube (Iberia: 20,017,560 kt ->
  25,109 kt). Days with no cube row now add no biomass. A 1.4-1.7x gap remains against a direct
  per-cell sum because sensors are averaged over different cell subsets before the Kalman — a model
  input decision for Adam, not a unit error.
- `aoi_area_km2`: the polygon's R7 area (Chilecito 150,993 km²), no longer the area of cells with data.
- `calendar_series` ends on the cube's last day (`duckdb_engine.last_epoch_day()`); it no longer
  pads to 31 December with gap-filled days that have no data. Same for `/api/chaos-monkey`.
- `active_sensors`: decodes all five ETL bits (Terra, Aqua, VIIRS S-NPP, VIIRS NOAA-20,
  VIIRS NOAA-21). The previous `& 7` mask dropped NOAA-20/21, leaving 291-369 detection days per
  preset with an empty sensor list.
- Input limits (HTTP 422): more than 1,000 polygon positions; polygons estimated (R4 polyfill × 343)
  above twice the 250,000 R7 limit are rejected before the exact polyfill (60°×60°: 4.1 s -> 12 ms);
  `user_question` above 2,000 characters and `region_name` above 200 in `/api/explain-spike`.
- Chaos Monkey learns its prior only from years other than the target year (holdout). Measured effect
  is under 1%; the metric itself (recovery ~90-100% in every case) is for Adam to redefine.
- Caches are bounded by bytes as well as entries (`/analyze` bodies 256 MB, geometries 128 MB).
  Theil-Sen hex trends run in 64-row blocks (identical results, ~0.3 MB temporaries instead of
  ~370 MB); Iberia `/analyze` cold time dropped from ~1.6-2.1 s to ~1.2-1.6 s.

For Moha: a yearly map via `/api/map-period?start_date=YYYY-01-01&end_date=YYYY-12-31` returns the
same hexagons as the yearly `/api/analyze` call used by `loadMapYear`, without running the Kalman,
with 25-65% fewer bytes.

Still blocked by frozen tests (team decision needed): restricting CORS (`allow_origins == ["*"]`),
populating `forecast_series` / PM2.5, and raising the gzip level. Regression tests on a sparse,
real-shaped cube: `backend/tests/test_api_accounting.py` (306 backend tests pass).

## 2026-11-15 — Copilot integration with corrected daily footprints

Integrated the reviewed `antonio/api-energy-accounting` changes so the scientific
API and chat share per-day represented areas. Updated Copilot GJ totals and episode
ranking to use the corrected daily energy, rather than density times the full
polygon or historical cell union. Dossier series now include per-day `fre_gj` and
the peak-day represented area. Existing frozen fields/types remain unchanged.

Integration adjustments preserve R7-first polyfill (removed the proposed R4
pre-check, including its unsupported one-second timing assertion) and keep the
question limit at the composer's 6,000 characters. Schema/topology bounds remain
explicit HTTP 422 responses. Earlier archived energy snapshots describe the old
calculation; the new verification report supersedes them for GJ/biomass estimates.
Model estimates remain sensitive to the different spatial coverage of sensors.

Provider availability correction: GitHub Models itself retired in July 2026, after
the Azure URL retirement. The compatibility adapter now requires an explicitly
configured gateway endpoint; a GitHub PAT alone never calls a retired service.
Groq -> optional configured gateway -> Gemini -> deterministic fallback remains
bounded by the same deadline and token budget. Partial reconstruction alongside
real observations no longer suppresses incident research; the reconstruction gate
requires a purely estimated point with no active sensor or raw detection.

## 2026-11-15 — Groq agent, local document index and data tools

The online Copilot uses native tool selection, with a compact system message,
local FTS5/BM25 document retrieval and server-owned observations, energy, episode
and report tools. No public API fields or types changed. The UI supports K/E local
document source IDs. Offline and provider-failure handling reuse the local
scientific path through a request-local ContextVar, without global environment or
function mutation. Groq is the active provider; Gemini Search grounding is a
separate potential provider integration and is not activated by a Gemini web-app
subscription or by this change.

## 2026-11-15 — Settings and map/chat energy comparison

Moved display and industrial controls into Settings beside the appearance button;
added an in-menu keyboard shortcut list. Kept the functional raw-count versus
calibrated-energy visual comparison with clearer labels. Explore shows a separate
regional model total alongside mapped observations, and the Copilot computes the
same observed map total for comparison. Matched biomass, date coverage, selected
area and observed footprint are labeled explicitly. No public contract fields or
types changed. Tests compare mapped GJ with an independent sparse-cell area sum
and the actual map-period API; the model receives distinct estimator objects.


## 2026-11-15 — Simpler chronology and appearance settings

Moved the persisted Dark mode switch inside Settings. Replaced the mixed date/precision
controls with an explicit Day / Month / Year / Date range picker and Apply/Cancel.
The histogram is 56 px tall and changes dates only on click or drag. Previous/next
preserves the period type. Inclusive cross-year ranges use existing same-year map
requests in batches of four, merge H3 observations and update regional totals and
chat context. Invalid and reversed ranges are rejected; stale requests cannot replace
newer selections. Frozen public contracts remain unchanged.


## 2026-11-15 — Fire activity answers and low-count chronology bars

The Groq agent now gets one bounded opportunity to remove unsupported numerical
claims before falling back; citation identifiers are excluded from measurement
validation. Active-burning evidence, wildfire identity and ignition cause are
separate questions. Local fallback explains observed activity rather than leading
with an unrelated ignition disclaimer. Positive histogram bins have a 5 px minimum
versus a 1 px zero-count baseline; the timeline explicitly does not show incident
duration. Real map-period checks around the screenshot AOI returned observations
through 1 August, including 72 detections on 28 July, despite much smaller bars.
No public contracts changed. Free-provider quotas remain an external limitation.


## 2026-11-15 — Google Gemini provider and concise domain prompt

Configured the local deployment for Gemini 3.8 Flash after Google rejected 2.5 Flash
for this project and the user approved 3.8. Credentials remain in ignored `.env`.
`COPILOT_PROVIDER=gemini` selects Google for the tool agent and auxiliary prose;
provider failures use local evidence without silently switching to Groq.

The compact prompt uses practical terminology, separates active-burning evidence,
incident identity, ignition and spread, and prioritizes relevant official/scientific
sources. It does not add unavailable risk, emissions or burned-area calculations.
Grouped/doubled provider citations become individual verified source markers.
Uncertainty about ignition no longer erases valid event context.

Google Search source discovery is a separate native request. Only grounding metadata
URLs can enter the approved publisher reader; generated search prose is never an
article quotation. Discovery uses a 12-second shared budget because live four-second
attempts consistently timed out. Publisher/redirect reads retain a four-second cap.
Failures explicitly do not establish absence of an incident or report.

Gemini tool batches are executed sequentially, with at most three calls per response;
complete assistant/tool exchanges and opaque metadata survive context trimming.
The agent keeps its 35-second overall budget and server-owned numerical validation.
No frozen public API fields or types changed. Existing legacy-provider tests declare
their provider rather than inheriting the developer's local Google credentials.


## 2026-11-15 — Risk AI recalibration and operational telemetry

Additive, optional/nullable Python/TypeScript contract update (`backend/api/schemas.py`,
`frontend/src/api/types.ts`), documented in SPECS §5.2 and §5.6. No existing field was
renamed, removed or retyped, and every new field defaults to `null`.

New models: `RiskObservationStatus` (`status`, `coverage_nominal`, `uncertainty_pct`,
`days_since_observation`), `RiskIntensityRegime` (`regime`, `guidance`, `intensity_mw`,
`diurnal_amplification_ratio`, `contagion_origin`, `neighbor_frp_mw`), `RiskPhenology`
(`days_to_peak`, `peak_date_label`, `kappa`, `season_width_days`, `decadal_shift_days`,
`biomass_exposure_tonnes`, `persistence_entropy`, `fuel_regime`) and `RiskOutlookPoint`
(`date`, `prob_pct`, `baseline_prob_pct`).

New optional fields on existing models:

- `AIRiskAssessment`: `baseline_climatology_pct`, `multi_year_trend_delta_pct`,
  `short_term_anomaly_delta_pct`, `anomaly_multiplier`, `markov_persistence`,
  `horizon_explanation`, `observation`, `intensity`, `phenology`, `outlook_series`.
- `RiskFactor`: `signed_impact_pct`, `observed_value`, `unit`.
- `RiskDailyProbability`: `baseline_prob_pct`, `observed_event`.

Behaviour changes in `backend/core/risk_predictor.py`:

- The 24-hour probability uses a causal seasonal base rate (event-day frequency within
  day of year ±15 days in strictly earlier years, shrunk by pseudo-counts; long-term and
  recent-five-year versions) plus a persistence-state term (no event today, a run of 1–2
  days, a run of 3 or more days) as the logistic offset.
- Each target gets one 24-hour fit; the logistic, boosted-stump and Gaussian naive Bayes
  learners enter as centred residuals on that offset. The nine independent per-horizon
  fits and the running-maximum ratchet are gone.
- The 7- and 14-day probabilities are a first-order autocorrelated Markov accumulation,
  P_H = 1 − (1 − p_1) · Π_{k=2..H} (1 − p_k (1 − ρ)), where p_k relaxes from p_1 to the
  seasonal base rate of day t+k and ρ is chosen from {0.55 … 0.85} on the calibration
  slice (default 0.68, the RTS Kalman φ).
- The 24-hour risk decomposes exactly (up to rounding) as baseline + multi-year trend +
  short-term anomaly; driver bars now also carry a signed contribution in probability
  points, an observed value, a unit and a physical description.
- New operational telemetry: observation status, intensity regime (25/120/350 MW bands on
  the peak mean FRP per detection), contagion origin, phenology (days to peak, κ, season
  width, Theil–Sen decadal shift, biomass exposure, energy-weighted temporal entropy) and a
  14-day outlook series.
- `backend/db/queries.py`: `fetch_risk_daily` returns the extra causal array
  `peak_detection_frp`; new `fetch_risk_diurnal_ratio` returns the matched-days-weighted
  median ETL Aqua/Terra ratio from `data/lookup/diurnal_ratios.parquet` (None when the file
  is absent). `backend/api/routes.py` merges it into `intensity.diurnal_amplification_ratio`.
- Frontend: `RiskPredictionPanel.tsx` redesigned; new pure helper module
  `src/components/Risk/riskPresentation.ts` and test `tests/risk-panel.test.mjs`.

Limitations, unchanged in substance:

1. The target is still a satellite thermal-event proxy, not confirmed incidents.
2. The persistence range ρ ∈ [0.55, 0.85] is a design constraint. The measured lag-1
   autocorrelation of the daily event indicator is lower in some regions (about 0.21 for
   Orlando, about 0.42 for Iberia, combined target), so 7- and 14-day probabilities are
   under-predicted there. Holdout Brier score, combined target, before → after: Orlando 7 d
   0.186 → 0.215 and 14 d 0.167 → 0.196; Iberia 14 d 0.105 → 0.132. The 24-hour Brier score
   is equal or better in three of four presets (Chilecito 0.051 → 0.044, Manaus 0.085 →
   0.069, Iberia 0.159 → 0.161, Orlando 0.097 → 0.097).
3. `observation.uncertainty_pct` measures observation coverage (gaps, staleness and cloud
   when available). It is not a Kalman posterior variance: the predictor deliberately does
   not use RTS-smoothed values, which would leak future information. Cloud cover is absent
   (all missing) in the current real cube.
4. `intensity.regime` uses satellite FRP per detection in MW as an equivalent scale, not
   fireline intensity in kW/m. `contagion_origin` uses 1-ring neighbours inside the selected
   area only, so it separates adjacent-cell spread from isolated ignition but cannot detect
   ingress from outside the area.
5. `biomass_exposure_tonnes` uses the project's one-hour FRP integration proxy and is an
   order-of-magnitude estimate.
6. `intensity.diurnal_amplification_ratio` is null when the ETL lookup is absent (always
   with the synthetic cube).
7. Fewer than 365 daily rows always use the causal prior. Between 365 and roughly 610 rows
   (the fit slice, the first 60%, must contain days with a prior-year seasonal window) and
   whenever the fit or calibration slice has fewer than five events or five non-events, the
   prior path is used too; `prior_targets` lists the affected targets.
8. `risk_predictor.py` reimplements Best–Fisher κ, the day-of-year label, entropy and
   Theil–Sen locally, pinned by equivalence tests, because `test_core_has_only_allowed_imports`
   forbids sibling imports in that module. The entropy shown is FRP-energy-weighted per month.

Validation: backend 521 passed, 1 skipped, 1 pre-existing failure
(`test_cube_schema.py::test_real_cube_november_2026_coverage_and_schema`: the local real
cube ends 2026-11-01, unrelated to this change); frontend 45 tests passed; `tsc --noEmit`
clean; production build succeeds.


## Branch consolidation (2026-11-15)

All branch histories are consolidated in main. Streaming archive ETL, cloud/swath ancillary acquisition and the calculation/provenance Copilot tools coexist with the current scientific policy and Gemini incident investigator. Pipeline defaults and fixtures use the four current study regions; missing ancillary values remain null. Coordinated pipeline fixture/hash revisions preserve border, deduplication and SAMA controls without restoring retired regions. Numerical quantity checks preserve units; comparison questions may name years in either order while reversed explicit date ranges remain invalid. Backend contract hashes remain unchanged. See docs/verification/2026-11-15-branch-consolidation/ at the repository root for branch-tip inventory and test evidence.

## Cell-traced AOI vertex limit (2026-11-15)

A cell-traced AOI follows every hexagon edge, so its boundary has far more positions than a hand-drawn box (395 cells produce about 161 vertices, and medium areas exceeded the previous 512-position limit). That returned HTTP 422 and left the map and chronology empty. The limit is now **20,000 positions and 64 rings**, defined once in `backend/api/schemas.py` and reused by `backend/db/queries.py`; `SPECS.md` is updated. The real guards remain 250,000 R7 cells and 1,250,000 km² geodesic area. `test_polygon_vertex_limit` uses the shared constant, so the boundary test follows the new value. The frontend also keeps the last rendered map and the chronology when an analysis or map-period request fails, and shows the error in the map legend.

