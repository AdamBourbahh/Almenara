# PLANIFICATION — Calendario armonizado de actividad de quema (MODIS + VIIRS)

**Reto:** NASA Space Apps Challenge, "Harmonization of MODIS and VIIRS Hot Spots".
**Equipo:** 4 personas, 48 h.
**Estado:** plan de viabilidad. Aún no se ha escrito código ni medido ningún resultado. Las cifras marcadas como `[resultado a medir]` o `[verificar]` son pendientes, no hechos.

---

## 1. Resumen ejecutivo

1. **Plan original ("Documento de Moha"): no viable.** Requiere unas 175–235 horas-persona (h·p) y el equipo dispone de unas 84 h·p útiles. Además se aleja de lo que pide el reto: el reto pide **conteos de hotspots**, y el plan los sustituye por densidad de FRE. Le faltan la exportación CSV y la comparación "mes actual frente a la mediana histórica".
2. **Propuesta recortada: viable con recortes.** El MVP cuesta unas 70 h·p, con un 15–20 % de margen. Consiste en un factor de armonización empírico por celda y mes, estimado en el periodo de solapamiento (2012 en adelante) y validado fuera de muestra, más una web con mapa, área de interés (AOI), calendario años × meses, comparación con la mediana y exportación CSV.
3. **La validación más sólida no es un test de Chow.** Consiste en predecir la serie de VIIRS a partir de la de MODIS en años que el modelo no ha visto (ambos sensores coexisten desde 2012) y medir el error y la coincidencia de anomalías.
4. **Cuatro de las seis ideas del documento pasan a trabajo futuro:** PSF elíptica sobre H3, EQM con cola de Pareto, ST-DBSCAN con FRE y Horvitz-Thompson. La quinta (filtro de entropía) se sustituye por el campo `type` de FIRMS, que ya marca fuentes estáticas. De la sexta (calendario de von Mises) solo se conserva el día pico como media circular, que es barato.
5. **Riesgos principales:** descarga de datos (pedirlos antes del evento), deriva orbital de Terra y Aqua después de 2020 e integración tardía. Se mitigan con datos y esquema preparados de antemano, datos simulados para el frontend desde la hora 0 y congelación de funcionalidades en la hora 38.

---

## 2. El reto en lenguaje llano

**Qué pide:** una aplicación web que muestre, para un área elegida por el usuario, un **calendario de actividad de quema**. El calendario debe indicar cuántos hotspots se detectaron cada mes de cada año desde principios de los 2000 hasta hoy. Debe construirse sobre una serie **armonizada**, es decir, que no dependa de si el dato viene de MODIS (2000 en adelante, 1 km) o de VIIRS (2012 en adelante, 375 m). El objetivo es que un gestor de emergencias vea rápidamente qué meses y qué años tuvieron más actividad, y cómo se compara el mes actual con la mediana histórica.

El enunciado lo plantea en dos fases:
1. **Armonización** MODIS ↔ VIIRS: al final, el sensor de origen deja de importar.
2. **Aplicación web** que consume los datos armonizados: selección de región y rango de fechas, visualizaciones, descarga de analíticas y CSV.

| Elemento | Obligatorio / Opcional | Fuente en el enunciado |
|---|---|---|
| Serie de hotspots armonizada MODIS + VIIRS | **Obligatorio** | "harmonized burning activity calendar… consistent time series" |
| Aplicación web | **Obligatorio** | "build a web application" |
| Calendario de actividad (n.º de hotspots, años × meses, de los 2000 a hoy) | **Obligatorio** | Objetivos |
| Selección de región y rango de fechas | **Obligatorio** (de facto) | "a user could select a region and a specific date range" |
| Descarga de analíticas o visualizaciones | Muy recomendable | "download analytics and visualizations" |
| CSV de los hotspots de la búsqueda | Muy recomendable | "A downloadable CSV File… would be another useful output" |
| Mes actual frente a mediana histórica | Muy recomendable | Background |
| Rampas de color accesibles | Opcional (bien valorado) | Potential Considerations |
| Dibujar el AOI en el mapa o introducir lat/lon | Opcional | Potential Considerations |
| Anomalías frente a medias plurianuales | Opcional | Potential Considerations |
| FRP, FRE, eventos, fenología, filtros industriales | **No se pide** | — |

**Criterios del jurado (supuesto, ver §3):** los cinco criterios habituales de Space Apps son impacto, creatividad, validez, relevancia y presentación. "Validez" y "relevancia" premian hacer bien lo que se pide, más que añadir técnicas.

---

## 3. Supuestos

Se han hecho porque faltaban estos datos en el prompt. **Conviene confirmarlos** (ver §13).

| # | Supuesto | Impacto si es falso |
|---|---|---|
| S1 | Perfiles: 2 devs Python/backend, 1 frontend (JS/TS), 1 ciencia de datos/estadística. | Si nadie domina JS, el frontend se simplifica con Streamlit o Panel (ver §8). |
| S2 | Portátiles con 16 GB de RAM; sistemas mixtos (Linux, Windows con WSL2, macOS). | Con 8 GB conviene limitarse a 1–2 regiones y trabajar en Parquet desde el principio. |
| S3 | Internet del evento razonable pero no fiable. La demo debe funcionar **sin conexión**. | — |
| S4 | Entrega según Space Apps: página del proyecto, demo de unos 30 s en vídeo o unas 7 diapositivas, y enlace al repositorio o al proyecto. Si hay evento local, pitch en vivo de unos 3 min. `[verificar en las reglas de 2026]` | Si solo hay vídeo, la demo en vivo pierde peso y el vídeo debe estar listo antes (h44). |
| S5 | Jurado con los cinco criterios de Space Apps: Impact, Creativity, Validity, Relevance, Presentation. `[verificar]` | — |
| S6 | Antes del evento **se permite** crear cuentas y descargar datos, pero **no escribir código del proyecto**. `[verificar reglas]` | Si tampoco se permite descargar, se aplica el plan B de datos (§9) desde la hora 0. |
| S7 | "Hoy" es noviembre de 2026. Al menos uno de los dos MODIS podría haber dejado de producir datos o estar en fase final. `[verificar estado de Terra y Aqua]` | Refuerza la necesidad de armonizar: el periodo reciente sería solo VIIRS. |
| S8 | Dos noches de 48 h; cada persona duerme unas 10 h en total, en turnos escalonados. | — |

---

## 4. Capacidad del equipo

| Concepto | Por persona | × 4 |
|---|---|---|
| Tiempo total | 48 h | 192 h·p |
| Sueño (2 bloques de unas 5 h) | −10 h | −40 |
| Comidas, descansos, aseo | −5 h | −20 |
| Ceremonias, mentores, check-ins y logística | −3 h | −12 |
| **Horas despiertas de trabajo** | **30 h** | **120 h·p** |
| Integración y depuración entre piezas (unos 20 %) | −6 h | −24 |
| Pitch, vídeo, diapositivas y ensayo (repartido, más carga para el responsable del pitch) | −3 h | −12 |
| **Horas útiles de desarrollo** | **unas 21 h** | **unas 84 h·p** |

La fatiga a partir de la hora 30 reduce la productividad. Por eso **el plan no compromete más de unas 70 h·p** en el MVP y deja unas 14 h·p de margen para imprevistos o para la capa "Recomendable".

---

## 5. Viabilidad del plan original

### 5.1 Coste estimado por componente

Estimación de un equipo competente sin experiencia previa en cada pieza. Rango optimista–realista.

| Componente del documento | h·p | Comentario |
|---|---|---|
| Ingesta FIRMS 2000–2026 de 3 regiones + limpieza | 8–10 | Es necesaria en cualquier caso. |
| 1. Huella elíptica (PSF) gaussiana repartida sobre H3 | 10–14 | Integración sobre polígonos y anillos `grid_disk`; difícil de validar. |
| 2a. Logística de detectabilidad por bioma × ángulo | 8–12 | Requiere emparejar pasos casi simultáneos Aqua/SNPP. |
| 2b. EQM por 17 biomas × 10 bins de θ + GPD | 10–14 | Muchas celdas de estratificación con pocos datos. |
| MCD12Q1: descarga HDF4, reproyección sinusoidal y muestreo | 6–10 | Requiere Earthdata Login, mosaicos y tiles. |
| 3. ST-DBSCAN/DAG + modelo diurno + FRE + velocidad del frente | 12–18 | Cada parámetro (k, Δt, ω) necesita calibración. |
| 4. Von Mises + "Mann-Kendall circular" + Theil-Sen | 6–8 | Ver revisión científica. |
| 5. Entropía en H3 res10 + ΔT4/11 | 4–6 | Redundante con el campo `type`. |
| 6. Horvitz-Thompson orbital + nubosidad (producto de nubes) | 12–20 | La ingesta del producto de nubes (MOD35/VIIRS cloud mask) es por sí sola un proyecto. |
| Validación MCD64A1 (descarga + rasterizado a celdas) | 10–14 | HDF4 mensual, Earthdata Login. |
| Backend Arrow IPC / DuckDB-Wasm | 8–12 | Útil, pero innecesario para una demo. |
| Frontend deck.gl + DataFilterExtension + lazo + reloj polar + heatmap + interruptor | 24–32 | — |
| Panel de auditoría (Chow, W1 y R² en vivo) | 6–8 | — |
| PMTiles locales de mapa base y biomas | 3–5 | — |
| Integración | 15–20 | — |
| Pitch y vídeo | 10–12 | — |
| **Total** | **unas 152–215 h·p** | **Entre 1,8 y 2,6 veces la capacidad** (84 h·p) |

Incluso suprimiendo la integración y el pitch, que no se pueden suprimir, el resto supera las 120 h·p.

### 5.2 Camino crítico del plan original

Descarga de FIRMS y MCD12Q1 → emparejamiento Aqua/SNPP → logística + EQM + GPD → cubo armonizado → ST-DBSCAN/FRE (consume FRP armonizado) → von Mises y tendencias → panel de auditoría → demo.

Son seis etapas encadenadas y ninguna parte de la ciencia puede avanzar en paralelo. Si el EQM se retrasa 6 h, todo lo posterior se retrasa. El propio cronograma del documento (bloques de 0–6, 6–18, 18–32, 32–42 y 42–48 h) supone trabajo continuo sin sueño.

### 5.3 Desajustes con el enunciado

- **Métrica:** el reto pide "the number of hotspots detected". El documento sustituye los conteos por "densidad de FRE en MJ·km⁻²·día⁻¹". Es defendible como capa adicional, pero no como métrica principal: el usuario objetivo (gestores de emergencias) piensa en número de focos.
- **Faltan:** exportación CSV, "mes actual frente a mediana histórica", entrada por lat/lon y rampas de color accesibles.
- **Resultados inventados:** la sección "Momento Demo" presenta cifras como hechos (+420 %, F = 142,8, W₁ 38,4 → 2,1, R² 0,51 → 0,91, +19 días, +34 %, "alerta temprana a 14 días"). **No pueden aparecer en ningún material** hasta medirlas, y la última no se puede sostener con estos datos.

**Veredicto del plan original: no viable** en 48 h con 4 personas.

### 5.4 Viabilidad de la propuesta recortada

MVP de unas 70 h·p frente a 84 h·p disponibles (ver §6): **viable con recortes**. Tiene un camino crítico de cuatro etapas y el frontend trabaja en paralelo desde la hora 0 con datos simulados.

---

## 6. Enfoque propuesto

### 6.1 Idea central (MVP)

1. **Unidad de análisis:** hotspot (detección FIRMS) limpio, es decir, `type = 0` (presunto fuego de vegetación) y confianza nominal o alta.
2. **Unidad de referencia armonizada:** "hotspots equivalentes a VIIRS" (VIIRS-equivalentes). VIIRS es el sensor que continúa en el futuro. Se mantiene también la vista "MODIS-equivalente" para quien la prefiera.
3. **Modelo:** para cada celda espacial (rejilla de 0,5° o H3 res 4–5) y mes del año, se estima en el periodo de solapamiento un factor `k = conteo VIIRS / conteo MODIS`, con contracción hacia el factor de la región cuando la celda tiene pocos datos (modelo jerárquico sencillo o mezcla ponderada por número de detecciones). Antes de 2012, cada hotspot MODIS recibe un **peso** `w = k`. Desde 2012, el calendario usa VIIRS con `w = 1`.
4. **Calendario de un AOI:** suma de pesos por año y mes. El CSV exportado incluye cada hotspot con su sensor, sus columnas originales y su peso. Es transparente y auditable.
5. **Validación:** el factor se ajusta en 2012–2017 y se comprueba en 2018 en adelante, donde ambos sensores coexisten (detalle en §11).

**Por qué es defendible:** al aplicar un factor constante por celda y mes, las anomalías relativas dentro de cada época no cambian. La armonización solo afecta a la comparación entre épocas, que es justamente el problema que plantea el reto. Además, el factor por celda absorbe de forma empírica las diferencias de resolución, sensibilidad, ancho de barrido y revisita, sin tener que modelar cada efecto por separado.

### 6.2 Componentes por niveles

#### Imprescindible (MVP): demostrable de principio a fin por sí solo

| # | Componente | Qué hace | Por qué le importa al jurado | h·p | Riesgo | Depende de |
|---|---|---|---|---|---|---|
| M1 | Ingesta y limpieza | CSV de FIRMS → Parquet con esquema único; filtros de `type` y confianza; normalización de fecha y hora UTC | Base de "validez" | 8 | Medio (volumen y formatos) | Datos descargados |
| M2 | Factor de armonización por celda × mes | Estima `k` en el solapamiento, con contracción y fallback regional; asigna pesos | Es el núcleo del reto | 10 | Medio | M1 |
| M3 | Validación fuera de muestra | Métricas y 2–3 gráficos (serie, dispersión, coincidencia de anomalías) | "Validity": demuestra que funciona | 6 | Bajo-medio | M2 |
| M4 | Agregados y API | Agregados por celda × mes; endpoints de calendario, resumen y CSV por AOI y fechas | Hace usable la app | 8 | Bajo | M2 (esquema desde h0) |
| M5 | Mapa y selección de AOI | MapLibre; dibujar polígono o rectángulo; entrada por lat/lon y radio o bbox; rango de fechas | "Relevance" (pedido explícitamente) | 10 | Medio | Mock h0 → M4 |
| M6 | Calendario y comparativas | Heatmap años × meses con rampa accesible; barras por año; mes actual frente a mediana; interruptor crudo / armonizado | Es el entregable principal | 10 | Medio | Mock h0 → M4 |
| M7 | Exportación CSV | Descarga de hotspots del AOI con peso y sensor; resumen mensual en CSV | Pedido explícitamente | 2 | Bajo | M4 |
| M8 | Integración y empaquetado offline | Arranque con un comando en local; datos incluidos; sin dependencia de internet | Demo sin fallos | 6 | Medio | Todo |
| M9 | Pitch, vídeo y diapositivas | Guion, capturas y vídeo de respaldo | "Presentation" | 10 | Bajo | M3, M6 |
| | **Total MVP** | | | **70** | | |

#### Recomendable (unas 14 h·p de margen; elegir por orden)

| # | Componente | Valor | h·p | Riesgo |
|---|---|---|---|---|
| R1 | Anomalías: percentil o z-score robusto (mediana/MAD) por mes frente a la climatología | Pedido como consideración; muy visual | 3 | Bajo |
| R2 | Bandas de incertidumbre del factor `k` (bootstrap por años) en el calendario anterior a 2012 | Honestidad científica | 3 | Bajo |
| R3 | Factores separados día y noche | La sensibilidad difiere entre día y noche; mejora el ajuste | 2 | Bajo |
| R4 | Día pico de la temporada (media circular ponderada) y concentración R̄ por año | Recoge lo útil de la idea 4 sin von Mises | 2 | Bajo |
| R5 | Datos recientes (NRT) con la FIRMS API (MAP_KEY) para "el mes actual" | Conecta con alerta temprana | 4 | Medio (NRT no trae `type`; caché para la demo) |
| R6 | Métrica alternativa "días-celda con fuego" (celdas de unos 1 km con al menos una detección por día) | Más robusta a la resolución; buen argumento técnico | 3 | Bajo |
| R7 | Bandera de persistencia (celdas con detecciones en más del X % de meses) para revisar fuentes estáticas que se escapan de `type` | Recoge lo útil de la idea 5 | 2 | Bajo |

#### Si sobra tiempo / trabajo futuro (mencionar en el pitch como hoja de ruta)

| Idea | Por qué se aplaza |
|---|---|
| Huella elíptica (PSF) repartida sobre H3 | No cambia el conteo del calendario; difícil de validar; ver §7.1 |
| EQM de FRP con logística + GPD | Armoniza intensidad, no conteos; ver §7.2 |
| ST-DBSCAN, eventos y FRE | Parámetros arbitrarios; FRE con 4–6 pasos al día es muy incierta |
| Horvitz-Thompson orbital y por nubes | Irrelevante para anomalías dentro de un mismo AOI; la parte de nubes es inestable; ver §7.6 |
| Estratificación con MCD12Q1 | Coste de ingesta alto; el factor por celda ya captura el bioma |
| Validación con MCD64A1 | Coste alto y no es independiente de MODIS; ver §7.7 |
| DuckDB-Wasm 100 % en el navegador, Arrow IPC, deck.gl en GPU | Optimización innecesaria para el volumen de una demo |

### 6.3 Camino crítico de la propuesta

Datos descargados (antes del evento) → **M1** (h0–8) → **M2** (h8–16) → **M4** con datos reales (h16–22) → **M8** integración (h22–30) → freeze (h38).

M5 y M6 avanzan en paralelo con datos simulados que respetan el esquema acordado. M3 avanza en paralelo a M4.

---

## 7. Revisión científica

Notación de fiabilidad: **[seguro]** = documentado y conocido; **[probable]** = recuerdo razonable que conviene confirmar; **[verificar]** = no sé el dato con certeza; se indica cómo comprobarlo.

### 7.0 Qué columnas trae realmente FIRMS

| Columna | MODIS (MCD14ML C6.1) | VIIRS 375 m (VNP14IMG / VJ114IMG / VJ214IMG) |
|---|---|---|
| `latitude`, `longitude` | Sí | Sí |
| Temperatura de brillo | `brightness` (banda 21/22, K), `bright_t31` (K) | `bright_ti4` (K), `bright_ti5` (K) |
| `scan`, `track` (tamaño real del píxel, km) | Sí | Sí |
| `acq_date`, `acq_time` (UTC, HHMM) | Sí | Sí |
| `satellite` | Terra / Aqua | N (SNPP), N20 / 1, N21 `[verificar codificación exacta]` |
| `confidence` | 0–100 (FIRMS sugiere bajo < 30, nominal 30–80, alto > 80) [probable] | `l` / `n` / `h` [seguro] |
| `version` | Ej. 6.1 / 6.1NRT | Ej. 2 / 2.0NRT |
| `frp` (MW) | Sí | Sí (calculado con la banda M13 de 750 m) [probable] |
| `daynight` | D / N | D / N |
| `type` | **Sí, en el archivo estándar**: 0 = presunto fuego de vegetación, 1 = volcán activo, 2 = otra fuente terrestre estática, 3 = offshore [seguro] | **Sí, en el archivo estándar** [probable]. **No viene en los datos NRT** [seguro] |

**Consecuencia:** la afirmación del documento de que "MODIS ya viene filtrado en `type` pero VIIRS no" es **incorrecta para los datos de archivo**. Solo es cierta para los datos NRT. Filtrar `type = 0` resuelve la mayoría de antorchas de gas, siderurgias y volcanes sin necesidad de un filtro de entropía.
*Cómo verificarlo:* descargar un CSV de archivo VIIRS de cualquier país desde FIRMS (Archive Download o descarga anual por país) y revisar la cabecera. Conviene contrastarlo también con el documento "FIRMS Attributes" de Earthdata.

### 7.1 Idea 1: huella elíptica (PSF) sobre H3

- **Lo correcto:** el píxel de MODIS crece fuera del nadir hasta unos 4,8 km (dirección de barrido) × 2,0 km (dirección de traza) en el borde del barrido [seguro]. VIIRS crece mucho menos gracias a la agregación a bordo [seguro]. Las columnas `scan` y `track` ya dan esas dimensiones.
- **Lo exagerado o incorrecto:**
  - Para un **calendario de conteos** repartir cada detección entre celdas no cambia el total del AOI; solo difumina el borde. El coste es alto y el beneficio, marginal para el entregable.
  - Una gaussiana con FWHM igual al tamaño del píxel no es la PSF real de MODIS (aproximadamente triangular en la dirección de barrido) [probable]. Además, la posición de la detección es el centro del píxel, no la posición del fuego. Repartir "energía" según la PSF no recupera dónde estaba el fuego.
  - La "cuadratura baricéntrica O(1)" y los "10 M de registros en < 4 s" son promesas sin medir.
- **Alternativa:** asignar cada hotspot a una celda por su centro y usar la rejilla solo para agregar y para el factor `k`. Los efectos de tamaño de píxel quedan absorbidos en `k` (por celda) y, si se quiere afinar, en la métrica R6 (días-celda).

### 7.2 Idea 2: mapeo cuantílico por bioma y ángulo + cola de Pareto

- **Armoniza la variable equivocada:** el EQM sobre FRP ajusta **intensidades**, pero el reto pide **número de hotspots**. Una detección de MODIS no corresponde a N detecciones de VIIRS de forma uno a uno.
- **Estratificación excesiva:** 17 clases IGBP × 10 bins de θ × 100 percentiles da unas 17 000 cuantilas que estimar con pares coincidentes (|Δt| < 25 min). En 3 regiones habrá muchas clases y bins con pocos o ningún dato. Necesitaría contracción jerárquica, que el documento no menciona.
- **Uso incorrecto de la GPD:** la distribución de Pareto generalizada procede de la teoría de valores extremos y modela la **cola superior** (excesos sobre un umbral alto, método *peaks-over-threshold*). La región por debajo del umbral de MODIS es un problema de **censura o truncamiento por la izquierda** de la variable FRP. Ajustar ahí una GPD e "integrar la cola izquierda" no es una aplicación estándar. Además, extrapolar hacia abajo una ley de potencias de FRP es muy sensible al exponente elegido. Lo defendible sería un modelo de detectabilidad (curva de probabilidad de detección frente a FRP) o un ajuste de ley de potencias con umbral estimado (estilo Clauset et al., 2009), presentado con su incertidumbre.
- **Saturación:** es cierto que la banda I4 de VIIRS satura con frecuencia en fuegos intensos [seguro]. Sin embargo, el FRP de VIIRS 375 m se calcula con la banda M13 de 750 m, que satura mucho menos [probable]. Por tanto, el argumento "VIIRS satura antes en FRP" es, como mínimo, discutible. *Verificar en Schroeder et al. (2014), RSE, producto VIIRS 375 m.*
- **Umbrales de detección:** "FRPmín ≈ 0,5 MW frente a 8 MW" son órdenes de magnitud plausibles, pero dependen del ángulo, del día o la noche y del fondo. Deben citarse como aproximados, con fuente (Giglio et al., 2016; Schroeder et al., 2014) `[verificar valores]`.
- **"4× a 10× más puntos":** plausible y muy dependiente de la región y la estación. En el pitch debe aparecer como `[resultado a medir]` para las regiones de la demo.
- **Alternativa:** factor de conteo por celda × mes (MVP). Como extensión, regresión log-lineal `log(V+1) ~ log(M+1)`, que permite que la relación no sea proporcional.

### 7.3 Idea 3: deduplicación espacio-temporal y FRE

- Para un calendario de hotspots **no hace falta deduplicar entre sensores** si se usa una sola serie por época: MODIS hasta 2011 y VIIRS después, con factor. Mezclar sensores en el mismo periodo sí duplicaría conteos, y la propuesta lo evita.
- ST-DBSCAN con un Δt de 18 h y un k arbitrario genera "eventos" cuyo número depende fuertemente de los parámetros, y no hay datos de referencia en el evento para calibrarlos.
- La FRE integrada con 4–6 observaciones al día (Terra, Aqua, SNPP, NOAA-20 y NOAA-21, cada uno con un paso diurno y otro nocturno) y un modelo diurno supuesto tiene una incertidumbre muy grande. La literatura lo hace con satélites geoestacionarios o con modelos diurnos calibrados.
- **"Vector de velocidad del frente de llama"** con píxeles de 375 m a 1 km y pocos pasos al día: **no es defendible**. Hay que eliminarlo.
- **Alternativa:** métrica de "días-celda con fuego" (R6) si se quiere robustez frente a duplicados.

### 7.4 Idea 4: calendario circular (von Mises) y tendencias

- **Lo correcto:** tratar el día del año como ángulo y calcular la media circular ponderada (C̄, S̄, R̄) es estándar y barato [seguro]. La aproximación de Best & Fisher (1981) para A⁻¹(R̄) existe [seguro].
- **Problemas:**
  - Muchas regiones tienen **dos temporadas** de quema (por ejemplo, agrícola de primavera y forestal de verano). Una von Mises unimodal da entonces una media sin sentido y un κ bajo. Hay que comprobar la bimodalidad o, simplemente, mostrar el heatmap, que ya enseña la estacionalidad.
  - **"Mann-Kendall circular" no es un test estándar** con ese nombre. Para la tendencia del día pico se puede: (a) desenrollar los ángulos si la temporada está concentrada (R̄ alto) y aplicar Mann-Kendall y Theil-Sen a la serie lineal resultante; o (b) usar una regresión o correlación circular-lineal (Fisher, 1993; Mardia & Jupp, 2000).
  - Con unos 25 puntos anuales y un **cambio de sensor en mitad de la serie**, cualquier tendencia en fenología puede ser un artefacto de la armonización. Hay que mostrarla con intervalo de confianza y comprobar si persiste dentro de cada época.
  - "Umbral exacto de alerta temprana para los próximos 14 días" no se deduce de una climatología. **Hay que eliminarlo.**
- **Alternativa:** R4 (día pico y R̄ por año, sin pruebas de tendencia en el MVP).

### 7.5 Idea 5: filtro de entropía para fuentes industriales

- Ya existe `type` (ver §7.0). Primera línea de defensa: filtrar `type = 0`.
- **H3 res10 (unos 0,015 km²) es incoherente con el tamaño de píxel**: un píxel de VIIRS en nadir mide unos 0,14 km² y uno de MODIS 1 km² o más. El error de geolocalización es de cientos de metros. Una antorcha fija aparecerá repartida en decenas de celdas res10, lo que diluye la persistencia que se pretende detectar.
- "σ²pos < 50 m²" (unos 7 m de desviación) es físicamente imposible con esta geolocalización.
- Los umbrales Htemp < 0,25 / > 0,75 son arbitrarios. Una sabana que arde cada año en la misma estación puede dar entropías intermedias.
- El "ΔT4/11" requiere las temperaturas de brillo por píxel, que sí están (`bright_ti4` y `bright_ti5`), pero carece de umbrales validados.
- **Alternativa (R7):** bandera de persistencia en celdas de unos 1 km (H3 res 8 o rejilla de 0,01°) como revisión complementaria, no como filtro principal. Como referencia externa, existe el producto VIIRS Nightfire (Earth Observation Group) de antorchas de gas `[verificar licencia y acceso]`.

### 7.6 Idea 6: Horvitz-Thompson por órbita y nubosidad

- **Lo correcto:** la frecuencia de observación de los satélites polares aumenta con la latitud [seguro]. MODIS (barrido de unos 2330 km) deja pequeños huecos entre pasadas consecutivas cerca del ecuador. VIIRS (unos 3040 km) no [seguro].
- **Problemas:**
  - **Para el calendario de un AOI, la corrección orbital es casi constante** (la latitud no cambia), así que no altera ni la forma del calendario ni las anomalías. Solo importa para comparar regiones distintas, cosa que el reto no pide.
  - πorb ∝ 1/cos(φ) es una aproximación cualitativa, no una probabilidad de inclusión. Horvitz-Thompson requiere probabilidades de inclusión conocidas por unidad muestral.
  - Dividir por (1 − C) con C de hasta 0,95 multiplica por 20 los conteos en celdas nubosas: varianza explosiva. Además, la nubosidad no viene en FIRMS. Habría que procesar MOD35, VIIRS Cloud Mask o similares (HDF/NetCDF, Earthdata Login, decenas de GB): no cabe en 48 h.
  - Bajo nubes densas no hay fuego que "falte por detectar" de forma aleatoria: la nubosidad está correlacionada con la estación húmeda, en la que hay menos fuego. La hipótesis de ignorabilidad no se cumple.
- **Alternativa:** ninguna en el MVP. El factor `k` por celda ya absorbe las diferencias medias de revisita entre sensores. Hay que mencionar la nubosidad como limitación conocida.

### 7.7 Validación propuesta en el documento

| Prueba | Qué demuestra y qué no | Veredicto |
|---|---|---|
| Test de Chow en enero de 2012 con p > 0,10 | No rechazar H₀ **no demuestra** homogeneidad. Puede ser falta de potencia (series cortas, ruido, autocorrelación, estacionalidad no modelada). Además, una ruptura real (cambios de uso del suelo o de políticas) coincidente con 2012 se confundiría con la instrumental. Chow exige fijar la fecha de antemano; el escalón real puede no estar en enero de 2012 (VIIRS llega a FIRMS a partir del 20/01/2012 [probable]). | Usar solo como diagnóstico secundario, junto a la validación en el solapamiento (§11). Si se usa un test de ruptura, mejor Pettitt o Bai-Perron sobre la **serie desestacionalizada**, interpretado con cautela. |
| W₁ y KL entre distribuciones de FRP | Miden el parecido de la distribución de **intensidades**, no de conteos. KL es infinita o inestable con bins vacíos. | Opcional (W₁ como diagnóstico del FRP); no es la métrica principal. |
| R² contra área quemada MCD64A1 | MCD64A1 es un producto **MODIS** que usa los fuegos activos de MODIS en su algoritmo [probable], así que no es independiente de la serie MODIS. La relación entre hotspots y área quemada varía por bioma (agrícola frente a forestal). Su ingesta es costosa. | Trabajo futuro. |

### 7.8 Resolución H3 frente a tamaño de píxel

| Resolución H3 | Área media | Coherencia |
|---|---|---|
| res 4 | unos 1770 km² | Celda para el factor `k` en regiones con pocos datos |
| res 5 | unos 253 km² | **Celda recomendada para `k` y el mapa** (unos 0,15°) |
| res 6 | unos 36 km² | Mapa de detalle; todavía muchas detecciones por celda |
| res 7 | unos 5,2 km² | El documento la propone. Es del orden de varios píxeles MODIS, demasiado fina para estimar `k` con estabilidad |
| res 8 | unos 0,74 km² | Escala de píxel MODIS / varios VIIRS: adecuada para R6 y R7 |
| res 10 | unos 0,015 km² | **Por debajo del píxel de ambos sensores**: incoherente |

H3 no es obligatorio. Una rejilla regular (0,25° o 0,5°) es igual de válida, más fácil de explicar y no necesita extensiones. Se puede usar H3 si alguien del equipo ya lo conoce.

### 7.9 Deriva orbital en el periodo de solapamiento

- Terra (paso descendente nominal a las 10:30) dejó de hacer maniobras de inclinación hacia 2020 y su hora de paso **se adelanta**. Aqua (paso ascendente a las 13:30) salió del A-Train hacia 2022 y su hora de paso **se retrasa** [probable; *verificar las horas actuales en las páginas de misión de NASA/GSFC*].
- El ciclo diurno del fuego alcanza su máximo a primera hora de la tarde. Un paso más tardío de Aqua tiende a ver **más** fuego y uno más temprano de Terra, **menos**. La relación VIIRS/MODIS **cambia con el tiempo** después de 2020.
- SNPP mantiene el paso de las 13:30. NOAA-20 y NOAA-21 comparten órbita desfasados unos 50 min (media órbita) [seguro].
- **Implicaciones para el plan:**
  1. Calibrar `k` en un periodo de órbitas estables: **2012–2019** (o 2012–2017 si se reservan años para la prueba).
  2. Mostrar en la validación `k` por año (estabilidad del factor). Si cambia después de 2020, decirlo como hallazgo, no esconderlo.
  3. Elegir una configuración de sensores **constante** por época: MODIS = Terra + Aqua (Aqua solo existe desde mediados de 2002, lo que introduce **otro escalón en 2002**; se puede corregir con un factor Terra → Terra + Aqua estimado en 2003–2011, o arrancar la serie en julio de 2002). VIIRS = solo SNPP, con NOAA-20 para cubrir huecos de SNPP. No conviene sumar NOAA-20 y NOAA-21, porque crearía escalones en 2018 y 2023.

---

## 8. Stack recomendado

Criterio: lo que el equipo ya conoce, que funcione sin conexión y que tenga el menor número de piezas posible.

| Capa | Recomendación | Por qué | Alternativa más simple | Riesgo |
|---|---|---|---|---|
| Ingesta | Descarga manual o por script de CSV de archivo de FIRMS; conversión inmediata a Parquet | CSV ocupa 5–10 veces más que Parquet; Parquet acelera todo lo posterior | Trabajar en CSV si la región es pequeña | Peticiones de archivo lentas (por correo) |
| Almacenamiento | Parquet particionado por sensor y año | Sin servidor; se lee igual desde Python y DuckDB | CSV o un único Parquet | Bajo |
| Procesamiento | DuckDB (SQL) + pandas o Polars | DuckDB es muy rápido con Parquet y aguanta volúmenes mayores que la RAM | Solo pandas | Bajo |
| Geometría | Rejilla regular de 0,5°/0,25° o H3 (res 4–5) mediante la librería Python `h3`; Shapely para AOI | Sencillo de explicar | Solo rejilla regular | Bajo |
| Estadística | SciPy y statsmodels (bootstrap, Spearman, regresión log-lineal); `pymannkendall` si se usa R4 | Librerías conocidas | NumPy a mano | Bajo |
| Backend | FastAPI con respuestas JSON (calendario de unos 300 valores) y CSV en streaming | El volumen de respuesta es diminuto: JSON basta; no hace falta Arrow IPC | Frontend estático con agregados precalculados por región (sin backend) | Bajo |
| Frontend | Vite + React (o JS sin framework) + MapLibre GL JS + herramienta de dibujo (Terra Draw o mapbox-gl-draw compatible con MapLibre) | Estándar, abundante documentación | Streamlit o Panel con folium/pydeck si el frontend flojea (pierde vistosidad) | Medio (dibujo de AOI) |
| Visualización | Apache ECharts u Observable Plot para el heatmap y las barras; rampas viridis/cividis o ColorBrewer secuencial (apta para daltónicos) | Heatmap de calendario listo; accesible | Plotly | Bajo |
| Mapa base | Offline: GeoJSON de países (Natural Earth) como capa vectorial; opcional, PMTiles local | Sin depender de teselas remotas en la demo | Teselas online + vídeo de respaldo | Medio |
| Entorno de demo | Un portátil con todo en local (backend + frontend + datos); un segundo portátil clonado; vídeo grabado | Dos niveles de respaldo | — | — |
| Repositorio | Git con ramas cortas; `main` siempre ejecutable desde h24 | Integración continua | — | Conflictos |

**Optimizaciones del documento que sobran en una demo:** Arrow IPC y "cero JSON"; DuckDB-Wasm en el navegador; DataFilterExtension en el vertex shader y "60 FPS con 500 000 hexágonos"; ordenación física por (h3_r4, year, doy, h3_r7) para zone maps; latencias inferiores a 15 ms; extensiones C++/Rust. Con 3 regiones, una consulta de DuckDB sobre Parquet local tardará del orden de cientos de milisegundos `[a medir]`, lo cual es suficiente.

---

## 9. Plan de datos

### 9.1 Productos

| Producto | Uso | Dónde | Autenticación | Formato |
|---|---|---|---|---|
| MODIS C6.1 (MCD14ML vía FIRMS), archivo estándar 2000 → presente | Serie histórica | FIRMS → Archive Download (por país o región y fechas) o descarga anual por país | Correo para la petición de archivo; la descarga anual por país es directa [probable] | CSV / SHP / JSON |
| VIIRS SNPP 375 m (VNP14IMG), archivo 2012 → presente | Serie moderna y calibración | Ídem | Ídem | CSV |
| VIIRS NOAA-20 375 m (VJ114IMG) | Cubrir huecos de SNPP | Ídem | Ídem | CSV |
| FIRMS NRT (últimos días) — R5 | "Mes actual" | FIRMS API (endpoint por área) | MAP_KEY gratuita | CSV |
| Natural Earth (países, admin-1) | Mapa base offline y AOI predefinidas | naturalearthdata.com | Ninguna | GeoJSON / SHP |

No se usan en el MVP: MCD12Q1, MCD64A1, productos de nubes.

### 9.2 Regiones y años

Elegir **3 regiones** con regímenes distintos, más una de respaldo pequeña:

| Región | Por qué | Volumen orientativo |
|---|---|---|
| Península Ibérica (España + Portugal) | Cercana al equipo; estacionalidad estival clara; quemas agrícolas en invierno y primavera | Pequeño: del orden de 10⁴–10⁵ filas por año en VIIRS `[a medir]` |
| Brasil (o solo Cerrado/Amazonía) | Temporada intensa; gran contraste MODIS/VIIRS; relevancia global | Grande: del orden de 10⁶ o más filas por año en VIIRS `[a medir]` |
| Australia o África austral | Temporadas que cruzan el fin de año; muestra el valor del calendario | Medio-grande `[a medir]` |

Años: **2000 → presente** para MODIS, **2012 → presente** para VIIRS SNPP y lo necesario de NOAA-20.

### 9.3 Volumen y tiempo de descarga (estimaciones a verificar)

- Una fila de CSV de FIRMS ocupa unos 100–130 bytes, así que 10⁶ filas son unos 120 MB en CSV y unos 15–30 MB en Parquet `[a medir]`.
- Escenario de 3 regiones: del orden de 10⁷–5·10⁷ filas en total, unos 2–6 GB en CSV y menos de 1 GB en Parquet `[a medir]`. Con 50 Mbit/s, la descarga directa tarda minutos. El cuello de botella es **la cola de peticiones de archivo de FIRMS** (que se entregan por correo y pueden tardar horas) `[verificar el tiempo real con una petición de prueba]`.
- Descarga global completa: **no**. Son decenas de GB y no aporta nada a la demo.

### 9.4 Antes del evento (si las reglas lo permiten)

1. Crear la cuenta de NASA Earthdata y pedir la MAP_KEY de FIRMS.
2. Hacer una petición de archivo de prueba pequeña para medir el tiempo de entrega y **comprobar las cabeceras** (presencia de `type` en VIIRS, códigos de `satellite`).
3. Pedir y descargar las 3 regiones (MODIS + SNPP + NOAA-20). Guardar los CSV originales en una carpeta de solo lectura, con sumas de verificación.
4. Copiar los datos en al menos **dos portátiles y un USB**.
5. Acordar el esquema de datos (§10.3) y el contrato de la API.

### 9.5 Durante el evento

- h0–2: conversión a Parquet y recuento de filas por sensor, año y región. Contrastar con las expectativas para detectar huecos.
- R5 (NRT): descargar el último mes por la API antes de h30 y **guardarlo en caché**; la demo no lo consultará en vivo.

### 9.6 Plan B (subconjunto pequeño)

Si las peticiones de archivo no llegan o se pierde la conexión: **solo la Península Ibérica** (o un único país pequeño) mediante la descarga anual por país, de unos pocos MB. Todo el MVP funciona igual con una sola región. El factor `k` se estima entonces con contracción hacia el valor regional. Si tampoco funciona eso, se recurre a un CSV de muestra preparado de antemano en el USB.

---

## 10. Roles y cronograma de 48 h

### 10.1 Roles

| Persona | Rol principal | Responsabilidades | Secundario |
|---|---|---|---|
| **P1** Ciencia de datos | Armonización y validación | M2, M3, R1–R4; redacta la sección científica del pitch | Revisa los datos de M1 |
| **P2** Backend | Datos y pipeline | M1, M4 (agregados), M7 (CSV) | Apoya a P1 en DuckDB |
| **P3** Backend / full-stack | **Responsable de integración** | API (M4), M8, repositorio y `main` estable, scripts de arranque, ensayos offline; decide qué entra en `main` | Apoya al frontend en la conexión con la API |
| **P4** Frontend | **Responsable del pitch** + frontend | M5, M6, accesibilidad; guion, vídeo y diapositivas (M9) a partir de h30 | — |

Si P4 no puede asumir el frontend y el pitch a la vez, P3 asume el pitch a partir de h36.

### 10.2 Cronograma por bloques

Los turnos de sueño son escalonados para que siempre haya al menos dos personas despiertas: P1 y P4 duermen en h14–19 y h34–38; P2 y P3, en h17–22 y h37–41 (aproximadamente).

| Bloque | P1 (ciencia) | P2 (datos) | P3 (integración) | P4 (frontend / pitch) |
|---|---|---|---|---|
| h0–2 | Kick-off: congelar el alcance del MVP, esquema y contrato de la API | Ídem | Ídem; crea el repositorio y la estructura | Ídem |
| h2–8 | Análisis exploratorio del solapamiento: recuentos y primeras razones VIIRS/MODIS | M1: ingesta → Parquet, filtros | Esqueleto de la API con datos simulados (mock) | Mapa + dibujo de AOI con el mock |
| h8–12 | M2: factor `k` por celda × mes, contracción | Agregados por celda × mes (crudo) | API conectada a los agregados crudos | Heatmap del calendario + barras con el mock |
| **h12: hito 1** | **Hecho:** primera versión de `k` y pesos en Parquet | **Hecho:** datos limpios de las 3 regiones | **Hecho:** la API devuelve el calendario crudo de un AOI real | **Hecho:** AOI dibujado → heatmap con el mock |
| h12–18 | M3: validación fuera de muestra (2012–17 → 2018+) | Agregados armonizados; CSV de exportación | Integra el frontend con la API real | Rango de fechas, lat/lon, rampa accesible |
| h18–24 | Ajustes del modelo; gráficos de validación | M7 + rendimiento | Empaquetado offline (un comando) | Interruptor crudo / armonizado; mes actual frente a mediana |
| **h24: hito 2** | **Hecho:** métricas de validación calculadas (aunque sean malas) | **Hecho:** CSV descargable | **Hecho:** demo de extremo a extremo en `main` sobre un portátil sin red | **Hecho:** las tres vistas principales funcionan con datos reales |
| h24–30 | R1 anomalías, R2 bandas de incertidumbre | R3 día/noche o R6 | Corrección de errores; segundo portátil clonado | Pulido de la interfaz; panel de validación |
| h30–36 | R4 o R7 si hay tiempo; texto científico para las diapositivas | R5 NRT en caché | Pruebas en modo avión | Guion del pitch v1; capturas |
| **h36: hito 3** | **Hecho:** cifras finales con `[resultado medido]` sustituidas | — | **Hecho:** la build candidata se arranca en 2 portátiles sin red | **Hecho:** guion v1 + borrador del vídeo |
| **h38: congelación de funcionalidades** | Solo correcciones | Solo correcciones | Etiqueta `v1.0-demo` | — |
| h38–44 | Revisa la honestidad de las afirmaciones | README de reproducción | Corrige solo errores bloqueantes | Graba el vídeo (más uno de respaldo); diapositivas |
| h44–47 | Ensayos cronometrados (×3) | Ídem | Ídem | Ídem |
| h47–48 | **Envío** (página del proyecto, vídeo, repositorio). No dejarlo para el último minuto | | | |

### 10.3 Trabajo en paralelo desde la hora 0

Se acuerdan en h0–2 y se escriben en el README.

**Tabla de hotspots armonizados** (Parquet; también es la base del CSV):

| Columna | Tipo | Descripción |
|---|---|---|
| `hotspot_id` | texto | Identificador único (sensor + fecha + hora + lat + lon) |
| `sensor` | texto | MODIS / VIIRS |
| `satellite` | texto | Terra, Aqua, SNPP, NOAA-20 |
| `acq_datetime_utc` | marca temporal | Fecha y hora de adquisición |
| `latitude`, `longitude` | decimal | Centro del píxel |
| `frp` | decimal | MW (informativo) |
| `confidence_class` | texto | low / nominal / high (normalizada entre sensores) |
| `daynight` | texto | D / N |
| `type` | entero | Valor original de FIRMS |
| `cell_id` | texto | Celda de rejilla o H3 res 5 |
| `era` | texto | `modis_only` / `overlap` |
| `in_calendar` | booleano | Si cuenta en la serie armonizada (evita duplicar sensores) |
| `weight_harm` | decimal | Peso VIIRS-equivalente (1 para VIIRS; `k` para MODIS antes de 2012) |

**Tabla agregada mensual:** `cell_id`, `year`, `month`, `n_modis_raw`, `n_viirs_raw`, `n_harm`, `n_harm_low`, `n_harm_high`.

**Contrato de la API** (descripción, sin implementación):

| Endpoint | Entrada | Salida |
|---|---|---|
| `calendar` | AOI (GeoJSON, o bbox, o lat/lon + radio), fechas, modo (crudo / armonizado) | Matriz años × meses, mediana por mes, valor del mes actual, totales anuales |
| `export` | Igual que `calendar` | CSV de hotspots o CSV de la matriz mensual |
| `validation` | Región | Métricas y series para el panel de validación |

**Datos simulados (mock):** P3 genera en h1 un archivo JSON con la forma exacta de la respuesta de `calendar` (valores aleatorios con estacionalidad), para que P4 avance sin esperar a nadie.

---

## 11. Validación y guion de la demo

### 11.1 Métricas que demuestran que la armonización funciona

Idea clave: **en 2012–presente existen ambos sensores**, así que se puede comprobar directamente.

| Métrica | Cómo se calcula | Qué demuestra | Resultado |
|---|---|---|---|
| Error fuera de muestra | Ajustar `k` con 2012–2017; predecir conteos VIIRS a partir de MODIS en 2018–2019 (órbitas aún estables) y 2020 en adelante (deriva); MAPE mediano o error en escala logarítmica por región y mes | La armonización generaliza a años no vistos | `[resultado a medir]` |
| Correlación de series mensuales | Spearman entre la serie MODIS armonizada y la VIIRS observada, en el periodo de prueba | Forma estacional y anual coherente | `[resultado a medir]` |
| Coincidencia de anomalías | Clasificar cada mes como por debajo / normal / por encima de la mediana según cada sensor; porcentaje de acuerdo y kappa de Cohen | **Lo que usa el gestor de emergencias** sale igual con cualquier sensor | `[resultado a medir]` |
| Ranking de años | Spearman entre los rankings anuales de actividad de cada sensor; coincidencia de los "3 peores años" | "¿Qué años tuvieron más actividad?" es consistente | `[resultado a medir]` |
| Estabilidad de `k` | `k` por año, con intervalo bootstrap | Detecta la deriva orbital después de 2020 | `[resultado a medir]` |
| Escalón en la costura (diagnóstico) | Razón entre la media 2009–2011 y la de 2012–2014 en la serie cruda y en la armonizada, desestacionalizada | El escalón artificial se reduce, sin afirmar que desaparece | `[resultado a medir]` |

**Comparación de referencia (baseline):** un único factor global (`k` constante). La armonización por celda y mes debe superarlo; si no lo supera, se dice.

**Cómo presentarlo con honestidad:**
- Mostrar las métricas por región, incluida la peor.
- Indicar las limitaciones: deriva orbital, NRT sin `type`, nubosidad no corregida, `k` incierto en celdas con pocos datos (bandas de incertidumbre).
- Expresar las afirmaciones en términos relativos: "reduce", "coincide en X % de los meses".

### 11.2 Guion del pitch (unos 3 min) y de la demo

| Tiempo | Contenido |
|---|---|
| 0:00–0:20 | **Problema:** "Un gestor quiere saber si este agosto es anómalo. Si junta MODIS y VIIRS sin más, 2012 parece el año en que el mundo empezó a arder más." Mostrar la serie cruda con el escalón (`[magnitud a medir]`). |
| 0:20–0:50 | **Método en una frase:** "Calibramos cuántos hotspots de VIIRS equivalen a uno de MODIS, celda a celda y mes a mes, usando los años en que ambos satélites observan a la vez." Diagrama de 3 cajas. |
| 0:50–1:50 | **Demo en vivo:** (1) dibujar un AOI en la Península Ibérica o el Cerrado; (2) aparece el calendario años × meses con una rampa accesible; (3) cambiar entre crudo y armonizado, y el escalón de 2012 se reduce; (4) "este mes frente a la mediana histórica" → `[valor]`; (5) descargar el CSV. |
| 1:50–2:30 | **Validación:** gráfica fuera de muestra y porcentaje de coincidencia de anomalías `[resultado a medir]`. Una frase sobre las limitaciones (deriva orbital, nubosidad). |
| 2:30–3:00 | **Impacto y hoja de ruta:** datos NRT para el mes actual, la armonización está preparada para cuando MODIS deje de operar, trabajo futuro (FRP, eventos, área quemada). Cierre. |

**Respaldo:** si la demo en vivo falla, se reproduce el vídeo de 30–60 s grabado en h40 sin interrumpir el discurso.

---

## 12. Riesgos y mitigaciones

| # | Tipo | Riesgo | Prob. | Impacto | Mitigación | Señal de alarma temprana |
|---|---|---|---|---|---|---|
| 1 | Datos | Las peticiones de archivo de FIRMS tardan o no llegan | Media | Alto | Pedirlas días antes; plan B con la descarga anual por país; USB | La petición de prueba tarda más de 12 h |
| 2 | Datos | Un sensor o año tiene huecos (paradas de SNPP, etc.) | Media | Medio | Recuento por mes en h2; cubrir con NOAA-20; marcar el hueco en la interfaz | Meses con 0 detecciones en temporada alta |
| 3 | Datos | VIIRS de archivo sin `type`, o códigos distintos de los esperados | Baja-media | Medio | Comprobar la cabecera antes del evento; fallback con R7 | Cabecera distinta en la petición de prueba |
| 4 | Científico | `k` inestable en celdas con pocos datos | Alta | Medio | Contracción hacia la región; celdas más grandes (res 4 / 0,5°); bandas de incertidumbre | Varianza de `k` entre años muy alta |
| 5 | Científico | Deriva orbital después de 2020: `k` cambia con el tiempo | Alta | Medio | Calibrar en 2012–2019; mostrarlo como hallazgo; opción de `k` por año | El error fuera de muestra de 2020 en adelante es mucho mayor que el de 2018–2019 |
| 6 | Científico | La armonización no supera la comparación de referencia (`k` global) | Media | Medio | Presentarlo con honestidad; elegir el modelo más simple que funcione | Métricas de h24 |
| 7 | Científico | Escalón de 2002 (entrada de Aqua) olvidado | Media | Bajo-medio | Factor Terra → Terra + Aqua o arrancar en julio de 2002 | Salto visible en el calendario de 2002 |
| 8 | Técnico | Herramienta de dibujo de AOI incompatible o con errores | Media | Medio | Fallback de bbox y lat/lon + radio (también pedido) | Sin dibujo funcional en h12 |
| 9 | Técnico | Rendimiento de la consulta por AOI en Brasil | Baja-media | Medio | Usar agregados por celda para el calendario; puntos solo para el CSV con límite de filas | Consulta de más de 3 s en h20 |
| 10 | Técnico | Entornos distintos (Windows / WSL / macOS) | Media | Medio | Fijar las dependencias; un portátil "de demo" designado desde h0 | No arranca en un segundo equipo en h24 |
| 11 | Equipo | Ampliación de alcance ("añadamos FRE…") | Alta | Alto | Alcance congelado en h2; el responsable de integración decide; lista de "futuro" visible | Tareas fuera del MVP antes de h24 |
| 12 | Equipo | Agotamiento o caída de una persona | Media | Alto | Turnos de sueño; cada componente con un suplente (§10.1) | Errores en cadena o lentitud después de h30 |
| 13 | Demo | Sin internet en la sala | Media | Alto | Todo en local, mapa base offline, NRT en caché | Prueba en modo avión fallida en h36 |
| 14 | Demo | Afirmaciones no sostenidas ante un jurado experto | Media | Alto | Revisión de honestidad en h38 (P1); prohibir cifras sin medir | Diapositivas con números sin fuente |
| 15 | Entrega | Envío tardío o requisitos de formato no cumplidos | Baja | Muy alto | Leer las reglas antes; enviar un borrador en h44 si se permite editar | Vídeo sin terminar en h44 |

---

## 13. Preguntas abiertas

1. ¿Qué perfiles exactos tiene el equipo? ¿Alguien domina React o MapLibre? ¿Alguien conoce H3?
2. ¿Qué RAM y sistema operativo tiene cada portátil? ¿Cuál será el portátil de la demo?
3. ¿Qué exige la entrega en 2026 (vídeo de 30 s, diapositivas, pitch en vivo y su duración) y cuáles son los criterios exactos del jurado local y global?
4. ¿Permiten las reglas descargar datos y crear cuentas antes del evento? ¿Y preparar material no relacionado con el código (diapositivas base)?
5. ¿Qué recursos enlaza la pestaña "Resources" del reto? ¿Hay algún conjunto de datos recomendado o un método de armonización sugerido por los organizadores?
6. ¿Qué regiones de demo prefiere el equipo? ¿Hay alguna con valor local (por ejemplo, la Comunidad Valenciana o Castellón)?
7. ¿Unidad de referencia: VIIRS-equivalente (recomendada) o MODIS-equivalente?
8. ¿Se incluye el mes actual con datos NRT (R5) o basta con el archivo hasta el último mes disponible?
9. ¿Cuál es el estado actual de Terra y Aqua MODIS (noviembre de 2026)? ¿Hasta qué fecha hay datos de archivo C6.1?
10. ¿Hay que desplegar la web en público (GitHub Pages, Render) o basta con la ejecución local y el vídeo?

---

## 14. Checklist previa al evento

**Cuentas y reglas**
- [ ] Leer las reglas y el formato de entrega de Space Apps 2026; confirmar los supuestos S4–S6.
- [ ] Revisar la pestaña "Resources" del reto y anotar los enlaces.
- [ ] Cuenta de NASA Earthdata creada (los 4 miembros, o al menos 2).
- [ ] MAP_KEY de FIRMS obtenida.

**Datos**
- [ ] Petición de archivo de prueba hecha; tiempo de entrega medido.
- [ ] Cabeceras verificadas: `type` en VIIRS de archivo, códigos de `satellite`, formato de `confidence`.
- [ ] 3 regiones descargadas (MODIS 2000 → presente, VIIRS SNPP 2012 → presente, NOAA-20).
- [ ] Datos del plan B (Península Ibérica, descarga anual por país) descargados.
- [ ] Copias en 2 portátiles y un USB, con sumas de verificación.
- [ ] Natural Earth (países y admin-1) descargado para el mapa offline.

**Equipo y entorno**
- [ ] Roles asignados, incluidos el responsable de integración y el del pitch.
- [ ] Turnos de sueño acordados.
- [ ] Repositorio con README y ramas acordadas (sin código del proyecto si las reglas lo prohíben).
- [ ] Python 3.11+, Node LTS, DuckDB y editores instalados y probados en cada portátil.
- [ ] Portátil de demo designado; adaptador HDMI/USB-C y cargadores.

**Contenido**
- [ ] Esquema de datos y contrato de la API (§10.3) leídos por todos.
- [ ] Lista de "trabajo futuro" impresa o visible, para frenar la ampliación de alcance.
- [ ] Regla acordada: **ninguna cifra en el pitch sin haberla medido**.
