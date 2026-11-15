/** Pure presentation helpers for the risk panel. No React, DOM or icon imports so they run under `node --test`. */
import type { AIRiskAssessment, RiskFactor, RiskHorizon, RiskObservationStatus, RiskOutlookPoint } from "../../api/types";

export const NOT_AVAILABLE = "not available";
const MINUS = "−";

export type HazardLevel = "LOW" | "MODERATE" | "HIGH" | "CRITICAL";

export function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Rounds to one decimal and never yields "-0.0". */
function oneDecimal(value: number): string {
  const text = value.toFixed(1);
  return text === "-0.0" ? "0.0" : text;
}

export function formatPct(value: number | null | undefined): string {
  if (!isFiniteNumber(value)) return NOT_AVAILABLE;
  if (value > 0 && value < 0.1) return "<0.1%";
  if (value < 100 && value > 99.9) return ">99.9%";
  return oneDecimal(value) + "%";
}

/** Explicit sign with a real minus; values that round to zero carry no sign. */
export function formatSignedPct(value: number | null | undefined): string {
  if (!isFiniteNumber(value)) return NOT_AVAILABLE;
  const text = oneDecimal(Math.abs(value));
  if (text === "0.0") return "0.0%";
  return (value > 0 ? "+" : MINUS) + text + "%";
}

export function formatMultiplier(value: number | null | undefined): string {
  return isFiniteNumber(value) ? oneDecimal(value) + "×" : NOT_AVAILABLE;
}

export function formatMw(value: number | null | undefined): string {
  return isFiniteNumber(value) ? oneDecimal(value) + " MW" : NOT_AVAILABLE;
}

export function formatTonnes(value: number | null | undefined): string {
  return isFiniteNumber(value)
    ? value.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + " t" : NOT_AVAILABLE;
}

export function diurnalPhrase(ratio: number | null | undefined): string {
  return isFiniteNumber(ratio) ? "×" + oneDecimal(ratio) + " afternoon ramp (13:30 / 10:30)" : NOT_AVAILABLE;
}

export function persistencePhrase(rho: number | null | undefined): string | null {
  return isFiniteNumber(rho) ? "persistence ρ = " + rho.toFixed(2) : null;
}

export function hazardLevel(a: Pick<AIRiskAssessment, "overall_hazard_level" | "combined_risk_pct">): HazardLevel | null {
  if (a.overall_hazard_level) return a.overall_hazard_level;
  const c = a.combined_risk_pct;
  if (!isFiniteNumber(c)) return null;
  return c < 20 ? "LOW" : c < 50 ? "MODERATE" : c < 75 ? "HIGH" : "CRITICAL";
}

export interface EquationModel {
  terms: { key: "baseline" | "regime" | "surge"; label: string; value: number; text: string }[];
  total: { text: string; multiplier: string | null };
  /** total minus the sum of the three terms (percentage points). */
  residual: number;
  /** True when the terms add up to the total within display rounding. */
  closes: boolean;
}

export function buildEquation(a: Pick<AIRiskAssessment, "baseline_climatology_pct" | "multi_year_trend_delta_pct" |
  "short_term_anomaly_delta_pct" | "combined_risk_pct" | "anomaly_multiplier">): EquationModel | null {
  const { baseline_climatology_pct: b, multi_year_trend_delta_pct: r, short_term_anomaly_delta_pct: s, combined_risk_pct: total } = a;
  if (!isFiniteNumber(b) || !isFiniteNumber(r) || !isFiniteNumber(s) || !isFiniteNumber(total)) return null;
  const residual = total - (b + r + s);
  return {
    terms: [
      { key: "baseline", label: "Baseline climatology", value: b, text: formatPct(b) },
      { key: "regime", label: "Decadal regime shift", value: r, text: formatSignedPct(r) },
      { key: "surge", label: "Tactical & contagion surge", value: s, text: formatSignedPct(s) },
    ],
    total: {
      text: formatPct(total),
      multiplier: isFiniteNumber(a.anomaly_multiplier) ? formatMultiplier(a.anomaly_multiplier) + " seasonal norm" : null,
    },
    residual,
    closes: Math.abs(residual) <= 0.15,
  };
}

export interface ObservationPillModel { warning: boolean; parts: string[] }

export function observationPill(obs: RiskObservationStatus | null | undefined): ObservationPillModel | null {
  if (!obs || !obs.status) return null;
  const parts = [obs.status];
  if (isFiniteNumber(obs.uncertainty_pct)) parts.push(oneDecimal(obs.uncertainty_pct) + "% of the last 7 days unobserved");
  if (isFiniteNumber(obs.days_since_observation) && obs.days_since_observation > 0) {
    parts.push("last observation " + Math.round(obs.days_since_observation) + " d ago");
  }
  return { warning: !obs.coverage_nominal, parts };
}

function plural(n: number, unit: string): string {
  return n + " " + unit + (n === 1 ? "" : "s");
}

/** Positive `daysToPeak` means the peak is still ahead. */
export function peakPhrase(daysToPeak: number | null | undefined, label?: string | null): string {
  if (!isFiniteNumber(daysToPeak)) return NOT_AVAILABLE;
  const days = Math.round(daysToPeak);
  const text = days === 0 ? "At seasonal peak" : plural(Math.abs(days), "day") + (days > 0 ? " before peak" : " after peak");
  return label ? text + " · " + label : text;
}

export function driftPhrase(daysPerDecade: number | null | undefined): string {
  if (!isFiniteNumber(daysPerDecade)) return NOT_AVAILABLE;
  const text = oneDecimal(Math.abs(daysPerDecade));
  const sign = text === "0.0" ? "" : daysPerDecade > 0 ? "+" : MINUS;
  return sign + text + " days/decade";
}

export interface DriverBar {
  feature: string;
  description: string;
  label: string;
  tone: "raises" | "lowers";
  side: "left" | "right";
  /** Share of the half-track (0-100) the bar fills. */
  widthPct: number;
  observed: string | null;
}

export function driverBars(factors: RiskFactor[]): DriverBar[] {
  const valid = factors.filter((f) => f.feature && isFiniteNumber(f.impact_pct));
  const signedMode = valid.length > 0 && valid.every((f) => isFiniteNumber(f.signed_impact_pct));
  const values = valid.map((f) => signedMode ? f.signed_impact_pct as number : (f.direction === "raises" ? 1 : -1) * f.impact_pct);
  const max = signedMode ? Math.max(...values.map(Math.abs)) : 100;
  return valid.map((f, i) => {
    const v = values[i];
    const raises = signedMode ? v > 0 || (v === 0 && f.direction === "raises") : f.direction === "raises";
    return {
      feature: f.feature,
      description: f.description,
      label: signedMode ? formatSignedPct(v) : (raises ? "Raises" : "Lowers") + " · " + formatPct(f.impact_pct),
      tone: raises ? "raises" : "lowers",
      side: raises ? "right" : "left",
      widthPct: max > 0 ? Math.min(100, (Math.abs(v) / max) * 100) : 0,
      observed: isFiniteNumber(f.observed_value)
        ? oneDecimal(f.observed_value) + (f.unit ? " " + f.unit : "") : null,
    };
  });
}

/* ---------- chart geometry ---------- */

const clampPct = (v: number) => Math.min(100, Math.max(0, v));

function linePath(pts: { x: number; y: number | null }[]): string {
  let out = "";
  let open = false;
  for (const p of pts) {
    if (p.y === null) { open = false; continue; }
    out += (open ? " L " : (out ? " M " : "M ")) + p.x.toFixed(1) + " " + p.y.toFixed(1);
    open = true;
  }
  return out;
}

export const CHART = { width: 640, height: 170, top: 14, right: 14, bottom: 30, left: 36 };
const plotBox = { left: CHART.left, top: CHART.top, width: CHART.width - CHART.left - CHART.right, height: CHART.height - CHART.top - CHART.bottom };
export type PlotBox = typeof plotBox;
const yOf = (v: number | null | undefined): number | null =>
  isFiniteNumber(v) ? plotBox.top + plotBox.height - (clampPct(v) / 100) * plotBox.height : null;

export interface TrajectoryPoint {
  date: string; x: number;
  wildfire: number | null; accident: number | null; baseline: number | null; observedEvent: boolean;
  yFire: number | null; yAcc: number | null; yBase: number | null;
}
export interface TrajectoryGeometry {
  plot: PlotBox; points: TrajectoryPoint[];
  firePath: string; accPath: string; baselinePath: string; fireArea: string;
  events: { date: string; x: number }[];
  firstLabel: string; lastLabel: string; hasBaseline: boolean;
}
type SeriesRow = AIRiskAssessment["daily_probability_series"][number];

export function buildTrajectory(series: SeriesRow[]): TrajectoryGeometry | null {
  if (series.length < 2) return null;
  const points: TrajectoryPoint[] = series.map((s, i) => {
    const num = (v: number | null | undefined) => isFiniteNumber(v) ? v : null;
    return {
      date: s.date, x: plotBox.left + (i / (series.length - 1)) * plotBox.width,
      wildfire: num(s.wildfire_prob_pct), accident: num(s.accident_prob_pct), baseline: num(s.baseline_prob_pct),
      observedEvent: s.observed_event === true,
      yFire: yOf(s.wildfire_prob_pct), yAcc: yOf(s.accident_prob_pct), yBase: yOf(s.baseline_prob_pct),
    };
  });
  const firePath = linePath(points.map((p) => ({ x: p.x, y: p.yFire })));
  const fireRun = points.filter((p) => p.yFire !== null);
  const floor = plotBox.top + plotBox.height;
  const fireArea = fireRun.length > 1
    ? linePath(fireRun.map((p) => ({ x: p.x, y: p.yFire }))) + ` L ${fireRun[fireRun.length - 1].x.toFixed(1)} ${floor.toFixed(1)} L ${fireRun[0].x.toFixed(1)} ${floor.toFixed(1)} Z` : "";
  const baselinePath = linePath(points.map((p) => ({ x: p.x, y: p.yBase })));
  return {
    plot: plotBox, points, firePath, fireArea, baselinePath,
    accPath: linePath(points.map((p) => ({ x: p.x, y: p.yAcc }))),
    events: points.filter((p) => p.observedEvent).map((p) => ({ date: p.date, x: p.x })),
    firstLabel: series[0].date, lastLabel: series[series.length - 1].date, hasBaseline: baselinePath !== "",
  };
}

export function nearestIndex(relativeX: number, count: number): number {
  if (count <= 1) return 0;
  return Math.min(count - 1, Math.max(0, Math.round(relativeX * (count - 1))));
}

export interface OutlookGeometry {
  plot: PlotBox;
  points: { date: string; x: number; prob: number | null; baseline: number | null; yProb: number | null; yBase: number | null }[];
  probPath: string; baselinePath: string; firstLabel: string; lastLabel: string;
}

export function buildOutlook(outlook: RiskOutlookPoint[] | null | undefined): OutlookGeometry | null {
  if (!outlook || outlook.length < 2 || !outlook.some((p) => isFiniteNumber(p.prob_pct))) return null;
  const points = outlook.map((p, i) => ({
    date: p.date, x: plotBox.left + (i / (outlook.length - 1)) * plotBox.width,
    prob: isFiniteNumber(p.prob_pct) ? p.prob_pct : null, baseline: isFiniteNumber(p.baseline_prob_pct) ? p.baseline_prob_pct : null,
    yProb: yOf(p.prob_pct), yBase: yOf(p.baseline_prob_pct),
  }));
  return {
    plot: plotBox, points,
    probPath: linePath(points.map((p) => ({ x: p.x, y: p.yProb }))),
    baselinePath: linePath(points.map((p) => ({ x: p.x, y: p.yBase }))),
    firstLabel: outlook[0].date, lastLabel: outlook[outlook.length - 1].date,
  };
}

export const ESCALATION = { width: 220, height: 84, padX: 26, top: 22, bottom: 20 };
const horizonLabel: Record<number, string> = { 1: "24h", 7: "7d", 14: "14d" };

export interface EscalationGeometry {
  points: { days: number; label: string; value: number; text: string; x: number; y: number }[];
  path: string;
}

/** Combined risk across horizons on a 0-100 scale; null with fewer than two numeric horizons. */
export function buildEscalation(horizons: RiskHorizon[]): EscalationGeometry | null {
  const usable = horizons.filter((h) => isFiniteNumber(h.combined_risk_pct));
  if (usable.length < 2) return null;
  const innerW = ESCALATION.width - ESCALATION.padX * 2;
  const innerH = ESCALATION.height - ESCALATION.top - ESCALATION.bottom;
  const points = usable.map((h, i) => {
    const value = h.combined_risk_pct as number;
    return {
      days: h.days, label: horizonLabel[h.days] ?? h.days + "d", value, text: formatPct(value),
      x: ESCALATION.padX + (i / (usable.length - 1)) * innerW,
      y: ESCALATION.top + innerH - (clampPct(value) / 100) * innerH,
    };
  });
  return { points, path: linePath(points) };
}
