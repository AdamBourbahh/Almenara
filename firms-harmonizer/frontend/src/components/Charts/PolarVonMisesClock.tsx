import { useMemo } from "react";
import { useAnalysisStore } from "../../store/useAnalysisStore";

const DAYS = 365.25;
const CX = 150;
const CY = 150;
const R_OUTER = 116;
const R_LABEL = 133;
const R_MIN = 20;
const R_MAX = 102;
const R_CORE = 54;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTH_START = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335];

const THERMAL: Array<[number, number, number]> = [
  [253, 212, 158],
  [230, 85, 13],
  [179, 0, 0]
];

function polar(radius: number, angle: number): { x: number; y: number } {
  return { x: CX + radius * Math.sin(angle), y: CY - radius * Math.cos(angle) };
}

function doyToAngle(doy: number): number {
  return (2 * Math.PI * ((doy - 1) % DAYS)) / DAYS;
}

function thermalColor(t: number): string {
  const clamped = Math.max(0, Math.min(1, t));
  const scaled = clamped * (THERMAL.length - 1);
  const k = Math.min(THERMAL.length - 2, Math.floor(scaled));
  const f = scaled - k;
  const [r, g, b] = THERMAL[k].map((c, i) => Math.round(c + (THERMAL[k + 1][i] - c) * f));
  return `rgb(${r}, ${g}, ${b})`;
}

function formatP(p: number | undefined): string {
  if (p === undefined || !Number.isFinite(p)) return "—";
  if (p <= 0) return "< 1e-300";
  if (p < 1e-4) return p.toExponential(1);
  return p.toFixed(3);
}

export function PolarVonMisesClock() {
  const analysisData = useAnalysisStore((s) => s.analysisData);
  const phenology = analysisData?.phenology_by_year ?? [];
  const audit = analysisData?.audit_metrics;

  const geometry = useMemo(() => {
    const years = phenology.map((entry) => entry.year);
    const minYear = years.length ? Math.min(...years) : 2001;
    const maxYear = years.length ? Math.max(...years) : 2026;
    const span = Math.max(maxYear - minYear, 1);
    const maxKappa = phenology.reduce((acc, entry) => Math.max(acc, entry.concentration_kappa), 1e-6);

    const vectors = phenology.map((entry) => {
      const angle = doyToAngle(entry.peak_doy_mu);
      const radius = R_MIN + Math.min(1, entry.concentration_kappa / maxKappa) * (R_MAX - R_MIN);
      return { year: entry.year, tip: polar(radius, angle), color: thermalColor((entry.year - minYear) / span) };
    });

    const latest = phenology.length ? phenology[phenology.length - 1] : null;
    const peakAngle = latest ? doyToAngle(latest.peak_doy_mu) : 0;
    const halfWindow = latest ? (Math.PI * latest.season_width_days) / DAYS : Math.PI / 4;
    const start = polar(R_OUTER, peakAngle - halfWindow);
    const end = polar(R_OUTER, peakAngle + halfWindow);
    const largeArc = halfWindow * 2 > Math.PI ? 1 : 0;
    const windowPath =
      `M ${CX} ${CY} L ${start.x.toFixed(2)} ${start.y.toFixed(2)} ` +
      `A ${R_OUTER} ${R_OUTER} 0 ${largeArc} 1 ${end.x.toFixed(2)} ${end.y.toFixed(2)} Z`;

    return { minYear, maxYear, vectors, windowPath, latest };
  }, [phenology]);

  const shift = audit?.phenology_shift_days_per_decade ?? 0;
  const shiftLabel = `${shift >= 0 ? "+" : ""}${shift.toFixed(1)}`;
  const meanMu = phenology.length ? phenology.reduce((a, p) => a + p.peak_doy_mu, 0) / phenology.length : 0;
  const meanKappa = phenology.length ? phenology.reduce((a, p) => a + p.concentration_kappa, 0) / phenology.length : 0;
  const meanWidth = phenology.length ? phenology.reduce((a, p) => a + p.season_width_days, 0) / phenology.length : 0;
  const peakLabel = geometry.latest?.peak_date_label ?? "—";

  return (
    <section className="border border-rule bg-panel p-6">
      <header className="mb-1">
        <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-faint">Fire-season clock</p>
        <h3 className="mt-1 font-serif text-xl text-ink">How the fire season is moving</h3>
      </header>

      <p className="mb-5 max-w-xl text-sm leading-relaxed text-muted">
        The fire-season peak is moving{" "}
        <strong className="font-medium text-thermal-4 tnum">
          {shift >= 0 ? "+" : ""}
          {shift.toFixed(1)} days per decade
        </strong>
        . Each spoke is one year: its direction is the peak day, its length the seasonal concentration.
      </p>

      <div className="flex justify-center">
        <svg viewBox="0 0 300 300" className="h-auto w-full max-w-[320px]" role="img" aria-label="Fire-season clock">
          {[0.34, 0.67, 1].map((ratio) => (
            <circle key={ratio} cx={CX} cy={CY} r={R_OUTER * ratio} fill="none" stroke="var(--color-rule)" strokeDasharray="2 4" />
          ))}
          <circle cx={CX} cy={CY} r={R_OUTER} fill="none" stroke="var(--color-rule-strong)" />

          {MONTH_START.map((startDoy, index) => {
            const spoke = polar(R_OUTER, doyToAngle(startDoy));
            const label = polar(R_LABEL, doyToAngle(startDoy) + Math.PI / 12);
            return (
              <g key={MONTHS[index]}>
                <line x1={CX} y1={CY} x2={spoke.x} y2={spoke.y} stroke="var(--color-rule)" />
                <text x={label.x} y={label.y} fill="var(--color-faint)" fontSize="8" textAnchor="middle" dominantBaseline="middle">
                  {MONTHS[index]}
                </text>
              </g>
            );
          })}

          {phenology.length > 0 && (
            <path d={geometry.windowPath} fill="rgba(253, 190, 133, 0.18)" stroke="rgba(230, 85, 13, 0.55)" strokeDasharray="4 3" />
          )}

          {geometry.vectors.map((vector) => (
            <g key={vector.year}>
              <line x1={CX} y1={CY} x2={vector.tip.x} y2={vector.tip.y} stroke={vector.color} strokeWidth={1.4} opacity={0.85} />
              <circle cx={vector.tip.x} cy={vector.tip.y} r={1.7} fill={vector.color} />
            </g>
          ))}

          <circle cx={CX} cy={CY} r={R_CORE} fill="var(--color-panel)" stroke="var(--color-rule-strong)" />
          <text x={CX} y={CY - 8} fill="var(--color-faint)" fontSize="7" textAnchor="middle" letterSpacing="1">
            AVERAGE PEAK
          </text>
          <text x={CX} y={CY + 9} fill="var(--color-ink)" fontSize="16" fontFamily="var(--font-serif)" textAnchor="middle">
            {peakLabel}
          </text>
        </svg>
      </div>

      <div className="mt-5 flex items-center gap-2 text-[10px] text-faint">
        <span>{geometry.minYear}</span>
        <span className="h-1.5 flex-1" style={{ background: "linear-gradient(90deg, #fdd49e, #e6550d, #b30000)" }} />
        <span>{geometry.maxYear}</span>
      </div>

      <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-2 border-t border-rule pt-4 text-xs">
        <div className="flex items-baseline justify-between gap-2">
          <dt className="text-faint">Mean peak day (μ)</dt>
          <dd className="text-ink tnum">{meanMu.toFixed(0)}</dd>
        </div>
        <div className="flex items-baseline justify-between gap-2">
          <dt className="text-faint">Concentration (κ)</dt>
          <dd className="text-ink tnum">{meanKappa.toFixed(2)}</dd>
        </div>
        <div className="flex items-baseline justify-between gap-2">
          <dt className="text-faint">Season width</dt>
          <dd className="text-ink tnum">{meanWidth.toFixed(0)} days</dd>
        </div>
        <div className="flex items-baseline justify-between gap-2">
          <dt className="text-faint">Mann–Kendall (p)</dt>
          <dd className="text-ink tnum">{formatP(audit?.mann_kendall_p_value)}</dd>
        </div>
        <div className="flex items-baseline justify-between gap-2">
          <dt className="text-faint">Theil–Sen drift</dt>
          <dd className="text-thermal-4 tnum">{shiftLabel} d/decade</dd>
        </div>
      </dl>
    </section>
  );
}
