# Reparto del trabajo en bloques

Versión corta y sencilla del plan. El detalle técnico está en [`PLANIFICATION.md`](PLANIFICATION.md), sobre todo en las secciones 6 (enfoque), 10 (roles y cronograma) y 11 (validación y demo).

## La idea en una frase

Es como una cadena de montaje con **cinco puestos**. Para que nadie tenga que esperar a otro, en la primera hora todos acordáis **qué forma tienen los datos que se pasan de un puesto al siguiente**, como quien decide el tipo de enchufe antes de fabricar el aparato y la toma. Mientras el puesto anterior no tenga datos reales, cada uno trabaja con **datos de mentira** que tienen esa misma forma.

```
 [A] Datos  ──►  [B] Ciencia  ──►  [C] Servidor  ──►  [D] Web  ──►  [E] Presentación
 descargar y     igualar MODIS     responde a las      mapa y          vídeo y pitch
 limpiar         y VIIRS           preguntas de la web calendario
```

---

## Bloque A — Datos ("la despensa")

- **Quién:** P2 (backend).
- **Qué es:** descargar los focos de fuego de la NASA (FIRMS), quitar la basura (volcanes, fábricas, detecciones dudosas) y guardarlo todo ordenado en un formato rápido (Parquet).
- **Entrega:** un archivo limpio por sensor y región.
- **Empieza sin esperar:** sí; los datos se descargan antes del evento.
- **Hecho cuando:** en la hora 12 están las tres regiones limpias y se ha comprobado que no faltan meses.

## Bloque B — Ciencia: armonizar ("traducir de un idioma a otro")

- **Quién:** P1 (ciencia de datos).
- **Qué es:** VIIRS ve muchos más focos que MODIS porque tiene mejor resolución. Desde 2012 funcionan los dos a la vez, así que se puede medir cuántos focos de VIIRS equivalen a uno de MODIS en cada zona y en cada mes. Con esa equivalencia se traducen los años antiguos (2000–2011, solo con MODIS) a la misma escala que los actuales.
- **Comprobación:** se calcula la equivalencia con unos años y se mira si acierta en otros años que no se usaron para calcularla.
- **Entrega:** cada foco con un "peso" y unas pocas gráficas que demuestran que la traducción funciona.
- **Empieza sin esperar:** explorando los datos de muestra mientras A termina la limpieza.
- **Hecho cuando:** en la hora 12 hay una primera equivalencia; en la hora 24, las cifras de comprobación (aunque salgan malas).

## Bloque C — Servidor y unión ("el camarero")

- **Quién:** P3. También es el **responsable de integración**: decide qué entra en la versión buena.
- **Qué es:** un programa que recibe la petición de la web (por ejemplo, "dame el calendario de esta zona entre estas fechas" o "dame el CSV") y devuelve la respuesta. Además se encarga de que todo arranque en un portátil **sin internet**.
- **Entrega:** tres respuestas: calendario, CSV y validación.
- **Empieza sin esperar:** en la hora 1 prepara respuestas de mentira para que la web pueda avanzar.
- **Hecho cuando:** en la hora 24 la demo funciona completa en un portátil en modo avión.

## Bloque D — Web ("el escaparate")

- **Quién:** P4 (frontend).
- **Qué es:** lo que ve el usuario:
  - un mapa donde dibujar la zona o escribir latitud y longitud;
  - un **calendario de colores** (años en filas, meses en columnas), con colores aptos para daltónicos;
  - un botón "datos sin armonizar / armonizados";
  - "este mes frente a lo normal";
  - un botón para descargar el CSV.
- **Empieza sin esperar:** con los datos de mentira del bloque C.
- **Hecho cuando:** en la hora 24 las tres vistas funcionan con datos reales.

## Bloque E — Presentación ("vender el producto")

- **Quién:** P4 lo dirige desde la hora 30 y todos ensayan al final.
- **Qué es:** contar el problema, el método en una frase, enseñar la demo, enseñar la comprobación y explicar el impacto. Incluye grabar un vídeo de respaldo por si falla la demo en directo.
- **Regla de oro:** ningún número en la presentación que no se haya medido de verdad.
- **Hecho cuando:** en la hora 44 el vídeo está grabado y se ha ensayado tres veces.

---

## Los tres controles (para saber si vais bien)

| Hora | Qué tiene que funcionar |
|---|---|
| **12** | Datos limpios, primera equivalencia y una web que dibuja una zona y enseña un calendario (todavía con datos de mentira) |
| **24** | La demo completa con datos reales, sin internet |
| **36** | Cifras finales y guion listo; **en la hora 38 se congela**: a partir de ahí solo se corrigen errores |

## Si sobra tiempo (por orden)

1. Marcar los meses anómalos.
2. Añadir márgenes de error a los años antiguos.
3. Separar los focos de día y de noche.
4. Mostrar el día pico de la temporada.
5. Añadir los datos del mes en curso.

Las ideas más complejas del documento original (elipses, Pareto, clusters, corrección por nubes) se presentan como **trabajo futuro**.
