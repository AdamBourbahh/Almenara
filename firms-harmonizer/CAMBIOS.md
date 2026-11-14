# CAMBIOS — registro de cambios que afectan a otros integrantes

Cada fila es un cambio hecho por Moha (dueño de `backend/db/` y `backend/api/`) sobre un archivo compartido o de otra persona. Motivo general: implementar la API sin datos falsos ni sustitutos silenciosos (plan v2).

| Fecha | Archivo | Dueño original | Cambio | Motivo | Afecta a |
|---|---|---|---|---|---|
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
