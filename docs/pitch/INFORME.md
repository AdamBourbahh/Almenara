# Pitch — diapositivas MODIS/VIIRS

Dos diapositivas 16:9 en español para el pitch:

1. **`problema`**: el problema. Esquema de un pixel MODIS de 1 km frente a una cuadrícula VIIRS de 375 m, más un ejemplo ilustrativo de 100 → 500 detecciones.
2. **`matematica`**: la base matemática. Flujo de 4 etapas con las fórmulas de los documentos.

Deck publicado (privado; se comparte desde *Share*): https://claude.ai/artifact/WYhmf2q7V21rhrAWizqN1e

## Estructura

```
deck/project/            fuente del deck (tipo Slides)
  deck.json              índice: orden, título, tipografía (Inter)
  deck.css               estilos comunes (MODIS = ámbar, VIIRS = cian, advertencia = coral)
  slides/problema.html
  slides/matematica.html generado: no editar a mano
build/                   regeneración de la diapositiva 2
  formulas.json          LaTeX de cada fórmula, copiado tal cual de la fuente
  split.js               corta las fórmulas largas en dos líneas (sin cambiar símbolos)
  render.js              MathJax 3.2.2 → SVG (el deck no ejecuta scripts, así que no se usa KaTeX)
  matematica.tpl.html    plantilla con huecos {{clave}}
  build.js               rellena la plantilla y escribe slides/matematica.html
```

Para regenerarla: `cd build && npm install && npm run build`.

## Fórmulas por etapa y fuente

| Etapa | Fórmulas | Fuente |
|---|---|---|
| 1 · Malla y ordenación | η_overlap, Σ_k, A_k, w_j, A_H3₇ | SPECS.md L39, L41, L42 |
| | Conexión ST-H3 (DAG), FRE del evento | docs/Nasa (3).pdf p.3 |
| 2 · Filtro industrial | H_temp, umbrales 0.25/0.75, ΔT₄/₁₁, σ²_pos, H₀, filtro SAMA | SPECS.md L49–L54 |
| 3 · Armonización | FRP_min, EQM, ΔE_sub (GPD), W₁, F_Chow | SPECS.md L57, L60, L62, L107, L104 |
| | π_det | docs/Nasa (3).pdf p.2 |
| 4 · Huecos con incertidumbre | Estimador Horvitz-Thompson | docs/Nasa (3).pdf p.4 |
| | π_orb, κ(τ_s), μ_cross, predicción, S/K, Joseph, y_guard/R_guard, G_t, x̂_{t\|T}, P_{t\|T}, IC 95 % | SPECS.md L66–L83 |
| Salidas | ψ_d, C̄/S̄/R̄, μ̂_y, κ̂_y (Best-Fisher), W_y, M_biomass, E_PM2.5/E_CO2, H = 14 ± 1.96√P | SPECS.md L84, L89–L99 |

Las 36 fórmulas de SPECS.md se comprobaron carácter a carácter contra el archivo. Las 4 que solo aparecen en un PDF se transcribieron a mano desde la página.

## Criterios y ajustes

- **Prioridad de fuentes:** cuando dos versiones de una fórmula no coinciden, manda SPECS.md (es la implementada). Versiones del PDF descartadas:
  - Shannon con 1/log M.
  - ΔE_sub sin π_sub.
  - π_orb con W_swath.
  - Momentos de von Mises sin +10⁻⁸.
  - W₁ de Nasa (3).pdf p.1, que duplica la de SPECS.
- **No incluidas:**
  - El código Kalman de Nasa.pdf p.8: es código, no una fórmula, y usa φ = 0.72 frente al 0.68 de SPECS.
  - La ganancia matricial de Nasa.pdf p.7: la sustituye la versión escalar de SPECS.
- **Orden de las etapas:** ningún PDF tiene el diagrama de 4 etapas, así que se siguen los Módulos 1–4 de SPECS.md §3.
- **Ubicación por función:**
  - DAG y FRE van en la etapa 1 (en SPECS §2 aparecen como integración diaria por celda).
  - W₁ y Chow van en la etapa 3 (en SPECS son el Módulo 7, auditoría).
- **Tira de «Salidas»:** von Mises, biomasa, emisiones y previsión van en una tira bajo las columnas 1–3, alimentada desde la etapa 4, para que la columna 4 no se desborde.
- **Previsión de 14 días:** rotulada «(pendiente)», porque SPECS la deja fuera del MVP.
- **Micro-etiquetas a 15 px:** por debajo de los 24 px que recomienda el tipo Slides, por petición expresa de que sean pequeñas.
- **Idioma:** las diapositivas están en español por petición del equipo. La regla de inglés de AGENTS.md se aplica a la UI de la app y al README, no a este material de pitch.
