import { useEffect, useState } from "react";
import { Activity, RefreshCw } from "lucide-react";
import type { RiskFactor, RiskValidation } from "../../api/types";
import { PRESET_REGIONS, riskForecastDate, useAnalysisStore } from "../../store/useAnalysisStore";

const HORIZONS = [1, 7, 14] as const;
const horizonLabels = { 1: "24-Hour", 7: "7-Day", 14: "14-Day" };
const colors = {
  LOW: "border-emerald-600/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  MODERATE: "border-amber-600/40 bg-amber-500/10 text-amber-800 dark:text-amber-300",
  HIGH: "border-orange-600/40 bg-orange-500/10 text-orange-800 dark:text-orange-300",
  CRITICAL: "border-red-600/40 bg-red-500/10 text-red-700 dark:text-red-300",
};
const modelNames: Record<string, string> = {
  logistic: "L2 logistic",
  boosted_stumps: "Boosted stumps",
  gaussian_naive_bayes: "Gaussian naive Bayes",
  causal_prior: "Causal prior",
};
const forecastTracks = [
  { label: "High heat in non-persistent cells", key: "wildfire_prob_pct", target: "wildfire", color: "bg-orange-500" },
  { label: "Excursion in persistent cells", key: "accident_prob_pct", target: "accident", color: "bg-violet-500" },
  { label: "Either thermal event", key: "combined_risk_pct", target: "combined", color: "bg-blue-500" },
] as const;

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function formatPct(value: number): string {
  if (value > 0 && value < 0.1) return "<0.1%";
  if (value < 100 && value > 99.9) return ">99.9%";
  return value.toFixed(1) + "%";
}

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
      {isFiniteNumber(stats.roc_auc) && <div><dt>ROC-AUC</dt><dd className="font-mono font-semibold">{stats.roc_auc.toFixed(3)}</dd></div>}
      {isFiniteNumber(stats.brier_score) && <div><dt>Brier score</dt><dd className="font-mono font-semibold">{stats.brier_score.toFixed(3)}</dd></div>}
    </dl>
    {bins.length > 0 && <details className="mt-2 text-muted">
      <summary className="cursor-pointer">Calibration reliability</summary>
      <table className="mt-2 w-full text-left tabular-nums">
        <thead><tr><th>Predicted</th><th>Observed</th><th>Windows</th></tr></thead>
        <tbody>{bins.map((bin, i) => <tr key={i}>
          <td>{formatPct(bin.mean_predicted_pct)}</td><td>{formatPct(bin.observed_pct)}</td><td>{bin.samples}</td>
        </tr>)}</tbody>
      </table>
    </details>}
  </div>;
}

function Drivers({ title, factors }: { title: string; factors: RiskFactor[] }) {
  const valid = factors.filter((factor) => factor.feature && isFiniteNumber(factor.impact_pct));
  if (!valid.length) return null;
  return <section className="min-w-0">
    <h5 className="font-semibold text-ink">{title}</h5>
    <ul className="mt-3 space-y-3">
      {valid.map((factor) => <li key={factor.feature} title={factor.description}>
        <p className="flex flex-wrap justify-between gap-1"><span>{factor.feature}</span>
          <span className="text-muted">{factor.direction === "raises" ? "Raises" : "Lowers"} · {formatPct(factor.impact_pct)}</span></p>
        <div className="relative mt-1.5 h-2 rounded-sm bg-rule/60" aria-hidden="true">
          <span className="absolute inset-y-0 left-1/2 border-l border-muted" />
          <span className={"absolute inset-y-0 " + (factor.direction === "raises" ? "left-1/2 bg-orange-500" : "right-1/2 bg-blue-500")}
            style={{ width: (factor.impact_pct / 2) + "%" }} />
        </div>
        <p className="mt-1 leading-relaxed text-muted">{factor.description}</p>
      </li>)}
    </ul>
  </section>;
}
function ProbabilityTrajectoryChart({
  series
}: {
  series: { date: string; wildfire_prob_pct: number | null; accident_prob_pct: number | null }[];
}) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  if (series.length < 2) return null;

  const width = 640;
  const height = 160;
  const padding = { top: 15, right: 15, bottom: 25, left: 35 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  const validPoints = series.map((s, idx) => ({
    ...s,
    x: padding.left + (idx / (series.length - 1)) * chartW,
    yFire:
      isFiniteNumber(s.wildfire_prob_pct)
        ? padding.top + chartH - (Math.min(100, Math.max(0, s.wildfire_prob_pct)) / 100) * chartH
        : null,
    yAcc:
      isFiniteNumber(s.accident_prob_pct)
        ? padding.top + chartH - (Math.min(100, Math.max(0, s.accident_prob_pct)) / 100) * chartH
        : null
  }));

  const firePoints = validPoints.filter((p): p is typeof p & { yFire: number } => p.yFire !== null);
  const accPoints = validPoints.filter((p): p is typeof p & { yAcc: number } => p.yAcc !== null);

  const fireLine = firePoints.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.yFire.toFixed(1)}`).join(" ");
  const accLine = accPoints.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.yAcc.toFixed(1)}`).join(" ");

  const fireArea =
    firePoints.length > 0
      ? `${fireLine} L ${firePoints[firePoints.length - 1].x.toFixed(1)} ${(padding.top + chartH).toFixed(1)} L ${firePoints[0].x.toFixed(1)} ${(padding.top + chartH).toFixed(1)} Z`
      : "";

  const hoveredPoint = hoverIndex !== null && hoverIndex >= 0 && hoverIndex < validPoints.length ? validPoints[hoverIndex] : null;

  return (
    <div className="relative">
      <div className="mb-2 flex items-center justify-between text-xs">
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1.5 font-medium text-ink">
            <span className="inline-block h-2 w-2 rounded-full bg-[#e6550d]" />
            Non-persistent heat Risk (24h)
          </span>
          <span className="flex items-center gap-1.5 font-medium text-ink">
            <span className="inline-block h-2 w-2 rounded-full bg-[#6a3d9a]" />
            Persistent-source excursion
          </span>
        </div>
        <span className="text-[11px] text-faint">
          {series[0]?.date} → {series[series.length - 1]?.date}
        </span>
      </div>

      <div className="relative border border-rule bg-panel overflow-hidden">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="h-44 w-full touch-none select-none"
          onPointerLeave={() => setHoverIndex(null)}
          onPointerMove={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const relX = (e.clientX - rect.left) / rect.width;
            const targetIdx = Math.round(relX * (validPoints.length - 1));
            if (targetIdx >= 0 && targetIdx < validPoints.length) {
              setHoverIndex(targetIdx);
            }
          }}
        >
          {/* Horizontal grid lines */}
          {[0, 25, 50, 75, 100].map((pct) => {
            const y = padding.top + chartH - (pct / 100) * chartH;
            return (
              <g key={pct}>
                <line
                  x1={padding.left}
                  y1={y}
                  x2={width - padding.right}
                  y2={y}
                  stroke="currentColor"
                  strokeOpacity={pct === 50 ? 0.25 : 0.12}
                  strokeDasharray={pct === 50 ? "4 4" : undefined}
                />
                <text
                  x={padding.left - 6}
                  y={y + 3}
                  textAnchor="end"
                  fontSize="9"
                  fill="currentColor"
                  opacity={0.5}
                  className="font-mono"
                >
                  {pct}%
                </text>
              </g>
            );
          })}

          {/* Area under wildfire curve */}
          {fireArea && <path d={fireArea} fill="#e6550d" fillOpacity={0.12} />}

          {/* Lines */}
          {accLine && (
            <path
              d={accLine}
              fill="none"
              stroke="#6a3d9a"
              strokeWidth={1.75}
              strokeDasharray="4 2"
            />
          )}
          {fireLine && (
            <path
              d={fireLine}
              fill="none"
              stroke="#e6550d"
              strokeWidth={2}
            />
          )}

          {/* Hover indicator */}
          {hoveredPoint && (
            <g>
              <line
                x1={hoveredPoint.x}
                y1={padding.top}
                x2={hoveredPoint.x}
                y2={padding.top + chartH}
                stroke="currentColor"
                strokeOpacity={0.4}
                strokeWidth={1}
                strokeDasharray="2 2"
              />
              {hoveredPoint.yFire !== null && (
                <circle cx={hoveredPoint.x} cy={hoveredPoint.yFire} r={4} fill="#e6550d" stroke="#ffffff" strokeWidth={1.5} />
              )}
              {hoveredPoint.yAcc !== null && (
                <circle cx={hoveredPoint.x} cy={hoveredPoint.yAcc} r={3.5} fill="#6a3d9a" stroke="#ffffff" strokeWidth={1.5} />
              )}
            </g>
          )}
        </svg>

        {/* Floating tooltip on hover */}
        {hoveredPoint && (
          <div
            className="pointer-events-none absolute top-2 right-2 rounded border border-rule bg-panel/95 p-2 shadow-sm backdrop-blur text-xs"
          >
            <div className="font-mono font-semibold text-ink">{hoveredPoint.date}</div>
            {isFiniteNumber(hoveredPoint.wildfire_prob_pct) && <div className="mt-1 flex items-center justify-between gap-3 text-muted">
              <span className="flex items-center gap-1">
                <span className="h-1.5 w-1.5 rounded-full bg-[#e6550d]" />
                Non-persistent heat:
              </span>
              <span className="font-mono font-bold text-ink">{formatPct(hoveredPoint.wildfire_prob_pct)}</span>
            </div>}
            {isFiniteNumber(hoveredPoint.accident_prob_pct) && <div className="mt-0.5 flex items-center justify-between gap-3 text-muted">
              <span className="flex items-center gap-1">
                <span className="h-1.5 w-1.5 rounded-full bg-[#6a3d9a]" />
                Persistent-source excursion:
              </span>
              <span className="font-mono font-bold text-ink">{formatPct(hoveredPoint.accident_prob_pct)}</span>
            </div>}
          </div>
        )}
      </div>
    </div>
  );
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
  const severity = assessment?.overall_hazard_level ?? (isFiniteNumber(combined)
    ? combined < 20 ? "LOW" : combined < 50 ? "MODERATE" : combined < 75 ? "HIGH" : "CRITICAL"
    : null);
  const weights = Object.entries(assessment?.model_metrics.model_weights ?? {}).filter(([, value]) => isFiniteNumber(value));
  const points = assessment?.daily_probability_series.filter((point) =>
    isFiniteNumber(point.wildfire_prob_pct) || isFiniteNumber(point.accident_prob_pct)) ?? [];
  const diagnostics = horizon ? [
    { label: "Non-persistent heat", stats: horizon.wildfire_validation },
    { label: "Persistent-source excursion", stats: horizon.accident_validation },
    { label: "Either thermal event", stats: horizon.combined_validation },
  ].filter(({ stats }) => hasMetrics(stats)) : [];

  return <section aria-label="Risk AI forecast" className="space-y-5 text-ink">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-rule pb-4">
      <div>
        <h3 className="font-serif text-xl font-semibold">{preset === "CUSTOM" ? "Custom area" : PRESET_REGIONS[preset].label}</h3>
        <p className="mt-1 text-sm text-muted">Forecasts estimate satellite thermal signals. Confirmed fire and accident probabilities require incident records.</p>
      </div>
      {response && <span className="rounded border border-rule px-2 py-1 text-xs text-muted">
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
      <div className="grid gap-4 sm:grid-cols-[1fr_1.5fr]">
        {severity && isFiniteNumber(combined) && <div className="border border-rule bg-panel p-4">
          <p className="text-xs text-muted">Overall Hazard</p>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <span className={"rounded border px-2 py-1 text-xs font-semibold " + colors[severity]}>{severity}</span>
            <strong className="font-serif text-3xl">{formatPct(combined)}</strong>
          </div>
          <p className="mt-2 text-xs text-muted">24-hour combined likelihood{isFiniteNumber(week) && " · " + formatPct(week) + " over 7 days"}</p>
        </div>}
        <div className="border border-rule bg-panel p-4 text-sm">
          <p className="font-semibold">Forecast as of <time dateTime={assessment.as_of_date}>{assessment.as_of_date}</time> UTC</p>
          {assessment.last_observation_date && assessment.last_observation_date !== assessment.as_of_date &&
            <p className="mt-1 text-muted">Last cube record {assessment.last_observation_date} UTC. The longer the gap, the more the forecast relies on historical event rates.</p>}
          <p className="mt-2 text-muted">Non-persistent heat threshold {assessment.vegetation_event_threshold_mw.toLocaleString("en-US", { maximumFractionDigits: 2 })} MW</p>
          <p className="mt-1 text-muted">Persistent-source excursions exceed the past baseline by 2.5 standard deviations.</p>
        </div>
      </div>
      <div role="group" aria-label="Forecast horizon" className="flex flex-wrap gap-1">
        {HORIZONS.map((days) => <button key={days} type="button" aria-pressed={active === days} onClick={() => setActive(days)}
          className="border border-rule px-3 py-2 text-xs font-medium aria-pressed:bg-ink aria-pressed:text-paper hover:border-reference">
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
            className={"min-w-0 rounded border p-3 " + (item.days === active ? "border-reference" : "border-rule")}>
            <h5 className="text-sm font-semibold">{horizonLabels[item.days]}</h5>
            <div className="mt-3 space-y-3">{forecastTracks.map((track) => {
              const value = item[track.key];
              if (!isFiniteNumber(value)) return null;
              return <div key={track.key}>
                <div className="flex items-baseline justify-between gap-1 text-xs">
                  <span className="text-muted">{track.label}</span><strong className="shrink-0 font-mono">{formatPct(value)}</strong>
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
      </section>}
      {(assessment.top_risk_factors.length > 0 || assessment.industrial_risk_factors.length > 0) &&
        <section className="border-t border-rule pt-4 text-xs">
          <h4 className="mb-3 text-sm font-semibold">Top Physical Risk Drivers · 24 hours</h4>
          <p className="mb-3 text-muted">Bars show the share of absolute log-odds contribution in the logistic model or causal prior. Left lowers, right raises.</p>
          <div className="grid gap-4 sm:grid-cols-2">
            <Drivers title="Non-persistent heat" factors={assessment.top_risk_factors} />
            <Drivers title="Persistent-source excursion" factors={assessment.industrial_risk_factors} />
          </div>
        </section>}
      <details className="border-t border-rule pt-4 text-sm text-muted">
        <summary className="cursor-pointer font-semibold text-ink">What the model uses</summary>
        <p className="mt-2">The local FIRMS cube supplies reported fire radiative power (FRP), recent heat, neighboring activity, seasonal history and deviations at persistent sources. Features use records through the forecast date. Coverage gaps are treated as unknown.</p>
        <p className="mt-2">Logistic regression, boosted stumps and Gaussian naive Bayes are fitted on earlier dates and calibrated before validation. For sparse data, a causal prior combines earlier event frequency with recent heat and seasonal signals.</p>
      </details>
    </>}
  </section>;
}
