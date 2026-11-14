import type { ReactNode } from "react";
import {
  Activity,
  CheckCircle2,
  Download,
  Flame,
  Gauge,
  ShieldCheck,
  TrendingUp,
  Wind,
} from "lucide-react";
import { useAnalysisStore } from "../../store/useAnalysisStore";
import type { AnalyzeResponse } from "../../api/types";

/**
 * Live statistical peer-review panel.
 *
 * A single executive verdict banner and five data-driven audit cards whose state
 * flips between the RAW (2012 artifact) and HARMONIZED (RTS Kalman physics) regimes.
 * The CSV exporter is self-contained so the panel does not depend on any external
 * network call for the deliverable download.
 */

type Severity = "ok" | "warn" | "bad" | "info";

const SEVERITY_TEXT: Record<Severity, string> = {
  ok: "text-emerald-400",
  warn: "text-amber-400",
  bad: "text-red-400",
  info: "text-sky-400",
};

const SEVERITY_PILL: Record<Severity, string> = {
  ok: "border-emerald-700/60 bg-emerald-500/10 text-emerald-300",
  warn: "border-amber-700/60 bg-amber-500/10 text-amber-300",
  bad: "border-red-700/60 bg-red-500/10 text-red-300",
  info: "border-sky-700/60 bg-sky-500/10 text-sky-300",
};

function formatP(p: number): string {
  if (!Number.isFinite(p)) return "n/a";
  if (p <= 0) return "< 1e-300";
  if (p < 1e-4) return `= ${p.toExponential(1)}`;
  return `= ${p.toFixed(3)}`;
}

function formatNumber(value: number, digits = 1): string {
  if (!Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function csvCell(value: unknown): string {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function downloadIpccCsv(data: AnalyzeResponse): void {
  const headers = [
    "date",
    "year",
    "doy",
    "raw_hotspot_count",
    "raw_frp_mw",
    "harmonized_fre_mj_km2",
    "historical_cross_prior_fre",
    "ci_95_lower",
    "ci_95_upper",
    "uncertainty_pct",
    "biomass_burned_tonnes",
    "pm25_emitted_kg",
    "z_score_anomaly",
    "is_gap_filled",
    "is_forecast",
    "gap_reason",
    "active_sensors",
    "tooltip_narrative",
  ];

  const rows = [...data.calendar_series, ...data.forecast_series].map((cell) =>
    [
      cell.date,
      cell.year,
      cell.doy,
      cell.raw_hotspot_count,
      cell.raw_frp_mw,
      cell.harmonized_fre_mj_km2,
      cell.historical_cross_prior_fre,
      cell.ci_95_lower,
      cell.ci_95_upper,
      cell.uncertainty_pct,
      cell.biomass_burned_tonnes,
      cell.pm25_emitted_kg,
      cell.z_score_anomaly,
      cell.is_gap_filled,
      cell.is_forecast,
      cell.gap_reason ?? "",
      cell.active_sensors.join("|"),
      cell.tooltip_narrative,
    ]
      .map(csvCell)
      .join(","),
  );

  const csv = [headers.join(","), ...rows].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `firms_harmonizer_ipcc_${data.query_hash.slice(0, 8)}.csv`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

function StatusPill({
  severity,
  children,
}: {
  severity: Severity;
  children: ReactNode;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wide ${SEVERITY_PILL[severity]}`}
    >
      {children}
    </span>
  );
}

function MetricCard({
  icon,
  title,
  subtitle,
  value,
  unit,
  detail,
  severity,
  statusText,
}: {
  icon: ReactNode;
  title: string;
  subtitle: string;
  value: string;
  unit?: string;
  detail: ReactNode;
  severity: Severity;
  statusText: string;
}) {
  return (
    <article className="flex flex-col rounded-2xl border border-line bg-base/40 p-3 shadow-lg">
      <header className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2">
          <span className={`mt-0.5 ${SEVERITY_TEXT[severity]}`}>{icon}</span>
          <div>
            <h3 className="text-xs font-bold leading-tight text-slate-100">
              {title}
            </h3>
            <p className="font-mono text-[9px] uppercase tracking-wider text-slate-500">
              {subtitle}
            </p>
          </div>
        </div>
        <StatusPill severity={severity}>{statusText}</StatusPill>
      </header>
      <div className="mt-2 flex items-baseline gap-1">
        <span className={`font-mono text-xl font-bold tabular-nums ${SEVERITY_TEXT[severity]}`}>
          {value}
        </span>
        {unit && <span className="text-[10px] text-slate-500">{unit}</span>}
      </div>
      <div className="mt-1 text-[10px] leading-snug text-slate-400">{detail}</div>
    </article>
  );
}

export function AuditMetricsPanel() {
  const analysisData = useAnalysisStore((state) => state.analysisData);
  const viewMode = useAnalysisStore((state) => state.viewMode);
  const audit = analysisData?.audit_metrics;

  if (!analysisData || !audit) {
    return (
      <section className="rounded-2xl border border-line bg-surface p-4 shadow-panel">
        <h2 className="flex items-center gap-2 text-sm font-bold text-slate-100">
          <ShieldCheck className="h-4 w-4 text-emerald-400" />
          Scientific Audit Panel
        </h2>
        <p className="mt-2 text-xs text-slate-400">
          Run an analysis to populate the live statistical peer-review metrics.
        </p>
      </section>
    );
  }

  const isRaw = viewMode === "RAW";

  const chowF = isRaw ? audit.chow_test_f_stat_raw : audit.chow_test_f_stat_harm;
  const chowP = isRaw ? audit.chow_test_p_val_raw : audit.chow_test_p_val_harm;
  const chowPass = chowP > 0.1;

  const w1 = isRaw ? audit.wasserstein_w1_raw : audit.wasserstein_w1_harm;
  const w1Reduction =
    audit.wasserstein_w1_raw > 0
      ? (1 - audit.wasserstein_w1_harm / audit.wasserstein_w1_raw) * 100
      : 0;

  const r2 = isRaw ? audit.burned_area_r2_raw : audit.burned_area_r2_harm;
  const removed = audit.industrial_false_positives_removed;
  const biomass = audit.total_biomass_burned_kt;
  const pm25 = audit.total_pm25_emitted_tonnes;

  const verdict = audit.executive_verdict_en;
  const verdictSeverity: Severity = /\bfail/i.test(verdict)
    ? "bad"
    : /\bpass/i.test(verdict)
      ? "ok"
      : "warn";
  const verdictBg =
    verdictSeverity === "ok"
      ? "border-emerald-700/60 bg-emerald-500/10"
      : verdictSeverity === "bad"
        ? "border-red-700/60 bg-red-500/10"
        : "border-amber-700/60 bg-amber-500/10";

  return (
    <section className="rounded-2xl border border-line bg-surface p-4 shadow-panel">
      <header className="mb-3 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-bold text-slate-100">
          <ShieldCheck className="h-4 w-4 text-emerald-400" />
          Scientific Audit Panel
          <span className="rounded border border-slate-700 bg-slate-900 px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider text-slate-400">
            {isRaw ? "RAW regime" : "HARMONIZED regime"}
          </span>
        </h2>
      </header>

      {/* Executive verdict banner */}
      <div className={`mb-3 rounded-xl border p-3 ${verdictBg}`}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-2">
            {verdictSeverity === "ok" ? (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
            ) : (
              <Gauge className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
            )}
            <div>
              <p className="font-mono text-[9px] uppercase tracking-[0.22em] text-slate-400">
                Executive Audit Verdict
              </p>
              <p className="mt-0.5 max-w-3xl text-xs leading-snug text-slate-200">
                {verdict}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => downloadIpccCsv(analysisData)}
            className="flex shrink-0 items-center gap-1.5 rounded-lg border border-ember/40 bg-ember/10 px-3 py-1.5 text-xs font-semibold text-ember transition-colors hover:bg-ember/20"
          >
            <Download className="h-3.5 w-3.5" />
            Export IPCC-Ready CSV
          </button>
        </div>
      </div>

      {/* Five scientific audit cards */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-3">
        <MetricCard
          icon={<Activity className="h-4 w-4" />}
          title="Chow Structural Break"
          subtitle="Jan 2012 · F(k, N−2k)"
          value={`F = ${formatNumber(chowF, 2)}`}
          detail={
            <>
              p-value{" "}
              <span className="font-mono text-slate-200">{formatP(chowP)}</span> ·{" "}
              {chowPass
                ? "homogeneous regime (p > 0.10)"
                : "structural break detected (p ≤ 0.10)"}
            </>
          }
          severity={chowPass ? "ok" : "bad"}
          statusText={chowPass ? "Passed" : "Failed"}
        />

        <MetricCard
          icon={<TrendingUp className="h-4 w-4" />}
          title="Wasserstein-1 Distance"
          subtitle="MODIS ↔ VIIRS divergence"
          value={formatNumber(w1, 3)}
          unit="W₁"
          detail={
            <>
              Harmonization reduces divergence by{" "}
              <span
                className={`font-mono ${w1Reduction >= 80 ? "text-emerald-300" : "text-amber-300"}`}
              >
                {formatNumber(w1Reduction, 1)}%
              </span>{" "}
              ({formatNumber(audit.wasserstein_w1_raw, 2)} → {formatNumber(audit.wasserstein_w1_harm, 3)}).
            </>
          }
          severity={w1Reduction >= 80 ? "ok" : w1Reduction >= 40 ? "warn" : "bad"}
          statusText={`${formatNumber(w1Reduction, 0)}% ↓`}
        />

        <MetricCard
          icon={<Flame className="h-4 w-4" />}
          title="Burned Area Validation"
          subtitle="R² vs MCD64A1"
          value={formatNumber(r2, 3)}
          unit="R²"
          detail={
            <>
              Coefficient of determination against independent{" "}
              <span className="font-mono text-slate-200">MCD64A1</span> burned area for
              the {isRaw ? "raw pixel counts" : "harmonized FRE"} series.
            </>
          }
          severity={r2 >= 0.9 ? "ok" : r2 >= 0.7 ? "warn" : "bad"}
          statusText={r2 >= 0.9 ? "Strong" : r2 >= 0.7 ? "Moderate" : "Weak"}
        />

        <MetricCard
          icon={<ShieldCheck className="h-4 w-4" />}
          title="Shannon Entropy Filter"
          subtitle="H_temp > 0.75 · industrial"
          value={removed.toLocaleString("en-US")}
          unit="discarded"
          detail={
            <>
              Stationary anthropogenic heat sources (gas flares, refineries, steel mills)
              removed by normalized temporal persistence entropy.
            </>
          }
          severity="ok"
          statusText="Active"
        />

        <MetricCard
          icon={<Wind className="h-4 w-4" />}
          title="Wooster Biomass & Smoke"
          subtitle="β_comb = 0.368 kg·MJ⁻¹"
          value={formatNumber(biomass, 1)}
          unit="kt dry biomass"
          detail={
            <>
              <span className="font-mono text-slate-200">{formatNumber(pm25, 1)} t</span>{" "}
              PM2.5 emitted, stratified by biome emission factors.
            </>
          }
          severity="info"
          statusText="Accounted"
        />
      </div>
    </section>
  );
}
