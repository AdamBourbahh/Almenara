# CAMBIOS — registro de cambios que afectan a otros integrantes

Cada fila es un cambio hecho por Moha (dueño de `backend/db/` y `backend/api/`) sobre un archivo compartido o de otra persona. Motivo general: implementar la API sin datos falsos ni sustitutos silenciosos (plan v2).

| Fecha | Archivo | Dueño original | Cambio | Motivo | Afecta a |
|---|---|---|---|---|---|
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
