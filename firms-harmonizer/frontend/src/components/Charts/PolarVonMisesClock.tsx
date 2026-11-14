import { useMemo } from "react";
import { Compass, TrendingUp } from "lucide-react";
import { useAnalysisStore } from "../../store/useAnalysisStore";

/**
 * Circular von Mises phenology clock.
 *
 * Each year y contributes a directional vector whose angle is the weight-averaged
 * peak burning day mu_hat_y mapped onto [0, 2*pi) and whose length is the seasonal
 * concentration kappa_hat_y. Vectors are colour-graded from cyan (2001) to fire red
 * (2026) so the decadal rotation of the fire season is directly visible. The shaded
 * wedge is the critical fire-season window (season_width_days) of the latest year,
 * and the core readout shows the Theil-Sen drift (days/decade) plus the circular
 * Mann-Kendall p-value.
 */

const MONTH_LABELS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

// Day-of-year of the first day of each month (non-leap baseline).
const MONTH_START_DOY = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335];

const DAYS_IN_YEAR = 365.25;

const CX = 140;
const CY = 140;
const R_OUTER = 108;
const R_LABEL = 124;
const R_VECTOR_MIN = 18;
const R_VECTOR_MAX = 96;
const R_CORE = 52;

function polarToXY(radius: number, angle: number): { x: number; y: number } {
  // Angle 0 points up; positive angles rotate clockwise.
  return { x: CX + radius * Math.sin(angle), y: CY - radius * Math.cos(angle) };
}

function doyToAngle(doy: number): number {
  return (2 * Math.PI * ((doy - 1) % DAYS_IN_YEAR)) / DAYS_IN_YEAR;
}

function mix(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

function yearGradient(t: number): string {
  const clamped = Math.max(0, Math.min(1, t));
  const cyan = [90, 167, 224];
  const amber = [245, 158, 11];
  const fire = [239, 68, 68];
  const rgb =
    clamped < 0.5
      ? cyan.map((channel, index) => mix(channel, amber[index], clamped / 0.5))
      : amber.map((channel, index) =>
          mix(channel, fire[index], (clamped - 0.5) / 0.5),
        );
  return `rgb(${rgb.map((value) => Math.round(value)).join(", ")})`;
}

function formatPValue(p: number): string {
  if (!Number.isFinite(p)) return "p = n/a";
  if (p <= 0) return "p < 1e-300";
  if (p < 1e-4) return `p = ${p.toExponential(1)}`;
  return `p = ${p.toFixed(3)}`;
}

export function PolarVonMisesClock() {
  const analysisData = useAnalysisStore((state) => state.analysisData);
  const phenology = analysisData?.phenology_by_year ?? [];
  const audit = analysisData?.audit_metrics;

  const geometry = useMemo(() => {
    const years = phenology.map((entry) => entry.year);
    const minYear = years.length > 0 ? Math.min(...years) : 2001;
    const maxYear = years.length > 0 ? Math.max(...years) : 2026;
    const span = Math.max(maxYear - minYear, 1);
    const maxKappa = phenology.reduce(
      (acc, entry) => Math.max(acc, entry.concentration_kappa),
      1e-6,
    );

    const vectors = phenology.map((entry) => {
      const angle = doyToAngle(entry.peak_doy_mu);
      const normalized = Math.min(1, entry.concentration_kappa / maxKappa);
      const radius =
        R_VECTOR_MIN + normalized * (R_VECTOR_MAX - R_VECTOR_MIN);
      return {
        year: entry.year,
        angle,
        tip: polarToXY(radius, angle),
        color: yearGradient((entry.year - minYear) / span),
      };
    });

    const latest =
      phenology.length > 0 ? phenology[phenology.length - 1] : null;
    const peakAngle = latest ? doyToAngle(latest.peak_doy_mu) : 0;
    const halfWindow = latest
      ? (Math.PI * latest.season_width_days) / DAYS_IN_YEAR
      : Math.PI / 4;

    const start = polarToXY(R_OUTER, peakAngle - halfWindow);
    const end = polarToXY(R_OUTER, peakAngle + halfWindow);
    const largeArc = halfWindow * 2 > Math.PI ? 1 : 0;
    const windowPath =
      `M ${CX} ${CY} ` +
      `L ${start.x.toFixed(2)} ${start.y.toFixed(2)} ` +
      `A ${R_OUTER} ${R_OUTER} 0 ${largeArc} 1 ${end.x.toFixed(2)} ${end.y.toFixed(2)} Z`;

    return { vectors, minYear, maxYear, windowPath };
  }, [phenology]);

  const hasData = phenology.length > 0;
  const shift = audit?.phenology_shift_days_per_decade ?? 0;
  const shiftLabel = `${shift >= 0 ? "+" : ""}${shift.toFixed(1)}`;
  const mannKendall = formatPValue(audit?.mann_kendall_p_value ?? Number.NaN);

  return (
    <section className="flex h-full flex-col rounded-2xl border border-line bg-surface p-4 shadow-panel">
      <header className="mb-2 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-bold text-slate-100">
          <Compass className="h-4 w-4 text-ember" />
          von Mises Phenology Clock
        </h2>
        <span className="rounded border border-slate-700 bg-slate-900 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-slate-400">
          {geometry.minYear} → {geometry.maxYear}
        </span>
      </header>

      <div className="flex flex-1 items-center justify-center">
        <svg
          viewBox="0 0 280 280"
          className="h-auto w-full max-w-[300px]"
          role="img"
          aria-label="Circular fire-season phenology clock"
        >
          <defs>
            <linearGradient id="phenologyGradient" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#5AA7E0" />
              <stop offset="50%" stopColor="#f59e0b" />
              <stop offset="100%" stopColor="#ef4444" />
            </linearGradient>
          </defs>

          {/* Radial guide rings */}
          {[0.34, 0.67, 1].map((ratio) => (
            <circle
              key={ratio}
              cx={CX}
              cy={CY}
              r={R_OUTER * ratio}
              fill="none"
              stroke="rgba(148, 163, 184, 0.12)"
              strokeDasharray="2 4"
            />
          ))}
          <circle
            cx={CX}
            cy={CY}
            r={R_OUTER}
            fill="none"
            stroke="rgba(148, 163, 184, 0.28)"
          />

          {/* Month spokes and labels */}
          {MONTH_START_DOY.map((startDoy, index) => {
            const spoke = polarToXY(R_OUTER, doyToAngle(startDoy));
            const label = polarToXY(R_LABEL, doyToAngle(startDoy) + Math.PI / 12);
            return (
              <g key={MONTH_LABELS[index]}>
                <line
                  x1={CX}
                  y1={CY}
                  x2={spoke.x}
                  y2={spoke.y}
                  stroke="rgba(148, 163, 184, 0.14)"
                />
                <text
                  x={label.x}
                  y={label.y}
                  fill="#94a3b8"
                  fontSize="8"
                  fontFamily="ui-monospace, monospace"
                  textAnchor="middle"
                  dominantBaseline="middle"
                >
                  {MONTH_LABELS[index]}
                </text>
              </g>
            );
          })}

          {/* Critical fire-season window of the latest year */}
          {hasData && (
            <path
              d={geometry.windowPath}
              fill="rgba(56, 189, 248, 0.12)"
              stroke="rgba(56, 189, 248, 0.55)"
              strokeDasharray="4 3"
            />
          )}

          {/* Annual directional vectors */}
          {geometry.vectors.map((vector) => (
            <g key={vector.year}>
              <line
                x1={CX}
                y1={CY}
                x2={vector.tip.x}
                y2={vector.tip.y}
                stroke={vector.color}
                strokeWidth={1.6}
                strokeLinecap="round"
                opacity={0.92}
              />
              <circle
                cx={vector.tip.x}
                cy={vector.tip.y}
                r={1.8}
                fill={vector.color}
              />
            </g>
          ))}

          {/* Core readout */}
          <circle
            cx={CX}
            cy={CY}
            r={R_CORE}
            fill="#0b1220"
            stroke="rgba(148, 163, 184, 0.3)"
          />
          <text
            x={CX}
            y={CY - 20}
            fill="#64748b"
            fontSize="7"
            fontFamily="ui-monospace, monospace"
            textAnchor="middle"
            letterSpacing="1"
          >
            THEIL–SEN
          </text>
          <text
            x={CX}
            y={CY - 1}
            fill="#f59e0b"
            fontSize="17"
            fontWeight="700"
            fontFamily="ui-monospace, monospace"
            textAnchor="middle"
          >
            {hasData ? shiftLabel : "—"}
          </text>
          <text
            x={CX}
            y={CY + 11}
            fill="#94a3b8"
            fontSize="7"
            fontFamily="ui-monospace, monospace"
            textAnchor="middle"
          >
            days / decade
          </text>
          <text
            x={CX}
            y={CY + 29}
            fill="#38bdf8"
            fontSize="7"
            fontFamily="ui-monospace, monospace"
            textAnchor="middle"
          >
            {hasData ? mannKendall : "Mann–Kendall"}
          </text>
        </svg>
      </div>

      <div className="mt-2 space-y-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[9px] text-slate-400">2001</span>
          <span className="h-1.5 flex-1 rounded-full bg-gradient-to-r from-info via-heat to-danger" />
          <span className="font-mono text-[9px] text-slate-400">2026</span>
        </div>
        <p className="flex items-start gap-1.5 text-[10px] leading-snug text-slate-400">
          <TrendingUp className="mt-0.5 h-3 w-3 shrink-0 text-amber-400" />
          <span>
            Fire-season drift: Theil–Sen{" "}
            <span className="font-mono text-amber-300">
              {hasData ? `${shiftLabel} days/decade` : "pending"}
            </span>
            , Mann–Kendall{" "}
            <span className="font-mono text-info">
              {hasData ? mannKendall : "pending"}
            </span>
            .
          </span>
        </p>
      </div>
    </section>
  );
}
