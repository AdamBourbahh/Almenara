import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import type { AnalyzeResponse } from "../../api/types";
import { calendarKey, useAnalysisStore, type HoveredDay } from "../../store/useAnalysisStore";
import { getHatchPattern, hatchCss } from "./HatchPatternDefs";

// ============================================================================
// Layout & palette
// ============================================================================

const DAY_COLUMNS = 366;
const CANVAS_CSS_HEIGHT = 340;
const PAD = { left: 46, top: 20, right: 10, bottom: 16 };
const MONTH_START_DOY = [1, 32, 61, 92, 122, 153, 183, 214, 245, 275, 306, 336];
const MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const FONT = "ui-monospace, SFMono-Regular, Menlo, monospace";

const VIIRS_MARKER = { year: 2012, label: "Jan 2012 · Suomi-NPP VIIRS launch", color: "#f59e0b" };
const AQUA_MARKER = { year: 2022, startDoy: 212, endDoy: 228, label: "Aug 2022 · MODIS Aqua Safe Mode", color: "#ef4444" };

const FLAG_DATA = 1;
const FLAG_GAP = 2;
const FLAG_FORECAST = 4;

type Rgb = readonly [number, number, number];

/** 256-entry RGB lookup table interpolated between colour stops. */
function buildRamp(stops: Rgb[]): Uint8ClampedArray {
  const lut = new Uint8ClampedArray(256 * 3);
  for (let i = 0; i < 256; i++) {
    const t = (i / 255) * (stops.length - 1);
    const k = Math.min(stops.length - 2, Math.floor(t));
    const f = t - k;
    for (let c = 0; c < 3; c++) lut[i * 3 + c] = stops[k][c] + (stops[k + 1][c] - stops[k][c]) * f;
  }
  return lut;
}

const RAW_RAMP = buildRamp([[38, 10, 12], [220, 38, 38], [255, 196, 80]]);
const HARM_RAMP = buildRamp([[10, 22, 44], [30, 144, 255], [190, 242, 255]]);
const EMPTY_RGB: Rgb = [15, 23, 42];

// ============================================================================
// Data preparation (once per response, typed arrays)
// ============================================================================

interface PreparedGrid {
  rows: number;
  startYear: number;
  raw: Float32Array;
  harm: Float32Array;
  flags: Uint8Array;
  rawRef: number;
  harmRef: number;
  gapCells: number[];
  forecastCells: number[];
  hasData: boolean;
}

function percentile(values: number[], q: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor(q * (sorted.length - 1)))];
}

function prepareGrid(data: AnalyzeResponse | null, startYear: number, endYear: number): PreparedGrid {
  const rows = Math.max(1, endYear - startYear + 1);
  const size = rows * DAY_COLUMNS;
  const grid: PreparedGrid = {
    rows,
    startYear,
    raw: new Float32Array(size),
    harm: new Float32Array(size),
    flags: new Uint8Array(size),
    rawRef: 1,
    harmRef: 1,
    gapCells: [],
    forecastCells: [],
    hasData: false
  };
  if (!data) return grid;

  // Reference = p95 of the MODIS-only era (pre-2012): post-2012 raw counts saturate -> the artefact pops out.
  const preRaw: number[] = [];
  const preHarm: number[] = [];
  const allRaw: number[] = [];
  const allHarm: number[] = [];

  const place = (year: number, doy: number) => {
    const row = year - startYear;
    if (row < 0 || row >= rows || doy < 1 || doy > DAY_COLUMNS) return -1;
    return row * DAY_COLUMNS + (doy - 1);
  };

  for (const cell of data.calendar_series) {
    const idx = place(cell.year, cell.doy);
    if (idx < 0) continue;
    grid.raw[idx] = cell.raw_hotspot_count;
    grid.harm[idx] = cell.harmonized_fre_mj_km2;
    grid.flags[idx] = FLAG_DATA | (cell.is_gap_filled ? FLAG_GAP : 0);
    if (cell.is_gap_filled) grid.gapCells.push(idx);
    if (cell.raw_hotspot_count > 0) {
      allRaw.push(cell.raw_hotspot_count);
      if (cell.year < VIIRS_MARKER.year) preRaw.push(cell.raw_hotspot_count);
    }
    if (cell.harmonized_fre_mj_km2 > 0) {
      allHarm.push(cell.harmonized_fre_mj_km2);
      if (cell.year < VIIRS_MARKER.year) preHarm.push(cell.harmonized_fre_mj_km2);
    }
  }

  for (const cell of data.forecast_series ?? []) {
    const idx = place(cell.year, cell.doy);
    if (idx < 0 || grid.flags[idx] & FLAG_DATA) continue;
    grid.harm[idx] = cell.harmonized_fre_mj_km2;
    grid.flags[idx] = FLAG_DATA | FLAG_FORECAST;
    grid.forecastCells.push(idx);
  }

  grid.rawRef = Math.max(1, percentile(preRaw.length > 30 ? preRaw : allRaw, 0.95));
  grid.harmRef = Math.max(1, percentile(preHarm.length > 30 ? preHarm : allHarm, 0.95));
  grid.hasData = allRaw.length + allHarm.length > 0 || grid.forecastCells.length > 0;
  grid.gapCells.sort((a, b) => a - b);
  grid.forecastCells.sort((a, b) => a - b);
  return grid;
}

interface Layout {
  width: number;
  height: number;
  gridX: number;
  gridY: number;
  gridW: number;
  gridH: number;
  cellW: number;
  cellH: number;
  rows: number;
  startYear: number;
}

function computeLayout(width: number, rows: number, startYear: number): Layout {
  const gridW = Math.max(1, width - PAD.left - PAD.right);
  const gridH = CANVAS_CSS_HEIGHT - PAD.top - PAD.bottom;
  return {
    width,
    height: CANVAS_CSS_HEIGHT,
    gridX: PAD.left,
    gridY: PAD.top,
    gridW,
    gridH,
    cellW: gridW / DAY_COLUMNS,
    cellH: gridH / rows,
    rows,
    startYear
  };
}

/** Size the backing store to CSS size × devicePixelRatio and return a context in CSS-pixel units. */
function prepareCanvas(canvas: HTMLCanvasElement, L: Layout): CanvasRenderingContext2D | null {
  const dpr = window.devicePixelRatio || 1;
  const pxW = Math.round(L.width * dpr);
  const pxH = Math.round(L.height * dpr);
  if (canvas.width !== pxW) canvas.width = pxW;
  if (canvas.height !== pxH) canvas.height = pxH;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, L.width, L.height);
  return ctx;
}

/** Fill horizontal runs of consecutive cells in one call each (fewer draw calls, continuous stripes). */
function fillRuns(ctx: CanvasRenderingContext2D, L: Layout, sortedIdx: number[]) {
  let i = 0;
  while (i < sortedIdx.length) {
    const start = sortedIdx[i];
    const row = Math.floor(start / DAY_COLUMNS);
    let end = start;
    while (i + 1 < sortedIdx.length && sortedIdx[i + 1] === end + 1 && Math.floor(sortedIdx[i + 1] / DAY_COLUMNS) === row) end = sortedIdx[++i];
    const col = start % DAY_COLUMNS;
    ctx.fillRect(L.gridX + col * L.cellW, L.gridY + row * L.cellH, (end - start + 1) * L.cellW, L.cellH);
    i++;
  }
}

function labelBox(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, color: string, align: "left" | "right" = "left") {
  ctx.font = `9px ${FONT}`;
  const w = ctx.measureText(text).width + 8;
  const bx = align === "left" ? x : x - w;
  ctx.fillStyle = "rgba(7, 11, 20, 0.88)";
  ctx.fillRect(bx, y - 9, w, 12);
  ctx.strokeStyle = color;
  ctx.lineWidth = 1;
  ctx.setLineDash([]);
  ctx.strokeRect(bx + 0.5, y - 8.5, w - 1, 11);
  ctx.fillStyle = color;
  ctx.textAlign = "left";
  ctx.fillText(text, bx + 4, y);
}

// ============================================================================
// Component
// ============================================================================

export const BurningCalendarCanvas: React.FC = () => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const overlayRef = useRef<HTMLCanvasElement | null>(null);
  const offscreenRef = useRef<HTMLCanvasElement | null>(null);
  const renderMsRef = useRef<HTMLSpanElement | null>(null);
  const layoutRef = useRef<Layout | null>(null);
  const [width, setWidth] = useState(0);

  const { analysisData, viewMode, splitCurtainPct, setSplitCurtainPct, selectedYear, setSelectedYear, setHoveredDay, startYear, endYear } =
    useAnalysisStore(
      useShallow((s) => ({
        analysisData: s.analysisData,
        viewMode: s.viewMode,
        splitCurtainPct: s.splitCurtainPct,
        setSplitCurtainPct: s.setSplitCurtainPct,
        selectedYear: s.selectedYear,
        setSelectedYear: s.setSelectedYear,
        setHoveredDay: s.setHoveredDay,
        startYear: s.startYear,
        endYear: s.endYear
      }))
    );

  const grid = useMemo(() => prepareGrid(analysisData, startYear, endYear), [analysisData, startYear, endYear]);

  // Track the CSS width so the backing store matches the displayed size (sharp on HiDPI, exact hit-testing).
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => setWidth(Math.floor(entries[0].contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const drawOverlay = useCallback((hovered: HoveredDay | null) => {
    const canvas = overlayRef.current;
    const L = layoutRef.current;
    if (!canvas || !L) return;
    const ctx = prepareCanvas(canvas, L);
    if (!ctx || !hovered) return;
    const row = hovered.year - L.startYear;
    const col = hovered.doy - 1;
    if (row < 0 || row >= L.rows || col < 0 || col >= DAY_COLUMNS) return;
    const x = L.gridX + col * L.cellW;
    const y = L.gridY + row * L.cellH;
    ctx.fillStyle = "rgba(255, 255, 255, 0.06)";
    ctx.fillRect(L.gridX, y, L.gridW, L.cellH);
    ctx.fillRect(x, L.gridY, L.cellW, L.gridH);
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1;
    ctx.strokeRect(x - 1.5, y - 1.5, L.cellW + 3, L.cellH + 3);
  }, []);

  const renderCalendar = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || width <= 0) return;
    const t0 = performance.now();
    const L = computeLayout(width, grid.rows, grid.startYear);
    layoutRef.current = L;
    const ctx = prepareCanvas(canvas, L);
    if (!ctx) return;

    // 1) Cells: one ImageData pixel per day, upscaled with nearest-neighbour (single drawImage call).
    const offscreen = (offscreenRef.current ??= document.createElement("canvas"));
    if (offscreen.width !== DAY_COLUMNS) offscreen.width = DAY_COLUMNS;
    if (offscreen.height !== grid.rows) offscreen.height = grid.rows;
    const octx = offscreen.getContext("2d");
    if (!octx) return;
    const image = octx.createImageData(DAY_COLUMNS, grid.rows);
    const px = image.data;
    const curtainCol = viewMode === "RAW" ? DAY_COLUMNS : Math.round((DAY_COLUMNS * splitCurtainPct) / 100);
    const rawScale = 1 / (grid.rawRef * 2.5);
    const harmScale = 1 / (grid.harmRef * 1.25);

    for (let idx = 0; idx < grid.flags.length; idx++) {
      const flag = grid.flags[idx];
      const o = idx * 4;
      px[o + 3] = 255;
      if (!(flag & FLAG_DATA)) {
        px[o] = EMPTY_RGB[0];
        px[o + 1] = EMPTY_RGB[1];
        px[o + 2] = EMPTY_RGB[2];
        continue;
      }
      const useRaw = !(flag & FLAG_FORECAST) && idx % DAY_COLUMNS < curtainCol;
      const v = useRaw ? grid.raw[idx] * rawScale : grid.harm[idx] * harmScale;
      const lutIdx = Math.round(Math.pow(Math.min(1, v), 0.6) * 255) * 3;
      const lut = useRaw ? RAW_RAMP : HARM_RAMP;
      px[o] = lut[lutIdx];
      px[o + 1] = lut[lutIdx + 1];
      px[o + 2] = lut[lutIdx + 2];
    }
    octx.putImageData(image, 0, 0);
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(offscreen, L.gridX, L.gridY, L.gridW, L.gridH);

    // 2) Year separators and month guides.
    if (L.cellH >= 6) {
      ctx.fillStyle = "rgba(7, 11, 20, 0.85)";
      for (let r = 1; r < L.rows; r++) ctx.fillRect(L.gridX, L.gridY + r * L.cellH - 0.5, L.gridW, 1);
    }
    ctx.fillStyle = "rgba(148, 163, 184, 0.14)";
    ctx.font = `9px ${FONT}`;
    ctx.textAlign = "left";
    MONTH_START_DOY.forEach((doy, m) => {
      const x = L.gridX + (doy - 1) * L.cellW;
      ctx.fillStyle = "rgba(148, 163, 184, 0.14)";
      ctx.fillRect(x, L.gridY, 1, L.gridH);
      ctx.fillStyle = "#64748b";
      ctx.fillText(MONTH_LABELS[m], x + 2, PAD.top - 7);
    });

    // 3) Hatched overlays: gap-filled (cyan/white) and forecast (gold).
    const gapPattern = getHatchPattern(ctx, "gapFilled");
    if (gapPattern && grid.gapCells.length) {
      ctx.fillStyle = gapPattern;
      fillRuns(ctx, L, grid.gapCells);
    }
    const forecastPattern = getHatchPattern(ctx, "forecast");
    if (forecastPattern && grid.forecastCells.length) {
      ctx.fillStyle = forecastPattern;
      fillRuns(ctx, L, grid.forecastCells);
    }

    // 4) Year labels + selected row.
    const step = L.cellH >= 9 ? 1 : 2;
    for (let r = 0; r < L.rows; r++) {
      const year = L.startYear + r;
      const isSelected = year === selectedYear;
      if (r % step !== 0 && !isSelected && year !== VIIRS_MARKER.year && year !== AQUA_MARKER.year) continue;
      ctx.font = `${isSelected ? "bold " : ""}9px ${FONT}`;
      ctx.fillStyle = isSelected ? "#22d3ee" : "#94a3b8";
      ctx.textAlign = "right";
      ctx.fillText(String(year), L.gridX - 6, L.gridY + r * L.cellH + L.cellH / 2 + 3);
    }
    ctx.textAlign = "left";
    const selRow = selectedYear - L.startYear;
    if (selRow >= 0 && selRow < L.rows) {
      ctx.strokeStyle = "#22d3ee";
      ctx.lineWidth = 1.5;
      ctx.setLineDash([]);
      ctx.strokeRect(L.gridX - 0.75, L.gridY + selRow * L.cellH - 0.75, L.gridW + 1.5, L.cellH + 1.5);
    }

    // 5) Event markers.
    const viirsRow = VIIRS_MARKER.year - L.startYear;
    if (viirsRow >= 0 && viirsRow < L.rows) {
      const y = L.gridY + viirsRow * L.cellH;
      ctx.strokeStyle = VIIRS_MARKER.color;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(L.gridX - 4, y);
      ctx.lineTo(L.gridX + L.gridW, y);
      ctx.stroke();
      labelBox(ctx, VIIRS_MARKER.label, L.gridX + L.gridW - 2, y - 2, VIIRS_MARKER.color, "right");
    }
    const aquaRow = AQUA_MARKER.year - L.startYear;
    if (aquaRow >= 0 && aquaRow < L.rows) {
      const x = L.gridX + (AQUA_MARKER.startDoy - 1) * L.cellW;
      const w = (AQUA_MARKER.endDoy - AQUA_MARKER.startDoy + 1) * L.cellW;
      const y = L.gridY + aquaRow * L.cellH;
      ctx.strokeStyle = AQUA_MARKER.color;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([3, 2]);
      ctx.strokeRect(x - 2, y - 2, w + 4, L.cellH + 4);
      ctx.setLineDash([]);
      const labelWidth = ctx.measureText(AQUA_MARKER.label).width + 8;
      const fitsRight = x + w + 6 + labelWidth < L.gridX + L.gridW;
      labelBox(ctx, AQUA_MARKER.label, fitsRight ? x + w + 6 : x - 6, y + L.cellH / 2 + 3, AQUA_MARKER.color, fitsRight ? "left" : "right");
    }

    // 6) "2012 Time-Machine" split curtain (left = raw counts, right = harmonized FRE).
    if (viewMode === "HARMONIZED") {
      const cx = L.gridX + (L.gridW * splitCurtainPct) / 100;
      ctx.setLineDash([]);
      ctx.strokeStyle = "#38bdf8";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(cx, L.gridY - 4);
      ctx.lineTo(cx, L.gridY + L.gridH + 2);
      ctx.stroke();
      ctx.font = `bold 8px ${FONT}`;
      const tagY = L.gridY + L.gridH + 12;
      if (splitCurtainPct > 6) {
        ctx.fillStyle = "#f87171";
        ctx.textAlign = "right";
        ctx.fillText("◀ RAW COUNTS", cx - 4, tagY);
      }
      if (splitCurtainPct < 94) {
        ctx.fillStyle = "#38bdf8";
        ctx.textAlign = "left";
        ctx.fillText("HARMONIZED FRE ▶", cx + 4, tagY);
      }
      ctx.textAlign = "left";
    }

    if (!grid.hasData) {
      ctx.fillStyle = "#64748b";
      ctx.font = `11px ${FONT}`;
      ctx.textAlign = "center";
      ctx.fillText("Waiting for analysis…", L.gridX + L.gridW / 2, L.gridY + L.gridH / 2);
      ctx.textAlign = "left";
    }

    if (renderMsRef.current) renderMsRef.current.textContent = `${(performance.now() - t0).toFixed(2)} ms`;
    drawOverlay(useAnalysisStore.getState().hoveredDay);
  }, [grid, viewMode, splitCurtainPct, selectedYear, width, drawOverlay]);

  useEffect(() => {
    renderCalendar();
  }, [renderCalendar]);

  // Hover highlight without React re-renders: imperative subscription to hoveredDay.
  useEffect(
    () =>
      useAnalysisStore.subscribe((state, prev) => {
        if (state.hoveredDay !== prev.hoveredDay) drawOverlay(state.hoveredDay);
      }),
    [drawOverlay]
  );

  /** O(1) hit-test: pointer -> (year, doy) by arithmetic, then Map lookup. */
  const locate = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const L = layoutRef.current;
    const canvas = canvasRef.current;
    if (!L || !canvas) return null;
    const rect = canvas.getBoundingClientRect();
    const x = (e.clientX - rect.left) * (L.width / rect.width);
    const y = (e.clientY - rect.top) * (L.height / rect.height);
    const col = Math.floor((x - L.gridX) / L.cellW);
    const row = Math.floor((y - L.gridY) / L.cellH);
    if (col < 0 || col >= DAY_COLUMNS || row < 0 || row >= L.rows) return null;
    return { year: L.startYear + row, doy: col + 1 };
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const loc = locate(e);
    if (loc && useAnalysisStore.getState().calendarIndex.has(calendarKey(loc.year, loc.doy))) {
      setHoveredDay({ ...loc, clientX: e.clientX, clientY: e.clientY });
    } else {
      setHoveredDay(null);
    }
  };

  const handleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const loc = locate(e);
    if (loc) setSelectedYear(loc.year);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLCanvasElement>) => {
    if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedYear(selectedYear + (e.key === "ArrowUp" ? -1 : 1));
    }
  };

  const curtainDisabled = viewMode === "RAW";

  return (
    <div className="bg-slate-950 p-4 rounded-xl border border-slate-800 shadow-2xl text-slate-200">
      <div className="flex flex-wrap items-center justify-between gap-4 mb-3">
        <div>
          <h3 className="text-sm font-bold text-slate-100 flex items-center gap-2">
            <span>🔥 Burning Activity Calendar Matrix ({startYear}–{endYear})</span>
            <span className="text-xs bg-cyan-950 text-cyan-400 px-2 py-0.5 rounded border border-cyan-800 font-mono">
              Selected Year: {selectedYear}
            </span>
          </h3>
          <p className="text-xs text-slate-400">
            Click a row (or use ↑/↓) to inspect a year. Drag the curtain to compare raw pixel counts vs. harmonized FRE physics.
            <span className="ml-2 font-mono text-slate-500">
              render <span ref={renderMsRef}>–</span>
            </span>
          </p>
        </div>

        <label
          className={`flex items-center gap-2 bg-slate-900 px-3 py-1.5 rounded-lg border border-slate-800 text-xs ${curtainDisabled ? "opacity-50" : ""}`}
          title={curtainDisabled ? "Switch to HARMONIZED mode to use the curtain" : "Left: raw counts · Right: harmonized FRE"}
        >
          <span className="font-mono text-cyan-400">2012 Time-Machine Split Curtain</span>
          <input
            type="range"
            min={0}
            max={100}
            value={splitCurtainPct}
            disabled={curtainDisabled}
            onChange={(e) => setSplitCurtainPct(Number(e.target.value))}
            className="w-28 accent-cyan-500 cursor-pointer disabled:cursor-not-allowed"
            aria-label="2012 Time-Machine split curtain position"
          />
          <span className="font-mono text-slate-300 w-9 text-right">{splitCurtainPct}%</span>
        </label>
      </div>

      <div ref={containerRef} className="relative w-full" style={{ height: CANVAS_CSS_HEIGHT }}>
        <canvas
          ref={canvasRef}
          tabIndex={0}
          role="img"
          aria-label={`Burning activity calendar ${startYear}–${endYear}, ${viewMode.toLowerCase()} view`}
          onClick={handleClick}
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setHoveredDay(null)}
          onKeyDown={handleKeyDown}
          className="absolute inset-0 w-full h-full cursor-crosshair rounded-lg border border-slate-800 bg-[#070B14] focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500"
        />
        <canvas ref={overlayRef} aria-hidden="true" className="absolute inset-0 w-full h-full pointer-events-none" />
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] font-mono text-slate-400">
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-8 h-2.5 rounded-sm" style={{ background: "linear-gradient(90deg, rgb(38,10,12), rgb(220,38,38), rgb(255,196,80))" }} />
          Raw hotspot count
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-8 h-2.5 rounded-sm" style={{ background: "linear-gradient(90deg, rgb(10,22,44), rgb(30,144,255), rgb(190,242,255))" }} />
          Harmonized FRE (MJ/km²)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-4 h-2.5 rounded-sm border border-cyan-800" style={{ background: hatchCss("gapFilled") }} />
          Gap-filled (RTS Kalman / cross-guard)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-4 h-2.5 rounded-sm border border-amber-800" style={{ background: hatchCss("forecast") }} />
          14-day forecast
        </span>
      </div>
    </div>
  );
};
