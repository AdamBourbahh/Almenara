---
marp: true
theme: default
paginate: true
size: 16:9
lang: es
title: Project Almenara
description: Restaurando 26 años de memoria satelital de incendios de la NASA
math: mathjax
style: |
  :root { --paper:#f4f2ec; --card:#fffdf8; --ink:#1d2a33; --muted:#55626b; --rule:#d9d4c7;
          --red:#a3201d; --green:#1e6b4f; --modis:#c98a1b; --viirs:#1f8fa8; }
  section { background:var(--paper); color:var(--ink); font-family:'Noto Sans','Segoe UI',sans-serif;
            font-size:24px; padding:48px 64px 40px; justify-content:flex-start; }
  h1 { font-family:Georgia,'Libre Baskerville',serif; font-size:52px; margin:0 0 4px; color:var(--ink); }
  h2 { font-family:Georgia,serif; font-size:40px; margin:0 0 4px; color:var(--ink); }
  h3 { font-size:22px; margin:0 0 6px; }
  p.sub { color:var(--muted); margin:0 0 22px; font-size:24px; }
  section::after { color:var(--muted); font-size:16px; }
  a { color:var(--viirs); }
  .tag { display:inline-block; border:1px solid var(--rule); background:var(--card); border-radius:8px;
         padding:4px 12px; font-family:Consolas,monospace; font-size:18px; color:var(--muted); }
  .cols { display:grid; grid-template-columns:1fr 1fr; gap:28px; align-items:start; }
  .cols-3-2 { display:grid; grid-template-columns:3fr 2fr; gap:28px; align-items:start; }
  .card { background:var(--card); border:1px solid var(--rule); border-radius:12px; padding:18px 22px; }
  .cards4 { display:grid; grid-template-columns:repeat(4,1fr); gap:18px; }
  .num { font-family:Consolas,monospace; color:var(--red); font-size:30px; font-weight:700; }
  .mono { font-family:Consolas,monospace; font-size:16px; color:var(--muted); }
  .big { font-family:Consolas,monospace; font-size:64px; font-weight:700; line-height:1; }
  .red { color:var(--red); } .green { color:var(--green); } .muted { color:var(--muted); }
  .modis-c { color:var(--modis); font-weight:700; } .viirs-c { color:var(--viirs); font-weight:700; }
  details { margin-top:10px; border-top:1px dashed var(--rule); padding-top:8px; font-size:18px; }
  summary { cursor:pointer; color:var(--viirs); font-weight:600; list-style:none; }
  summary::before { content:"▸ "; } details[open] summary::before { content:"▾ "; }
  .card:hover { border-color:var(--ink); transition:border-color .15s; }
  table { font-size:19px; border-collapse:collapse; width:100%; }
  th { background:transparent; color:var(--muted); font-weight:600; border-bottom:2px solid var(--rule); }
  td, th { padding:7px 10px; border:none; border-bottom:1px solid var(--rule); background:transparent !important; }
  .pass { color:var(--green); font-weight:700; } .fail { color:var(--red); font-weight:700; }
  .footer-bar { position:absolute; left:64px; right:64px; bottom:44px; background:var(--ink); color:#fff;
                border-radius:10px; padding:12px 20px; font-family:Consolas,monospace; font-size:18px; }
  .footer-bar a { color:#f1c56b; }
  svg.chart { width:100%; height:auto; }
  svg.chart .grid { stroke:var(--rule); stroke-width:1; }
  svg.chart .ax { fill:var(--muted); font-size:14px; font-family:Consolas,monospace; }
  svg.chart .modis { fill:var(--modis); } svg.chart .viirs { fill:var(--viirs); }
  svg.chart .bar.partial rect { opacity:.4; }
  svg.chart .bar:hover rect { fill:var(--ink); }
  svg.chart .cut { stroke:var(--red); stroke-width:2; stroke-dasharray:6 4; }
  svg.chart .cutlbl { fill:var(--red); font-size:15px; font-weight:700; }
  .cover img { width:100%; border-radius:10px; border:1px solid var(--rule); box-shadow:0 10px 30px rgba(0,0,0,.12); }
  .sensor { display:flex; gap:40px; margin-top:26px; }
  .sensor div { text-align:center; font-family:Georgia,serif; font-size:26px; font-weight:700; }
  .sensor span { display:block; font-weight:400; font-size:22px; color:var(--muted); }
  .step { display:grid; grid-template-columns:48px 1fr; gap:12px; margin-bottom:10px; align-items:start; }
  .step b.n { font-family:Consolas,monospace; color:var(--red); font-size:24px; }
  ul { margin:0; padding-left:22px; } li { margin:4px 0; }
---

<!-- _paginate: false -->
<div class="cols-3-2 cover">
<div>

# Project Almenara

<p class="sub">Restaurando 26 años de memoria satelital de incendios de la NASA</p>

<span class="tag">26 años de registro continuo · 2000–2026</span>

<div class="sensor">
<div>MODIS<span>2000 · píxel de 1 km</span></div>
<div>VIIRS<span>2012 · píxel de 375 m</span></div>
</div>

<p style="margin-top:34px;font-size:20px" class="muted">Una serie de incendios comparable entre dos generaciones de satélites: armonizada, auditada y explicada.</p>

<p style="font-size:20px">▶ <a href="http://localhost:5173/">Abrir la demo en vivo · FIRMS Harmonizer</a></p>

</div>
<div>

![Mapa en vivo de FIRMS Harmonizer](img/app-map.png)

<p class="mono">App en vivo: mapa, calendario, tendencias, impacto, riesgo y FIRMS Copilot sobre el cubo real.</p>

</div>
</div>

---

## Rigor matemático y método científico
<p class="sub">Planteamos una hipótesis falsable, fijamos los umbrales antes de medir y publicamos también los fallos</p>

<div class="cols">
<div>

<div class="step"><b class="n">H₀</b><div><b>Hipótesis.</b> El salto de 2012 es instrumental (resolución de VIIRS), no climático. Si acertamos, la serie armonizada no muestra ruptura estructural en 2012.</div></div>

* **Umbrales fijados antes de ver resultados:** test de ruptura de Chow p > 0,10 y reducción de Wasserstein-1 ≥ 88 %.
* **Mismo código, cuatro regiones reales:** Chilecito (AR), Iberia (ES/PT), Manaos (BR), Orlando (EE. UU.).
* **Incertidumbre, no conjeturas:** suavizador RTS Kalman con covarianza estabilizada (Joseph) e intervalos del 95 %.
* **Huecos solo con evidencia:** un día sin datos nunca se rellena salvo que una caída de sensor o una máscara de nubes lo justifique.
* **Reproducible:** 720 tests automáticos en el backend y un informe de validación que cualquiera puede volver a ejecutar.

</div>
<div class="card">

### Los tests detrás del veredicto

$$F_{\text{Chow}}=\frac{\big(\text{RSS}_{p}-(\text{RSS}_1+\text{RSS}_2)\big)/k}{(\text{RSS}_1+\text{RSS}_2)/(N_1+N_2-2k)}$$

$$W_1(F_{\text{pre}},F_{\text{post}})=\int_{-\infty}^{\infty}\lvert F_{\text{pre}}(x)-F_{\text{post}}(x)\rvert\,dx$$

$$P_{t|t}=(1-K h)^2P_{t|t-1}+K^2R$$

<details>
<summary>Lo que <u>no</u> afirmamos</summary>

- Las detecciones son píxeles de satélite, no incendios individuales.
- No reconstruimos sin evidencia explícita de hueco.
- El R² frente a área quemada es descriptivo, no una validación fuera de muestra.
- El PM2.5 solo se muestra cuando existen datos de emisión.

</details>
</div>
</div>

---

## La ilusión del 400 %: resolución frente a realidad
<p class="sub">Sin armonización, una década de historia de incendios no es comparable</p>

<div class="cols-3-2">
<div class="card">

<span class="modis-c">■ MODIS</span> &nbsp; <span class="viirs-c">■ VIIRS</span> &nbsp; <span class="mono">detecciones crudas por año · nuestras 4 regiones · pasa el ratón por una barra</span>

{{CHART}}

</div>
<div>

<div class="card" style="margin-bottom:16px">
<div class="big red">{{JUMP}} %</div>
<p style="margin:6px 0 0">Detecciones crudas de 2011 a 2012: <b>{{T2011}} → {{T2012}}</b>. Los incendios no cambiaron; cambió el sensor.</p>
</div>

* Los píxeles de VIIRS miden **375 m**: en un píxel MODIS de 1 km caben unos 7.
* En 2012 VIIRS vio **{{RATIO}}×** más detecciones que MODIS en los mismos lugares y días.
* Contar píxeles a ciegas convierte una mejora del sensor en una falsa tendencia de incendios.

</div>
</div>

---

## Nuestra solución en cuatro pasos
<p class="sub">De puntos dispersos a una serie histórica limpia y comparable · haz clic en un paso para ver su matemática</p>

<div class="cards4">
<div class="card">
<div class="num">01</div>

### Malla de hexágonos
Puntos repartidos en un área H3 común.
<p class="mono">Cuadratura H3 · huella PSF</p>

<details><summary>Matemática</summary>

La PSF elíptica de cada detección se reparte entre su celda H3 r7 (5,16 km²) y sus 6 vecinas: $w_j\propto e^{-\frac12 d_j^\top\Sigma_k^{-1}d_j}$.

</details>
</div>
<div class="card">
<div class="num">02</div>

### Filtrado de ruido
Descarta el calor industrial permanente (antorchas, plantas).
<p class="mono">Entropía temporal de Shannon</p>

<details><summary>Matemática</summary>

$H_{\text{temp}}=-\frac{1}{\ln 12}\sum_m p_m\ln p_m$. Las fuentes activas todo el año ($H>0{,}75$) son industriales, no incendios estacionales.

</details>
</div>
<div class="card">
<div class="num">03</div>

### Armonización de sensores
Corrige el salto de sensibilidad de VIIRS.
<p class="mono">Mapeo cuantílico EQM + cola GPD</p>

<details><summary>Matemática</summary>

$\hat X_V=F_M^{-1}(F_V(X_V))+\Delta E_{\text{sub}}$, por bioma y ángulo de escaneo; $\Delta E_{\text{sub}}$ añade la energía que MODIS no ve por debajo de 8 MW, a partir de una cola de Pareto generalizada.

</details>
</div>
<div class="card">
<div class="num">04</div>

### Huecos de muestreo
Estima nubes y caídas de sensor con incertidumbre honesta.
<p class="mono">RTS Kalman + IC 95 %</p>

<details><summary>Matemática</summary>

Cuando todos los sensores están ciegos, un prior histórico entre sensores ($R=40$) mantiene vivo el estado; las bandas se ensanchan en lugar de inventar datos.

</details>
</div>
</div>

* **Área hexagonal H3 común** → todos los sensores se miden sobre el mismo terreno.
* **Sin calor industrial ni salto de VIIRS** → las tendencias reflejan incendios, no hardware.
* **Los huecos llevan incertidumbre** → el gráfico muestra qué sabemos y con qué precisión.

---

## Auditoría estadística: medida, no prometida
<p class="sub">Cubo real, recalculado el 15 nov 2026 · el mismo código que el panel de auditoría de la demo</p>

<div class="cols-3-2">
<div class="card">

| Región | p de Chow · cruda → armonizada | Control 2012 | Reducción W₁ |
|---|---|---|---|
| Iberia (ES/PT) | 0,083 → **0,57** | <span class="pass">APRUEBA</span> | 86,7 % |
| Chilecito (AR) | 0,034 → **0,31** | <span class="pass">APRUEBA</span> | 85,4 % |
| Manaos (BR) | 0,38 → **0,46** | <span class="pass">APRUEBA</span>* | 42,6 % |
| Orlando (EE. UU.) | 1,7·10⁻⁷ → **0,005** | <span class="fail">NO APRUEBA</span> | 72,2 % |

<details>
<summary>Cómo leer esta tabla</summary>

- p de Chow > 0,10 significa que no hay ruptura estructural en enero de 2012: la serie es continua.
- \*Los datos crudos de Manaos tampoco mostraban ruptura, así que su aprobado no prueba la corrección.
- W₁ mide cuánto difieren las distribuciones antes y después de 2012; ninguna región alcanza aún nuestro objetivo del 88 %.
- La ruptura de Orlando se reduce cinco órdenes de magnitud pero persiste: la mostramos en lugar de ocultarla.

</details>
</div>
<div>

<div class="card" style="margin-bottom:16px">
<div class="big green">3 / 4</div>
<p style="margin:6px 0 0">regiones superan el control de continuidad de 2012 tras la armonización</p>
</div>

<div class="card">
<div class="big" style="color:var(--viirs)">43–87 %</div>
<p style="margin:6px 0 0">menos divergencia entre épocas (Wasserstein-1)</p>
</div>

</div>
</div>

<div class="footer-bar">▶ <a href="http://localhost:5173/">Demo interactiva: FIRMS Harmonizer (2000–2026)</a> &nbsp;·&nbsp; Mapa H3 en vivo · Calendario · Riesgo e impacto · FIRMS Copilot</div>
