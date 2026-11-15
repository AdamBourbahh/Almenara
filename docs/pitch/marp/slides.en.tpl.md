---
marp: true
theme: default
paginate: true
size: 16:9
lang: en
title: Project Almenara
description: Restoring 26 years of NASA satellite fire memory
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

<p class="sub">Restoring 26 years of NASA satellite fire memory</p>

<span class="tag">26 years of continuous record · 2000–2026</span>

<div class="sensor">
<div>MODIS<span>2000 · 1 km pixel</span></div>
<div>VIIRS<span>2012 · 375 m pixel</span></div>
</div>

<p style="margin-top:34px;font-size:20px" class="muted">One comparable fire series across two satellite generations: harmonized, audited and explained.</p>

<p style="font-size:20px">▶ <a href="http://localhost:5173/">Open the live demo · FIRMS Harmonizer</a></p>

</div>
<div>

![FIRMS Harmonizer live map](img/app-map.png)

<p class="mono">Live app: map, calendar, trends, impact, risk and FIRMS Copilot over the real cube.</p>

</div>
</div>

---

## Mathematical Rigor & Scientific Method
<p class="sub">We state a falsifiable hypothesis, fix the pass thresholds first, and publish failures too</p>

<div class="cols">
<div>

<div class="step"><b class="n">H₀</b><div><b>Hypothesis.</b> The 2012 jump is instrumental (VIIRS resolution), not climatic. If we are right, the harmonized series shows no structural break in 2012.</div></div>

* **Thresholds fixed before looking at results:** Chow break test p > 0.10 and Wasserstein-1 reduction ≥ 88 %.
* **Same code, four real regions:** Chilecito (AR), Iberia (ES/PT), Manaus (BR), Orlando (US).
* **Uncertainty, not guesses:** RTS Kalman smoother with Joseph-stabilized covariance and 95 % intervals.
* **Gaps only with evidence:** a missing day is never filled unless an outage or cloud mask proves it.
* **Reproducible:** 720 automated backend tests and a validation report anyone can rerun.

</div>
<div class="card">

### The tests behind the verdict

$$F_{\text{Chow}}=\frac{\big(\text{RSS}_{p}-(\text{RSS}_1+\text{RSS}_2)\big)/k}{(\text{RSS}_1+\text{RSS}_2)/(N_1+N_2-2k)}$$

$$W_1(F_{\text{pre}},F_{\text{post}})=\int_{-\infty}^{\infty}\lvert F_{\text{pre}}(x)-F_{\text{post}}(x)\rvert\,dx$$

$$P_{t|t}=(1-K h)^2P_{t|t-1}+K^2R$$

<details>
<summary>What we do <u>not</u> claim</summary>

- Detections are satellite pixels, not individual fires.
- No reconstruction without explicit gap evidence.
- Burned-area R² is descriptive, not out-of-sample validation.
- PM2.5 is shown only when emission inputs exist.

</details>
</div>
</div>

---

## The 400% Illusion: Resolution vs. Reality
<p class="sub">Without harmonization, a decade of fire history is not comparable</p>

<div class="cols-3-2">
<div class="card">

<span class="modis-c">■ MODIS</span> &nbsp; <span class="viirs-c">■ VIIRS</span> &nbsp; <span class="mono">raw detections per year · our 4 regions · hover a bar</span>

{{CHART}}

</div>
<div>

<div class="card" style="margin-bottom:16px">
<div class="big red">{{JUMP}}%</div>
<p style="margin:6px 0 0">Raw detections from 2011 to 2012: <b>{{T2011}} → {{T2012}}</b>. The fires did not change; the sensor did.</p>
</div>

* VIIRS pixels are **375 m**: one MODIS 1 km pixel holds ~7 of them.
* In 2012 VIIRS saw **{{RATIO}}×** more detections than MODIS over the same places and days.
* Counting pixels blindly turns a sensor upgrade into a fake fire trend.

</div>
</div>

---

## Our Solution in Four Steps
<p class="sub">From scattered points to one clean, comparable historical series · click a step for its math</p>

<div class="cards4">
<div class="card">
<div class="num">01</div>

### Hexagon grid
Points spread over a common H3 area.
<p class="mono">H3 quadrature · PSF footprint</p>

<details><summary>Math</summary>

Each detection's elliptical PSF is spread over its H3 r7 cell (5.16 km²) and 6 neighbours: $w_j\propto e^{-\frac12 d_j^\top\Sigma_k^{-1}d_j}$.

</details>
</div>
<div class="card">
<div class="num">02</div>

### Noise filter
Drops always-on industrial heat (flares, plants).
<p class="mono">Shannon temporal entropy</p>

<details><summary>Math</summary>

$H_{\text{temp}}=-\frac{1}{\ln 12}\sum_m p_m\ln p_m$. Year-round sources ($H>0.75$) are industrial, not seasonal fires.

</details>
</div>
<div class="card">
<div class="num">03</div>

### Sensor harmonization
Corrects the VIIRS sensitivity jump.
<p class="mono">EQM quantile mapping + GPD tail</p>

<details><summary>Math</summary>

$\hat X_V=F_M^{-1}(F_V(X_V))+\Delta E_{\text{sub}}$, per biome and scan angle; $\Delta E_{\text{sub}}$ adds the energy MODIS misses below 8 MW, from a Generalized Pareto tail.

</details>
</div>
<div class="card">
<div class="num">04</div>

### Sampling gaps
Estimates clouds and outages with honest uncertainty.
<p class="mono">RTS Kalman + 95 % CI</p>

<details><summary>Math</summary>

When every sensor is blind, a cross-sensor historical prior ($R=40$) keeps the state alive; bands widen instead of inventing data.

</details>
</div>
</div>

* **Common hexagonal H3 area** → every sensor is measured on the same ground.
* **No industrial heat, no VIIRS jump** → trends reflect fires, not hardware.
* **Gaps carry uncertainty** → the chart shows what we know and how well.

---

## Statistical Audit: Measured, Not Promised
<p class="sub">Real cube, rerun on 15 Nov 2026 · same code as the live demo's audit panel</p>

<div class="cols-3-2">
<div class="card">

| Region | Chow p · raw → harmonized | 2012 gate | W₁ reduction |
|---|---|---|---|
| Iberia (ES/PT) | 0.083 → **0.57** | <span class="pass">PASS</span> | 86.7 % |
| Chilecito (AR) | 0.034 → **0.31** | <span class="pass">PASS</span> | 85.4 % |
| Manaus (BR) | 0.38 → **0.46** | <span class="pass">PASS</span>* | 42.6 % |
| Orlando (US) | 1.7·10⁻⁷ → **0.005** | <span class="fail">FAIL</span> | 72.2 % |

<details>
<summary>How to read this</summary>

- Chow p > 0.10 means no structural break at January 2012: the series is continuous.
- \*Manaus raw data showed no break either, so its pass is not evidence of correction.
- W₁ measures how different the pre-/post-2012 distributions are; none reaches our 88 % target yet.
- Orlando's break shrinks by five orders of magnitude but remains: we report it instead of hiding it.

</details>
</div>
<div>

<div class="card" style="margin-bottom:16px">
<div class="big green">3 / 4</div>
<p style="margin:6px 0 0">regions pass the 2012 continuity gate after harmonization</p>
</div>

<div class="card">
<div class="big" style="color:var(--viirs)">43–87%</div>
<p style="margin:6px 0 0">less cross-era divergence (Wasserstein-1)</p>
</div>

</div>
</div>

<div class="footer-bar">▶ <a href="http://localhost:5173/">Interactive demo: FIRMS Harmonizer (2000–2026)</a> &nbsp;·&nbsp; Live H3 map · Calendar · Risk & Impact · FIRMS Copilot</div>
