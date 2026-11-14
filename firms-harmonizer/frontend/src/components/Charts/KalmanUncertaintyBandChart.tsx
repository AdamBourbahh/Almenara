import { useMemo } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import { Loader2, Play, RotateCcw } from "lucide-react";
import { useAnalysisStore } from "../../store/useAnalysisStore";
import type { AnalyzeResponse, DailyCalendarCell } from "../../api/types";

/**
 * Kalman reconstruction + 14-day outlook, rewritten for the editorial theme.
 * Normal mode: observed year + 95 % CI + historical prior + forecast cone.
 * Stress mode: ground truth vs naive collapse vs cross-guard vs RTS Kalman.
 */

const WIDTH = 780;
const HEIGHT = 320;
const M = { top: 16, right: 16, bottom: 30, left: 54 };
const PW = WIDTH - M.left - M.right;
const PH = HEIGHT - M.top - M.bottom;

const MAIN = "#b30000";
const PRIOR = "#b45309";
const FORECAST = "#1d4ed8";
const MAIN_FILL = "rgba(179, 0, 0, 0.10)";
const FORECAST_FILL = "rgba(29, 78, 216, 0.08)";
const GAP_FILL = "rgba(107, 114, 128, 0.12)";
const TRUTH = "#111827";
const NAIVE = "#b91c1c";
const GUARD = "#b45309";
const KALMAN = "#15803d";
const GRID = "#eceef1";
const AXIS = "#6b7280";

function scaleX(index: number, count: number): number {
  return count <= 1 ? M.left : M.left + (index / (count - 1)) * PW;
}
function scaleY(value: number, max: number): number {
  return M.top + PH - (Math.max(0, value) / max) * PH;
}

interface NormalPoint {
  date: string;
  fre: number;
  prior: number;
  lower: number;
  upper: number;
  isForecast: boolean;
  isGap: boolean;
}

function buildNormal(data: AnalyzeResponse, year: number, month: number | null): { points: NormalPoint[]; historical: number } | null {
  const cells = data.calendar_series.filter((c) => c.year === year && (month === null || Number(c.date.slice(5, 7)) === month));
  if (cells.length === 0) return null;
  const points: NormalPoint[] = cells.map((c: DailyCalendarCell) => ({
    date: c.date,
    fre: c.harmonized_fre_mj_km2,
    prior: c.historical_cross_prior_fre ?? 0,
    lower: c.ci_95_lower,
    upper: c.ci_95_upper,
    isForecast: false,
    isGap: c.is_gap_filled
  }));
  for (const c of data.forecast_series ?? []) {
    if (c.year !== year || month !== null && Number(c.date.slice(5, 7)) !== month) continue;
    points.push({
      date: c.date,
      fre: c.harmonized_fre_mj_km2,
      prior: c.historical_cross_prior_fre ?? 0,
      lower: c.ci_95_lower,
      upper: c.ci_95_upper,
      isForecast: true,
      isGap: false
    });
  }
  return { points, historical: cells.length };
}

function line(pts: Array<{ x: number; y: number }>): string {
  return pts.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join(" ");
}
function band(pts: Array<{ x: number; up: number; lo: number }>): string {
  if (pts.length === 0) return "";
  const top = pts.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.up.toFixed(2)}`).join(" ");
  const bottom = [...pts].reverse().map((p) => `L ${p.x.toFixed(2)} ${p.lo.toFixed(2)}`).join(" ");
  return `${top} ${bottom} Z`;
}
function fmtDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", { day: "numeric", month: "short", timeZone: "UTC" });
}
function ticks(count: number, n = 6): number[] {
  if (count <= 0) return [];
  const set = new Set<number>();
  for (let i = 0; i < n; i++) set.add(Math.round((i / (n - 1)) * (count - 1)));
  return [...set].sort((a, b) => a - b);
}

export function KalmanUncertaintyBandChart() {
  const analysisData = useAnalysisStore((s) => s.analysisData);
  const lockedYear = useAnalysisStore((s) => s.selectedYear);
  const lockedMonth = useAnalysisStore((s) => s.selectedMonth);
  const selectedDate = useAnalysisStore((s) => s.selectedDate);
  const pinned = useAnalysisStore((s) => s.isDatePinned);
  const hoveredCell = useAnalysisStore((s) => s.hoveredCell);
  const dateIndex = useAnalysisStore((s) => s.dateIndex);
  const setHoveredCell = useAnalysisStore((s) => s.setHoveredCell);
  const setSelectedDate = useAnalysisStore((s) => s.setSelectedDate);
  const active = pinned && selectedDate ? dateIndex.get(selectedDate) : hoveredCell ?? (selectedDate ? dateIndex.get(selectedDate) : null);
  const selectedYear = active?.year ?? lockedYear;
  const selectedMonth = lockedMonth !== null && active ? Number(active.date.slice(5, 7)) : lockedMonth;
  const chaosData = useAnalysisStore((s) => s.chaosData);
  const chaosLoading = useAnalysisStore((s) => s.chaosLoading);
  const chaosError = useAnalysisStore((s) => s.chaosError);
  const triggerChaosMonkey = useAnalysisStore((s) => s.triggerChaosMonkey);
  const resetChaosMonkey = useAnalysisStore((s) => s.resetChaosMonkey);

  const normal = useMemo(() => (analysisData ? buildNormal(analysisData, selectedYear, selectedMonth) : null), [analysisData, selectedYear, selectedMonth]);

  const normalView = useMemo(() => {
    if (!normal) return null;
    const { points, historical } = normal;
    const count = points.length;
    const yMax = Math.max(1, ...points.map((p) => Math.max(p.upper, p.fre, p.prior))) * 1.12;
    const historicalPts = points.slice(0, historical).map((p, i) => ({ x: scaleX(i, count), fre: scaleY(p.fre, yMax), prior: scaleY(p.prior, yMax), up: scaleY(p.upper, yMax), lo: scaleY(p.lower, yMax) }));
    const forecastPts = points.slice(Math.max(0, historical - 1)).map((p, i) => ({ x: scaleX(Math.max(0, historical - 1) + i, count), fre: scaleY(p.fre, yMax), up: scaleY(p.upper, yMax), lo: scaleY(p.lower, yMax) }));
    const gapRuns: Array<{ start: number; end: number }> = [];
    let start = -1;
    points.forEach((p, i) => {
      if (p.isGap && !p.isForecast && start === -1) start = i;
      else if ((!p.isGap || p.isForecast) && start !== -1) {
        gapRuns.push({ start, end: i - 1 });
        start = -1;
      }
    });
    if (start !== -1) gapRuns.push({ start, end: points.length - 1 });
    return { count, yMax, historical, points, historicalPts, forecastPts, gapRuns };
  }, [normal]);

  const chaosView = useMemo(() => {
    if (!chaosData) return null;
    const count = chaosData.true_harmonized_fre.length;
    if (count === 0) return null;
    const yMax = Math.max(1, ...chaosData.true_harmonized_fre, ...chaosData.reconstructed_ci_upper) * 1.12;
    const x = (i: number) => scaleX(i, count);
    const pts = Array.from({ length: count }, (_, i) => ({
      x: x(i),
      truth: scaleY(chaosData.true_harmonized_fre[i] ?? 0, yMax),
      naive: scaleY(chaosData.corrupted_naive_fre[i] ?? 0, yMax),
      guard: scaleY(chaosData.historical_cross_guard_fre?.[i] ?? 0, yMax),
      kalman: scaleY(chaosData.kalman_reconstructed_fre[i] ?? 0, yMax),
      up: scaleY(chaosData.reconstructed_ci_upper[i] ?? 0, yMax),
      lo: scaleY(chaosData.reconstructed_ci_lower[i] ?? 0, yMax)
    }));
    const dateFor = (i: number) => chaosData.dates[i];
    return { count, yMax, pts, dateFor };
  }, [chaosData, selectedYear]);

  const isChaos = Boolean(chaosData);
  const count = isChaos ? chaosView?.count ?? 0 : normalView?.count ?? 0;
  const yMax = (isChaos ? chaosView?.yMax : normalView?.yMax) ?? 1;
  const dates = isChaos
    ? chaosView
      ? Array.from({ length: chaosView.count }, (_, i) => chaosView.dateFor(i))
      : []
    : normal?.points.map((p) => p.date) ?? [];

  const handleMove = (e: ReactMouseEvent<SVGRectElement>) => {
    if (count <= 0) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const ratio = rect.width > 0 ? (e.clientX - rect.left) / rect.width : 0;
    if (pinned) return;
    const index = Math.max(0, Math.min(count - 1, Math.round(ratio * (count - 1))));
    setHoveredCell(dateIndex.get(dates[index]) ?? null);
  };

  const datePositions = useMemo(() => new Map(dates.map((date, i) => [date, i])), [dates]);
  const hover = active ? datePositions.get(active.date) ?? null : null;
  const yTicks = [0, yMax * 0.25, yMax * 0.5, yMax * 0.75, yMax];
  const xTicks = ticks(count);
  const hoverX = hover !== null ? scaleX(hover, count) : null;

  const legend = isChaos
    ? [
        { color: TRUTH, label: "Truth" },
        { color: NAIVE, label: "Naive" },
        { color: GUARD, label: "Baseline" },
        { color: KALMAN, label: "RTS Kalman + 95% CI" }
      ]
    : [
        { color: MAIN, label: "Harmonized energy" },
        { color: PRIOR, label: "Historical baseline" },
        { color: FORECAST, label: "14-day forecast" },
        { color: GAP_FILL, label: "Repaired days" }
      ];

  const tooltip = () => {
    if (hover === null || hoverX === null) return null;
    const leftPct = Math.min(88, Math.max(12, (hoverX / WIDTH) * 100));
    if (isChaos && chaosData) {
      return (
        <div className="pointer-events-none absolute top-2 z-20 w-52 -translate-x-1/2 border border-rule bg-panel p-2 text-[10px] tnum" style={{ left: `${leftPct}%` }}>
          <p className="mb-1 font-serif text-xs text-ink">{fmtDate(dates[hover] ?? "")}</p>
          <Row label="Truth" value={chaosData.true_harmonized_fre[hover]} color="text-ink" />
          <Row label="Naive" value={chaosData.corrupted_naive_fre[hover]} color="text-bias" />
          <Row label="Baseline" value={chaosData.historical_cross_guard_fre?.[hover] ?? 0} color="text-terracotta" />
          <Row label="RTS Kalman" value={chaosData.kalman_reconstructed_fre[hover]} color="text-validated" />
        </div>
      );
    }
    const p = normal?.points[hover];
    if (!p) return null;
    return (
      <div className="pointer-events-none absolute top-2 z-20 w-52 -translate-x-1/2 border border-rule bg-panel p-2 text-[10px] tnum" style={{ left: `${leftPct}%` }}>
        <p className="mb-1 flex items-center justify-between font-serif text-xs text-ink">
          <span>{fmtDate(p.date)}</span>
          {p.isForecast && <span className="text-[9px] text-reference">forecast</span>}
        </p>
        <Row label="Energy" value={p.fre} color="text-thermal-4" />
        <Row label="Baseline" value={p.prior} color="text-terracotta" />
        <p className="mt-1 flex justify-between text-[9px] text-faint">
          <span>95% range</span>
          <span className="text-ink">[{p.lower.toFixed(0)}–{p.upper.toFixed(0)}]</span>
        </p>
      </div>
    );
  };

  return (
    <section className="border border-rule bg-panel p-6">
      <header className="mb-1 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-faint">Satellite gaps</p>
          <h3 className="mt-1 font-serif text-xl text-ink">Daily fire energy and uncertainty</h3>
        </div>

      </header>

      {active && <p aria-label="Chart active day" className="mb-3 text-xs text-ink tnum">{active.date} · DOY {active.doy} · FRE {active.harmonized_fre_mj_km2.toFixed(1)} MJ/km² · 95% CI [{active.ci_95_lower.toFixed(1)}, {active.ci_95_upper.toFixed(1)}] · Prior {active.historical_cross_prior_fre.toFixed(1)} · Raw {active.raw_hotspot_count}</p>}
      <p className="mb-4 max-w-2xl text-sm leading-relaxed text-muted">
        The model fills the days without a satellite pass instead of letting them fall to zero. The
        stress test wipes 25% of the data and simulates ten days of total cloud cover, then shows the
        energy it can recover.
      </p>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => void triggerChaosMonkey()}
          disabled={chaosLoading}
          className="flex items-center gap-2 border border-bias/50 bg-bias/5 px-3 py-1.5 text-xs font-medium text-bias hover:bg-bias/10 disabled:opacity-50"
        >
          {chaosLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
          {chaosLoading ? "Simulating…" : "Simulate a satellite outage (stress test)"}
        </button>
        <button
          type="button"
          onClick={resetChaosMonkey}
          disabled={!isChaos || chaosLoading}
          className="flex items-center gap-1.5 border border-rule px-3 py-1.5 text-xs text-muted hover:bg-paper disabled:opacity-40"
        >
          <RotateCcw className="h-3.5 w-3.5" /> Reset
        </button>
        {chaosData && (
          <span className="border border-validated/40 bg-validated/10 px-2 py-1 text-xs text-validated tnum">
            Energy recovered {chaosData.seasonal_energy_recovered_pct.toFixed(1)}%
          </span>
        )}
        {chaosError && <span className="text-xs text-bias">{chaosError}</span>}
      </div>

      {count === 0 ? (
        <div className="flex h-48 items-center justify-center text-sm text-faint">No daily series for {selectedYear}.</div>
      ) : (
        <>
          <div className="relative">
            {tooltip()}
            <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-auto w-full" role="img" aria-label="Kalman uncertainty band" tabIndex={0}>
              {yTicks.map((t) => (
                <g key={t}>
                  <line x1={M.left} x2={WIDTH - M.right} y1={scaleY(t, yMax)} y2={scaleY(t, yMax)} stroke={GRID} />
                  <text x={M.left - 8} y={scaleY(t, yMax)} textAnchor="end" dominantBaseline="middle" fill={AXIS} fontSize="9" fontFamily="var(--font-mono)">
                    {t.toFixed(0)}
                  </text>
                </g>
              ))}
              {xTicks.map((i) => (
                <text key={i} x={scaleX(i, count)} y={M.top + PH + 16} textAnchor="middle" fill={AXIS} fontSize="9" fontFamily="var(--font-mono)">
                  {dates[i] ? fmtDate(dates[i]) : ""}
                </text>
              ))}

              {isChaos && chaosView ? (
                <>
                  <path d={band(chaosView.pts)} fill="rgba(21, 128, 61, 0.10)" />
                  <path d={line(chaosView.pts.map((p) => ({ x: p.x, y: p.truth })))} fill="none" stroke={TRUTH} strokeWidth={1.4} />
                  <path d={line(chaosView.pts.map((p) => ({ x: p.x, y: p.guard })))} fill="none" stroke={GUARD} strokeWidth={1.2} strokeDasharray="3 3" />
                  <path d={line(chaosView.pts.map((p) => ({ x: p.x, y: p.naive })))} fill="none" stroke={NAIVE} strokeWidth={1.4} />
                  <path d={line(chaosView.pts.map((p) => ({ x: p.x, y: p.kalman })))} fill="none" stroke={KALMAN} strokeWidth={1.8} />
                </>
              ) : (
                normalView && (
                  <>
                    <path d={band(normalView.historicalPts)} fill={MAIN_FILL} />
                    {normalView.gapRuns.map((r, i) => (
                      <rect key={i} x={scaleX(r.start, normalView.count)} y={M.top} width={Math.max(2, scaleX(r.end + 1, normalView.count) - scaleX(r.start, normalView.count))} height={PH} fill={GAP_FILL} />
                    ))}
                    {normalView.forecastPts.length > 1 && <path d={band(normalView.forecastPts)} fill={FORECAST_FILL} stroke="rgba(29,78,216,0.35)" strokeDasharray="3 3" />}
                    <path d={line(normalView.historicalPts.map((p) => ({ x: p.x, y: p.prior })))} fill="none" stroke={PRIOR} strokeWidth={1.1} strokeDasharray="2 3" />
                    <path d={line(normalView.historicalPts.map((p) => ({ x: p.x, y: p.fre })))} fill="none" stroke={MAIN} strokeWidth={1.8} />
                    {normalView.forecastPts.length > 1 && <path d={line(normalView.forecastPts.map((p) => ({ x: p.x, y: p.fre })))} fill="none" stroke={FORECAST} strokeWidth={1.6} strokeDasharray="5 3" />}
                  </>
                )
              )}

              {isChaos && selectedMonth !== null && (() => {
                const indices = dates.map((date, i) => Number(date.slice(5, 7)) === selectedMonth ? i : -1).filter((i) => i >= 0);
                return indices.length ? <rect x={scaleX(indices[0], count)} y={M.top} width={Math.max(1, scaleX(indices[indices.length - 1], count) - scaleX(indices[0], count))} height={PH} fill="rgba(29,78,216,0.08)" /> : null;
              })()}
              {hoverX !== null && <g aria-label="Active day marker"><line x1={hoverX} x2={hoverX} y1={M.top} y2={M.top + PH} stroke="var(--color-reference)" strokeDasharray="3 3" />
                {active && <circle cx={hoverX} cy={scaleY(active.harmonized_fre_mj_km2, yMax)} r={4} fill={MAIN} stroke="var(--color-panel)" strokeWidth={2} />}</g>}
              <rect x={M.left} y={M.top} width={PW} height={PH} fill="transparent" onMouseMove={handleMove} onMouseLeave={() => setHoveredCell(null)} onClick={(e) => {
                const rect = e.currentTarget.getBoundingClientRect();
                const index = Math.max(0, Math.min(count - 1, Math.round((e.clientX - rect.left) / rect.width * (count - 1))));
                if (dates[index]) setSelectedDate(pinned && selectedDate === dates[index] ? null : dates[index], true);
              }} />
            </svg>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-[11px] text-muted">
            {legend.map((item) => (
              <span key={item.label} className="flex items-center gap-1.5">
                <span className="inline-block h-0.5 w-4" style={{ backgroundColor: item.color }} />
                {item.label}
              </span>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function Row({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <p className="flex justify-between text-[9px]">
      <span className="text-faint">{label}</span>
      <span className={color}>{Number.isFinite(value) ? value.toFixed(1) : "—"}</span>
    </p>
  );
}
