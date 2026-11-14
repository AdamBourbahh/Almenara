import { useCallback, useEffect, useRef } from "react";
import { CalendarDays } from "lucide-react";
import { useAnalysisStore } from "../../store/useAnalysisStore";
import { createHatchPattern } from "./HatchPatternDefs";

const WIDTH = 920;
const HEIGHT = 372;
const PAD_LEFT = 48;
const PAD_TOP = 34;
const PAD_RIGHT = 18;
const PAD_BOTTOM = 16;

const START_YEAR = 2001;
const END_YEAR = 2026;
const TOTAL_YEARS = END_YEAR - START_YEAR + 1;
const DAYS = 366;

const MONTHS = [
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
const MONTH_START_DOY = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335];

const HARMONIZED_STOPS = ["#1A1F2B", "#7A2D1E", "#D95F18", "#F2A93B", "#FFE29A"];
const RAW_STOPS = ["#241016", "#6E1621", "#B6212F", "#E5484D", "#FF9AA0"];

function hexToRgb(hex: string): [number, number, number] {
  const value = hex.replace("#", "");
  return [
    parseInt(value.slice(0, 2), 16),
    parseInt(value.slice(2, 4), 16),
    parseInt(value.slice(4, 6), 16),
  ];
}

function rampColor(stops: string[], t: number, alpha: number): string {
  const clamped = Math.max(0, Math.min(1, t));
  const scaled = clamped * (stops.length - 1);
  const index = Math.min(stops.length - 2, Math.floor(scaled));
  const fraction = scaled - index;
  const a = hexToRgb(stops[index]);
  const b = hexToRgb(stops[index + 1]);
  const r = Math.round(a[0] + (b[0] - a[0]) * fraction);
  const g = Math.round(a[1] + (b[1] - a[1]) * fraction);
  const bl = Math.round(a[2] + (b[2] - a[2]) * fraction);
  return `rgba(${r}, ${g}, ${bl}, ${alpha})`;
}

export function BurningCalendarCanvas() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const analysisData = useAnalysisStore((state) => state.analysisData);
  const viewMode = useAnalysisStore((state) => state.viewMode);
  const splitCurtainPct = useAnalysisStore((state) => state.splitCurtainPct);
  const setSplitCurtainPct = useAnalysisStore((state) => state.setSplitCurtainPct);
  const selectedYear = useAnalysisStore((state) => state.selectedYear);
  const setSelectedYear = useAnalysisStore((state) => state.setSelectedYear);
  const setHoveredDay = useAnalysisStore((state) => state.setHoveredDay);

  const plotWidth = WIDTH - PAD_LEFT - PAD_RIGHT;
  const plotHeight = HEIGHT - PAD_TOP - PAD_BOTTOM;
  const cellWidth = plotWidth / DAYS;
  const cellHeight = plotHeight / TOTAL_YEARS;

  const renderCalendar = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = WIDTH * dpr;
    canvas.height = HEIGHT * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, WIDTH, HEIGHT);

    const hatchRepaired = createHatchPattern(
      ctx,
      "rgba(90, 167, 224, 0.55)",
      "rgba(20, 32, 48, 0.35)",
    );
    const hatchForecast = createHatchPattern(
      ctx,
      "rgba(255, 180, 84, 0.7)",
      "rgba(60, 38, 12, 0.4)",
    );

    // Month guides
    ctx.fillStyle = "rgba(152, 161, 176, 0.9)";
    ctx.font = "500 10px 'Inter Variable', system-ui, sans-serif";
    for (let month = 0; month < 12; month += 1) {
      const x = PAD_LEFT + (MONTH_START_DOY[month] - 1) * cellWidth;
      ctx.fillText(MONTHS[month], x + 1, PAD_TOP - 12);
      ctx.strokeStyle = "rgba(255, 255, 255, 0.05)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, PAD_TOP);
      ctx.lineTo(x, HEIGHT - PAD_BOTTOM);
      ctx.stroke();
    }

    // Year labels
    ctx.fillStyle = "rgba(152, 161, 176, 0.85)";
    ctx.font = "500 10px 'IBM Plex Mono', monospace";
    for (let row = 0; row < TOTAL_YEARS; row += 1) {
      const y = PAD_TOP + row * cellHeight;
      ctx.fillText(String(START_YEAR + row), 8, y + cellHeight * 0.78);
    }

    const cells = analysisData?.calendar_series ?? [];
    if (cells.length === 0) {
      ctx.fillStyle = "rgba(255,255,255,0.03)";
      ctx.fillRect(PAD_LEFT, PAD_TOP, plotWidth, plotHeight);
      return;
    }

    let maxRaw = 1;
    let maxFre = 1;
    const cellMap = new Map<string, (typeof cells)[number]>();
    for (const cell of cells) {
      maxRaw = Math.max(maxRaw, cell.raw_hotspot_count);
      maxFre = Math.max(maxFre, cell.harmonized_fre_mj_km2);
      cellMap.set(`${cell.year}-${cell.doy}`, cell);
    }

    const curtainX = PAD_LEFT + plotWidth * (splitCurtainPct / 100);

    for (let row = 0; row < TOTAL_YEARS; row += 1) {
      const year = START_YEAR + row;
      const y = PAD_TOP + row * cellHeight;

      for (let doy = 1; doy <= DAYS; doy += 1) {
        const cell = cellMap.get(`${year}-${doy}`);
        const x = PAD_LEFT + (doy - 1) * cellWidth;

        if (!cell) {
          ctx.fillStyle = "rgba(255, 255, 255, 0.025)";
          ctx.fillRect(x, y, cellWidth - 0.4, cellHeight - 0.4);
          continue;
        }

        const isRawSide = viewMode === "RAW" || x < curtainX;
        if (isRawSide) {
          const t = Math.min(1, cell.raw_hotspot_count / maxRaw);
          ctx.fillStyle = rampColor(RAW_STOPS, t + 0.06, 0.92);
        } else {
          const t = Math.min(1, cell.harmonized_fre_mj_km2 / maxFre);
          ctx.fillStyle = rampColor(HARMONIZED_STOPS, t + 0.06, 0.94);
        }
        ctx.fillRect(x, y, cellWidth - 0.4, cellHeight - 0.4);

        if (cell.is_gap_filled && hatchRepaired) {
          ctx.fillStyle = hatchRepaired;
          ctx.fillRect(x, y, cellWidth - 0.4, cellHeight - 0.4);
        }
      }
    }

    // 14-day forecast band on the last row
    const forecast = analysisData?.forecast_series ?? [];
    if (forecast.length > 0) {
      const y = PAD_TOP + (TOTAL_YEARS - 1) * cellHeight;
      forecast.forEach((_cell, index) => {
        const x = PAD_LEFT + (180 + index) * cellWidth;
        if (hatchForecast) {
          ctx.fillStyle = hatchForecast;
          ctx.fillRect(x, y, cellWidth * 1.4, cellHeight - 0.4);
        }
      });
    }

    // Split curtain
    ctx.strokeStyle = "rgba(255, 107, 61, 0.95)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(curtainX, PAD_TOP - 4);
    ctx.lineTo(curtainX, HEIGHT - PAD_BOTTOM);
    ctx.stroke();
    ctx.fillStyle = "#FF6B3D";
    ctx.beginPath();
    ctx.arc(curtainX, PAD_TOP - 6, 3, 0, Math.PI * 2);
    ctx.fill();

    // Historical markers
    const marker = (doy: number, label: string, color: string) => {
      const x = PAD_LEFT + (doy - 1) * cellWidth;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(x, PAD_TOP);
      ctx.lineTo(x, HEIGHT - PAD_BOTTOM);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = color;
      ctx.font = "500 9px 'Inter Variable', system-ui, sans-serif";
      ctx.fillText(label, x + 4, PAD_TOP + 12);
    };
    marker(1, "Jan 2012 · VIIRS joins", "rgba(255, 180, 84, 0.9)");
    marker(225, "Aug 2022 · Aqua safe mode", "rgba(229, 72, 77, 0.9)");
  }, [analysisData, viewMode, splitCurtainPct, plotWidth, plotHeight, cellWidth, cellHeight]);

  useEffect(() => {
    renderCalendar();
  }, [renderCalendar]);

  const pointToCell = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    const x = ((event.clientX - rect.left) * WIDTH) / rect.width;
    const y = ((event.clientY - rect.top) * HEIGHT) / rect.height;
    const doy = Math.floor((x - PAD_LEFT) / cellWidth) + 1;
    const row = Math.floor((y - PAD_TOP) / cellHeight);
    if (doy < 1 || doy > DAYS || row < 0 || row >= TOTAL_YEARS) return null;
    return { year: START_YEAR + row, doy };
  };

  return (
    <div className="rounded-2xl border border-line bg-surface p-4 shadow-panel">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-ink">
            <CalendarDays className="h-4 w-4 text-ember" />
            Burning activity calendar
            <span className="rounded-md border border-line bg-base/60 px-2 py-0.5 font-mono text-[10px] text-dim">
              {selectedYear}
            </span>
          </h3>
          <p className="mt-0.5 text-xs text-dim">
            Click a row to inspect a year. Drag the curtain to compare raw and
            harmonized data.
          </p>
        </div>

        <div className="flex items-center gap-2 rounded-lg border border-line bg-base/60 px-3 py-1.5">
          <span className="text-[10px] font-medium text-dim">2012 curtain</span>
          <input
            type="range"
            min={0}
            max={100}
            value={splitCurtainPct}
            onChange={(event) => setSplitCurtainPct(Number(event.target.value))}
            className="w-28 accent-ember"
          />
          <span className="w-8 font-tabular text-[11px] text-ink">
            {splitCurtainPct}%
          </span>
        </div>
      </div>

      <div className="relative w-full">
        <canvas
          ref={canvasRef}
          style={{ width: "100%", height: "auto", aspectRatio: `${WIDTH} / ${HEIGHT}` }}
          onClick={(event) => {
            const cell = pointToCell(event);
            if (cell) setSelectedYear(cell.year);
          }}
          onMouseMove={(event) => {
            const cell = pointToCell(event);
            setHoveredDay(cell ? `${cell.year} (DOY: ${cell.doy})` : null);
          }}
          onMouseLeave={() => setHoveredDay(null)}
          className="cursor-crosshair rounded-lg border border-line bg-base"
        />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-[10px] text-dim">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-4 rounded-sm" style={{ background: "linear-gradient(90deg,#241016,#E5484D)" }} />
          Raw counts
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-4 rounded-sm" style={{ background: "linear-gradient(90deg,#7A2D1E,#FFE29A)" }} />
          Harmonized energy
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-4 rounded-sm border border-info/50" style={{ background: "repeating-linear-gradient(45deg, rgba(90,167,224,0.5) 0 2px, transparent 2px 4px)" }} />
          Auto-repaired day
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-4 rounded-sm border border-heat/50" style={{ background: "repeating-linear-gradient(45deg, rgba(255,180,84,0.6) 0 2px, transparent 2px 4px)" }} />
          14-day forecast
        </span>
      </div>
    </div>
  );
}
