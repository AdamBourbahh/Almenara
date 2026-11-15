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

<svg class="chart" viewBox="0 0 1000 350" role="img" aria-label="Raw satellite detections per year"><line x1="60" x2="990" y1="290.0" y2="290.0" class="grid"/><text x="52" y="295.0" class="ax" text-anchor="end">0k</text><line x1="60" x2="990" y1="222.5" y2="222.5" class="grid"/><text x="52" y="227.5" class="ax" text-anchor="end">50k</text><line x1="60" x2="990" y1="155.0" y2="155.0" class="grid"/><text x="52" y="160.0" class="ax" text-anchor="end">100k</text><line x1="60" x2="990" y1="87.5" y2="87.5" class="grid"/><text x="52" y="92.5" class="ax" text-anchor="end">150k</text><g class="bar partial"><title>2000 (partial year): MODIS 266 · VIIRS 0 · total 266</title><rect x="63.0" y="289.6" width="28.4" height="0.4" class="modis"/><rect x="63.0" y="289.6" width="28.4" height="0.0" class="viirs"/></g><text x="77.2" y="310" class="ax" text-anchor="middle">2000</text><g class="bar"><title>2001: MODIS 6,146 · VIIRS 0 · total 6,146</title><rect x="97.4" y="281.7" width="28.4" height="8.3" class="modis"/><rect x="97.4" y="281.7" width="28.4" height="0.0" class="viirs"/></g><g class="bar"><title>2002: MODIS 12,641 · VIIRS 0 · total 12,641</title><rect x="131.9" y="272.9" width="28.4" height="17.1" class="modis"/><rect x="131.9" y="272.9" width="28.4" height="0.0" class="viirs"/></g><g class="bar"><title>2003: MODIS 18,596 · VIIRS 0 · total 18,596</title><rect x="166.3" y="264.9" width="28.4" height="25.1" class="modis"/><rect x="166.3" y="264.9" width="28.4" height="0.0" class="viirs"/></g><g class="bar"><title>2004: MODIS 14,778 · VIIRS 0 · total 14,778</title><rect x="200.8" y="270.0" width="28.4" height="20.0" class="modis"/><rect x="200.8" y="270.0" width="28.4" height="0.0" class="viirs"/></g><text x="215.0" y="310" class="ax" text-anchor="middle">2004</text><g class="bar"><title>2005: MODIS 20,308 · VIIRS 0 · total 20,308</title><rect x="235.2" y="262.6" width="28.4" height="27.4" class="modis"/><rect x="235.2" y="262.6" width="28.4" height="0.0" class="viirs"/></g><g class="bar"><title>2006: MODIS 14,208 · VIIRS 0 · total 14,208</title><rect x="269.7" y="270.8" width="28.4" height="19.2" class="modis"/><rect x="269.7" y="270.8" width="28.4" height="0.0" class="viirs"/></g><g class="bar"><title>2007: MODIS 10,612 · VIIRS 0 · total 10,612</title><rect x="304.1" y="275.7" width="28.4" height="14.3" class="modis"/><rect x="304.1" y="275.7" width="28.4" height="0.0" class="viirs"/></g><g class="bar"><title>2008: MODIS 6,980 · VIIRS 0 · total 6,980</title><rect x="338.6" y="280.6" width="28.4" height="9.4" class="modis"/><rect x="338.6" y="280.6" width="28.4" height="0.0" class="viirs"/></g><text x="352.8" y="310" class="ax" text-anchor="middle">2008</text><g class="bar"><title>2009: MODIS 14,440 · VIIRS 0 · total 14,440</title><rect x="373.0" y="270.5" width="28.4" height="19.5" class="modis"/><rect x="373.0" y="270.5" width="28.4" height="0.0" class="viirs"/></g><g class="bar"><title>2010: MODIS 10,741 · VIIRS 0 · total 10,741</title><rect x="407.4" y="275.5" width="28.4" height="14.5" class="modis"/><rect x="407.4" y="275.5" width="28.4" height="0.0" class="viirs"/></g><g class="bar"><title>2011: MODIS 11,336 · VIIRS 0 · total 11,336</title><rect x="441.9" y="274.7" width="28.4" height="15.3" class="modis"/><rect x="441.9" y="274.7" width="28.4" height="0.0" class="viirs"/></g><g class="bar"><title>2012: MODIS 15,544 · VIIRS 51,267 · total 66,811</title><rect x="476.3" y="269.0" width="28.4" height="21.0" class="modis"/><rect x="476.3" y="199.8" width="28.4" height="69.2" class="viirs"/></g><text x="490.6" y="310" class="ax" text-anchor="middle">2012</text><g class="bar"><title>2013: MODIS 10,843 · VIIRS 39,267 · total 50,110</title><rect x="510.8" y="275.4" width="28.4" height="14.6" class="modis"/><rect x="510.8" y="222.4" width="28.4" height="53.0" class="viirs"/></g><g class="bar"><title>2014: MODIS 7,434 · VIIRS 32,191 · total 39,625</title><rect x="545.2" y="280.0" width="28.4" height="10.0" class="modis"/><rect x="545.2" y="236.5" width="28.4" height="43.5" class="viirs"/></g><g class="bar"><title>2015: MODIS 11,169 · VIIRS 48,379 · total 59,548</title><rect x="579.7" y="274.9" width="28.4" height="15.1" class="modis"/><rect x="579.7" y="209.6" width="28.4" height="65.3" class="viirs"/></g><g class="bar"><title>2016: MODIS 11,513 · VIIRS 43,471 · total 54,984</title><rect x="614.1" y="274.5" width="28.4" height="15.5" class="modis"/><rect x="614.1" y="215.8" width="28.4" height="58.7" class="viirs"/></g><text x="628.3" y="310" class="ax" text-anchor="middle">2016</text><g class="bar"><title>2017: MODIS 17,097 · VIIRS 62,733 · total 79,830</title><rect x="648.6" y="266.9" width="28.4" height="23.1" class="modis"/><rect x="648.6" y="182.2" width="28.4" height="84.7" class="viirs"/></g><g class="bar"><title>2018: MODIS 6,386 · VIIRS 55,145 · total 61,531</title><rect x="683.0" y="281.4" width="28.4" height="8.6" class="modis"/><rect x="683.0" y="206.9" width="28.4" height="74.4" class="viirs"/></g><g class="bar"><title>2019: MODIS 8,102 · VIIRS 66,113 · total 74,215</title><rect x="717.4" y="279.1" width="28.4" height="10.9" class="modis"/><rect x="717.4" y="189.8" width="28.4" height="89.3" class="viirs"/></g><g class="bar"><title>2020: MODIS 8,462 · VIIRS 67,125 · total 75,587</title><rect x="751.9" y="278.6" width="28.4" height="11.4" class="modis"/><rect x="751.9" y="188.0" width="28.4" height="90.6" class="viirs"/></g><text x="766.1" y="310" class="ax" text-anchor="middle">2020</text><g class="bar"><title>2021: MODIS 7,625 · VIIRS 59,977 · total 67,602</title><rect x="786.3" y="279.7" width="28.4" height="10.3" class="modis"/><rect x="786.3" y="198.7" width="28.4" height="81.0" class="viirs"/></g><g class="bar"><title>2022: MODIS 12,220 · VIIRS 86,882 · total 99,102</title><rect x="820.8" y="273.5" width="28.4" height="16.5" class="modis"/><rect x="820.8" y="156.2" width="28.4" height="117.3" class="viirs"/></g><g class="bar"><title>2023: MODIS 10,549 · VIIRS 132,982 · total 143,531</title><rect x="855.2" y="275.8" width="28.4" height="14.2" class="modis"/><rect x="855.2" y="96.2" width="28.4" height="179.5" class="viirs"/></g><g class="bar"><title>2024: MODIS 9,346 · VIIRS 118,247 · total 127,593</title><rect x="889.7" y="277.4" width="28.4" height="12.6" class="modis"/><rect x="889.7" y="117.7" width="28.4" height="159.6" class="viirs"/></g><text x="903.9" y="310" class="ax" text-anchor="middle">2024</text><g class="bar"><title>2025: MODIS 16,069 · VIIRS 157,459 · total 173,528</title><rect x="924.1" y="268.3" width="28.4" height="21.7" class="modis"/><rect x="924.1" y="55.7" width="28.4" height="212.6" class="viirs"/></g><g class="bar partial"><title>2026 (partial year): MODIS 13,405 · VIIRS 157,374 · total 170,779</title><rect x="958.6" y="271.9" width="28.4" height="18.1" class="modis"/><rect x="958.6" y="59.4" width="28.4" height="212.5" class="viirs"/></g><text x="972.8" y="310" class="ax" text-anchor="middle">2026</text><line x1="473.3" x2="473.3" y1="20" y2="290" class="cut"/><text x="465.3" y="36" class="cutlbl" text-anchor="end">VIIRS joins · Jan 2012</text></svg>

</div>
<div>

<div class="card" style="margin-bottom:16px">
<div class="big red">+489%</div>
<p style="margin:6px 0 0">Raw detections from 2011 to 2012: <b>11,336 → 66,811</b>. The fires did not change; the sensor did.</p>
</div>

* VIIRS pixels are **375 m**: one MODIS 1 km pixel holds ~7 of them.
* In 2012 VIIRS saw **3.3×** more detections than MODIS over the same places and days.
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
