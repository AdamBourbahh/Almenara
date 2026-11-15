import { useEffect, useState, type ReactNode } from "react";
import { Activity, RefreshCw } from "lucide-react";
import type { AIRiskAssessment, RiskFactor, RiskValidation } from "../../api/types";
import { PRESET_REGIONS, riskForecastDate, useAnalysisStore } from "../../store/useAnalysisStore";
import {
  NOT_AVAILABLE, buildEquation, buildEscalation, buildOutlook, buildTrajectory, diurnalPhrase, driftPhrase, driverBars,
  formatMw, formatPct, formatTonnes, hazardLevel, isFiniteNumber, nearestIndex, observationPill, peakPhrase,
  persistencePhrase, type PlotBox,
} from "./riskPresentation";

const HORIZONS = [1, 7, 14] as const;
const horizonLabels = { 1: "24-Hour", 7: "7-Day", 14: "14-Day" };
const colors = {
  LOW: "border-validated/40 bg-validated/10 text-validated",
  MODERATE: "border-terracotta/40 bg-terracotta/10 text-terracotta",
  HIGH: "border-thermal-3/50 bg-thermal-3/10 text-thermal-3",
  CRITICAL: "border-bias/50 bg-bias/10 text-bias",
};
const modelNames: Record<string, string> = {
  logistic: "L2 logistic",
  boosted_stumps: "Boosted stumps",
  gaussian_naive_bayes: "Gaussian naive Bayes",
  causal_prior: "Causal prior",
};
const forecastTracks = [
  { label: "High heat in non-persistent cells", key: "wildfire_prob_pct", target: "wildfire", color: "bg-thermal-3" },
  { label: "Excursion in persistent cells", key: "accident_prob_pct", target: "accident", color: "bg-industrial" },
  { label: "Either thermal event", key: "combined_risk_pct", target: "combined", color: "bg-reference" },
] as const;

function formatOffsetDate(asOf: string, offset: number): string {
  const date = new Date(asOf + "T00:00:00Z");
  date.setUTCDate(date.getUTCDate() + offset);
  return date.toISOString().slice(0, 10);
}


function hasMetrics(stats: RiskValidation): boolean {
  return isFiniteNumber(stats.brier_score) || isFiniteNumber(stats.roc_auc);
}

function Validation({ label, stats }: { label: string; stats: RiskValidation }) {
  const bins = stats.reliability.filter((bin) => isFiniteNumber(bin.mean_predicted_pct) &&
    isFiniteNumber(bin.observed_pct) && bin.samples > 0);
  return <div className="border border-rule p-3">
    <h5 className="font-semibold text-ink">{label}</h5>
    <p className="mt-1 text-muted">{stats.positives} of {stats.samples} windows contained an event</p>
    <dl className="mt-2 flex flex-wrap gap-4">
      {isFiniteNumber(stats.roc_auc) && <div><dt>ROC-AUC</dt><dd className="font-mono tnum font-semibold">{stats.roc_auc.toFixed(3)}</dd></div>}
      {isFiniteNumber(stats.brier_score) && <div><dt>Brier score</dt><dd className="font-mono tnum font-semibold">{stats.brier_score.toFixed(3)}</dd></div>}
    </dl>
    {bins.length > 0 && <details className="mt-2 text-muted">
      <summary className="cursor-pointer">Calibration reliability</summary>
      <table className="mt-2 w-full text-left tnum">
        <thead><tr><th>Predicted</th><th>Observed</th><th>Windows</th></tr></thead>
        <tbody>{bins.map((bin, i) => <tr key={i}>
          <td>{formatPct(bin.mean_predicted_pct)}</td><td>{formatPct(bin.observed_pct)}</td><td>{bin.samples}</td>
        </tr>)}</tbody>
      </table>
    </details>}
  </div>;
}

function CommandEquation({ assessment }: { assessment: AIRiskAssessment }) {
  const eq = buildEquation(assessment);
  if (!eq) return null;
  const tone = (v: number) => v > 0 ? "text-thermal-3" : v < 0 ? "text-validated" : "text-ink";
  const summary = eq.terms.map((t) => t.label + " " + t.text).join(", plus ") + ", equals " + eq.total.text + " 24-hour risk";
  return <div role="group" aria-label={summary} className="mt-4 flex flex-wrap items-stretch gap-x-2 gap-y-2 text-xs">
    {eq.terms.map((term, i) => <div key={term.key} className="flex items-stretch gap-2">
      {i > 0 && <span aria-hidden="true" className="self-center font-mono text-muted">+</span>}
      <div className="min-w-[7.5rem] border border-rule px-2.5 py-1.5">
        <p className="text-muted">{term.label}</p>
        <p className={"tnum font-mono text-sm font-semibold " + (term.key === "baseline" ? "text-ink" : tone(term.value))}>{term.text}</p>
      </div>
    </div>)}
    <div className="flex items-stretch gap-2">
      <span aria-hidden="true" className="self-center font-mono text-muted">=</span>
      <div className="min-w-[7.5rem] border border-rule-strong bg-paper px-2.5 py-1.5">
        <p className="text-muted">24h risk{eq.total.multiplier && <> · <span className="tnum font-mono text-ink">{eq.total.multiplier}</span></>}</p>
        <p className="tnum font-mono text-sm font-bold text-ink">{eq.total.text}</p>
      </div>
    </div>
  </div>;
}

function Row({ label, value, hint }: { label: string; value: string | null | undefined; hint?: string }) {
  const missing = !value || value === NOT_AVAILABLE;
  return <div className="flex flex-wrap items-baseline justify-between gap-x-3">
    <dt className="text-muted">{label}</dt>
    <dd className={"tnum min-w-0 text-right " + (missing ? "text-faint" : "font-mono font-semibold text-ink")}>
      {missing ? NOT_AVAILABLE : value}{hint && !missing && <span className="block font-sans text-[11px] font-normal text-muted">{hint}</span>}
    </dd>
  </div>;
}

function OpCard({ title, children }: { title: string; children: ReactNode }) {
  return <section aria-label={title} className="min-w-0 border border-rule bg-panel p-4 text-xs">
    <h4 className="font-serif text-sm font-semibold text-ink">{title}</h4>
    {children}
  </section>;
}

function IntensityCard({ a }: { a: AIRiskAssessment }) {
  const i = a.intensity;
  if (!i) return null;
  const origin = i.contagion_origin ? i.contagion_origin + (isFiniteNumber(i.neighbor_frp_mw) ? " · " + formatMw(i.neighbor_frp_mw) + " neighbor FRP" : "") : null;
  return <OpCard title="Intensity regime & diurnal window">
    <p className="mt-2 font-semibold text-ink">{i.regime}</p>
    {i.guidance && <p className="mt-1 leading-relaxed text-muted">{i.guidance}</p>}
    <dl className="mt-3 space-y-1.5 border-t border-rule pt-3">
      <Row label="Fire radiative power" value={formatMw(i.intensity_mw)} />
      <Row label="Diurnal cycle" value={diurnalPhrase(i.diurnal_amplification_ratio)} />
      <Row label="Contagion origin" value={origin} />
    </dl>
  </OpCard>;
}

function PhenologyCard({ a }: { a: AIRiskAssessment }) {
  const p = a.phenology;
  if (!p) return null;
  return <OpCard title="Phenological window & biomass exposure">
    <p className="mt-2 font-semibold text-ink">{peakPhrase(p.days_to_peak, p.peak_date_label)}</p>
    <dl className="mt-3 space-y-1.5 border-t border-rule pt-3">
      <Row label="Season width" value={isFiniteNumber(p.season_width_days) ? Math.round(p.season_width_days) + " days" : null} />
      <Row label="Concentration κ" value={isFiniteNumber(p.kappa) ? p.kappa.toFixed(2) : null} />
      <Row label="Decadal drift" value={driftPhrase(p.decadal_shift_days)} />
      <Row label="Biomass exposure" value={formatTonnes(p.biomass_exposure_tonnes)} hint="t dry biomass, last 7 days (est.)" />
      <Row label="Persistence entropy" value={isFiniteNumber(p.persistence_entropy) ? p.persistence_entropy.toFixed(2) + " of 1" : null}
        hint={p.fuel_regime ?? undefined} />
    </dl>
  </OpCard>;
}

function EscalationCard({ a }: { a: AIRiskAssessment }) {
  const g = buildEscalation(a.horizons);
  const rho = persistencePhrase(a.markov_persistence);
  const caption = a.horizon_explanation;
  if (!g && !rho && !caption) return null;
  return <OpCard title="Horizon escalation">
    {g && <svg viewBox="0 0 220 84" className="mt-2 h-auto w-full max-w-[18rem]" role="img"
      aria-label={"Combined risk by horizon: " + g.points.map((p) => p.label + " " + p.text).join(", ")}>
      <line x1="26" x2="194" y1="62" y2="62" className="stroke-rule-strong" strokeWidth="1" />
      <path d={g.path} fill="none" className="stroke-thermal-3" strokeWidth="1.75" />
      {g.points.map((p) => <g key={p.days}>
        <circle cx={p.x} cy={p.y} r="3.5" className="fill-thermal-3 stroke-panel" strokeWidth="1.5" />
        <text x={p.x} y={p.y - 8} textAnchor="middle" fontSize="10" className="fill-ink font-mono font-semibold">{p.text}</text>
        <text x={p.x} y="77" textAnchor="middle" fontSize="10" className="fill-muted font-mono">{p.label}</text>
      </g>)}
    </svg>}
    {rho && <p className="tnum mt-2 font-mono font-semibold text-ink">{rho}</p>}
    {caption && <p className="mt-1 leading-relaxed text-muted">{caption}</p>}
  </OpCard>;
}

function Drivers({ title, factors }: { title: string; factors: RiskFactor[] }) {
  const bars = driverBars(factors);
  if (!bars.length) return null;
  return <section className="min-w-0">
    <h5 className="font-semibold text-ink">{title}</h5>
    <ul className="mt-3 space-y-3">
      {bars.map((bar) => <li key={bar.feature}>
        <p className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5">
          <span>{bar.feature}{bar.observed && <span className="tnum ml-2 font-mono text-muted">{bar.observed}</span>}</span>
          <span className={"tnum font-mono font-semibold " + (bar.tone === "raises" ? "text-thermal-3" : "text-validated")}>{bar.label}</span>
        </p>
        <div role="img" aria-label={bar.feature + " " + bar.label + (bar.tone === "raises" ? ", raises risk" : ", lowers risk")}
          className="relative mt-1.5 h-2 rounded-sm bg-rule/60">
          <span className="absolute inset-y-0 left-1/2 border-l border-muted" />
          <span className={"absolute inset-y-0 motion-safe:transition-[width] motion-safe:duration-200 " +
            (bar.side === "right" ? "left-1/2 bg-thermal-3" : "right-1/2 bg-validated")} style={{ width: bar.widthPct / 2 + "%" }} />
        </div>
        {bar.description && <p className="mt-1 leading-relaxed text-muted">{bar.description}</p>}
      </li>)}
    </ul>
  </section>;
}

function Grid({ plot, width }: { plot: PlotBox; width: number }) {
  return <>
    {[0, 25, 50, 75, 100].map((pct) => {
      const y = plot.top + plot.height - (pct / 100) * plot.height;
      return <g key={pct}>
        <line x1={plot.left} y1={y} x2={width - 14} y2={y} stroke="currentColor" strokeOpacity={pct === 50 ? 0.25 : 0.12}
          strokeDasharray={pct === 50 ? "4 4" : undefined} />
        <text x={plot.left - 6} y={y + 3} textAnchor="end" fontSize="9" fill="currentColor" opacity={0.6} className="font-mono">{pct}%</text>
      </g>;
    })}
  </>;
}

function AxisDates({ plot, first, last }: { plot: PlotBox; first: string; last: string }) {
  const y = plot.top + plot.height + 20;
  return <>
    <text x={plot.left} y={y} fontSize="9" fill="currentColor" opacity={0.7} className="font-mono">{first}</text>
    <text x={plot.left + plot.width} y={y} textAnchor="end" fontSize="9" fill="currentColor" opacity={0.7} className="font-mono">{last}</text>
  </>;
}

function Swatch({ kind }: { kind: "heat" | "industrial" | "baseline" | "event" }) {
  if (kind === "event") return <span aria-hidden="true" className="inline-block h-2.5 w-0 border-l-2 border-ink" />;
  const style = kind === "heat" ? "border-thermal-3 border-t-2" : kind === "industrial" ? "border-industrial border-t-2 border-dashed" : "border-reference border-t border-dashed";
  return <span aria-hidden="true" className={"inline-block w-4 " + style} />;
}

function ProbabilityTrajectoryChart({ series }: { series: AIRiskAssessment["daily_probability_series"] }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const g = buildTrajectory(series);
  if (!g) return null;
  const { plot, points } = g;
  const hovered = hoverIndex !== null ? points[hoverIndex] ?? null : null;
  const width = 640;
  const summary = "Daily probability trajectory from " + g.firstLabel + " to " + g.lastLabel +
    (g.hasBaseline ? ", with seasonal baseline" : "") + (g.events.length ? ", " + g.events.length + " observed event days marked" : "");
  return <div className="relative">
    <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs font-medium text-ink">
      <span className="flex items-center gap-1.5"><Swatch kind="heat" />Non-persistent heat risk</span>
      <span className="flex items-center gap-1.5"><Swatch kind="industrial" />Persistent-source excursion</span>
      {g.hasBaseline && <span className="flex items-center gap-1.5"><Swatch kind="baseline" />Seasonal baseline</span>}
      {g.events.length > 0 && <span className="flex items-center gap-1.5"><Swatch kind="event" />Observed event day</span>}
    </div>
    <div className="relative overflow-hidden border border-rule bg-panel text-ink">
      <svg viewBox={"0 0 " + width + " 170"} className="h-44 w-full touch-pan-y select-none" role="img" aria-label={summary}
        onPointerLeave={() => setHoverIndex(null)}
        onPointerMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          if (rect.width > 0) setHoverIndex(nearestIndex((e.clientX - rect.left) / rect.width, points.length));
        }}>
        <Grid plot={plot} width={width} />
        {g.fireArea && <path d={g.fireArea} className="fill-thermal-3" fillOpacity={0.12} />}
        {g.baselinePath && <path d={g.baselinePath} fill="none" className="stroke-reference" strokeWidth={1} strokeDasharray="5 3" />}
        {g.accPath && <path d={g.accPath} fill="none" className="stroke-industrial" strokeWidth={1.75} strokeDasharray="4 2" />}
        {g.firePath && <path d={g.firePath} fill="none" className="stroke-thermal-3" strokeWidth={2} />}
        {g.events.map((ev) => <line key={ev.date} x1={ev.x} x2={ev.x} y1={plot.top + plot.height - 7} y2={plot.top + plot.height}
          stroke="currentColor" strokeWidth={2} />)}
        <AxisDates plot={plot} first={g.firstLabel} last={g.lastLabel} />
        {hovered && <g>
          <line x1={hovered.x} y1={plot.top} x2={hovered.x} y2={plot.top + plot.height} stroke="currentColor" strokeOpacity={0.4} strokeDasharray="2 2" />
          {hovered.yFire !== null && <circle cx={hovered.x} cy={hovered.yFire} r={4} className="fill-thermal-3 stroke-panel" strokeWidth={1.5} />}
          {hovered.yAcc !== null && <circle cx={hovered.x} cy={hovered.yAcc} r={3.5} className="fill-industrial stroke-panel" strokeWidth={1.5} />}
          {hovered.yBase !== null && <circle cx={hovered.x} cy={hovered.yBase} r={3} className="fill-reference stroke-panel" strokeWidth={1.5} />}
        </g>}
      </svg>
      {hovered && <div className="pointer-events-none absolute right-2 top-2 rounded-sm border border-rule bg-panel p-2 text-xs">
        <div className="tnum font-mono font-semibold text-ink">{hovered.date}</div>
        {[
          { key: "heat", label: "Non-persistent heat", value: hovered.wildfire, dot: "bg-thermal-3" },
          { key: "acc", label: "Persistent-source excursion", value: hovered.accident, dot: "bg-industrial" },
          { key: "base", label: "Seasonal baseline", value: hovered.baseline, dot: "bg-reference" },
        ].filter((row) => isFiniteNumber(row.value)).map((row) => <div key={row.key} className="mt-0.5 flex items-center justify-between gap-3 text-muted">
          <span className="flex items-center gap-1"><span className={"h-1.5 w-1.5 rounded-full " + row.dot} />{row.label}</span>
          <span className="tnum font-mono font-bold text-ink">{formatPct(row.value)}</span>
        </div>)}
        {hovered.observedEvent && <div className="mt-1 font-medium text-ink">Observed event day</div>}
      </div>}
    </div>
  </div>;
}

function OutlookStrip({ outlook }: { outlook: AIRiskAssessment["outlook_series"] }) {
  const g = buildOutlook(outlook);
  if (!g) return null;
  const width = 640;
  return <div className="mt-4">
    <p className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs font-medium text-ink">
      <span>{g.points.length}-day outlook</span>
      <span className="flex items-center gap-1.5"><Swatch kind="heat" />Forecast probability</span>
      <span className="flex items-center gap-1.5"><Swatch kind="baseline" />Seasonal baseline</span>
    </p>
    <div className="border border-rule bg-panel text-ink">
      <svg viewBox={"0 0 " + width + " 170"} className="h-36 w-full" role="img"
        aria-label={"Outlook from " + g.firstLabel + " to " + g.lastLabel + ": forecast probability against seasonal baseline"}>
        <Grid plot={g.plot} width={width} />
        {g.baselinePath && <path d={g.baselinePath} fill="none" className="stroke-reference" strokeWidth={1} strokeDasharray="5 3" />}
        <path d={g.probPath} fill="none" className="stroke-thermal-3" strokeWidth={2} />
        {g.points.map((p) => p.yProb !== null && <circle key={p.date} cx={p.x} cy={p.yProb} r={2.5} className="fill-thermal-3">
          <title>{p.date + ": " + formatPct(p.prob) + (p.baseline !== null ? " vs baseline " + formatPct(p.baseline) : "")}</title>
        </circle>)}
        <AxisDates plot={g.plot} first={g.firstLabel} last={g.lastLabel} />
      </svg>
    </div>
  </div>;
}

export function RiskPredictionPanel() {
  const response = useAnalysisStore((s) => s.riskResponse);
  const loading = useAnalysisStore((s) => s.isRiskLoading);
  const error = useAnalysisStore((s) => s.riskError);
  const fetchRisk = useAnalysisStore((s) => s.fetchRiskPredictionForAoi);
  const preset = useAnalysisStore((s) => s.selectedPreset);
  const forecastDate = useAnalysisStore(riskForecastDate);
  const analysis = useAnalysisStore((s) => s.analysisData);
  const [active, setActive] = useState<1 | 7 | 14>(1);
  useEffect(() => { void fetchRisk(forecastDate); }, [fetchRisk, forecastDate, analysis]);

  const assessment = response?.assessment?.as_of_date === forecastDate ? response.assessment : null;
  const horizon = assessment?.horizons.find((item) => item.days === active);
  const combined = assessment?.combined_risk_pct;
  const week = assessment?.horizons.find((item) => item.days === 7)?.combined_risk_pct;
  const severity = assessment ? hazardLevel(assessment) : null;
  const pill = observationPill(assessment?.observation);
  const signedDrivers = [...(assessment?.top_risk_factors ?? []), ...(assessment?.industrial_risk_factors ?? [])]
    .some((factor) => isFiniteNumber(factor.signed_impact_pct));
  const operational = assessment && (assessment.intensity || assessment.phenology || buildEscalation(assessment.horizons) ||
    persistencePhrase(assessment.markov_persistence) || assessment.horizon_explanation) ? [IntensityCard, PhenologyCard, EscalationCard] : [];
  const weights = Object.entries(assessment?.model_metrics.model_weights ?? {}).filter(([, value]) => isFiniteNumber(value));
  const points = assessment?.daily_probability_series.filter((point) =>
    isFiniteNumber(point.wildfire_prob_pct) || isFiniteNumber(point.accident_prob_pct)) ?? [];
  const diagnostics = horizon ? [
    { label: "Non-persistent heat", stats: horizon.wildfire_validation },
    { label: "Persistent-source excursion", stats: horizon.accident_validation },
    { label: "Either thermal event", stats: horizon.combined_validation },
  ].filter(({ stats }) => hasMetrics(stats)) : [];

  return <section aria-label="Risk AI forecast" className="@container space-y-5 text-ink">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-rule pb-4">
      <div>
        <h3 className="font-serif text-xl font-semibold">{preset === "CUSTOM" ? "Custom area" : PRESET_REGIONS[preset].label}</h3>
        <p className="mt-1 text-sm text-muted">Forecasts estimate satellite thermal signals. Confirmed fire and accident probabilities require incident records.</p>
      </div>
      {response && <span className="rounded-sm border border-rule px-2 py-1 text-xs text-muted">
        {response.data_source === "real" ? "Local FIRMS observations" : "Synthetic fixture"}
      </span>}
    </header>
    {loading && <p role="status" className="flex items-center gap-2 text-sm text-muted">
      <RefreshCw className="size-4 motion-safe:animate-spin" /> Calculating forecast for {forecastDate} UTC…
    </p>}
    {error && <div role="alert" className="border border-rule p-4 text-sm">
      <p>{error}</p>
      <button type="button" onClick={() => void fetchRisk()} className="mt-2 text-reference underline">Retry forecast</button>
    </div>}
    {response?.unavailable_reason && <p role="status" className="border border-rule bg-panel p-4 text-sm text-muted">
      {response.unavailable_reason}
    </p>}
    {assessment && horizon && <>
      <div className="grid gap-4 @3xl:grid-cols-[1.8fr_1fr]">
        {severity && isFiniteNumber(combined) && <div className="border border-rule bg-panel p-4">
          <p className="text-xs text-muted">Overall Hazard</p>
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2">
            <span className={"rounded-sm border px-2 py-1 text-xs font-semibold " + colors[severity]}>{severity}</span>
            <strong className="tnum font-serif text-3xl">{formatPct(combined)}</strong>
            {pill && <span className={"rounded-sm border px-2 py-1 text-xs " + (pill.warning
              ? "border-terracotta/50 bg-terracotta/10 text-terracotta" : "border-rule text-muted")}>
              <span className="sr-only">Observation status: </span>{pill.parts.map((part, i) => <span key={i} className="tnum">{i > 0 && " · "}{part}</span>)}
            </span>}
          </div>
          <p className="tnum mt-2 text-xs text-muted">24-hour combined likelihood{isFiniteNumber(week) && " · " + formatPct(week) + " over 7 days"}</p>
          <CommandEquation assessment={assessment} />
        </div>}
        <div className="border border-rule bg-panel p-4 text-sm">
          <p className="font-semibold">Forecast as of <time dateTime={assessment.as_of_date}>{assessment.as_of_date}</time> UTC</p>
          {assessment.last_observation_date && assessment.last_observation_date !== assessment.as_of_date &&
            <p className="mt-1 text-muted">Last cube record {assessment.last_observation_date} UTC. The longer the gap, the more the forecast relies on historical event rates.</p>}
          <p className="mt-2 text-muted">Non-persistent heat threshold {assessment.vegetation_event_threshold_mw.toLocaleString("en-US", { maximumFractionDigits: 2 })} MW</p>
          <p className="mt-1 text-muted">Persistent-source excursions exceed the past baseline by 2.5 standard deviations.</p>
        </div>
      </div>
      {operational.length > 0 && <div className="grid gap-4 @2xl:grid-cols-2 @5xl:grid-cols-3">
        {operational.map((Card, i) => <Card key={i} a={assessment} />)}
      </div>}
      <div role="group" aria-label="Forecast horizon" className="flex flex-wrap gap-1">
        {HORIZONS.map((days) => <button key={days} type="button" aria-pressed={active === days} onClick={() => setActive(days)}
          className="border border-rule px-3 py-2 text-xs font-medium transition-colors duration-150 aria-pressed:bg-ink aria-pressed:text-paper hover:border-reference">
          {horizonLabels[days]}
        </button>)}
      </div>
      <p className="text-xs text-muted">Forecast window {formatOffsetDate(assessment.as_of_date, 1)}
        {active > 1 && " to " + formatOffsetDate(assessment.as_of_date, active)} UTC
      </p>
      <section aria-label="Risk by forecast horizon" className="border border-rule bg-panel p-4">
        <h4 className="font-semibold">Risk across the three horizons</h4>
        <p className="mt-1 text-xs text-muted">Each bar shows the chance of at least one event within the window, on a shared 0–100% scale.</p>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          {assessment.horizons.map((item) => <div key={item.days}
            className={"min-w-0 rounded-sm border p-3 " + (item.days === active ? "border-reference" : "border-rule")}>
            <h5 className="text-sm font-semibold">{horizonLabels[item.days]}</h5>
            <div className="mt-3 space-y-3">{forecastTracks.map((track) => {
              const value = item[track.key];
              if (!isFiniteNumber(value)) return null;
              return <div key={track.key}>
                <div className="flex items-baseline justify-between gap-1 text-xs">
                  <span className="text-muted">{track.label}</span><strong className="tnum shrink-0 font-mono">{formatPct(value)}</strong>
                </div>
                <div className="mt-1 h-1.5 rounded-sm bg-rule/60" aria-hidden="true">
                  <div className={"h-full rounded-sm " + track.color} style={{ width: value + "%" }} />
                </div>
                {item.prior_targets?.includes(track.target) && <p className="mt-1 text-xs text-muted">Causal prior · limited examples</p>}
              </div>;
            })}</div>
          </div>)}
        </div>
      </section>
      {diagnostics.length > 0 && <section className="border-t border-rule pt-4 text-xs">
        <h4 className="mb-3 text-sm font-semibold">Held-out validation from {assessment.validation_start_date}</h4>
        <div className="grid gap-3 sm:grid-cols-3">
          {diagnostics.map(({ label, stats }) => <Validation key={label} label={label} stats={stats} />)}
        </div>
      </section>}
      {weights.length > 0 && <section className="border-t border-rule pt-4 text-xs">
        <h4 className="text-sm font-semibold">Ensemble Weights</h4>
        <p className="mt-1 text-muted">{weights[0][0] === "causal_prior"
          ? "24-hour non-persistent heat uses the causal prior."
          : "Signed calibration coefficients for 24-hour non-persistent heat."}</p>
        <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-2">
          {weights.map(([model, weight]) => <div key={model}><dt>{modelNames[model] ?? model}</dt>
            <dd className="font-mono font-semibold">{model === "causal_prior" ? formatPct(weight * 100) : weight.toFixed(3)}</dd></div>)}
        </dl>
      </section>}
      {points.length >= 2 && <section className="border border-rule bg-panel p-4">
        <h4 className="mb-3 flex items-center gap-2 text-sm font-semibold"><Activity className="size-4 text-reference" />
          Daily Probability Trajectory</h4>
        <ProbabilityTrajectoryChart series={points} />
        <OutlookStrip outlook={assessment.outlook_series} />
      </section>}
      {(assessment.top_risk_factors.length > 0 || assessment.industrial_risk_factors.length > 0) &&
        <section className="border-t border-rule pt-4 text-xs">
          <h4 className="mb-3 text-sm font-semibold">Top Physical Risk Drivers · 24 hours</h4>
          <p className="mb-3 text-muted">{signedDrivers
            ? "Bars show each factor's additive contribution to the 24-hour probability, in percentage points. Left lowers, right raises."
            : "Bars show the share of absolute log-odds contribution in the logistic model or causal prior. Left lowers, right raises."}</p>
          <div className="grid gap-4 sm:grid-cols-2">
            <Drivers title="Non-persistent heat" factors={assessment.top_risk_factors} />
            <Drivers title="Persistent-source excursion" factors={assessment.industrial_risk_factors} />
          </div>
        </section>}
      <details className="border-t border-rule pt-4 text-sm text-muted">
        <summary className="cursor-pointer font-semibold text-ink">What the model uses</summary>
        <p className="mt-2">The local FIRMS cube supplies reported fire radiative power (FRP), recent heat, neighboring activity, seasonal history and deviations at persistent sources. Features use records through the forecast date. Coverage gaps are treated as unknown.</p>
        <p className="mt-2">The 24-hour probability starts from a seasonal base-rate anchor: the historical event frequency for this area and time of year. A multi-year regime term and a short-term anomaly term (recent heat, neighboring activity, fuel exposure) are then added, so the three parts sum to the combined figure shown in the equation bar.</p>
        <p className="mt-2">Longer windows accumulate daily probabilities through a Markov persistence model: the persistence ρ measures how strongly one day's thermal state carries into the next. Each later day's probability relaxes from tomorrow's value toward the seasonal base rate, and only the share not already explained by persistence adds to the 7- and 14-day totals, so calm periods are not inflated by treating days as independent.</p>
        <p className="mt-2">Logistic regression, boosted stumps and Gaussian naive Bayes are fitted on earlier dates and calibrated before validation. For sparse data, a causal prior combines earlier event frequency with recent heat and seasonal signals. Driver bars use the additive decomposition of the 24-hour estimate.</p>
      </details>
    </>}
  </section>;
}
