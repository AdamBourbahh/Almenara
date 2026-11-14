import { useEffect, useMemo, useState } from "react";
import { fetchRiskPrediction } from "../../api/client";
import type { RiskFactor, RiskPredictionResponse, RiskValidation } from "../../api/types";
import { useAnalysisStore } from "../../store/useAnalysisStore";

const SEVERITY_COLORS = {
  LOW: "text-emerald-700 dark:text-emerald-300",
  MODERATE: "text-amber-700 dark:text-amber-300",
  HIGH: "text-orange-700 dark:text-orange-300",
  CRITICAL: "text-red-700 dark:text-red-300",
};
const HORIZON_LABELS = { 1: "Next 24 hours", 7: "Next 7 days", 14: "Next 14 days" };

function forecastDate(asOf: string, offset: number): string {
  const date = new Date(`${asOf}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + offset);
  return date.toISOString().slice(0, 10);
}

function percentage(value: number | null): string {
  if (value === null) return "Unavailable";
  if (value > 0 && value < 0.1) return "<0.1%";
  if (value < 100 && value > 99.9) return ">99.9%";
  return `${value.toFixed(1)}%`;
}

function Validation({ label, stats }: { label: string; stats: RiskValidation }) {
  return <div>
    <p className="font-medium text-ink">{label}</p>
    {stats.samples > 0 ? <p className="mt-1 text-muted">
      ROC-AUC {stats.roc_auc?.toFixed(3) ?? "—"} · Brier {stats.brier_score?.toFixed(3) ?? "—"}
      {" · "}{stats.positives}/{stats.samples} positive windows
    </p> : <p className="mt-1 text-muted">Insufficient historical examples</p>}
    {stats.reliability.length > 0 && <details className="mt-1 text-muted">
      <summary className="cursor-pointer">Calibration reliability</summary>
      <table className="mt-2 w-full text-left tabular-nums">
        <thead><tr><th>Predicted</th><th>Observed</th><th>Windows</th></tr></thead>
        <tbody>{stats.reliability.map((bin) => <tr key={bin.mean_predicted_pct}>
          <td>{percentage(bin.mean_predicted_pct)}</td><td>{percentage(bin.observed_pct)}</td><td>{bin.samples}</td>
        </tr>)}</tbody>
      </table>
    </details>}
  </div>;
}

function Drivers({ title, factors }: { title: string; factors: RiskFactor[] }) {
  if (factors.length === 0) return null;
  return <div>
    <h4 className="text-xs font-semibold text-ink">{title}</h4>
    <ul className="mt-2 space-y-2 text-xs text-muted">
      {factors.map((factor) => <li key={factor.feature} title={factor.description}>
        <p className="flex justify-between gap-2"><span>{factor.feature}</span>
          <span>{factor.direction} · {percentage(factor.impact_pct)}</span></p>
        <progress className="block h-2 w-full accent-[var(--color-reference)]" max={100}
          aria-label={`${factor.feature} share of driver magnitude`} value={factor.impact_pct} />
      </li>)}
    </ul>
  </div>;
}

export function FireRiskCard() {
  const aoi = useAnalysisStore((s) => s.currentAoi);
  const startYear = useAnalysisStore((s) => s.startYear);
  const endYear = useAnalysisStore((s) => s.endYear);
  const request = useMemo(() => ({ aoi, start_year: startYear, end_year: endYear }), [aoi, startYear, endYear]);
  const [state, setState] = useState<{ request: typeof request; data?: RiskPredictionResponse; error?: string }>();
  const [horizon, setHorizon] = useState<1 | 7 | 14>(1);

  useEffect(() => {
    const controller = new AbortController();
    fetchRiskPrediction(request, controller.signal).then((data) => {
      if (!controller.signal.aborted) setState({ request, data });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setState({
        request, error: error instanceof Error ? error.message : "Risk forecast unavailable.",
      });
    });
    return () => controller.abort();
  }, [request]);

  const current = state?.request === request ? state : undefined;
  const assessment = current?.data?.assessment;
  const selected = assessment?.horizons.find((item) => item.days === horizon);
  const level = assessment?.overall_hazard_level;
  return <section className="mb-6 border border-rule bg-panel p-5 sm:p-6" aria-labelledby="fire-risk-title">
    <h3 id="fire-risk-title" className="font-serif text-xl text-ink">Classical AI Fire &amp; Accident Risk Predictor</h3>
    <p className="mt-2 text-sm text-muted">
      Estimates are for satellite thermal signals. Confirmed ignition, spread and accident probabilities require independent incident records.
    </p>
    {!current && <p role="status" className="mt-4 text-sm text-muted">Calculating local forecast…</p>}
    {current?.error && <p role="alert" className="mt-4 text-sm text-bias">{current.error}</p>}
    {current?.data?.unavailable_reason && <p role="status" className="mt-4 text-sm text-muted">
      {current.data.unavailable_reason}{current.data.data_source === "synthetic" && " Synthetic fixture."}
    </p>}
    {assessment && selected && <>
      <p className="mt-3 text-xs text-muted">As of {assessment.as_of_date} UTC · {
        current.data?.data_source === "real" ? "Local FIRMS observations" : "Synthetic demonstration"
      }</p>
      <div className="mt-4 flex flex-wrap gap-1" role="group" aria-label="Forecast horizon">
        {([1, 7, 14] as const).map((days) => <button type="button" key={days} aria-pressed={horizon === days}
          onClick={() => setHorizon(days)} className="border border-rule px-3 py-2 text-xs aria-pressed:bg-ink aria-pressed:text-paper">
          {HORIZON_LABELS[days]}
        </button>)}
      </div>
      <p className="mt-2 text-xs text-muted">
        Forecast dates {forecastDate(assessment.as_of_date, 1)}
        {horizon > 1 && ` to ${forecastDate(assessment.as_of_date, horizon)}`} UTC
      </p>
      <dl className="mt-4 grid gap-3 sm:grid-cols-3" aria-live="polite">
        <div className="border border-rule p-3"><dt className="text-xs text-muted">High non-persistent heat</dt>
          <dd className="mt-1 font-serif text-xl text-ink">{percentage(selected.wildfire_prob_pct)}</dd></div>
        <div className="border border-rule p-3"><dt className="text-xs text-muted">Unusual heat at persistent sources</dt>
          <dd className="mt-1 font-serif text-xl text-ink">{percentage(selected.accident_prob_pct)}</dd></div>
        <div className="border border-rule p-3"><dt className="text-xs text-muted">Either thermal event</dt>
          <dd className="mt-1 font-serif text-xl text-ink">{percentage(selected.combined_risk_pct)}</dd>
          {horizon === 1 && level && <dd className={`text-xs font-semibold ${SEVERITY_COLORS[level]}`}>{level} proxy likelihood</dd>}
        </div>
      </dl>
      <p className="mt-3 text-xs text-muted">
        High heat means daily summed FRP of at least {assessment.vegetation_event_threshold_mw.toLocaleString("en-US", {
          maximumFractionDigits: 1,
        })} MW in non-persistent cells. Excursions are measured against each persistent cell’s past baseline.
        A day with no reported detection can still have unobserved activity.
      </p>
      <div className="mt-4 border-t border-rule pt-3 text-xs">
        <h4 className="mb-2 font-semibold text-ink">Held-out validation from {assessment.validation_start_date}</h4>
        <div className="grid gap-3 sm:grid-cols-3">
          <Validation label="High heat" stats={selected.wildfire_validation} />
          <Validation label="Persistent-source excursion" stats={selected.accident_validation} />
          <Validation label="Either event" stats={selected.combined_validation} />
        </div>
      </div>
      {(assessment.top_risk_factors.length > 0 || assessment.industrial_risk_factors.length > 0) && <div className="mt-4 border-t border-rule pt-3">
        <p className="mb-2 text-xs text-muted">24-hour drivers · share of absolute logistic log-odds contribution</p>
        <div className="grid gap-4 sm:grid-cols-2">
          <Drivers title="High non-persistent heat" factors={assessment.top_risk_factors} />
          <Drivers title="Persistent-source excursion" factors={assessment.industrial_risk_factors} />
        </div>
      </div>}
    </>}
  </section>;
}
