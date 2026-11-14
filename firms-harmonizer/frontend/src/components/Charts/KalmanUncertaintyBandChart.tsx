import { useMemo, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import { Activity, Loader2, Radio } from "lucide-react";
import { useAnalysisStore } from "../../store/useAnalysisStore";
import type { AnalyzeResponse, DailyCalendarCell } from "../../api/types";

/**
 * Kalman uncertainty band chart.
 *
 * Normal mode: plots the selected year's harmonized daily FRE with its 95% CI,
 * the amber dotted cross-sensor historical prior, cyan outage/cloud-gap
 * highlights and the 14-day operational forecast cone.
 *
 * Chaos mode (chaosData !== null): overlays the synthetic ground truth (white),
 * the sabotaged naive series collapsed to zero (red), the cross-sensor guard
 * (amber) and the RTS Kalman reconstruction (emerald) with its 95% CI band.
 */

const WIDTH = 760;
const HEIGHT = 300;
const MARGIN = { top: 18, right: 16, bottom: 30, left: 54 };
const PLOT_W = WIDTH - MARGIN.left - MARGIN.right;
const PLOT_H = HEIGHT - MARGIN.top - MARGIN.bottom;

const HISTORICAL_COLOR = "#5AA7E0";
const PRIOR_COLOR = "#f59e0b";
const FORECAST_COLOR = "#a855f7";
const FORECAST_FILL = "rgba(168, 85, 247, 0.16)";
const CI_FILL = "rgba(90, 167, 224, 0.16)";
const GAP_FILL = "rgba(90, 167, 224, 0.20)";
const CALM_COLOR = "#f8fafc";
const CORRUPT_COLOR = "#ef4444";
const KALMAN_COLOR = "#2FA97A";

function isGapCell(cell: DailyCalendarCell): boolean {
  if (cell.is_gap_filled) return true;
  const reason = (cell.gap_reason ?? "").toLowerCase();
  return (
    reason.includes("outage") ||
    reason.includes("cloud") ||
    reason.includes("blackout") ||
    reason.includes("gap") ||
    reason.includes("sensor")
  );
}

interface NormalPoint {
  date: string;
  fre: number;
  prior: number;
  lower: number;
  upper: number;
  isForecast: boolean;
  isGap: boolean;
  reason: string | null;
}

function buildNormalSeries(
  data: AnalyzeResponse,
  year: number,
): { points: NormalPoint[]; historicalCount: number } | null {
  const yearCells = data.calendar_series.filter((cell) => cell.year === year);
  if (yearCells.length === 0) return null;

  const points: NormalPoint[] = yearCells.map((cell) => ({
    date: cell.date,
    fre: cell.harmonized_fre_mj_km2,
    prior: cell.historical_cross_prior_fre,
    lower: cell.ci_95_lower,
    upper: cell.ci_95_upper,
    isForecast: false,
    isGap: isGapCell(cell),
    reason: cell.gap_reason,
  }));

  for (const cell of data.forecast_series ?? []) {
    points.push({
      date: cell.date,
      fre: cell.harmonized_fre_mj_km2,
      prior: cell.historical_cross_prior_fre,
      lower: cell.ci_95_lower,
      upper: cell.ci_95_upper,
      isForecast: true,
      isGap: false,
      reason: cell.gap_reason,
    });
  }

  return { points, historicalCount: yearCells.length };
}

function scaleX(index: number, count: number): number {
  if (count <= 1) return MARGIN.left;
  return MARGIN.left + (index / (count - 1)) * PLOT_W;
}

function scaleY(value: number, max: number): number {
  return MARGIN.top + PLOT_H - (Math.max(0, value) / max) * PLOT_H;
}

function pickTicks(count: number, tickCount = 6): number[] {
  if (count <= 0) return [];
  const ticks = new Set<number>();
  for (let index = 0; index < tickCount; index += 1) {
    ticks.add(
      Math.max(0, Math.min(count - 1, Math.round((index / (tickCount - 1)) * (count - 1)))),
    );
  }
  return Array.from(ticks).sort((a, b) => a - b);
}

function formatTick(date: string): string {
  const parsed = new Date(`${date}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return date;
  return parsed.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

function toLinePath<T>(
  coords: T[],
  getX: (value: T) => number,
  getY: (value: T) => number,
): string {
  return coords
    .map((value, index) => {
      const command = index === 0 ? "M" : "L";
      return `${command} ${getX(value).toFixed(2)} ${getY(value).toFixed(2)}`;
    })
    .join(" ");
}

function toBandPath<T>(
  coords: T[],
  getX: (value: T) => number,
  getUpper: (value: T) => number,
  getLower: (value: T) => number,
): string {
  if (coords.length === 0) return "";
  const upper = coords
    .map((value, index) => {
      const command = index === 0 ? "M" : "L";
      return `${command} ${getX(value).toFixed(2)} ${getUpper(value).toFixed(2)}`;
    })
    .join(" ");
  const lower = [...coords]
    .reverse()
    .map((value) => `L ${getX(value).toFixed(2)} ${getLower(value).toFixed(2)}`)
    .join(" ");
  return `${upper} ${lower} Z`;
}

export function KalmanUncertaintyBandChart() {
  const analysisData = useAnalysisStore((state) => state.analysisData);
  const selectedYear = useAnalysisStore((state) => state.selectedYear);
  const setSelectedYear = useAnalysisStore((state) => state.setSelectedYear);
  const chaosData = useAnalysisStore((state) => state.chaosData);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const normal = useMemo(() => {
    if (!analysisData) return null;
    return buildNormalSeries(analysisData, selectedYear);
  }, [analysisData, selectedYear]);

  const normalView = useMemo(() => {
    if (!normal) return null;
    const { points, historicalCount } = normal;
    const count = points.length;
    const yMax =
      Math.max(1, ...points.map((point) => Math.max(point.upper, point.fre, point.prior))) *
      1.12;

    const coords = points.map((point, index) => ({
      x: scaleX(index, count),
      fre: scaleY(point.fre, yMax),
      prior: scaleY(point.prior, yMax),
      lower: scaleY(point.lower, yMax),
      upper: scaleY(point.upper, yMax),
    }));

    const historical = coords.slice(0, historicalCount);
    const forecast = coords.slice(Math.max(0, historicalCount - 1));

    const gapRuns: Array<{ start: number; end: number }> = [];
    let runStart = -1;
    points.forEach((point, index) => {
      if (point.isGap && !point.isForecast) {
        if (runStart === -1) runStart = index;
      } else if (runStart !== -1) {
        gapRuns.push({ start: runStart, end: index - 1 });
        runStart = -1;
      }
    });
    if (runStart !== -1) {
      gapRuns.push({ start: runStart, end: points.length - 1 });
    }

    return {
      count,
      yMax,
      coords,
      historicalBand: toBandPath(historical, (c) => c.x, (c) => c.upper, (c) => c.lower),
      forecastBand:
        forecast.length > 1
          ? toBandPath(forecast, (c) => c.x, (c) => c.upper, (c) => c.lower)
          : "",
      priorLine: toLinePath(coords, (c) => c.x, (c) => c.prior),
      historicalLine: toLinePath(historical, (c) => c.x, (c) => c.fre),
      forecastLine:
        forecast.length > 1 ? toLinePath(forecast, (c) => c.x, (c) => c.fre) : "",
      gapRuns,
    };
  }, [normal]);

  const chaosView = useMemo(() => {
    if (!chaosData) return null;
    const count = chaosData.dates.length;
    if (count === 0) return null;

    const yMax =
      Math.max(
        1,
        ...chaosData.true_harmonized_fre,
        ...chaosData.corrupted_naive_fre,
        ...chaosData.historical_cross_guard_fre,
        ...chaosData.kalman_reconstructed_fre,
        ...chaosData.reconstructed_ci_upper,
      ) * 1.12;

    const coords = Array.from({ length: count }, (_unused, index) => ({
      date: chaosData.dates[index],
      x: scaleX(index, count),
      true: scaleY(chaosData.true_harmonized_fre[index] ?? 0, yMax),
      corrupted: scaleY(chaosData.corrupted_naive_fre[index] ?? 0, yMax),
      guard: scaleY(chaosData.historical_cross_guard_fre[index] ?? 0, yMax),
      kalman: scaleY(chaosData.kalman_reconstructed_fre[index] ?? 0, yMax),
      lower: scaleY(chaosData.reconstructed_ci_lower[index] ?? 0, yMax),
      upper: scaleY(chaosData.reconstructed_ci_upper[index] ?? 0, yMax),
    }));

    const zeroPoints = coords
      .map((coord, index) => ({ coord, index }))
      .filter(({ index }) => (chaosData.corrupted_naive_fre[index] ?? 0) <= 1e-9)
      .map(({ coord }) => coord);

    return {
      count,
      yMax,
      coords,
      band: toBandPath(coords, (c) => c.x, (c) => c.upper, (c) => c.lower),
      trueLine: toLinePath(coords, (c) => c.x, (c) => c.true),
      corruptedLine: toLinePath(coords, (c) => c.x, (c) => c.corrupted),
      guardLine: toLinePath(coords, (c) => c.x, (c) => c.guard),
      kalmanLine: toLinePath(coords, (c) => c.x, (c) => c.kalman),
      zeroPoints,
    };
  }, [chaosData]);

  const isChaos = chaosData !== null;
  const count = isChaos
    ? chaosData.dates.length
    : normal?.points.length ?? 0;
  const yMax = (isChaos ? chaosView?.yMax : normalView?.yMax) ?? 1;
  const dates = isChaos
    ? chaosData.dates
    : normal?.points.map((point) => point.date) ?? [];
  const activeCoords = isChaos ? chaosView?.coords ?? [] : normalView?.coords ?? [];

  const availableYears = useMemo(() => {
    const years = analysisData?.phenology_by_year.map((entry) => entry.year) ?? [];
    if (years.length > 0) return years.slice().sort((a, b) => a - b);
    return Array.from({ length: 26 }, (_unused, index) => 2001 + index);
  }, [analysisData]);

  const handleMove = (event: ReactMouseEvent<SVGRectElement>) => {
    if (count <= 0) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const ratio = bounds.width > 0 ? (event.clientX - bounds.left) / bounds.width : 0;
    const index = Math.round(ratio * (count - 1));
    setHoverIndex(Math.max(0, Math.min(count - 1, index)));
  };

  const yTicks = [0, yMax * 0.25, yMax * 0.5, yMax * 0.75, yMax];
  const xTicks = pickTicks(count);
  const hoverCoord =
    hoverIndex !== null && hoverIndex < activeCoords.length
      ? activeCoords[hoverIndex]
      : null;

  const renderTooltip = () => {
    if (!hoverCoord || hoverIndex === null) return null;
    const leftPercent = (hoverCoord.x / WIDTH) * 100;
    const date = dates[hoverIndex];

    if (isChaos && chaosData) {
      return (
        <div
          className="pointer-events-none absolute top-2 z-20 w-52 -translate-x-1/2 rounded-lg border border-slate-700 bg-slate-950/95 p-2 text-[10px] shadow-2xl"
          style={{ left: `${Math.min(88, Math.max(12, leftPercent))}%` }}
        >
          <p className="mb-1 font-mono text-info">{date}</p>
          <Row label="Ground truth" value={chaosData.true_harmonized_fre[hoverIndex]} color="text-slate-100" />
          <Row label="Naive (sabotaged)" value={chaosData.corrupted_naive_fre[hoverIndex]} color="text-red-400" />
          <Row label="Cross guard" value={chaosData.historical_cross_guard_fre[hoverIndex]} color="text-amber-300" />
          <Row label="RTS Kalman" value={chaosData.kalman_reconstructed_fre[hoverIndex]} color="text-emerald-400" />
        </div>
      );
    }

    const point = normal?.points[hoverIndex];
    if (!point) return null;
    return (
      <div
        className="pointer-events-none absolute top-2 z-20 w-52 -translate-x-1/2 rounded-lg border border-slate-700 bg-slate-950/95 p-2 text-[10px] shadow-2xl"
        style={{ left: `${Math.min(88, Math.max(12, leftPercent))}%` }}
      >
        <p className="mb-1 flex items-center justify-between font-mono text-info">
          <span>{point.date}</span>
          {point.isForecast && (
            <span className="rounded bg-violet-500/20 px-1 text-[8px] uppercase text-violet-300">
              forecast
            </span>
          )}
        </p>
        <Row label="Harmonized FRE" value={point.fre} color="text-info" />
        <Row label="Cross prior" value={point.prior} color="text-amber-300" />
        <p className="mt-1 flex justify-between font-mono text-[9px] text-slate-400">
          <span>95% CI</span>
          <span className="text-emerald-300">
            [{point.lower.toFixed(1)} – {point.upper.toFixed(1)}]
          </span>
        </p>
        {point.reason && (
          <p className="mt-1 text-[9px] italic text-sky-300">{point.reason}</p>
        )}
      </div>
    );
  };

  if (!analysisData) {
    return (
      <section className="rounded-2xl border border-line bg-surface p-4 shadow-panel">
        <Header isChaos={false} selectedYear={selectedYear} years={availableYears} onYearChange={setSelectedYear} />
        <div className="flex h-56 items-center justify-center gap-2 text-xs text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin text-ember" />
          Loading daily harmonized series…
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-2xl border border-line bg-surface p-4 shadow-panel">
      <Header
        isChaos={isChaos}
        selectedYear={selectedYear}
        years={availableYears}
        onYearChange={setSelectedYear}
      />

      {count === 0 ? (
        <div className="flex h-56 items-center justify-center text-xs text-slate-400">
          No daily series available for {selectedYear}.
        </div>
      ) : (
        <>
          <div className="relative">
            {renderTooltip()}
            <svg
              viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
              className="h-auto w-full"
              role="img"
              aria-label="Kalman harmonized FRE uncertainty band chart"
            >
              {/* Y grid + labels */}
              {yTicks.map((tick) => (
                <g key={tick}>
                  <line
                    x1={MARGIN.left}
                    x2={WIDTH - MARGIN.right}
                    y1={scaleY(tick, yMax)}
                    y2={scaleY(tick, yMax)}
                    stroke="rgba(148, 163, 184, 0.10)"
                  />
                  <text
                    x={MARGIN.left - 8}
                    y={scaleY(tick, yMax)}
                    textAnchor="end"
                    dominantBaseline="middle"
                    fill="#64748b"
                    fontSize="9"
                    fontFamily="ui-monospace, monospace"
                  >
                    {tick.toFixed(0)}
                  </text>
                </g>
              ))}

              {/* X ticks */}
              {xTicks.map((index) => {
                const x = scaleX(index, count);
                const label = dates[index] ? formatTick(dates[index]) : "";
                return (
                  <g key={index}>
                    <line
                      x1={x}
                      x2={x}
                      y1={MARGIN.top + PLOT_H}
                      y2={MARGIN.top + PLOT_H + 4}
                      stroke="rgba(148, 163, 184, 0.35)"
                    />
                    <text
                      x={x}
                      y={MARGIN.top + PLOT_H + 16}
                      textAnchor="middle"
                      fill="#64748b"
                      fontSize="9"
                      fontFamily="ui-monospace, monospace"
                    >
                      {label}
                    </text>
                  </g>
                );
              })}

              {isChaos && chaosView ? (
                <>
                  <path d={chaosView.band} fill="rgba(16, 185, 129, 0.16)" />
                  <path d={chaosView.trueLine} fill="none" stroke={CALM_COLOR} strokeWidth={1.6} />
                  <path
                    d={chaosView.guardLine}
                    fill="none"
                    stroke={PRIOR_COLOR}
                    strokeWidth={1.4}
                    strokeDasharray="3 3"
                  />
                  <path
                    d={chaosView.corruptedLine}
                    fill="none"
                    stroke={CORRUPT_COLOR}
                    strokeWidth={1.7}
                  />
                  {chaosView.zeroPoints.map((coord, index) => (
                    <circle
                      key={index}
                      cx={coord.x}
                      cy={coord.corrupted}
                      r={2.4}
                      fill={CORRUPT_COLOR}
                    />
                  ))}
                  <path
                    d={chaosView.kalmanLine}
                    fill="none"
                    stroke={KALMAN_COLOR}
                    strokeWidth={2}
                  />
                </>
              ) : (
                normalView && (
                  <>
                    <path d={normalView.historicalBand} fill={CI_FILL} />
                    {normalView.gapRuns.map((run, index) => {
                      const x0 = scaleX(run.start, normalView.count);
                      const x1 = scaleX(run.end + 1, normalView.count);
                      return (
                        <rect
                          key={index}
                          x={x0}
                          y={MARGIN.top}
                          width={Math.max(1.5, x1 - x0)}
                          height={PLOT_H}
                          fill={GAP_FILL}
                        />
                      );
                    })}
                    {normalView.forecastBand && (
                      <path
                        d={normalView.forecastBand}
                        fill={FORECAST_FILL}
                        stroke="rgba(168, 85, 247, 0.5)"
                        strokeDasharray="3 3"
                      />
                    )}
                    <path
                      d={normalView.priorLine}
                      fill="none"
                      stroke={PRIOR_COLOR}
                      strokeWidth={1.4}
                      strokeDasharray="2 3"
                    />
                    <path
                      d={normalView.historicalLine}
                      fill="none"
                      stroke={HISTORICAL_COLOR}
                      strokeWidth={2}
                    />
                    {normalView.forecastLine && (
                      <path
                        d={normalView.forecastLine}
                        fill="none"
                        stroke={FORECAST_COLOR}
                        strokeWidth={2}
                        strokeDasharray="5 3"
                      />
                    )}
                  </>
                )
              )}

              {/* Hover crosshair */}
              {hoverCoord && (
                <line
                  x1={hoverCoord.x}
                  x2={hoverCoord.x}
                  y1={MARGIN.top}
                  y2={MARGIN.top + PLOT_H}
                  stroke="rgba(226, 232, 240, 0.45)"
                  strokeDasharray="3 3"
                />
              )}

              {/* Interaction surface */}
              <rect
                x={MARGIN.left}
                y={MARGIN.top}
                width={PLOT_W}
                height={PLOT_H}
                fill="transparent"
                onMouseMove={handleMove}
                onMouseLeave={() => setHoverIndex(null)}
              />
            </svg>
          </div>

          <Legend isChaos={isChaos} />
        </>
      )}
    </section>
  );
}

function Header({
  isChaos,
  selectedYear,
  years,
  onYearChange,
}: {
  isChaos: boolean;
  selectedYear: number;
  years: number[];
  onYearChange: (year: number) => void;
}) {
  return (
    <header className="mb-2 flex flex-wrap items-center justify-between gap-2">
      <div className="flex items-center gap-2">
        <Activity className="h-4 w-4 text-ember" />
        <h2 className="text-sm font-bold text-slate-100">
          Kalman Uncertainty Band
          <span className="ml-2 font-mono text-[10px] font-normal uppercase tracking-wider text-slate-500">
            RTS · 95% CI · 14-day forecast
          </span>
        </h2>
      </div>
      <div className="flex items-center gap-2">
        {isChaos ? (
          <span className="flex items-center gap-1 rounded border border-red-700/60 bg-red-500/10 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-red-300">
            <Radio className="h-3 w-3" /> Chaos overlay active
          </span>
        ) : (
          <>
            <label className="font-mono text-[10px] uppercase tracking-wider text-slate-500">
              Year
            </label>
            <select
              value={selectedYear}
              onChange={(event) => onYearChange(Number(event.target.value))}
              className="rounded border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-[11px] text-slate-200 focus:outline-none focus:ring-2 focus:ring-ember/50"
            >
              {years.map((year) => (
                <option key={year} value={year}>
                  {year}
                </option>
              ))}
            </select>
          </>
        )}
      </div>
    </header>
  );
}

function Legend({ isChaos }: { isChaos: boolean }) {
  const items = isChaos
    ? [
        { color: CALM_COLOR, label: "Ground truth", dashed: false },
        { color: CORRUPT_COLOR, label: "Naive / sabotaged", dashed: false },
        { color: PRIOR_COLOR, label: "Cross-sensor guard", dashed: true },
        { color: KALMAN_COLOR, label: "RTS Kalman + 95% CI", dashed: false },
      ]
    : [
        { color: HISTORICAL_COLOR, label: "Harmonized FRE", dashed: false },
        { color: PRIOR_COLOR, label: "Cross-sensor prior", dashed: true },
        { color: FORECAST_COLOR, label: "14-day forecast", dashed: true },
        { color: GAP_FILL, label: "Sensor outage / cloud gap", dashed: false },
      ];

  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
      {items.map((item) => (
        <span
          key={item.label}
          className="flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-wider text-slate-400"
        >
          <span
            className="inline-block h-0.5 w-4 rounded"
            style={{
              backgroundColor: item.color,
              borderTop: item.dashed ? `1px dashed ${item.color}` : undefined,
            }}
          />
          {item.label}
        </span>
      ))}
    </div>
  );
}

function Row({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color: string;
}) {
  return (
    <p className="flex justify-between font-mono text-[9px]">
      <span className="text-slate-400">{label}</span>
      <span className={color}>{Number.isFinite(value) ? value.toFixed(1) : "—"}</span>
    </p>
  );
}
