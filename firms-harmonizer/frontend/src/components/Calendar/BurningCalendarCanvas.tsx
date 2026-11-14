import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import type { AnalyzeResponse } from "../../api/types";
import { useAnalysisStore, type HoveredDay } from "../../store/useAnalysisStore";
import { getHatchPattern, hatchCss } from "./HatchPatternDefs";
import { useTheme } from "../../lib/theme";

const DAY_COLUMNS = 366;
const CANVAS_CSS_HEIGHT = 340;
const PAD = { left: 46, top: 20, right: 10, bottom: 16 };
const MONTH_START_DOY = [1, 32, 61, 92, 122, 153, 183, 214, 245, 275, 306, 336];
const MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const FONT = "ui-monospace, SFMono-Regular, Menlo, monospace";

const VIIRS_MARKER = { year: 2012, label: "Jan 2012 · VIIRS comes online", color: "#b45309" };
const SNPP_MARKER = { year: 2022, startDoy: 208, endDoy: 222, label: "Jul-Aug 2022 · VIIRS SNPP outage (15 d)", color: "#b91c1c" };

const FLAG_DATA = 1;
const FLAG_GAP = 2;
const FLAG_FORECAST = 4;

type Rgb = readonly [number, number, number];

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

const HARM_RAMP = buildRamp([[254, 240, 217], [253, 190, 133], [230, 85, 13], [179, 0, 0]]);
const RAW_RAMP_LIGHT = buildRamp([[229, 231, 235], [156, 163, 175], [71, 85, 105]]);
const RAW_RAMP_DARK = buildRamp([[42, 47, 58], [107, 114, 128], [203, 213, 225]]);
const EMPTY_LIGHT: Rgb = [239, 238, 235];
const EMPTY_DARK: Rgb = [24, 28, 38];

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

function labelBox(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, color: string, bg: string, align: "left" | "right" = "left") {
  ctx.font = `9px ${FONT}`;
  const w = ctx.measureText(text).width + 8;
  const bx = align === "left" ? x : x - w;
  ctx.fillStyle = bg;
  ctx.fillRect(bx, y - 9, w, 12);
  ctx.strokeStyle = color;
  ctx.lineWidth = 1;
  ctx.setLineDash([]);
  ctx.strokeRect(bx + 0.5, y - 8.5, w - 1, 11);
  ctx.fillStyle = color;
  ctx.textAlign = "left";
  ctx.fillText(text, bx + 4, y);
}

export function BurningCalendarCanvas() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const baseRef = useRef<HTMLCanvasElement | null>(null);
  const hoverFrame = useRef<number | null>(null);
  const offscreenRef = useRef<HTMLCanvasElement | null>(null);
  const layoutRef = useRef<Layout | null>(null);
  const [width, setWidth] = useState(0);

  const theme = useTheme((s) => s.theme);
  const { analysisData, viewMode, splitCurtainPct, setSplitCurtainPct, selectedYear, selectedMonth, setHoveredDay, startYear, endYear } =
    useAnalysisStore(
      useShallow((s) => ({
        analysisData: s.analysisData,
        viewMode: s.viewMode,
        splitCurtainPct: s.splitCurtainPct,
        setSplitCurtainPct: s.setSplitCurtainPct,
        selectedYear: s.selectedYear,
        selectedMonth: s.selectedMonth,
        setHoveredDay: s.setHoveredDay,
        startYear: s.startYear,
        endYear: s.endYear
      }))
    );

  const grid = useMemo(() => prepareGrid(analysisData, startYear, endYear), [analysisData, startYear, endYear]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => setWidth(Math.floor(entries[0].contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const drawOverlay = useCallback((hovered: HoveredDay | null) => {
    const canvas = canvasRef.current;
    const L = layoutRef.current;
    if (!canvas || !L) return;
    const ctx = canvas.getContext("2d");
    if (!ctx || !baseRef.current) return;
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, L.width, L.height);
    ctx.drawImage(baseRef.current, 0, 0, L.width, L.height);
    const state = useAnalysisStore.getState();
    const active = state.isDatePinned && state.selectedDate ? state.dateIndex.get(state.selectedDate) : state.hoveredCell;
    if (active) hovered = { year: active.year, doy: active.doy, clientX: 0, clientY: 0 };
    if (!hovered) return;
    const row = hovered.year - L.startYear;
    const col = hovered.doy - 1;
    if (row < 0 || row >= L.rows || col < 0 || col >= DAY_COLUMNS) return;
    const x = L.gridX + col * L.cellW;
    const y = L.gridY + row * L.cellH;
    ctx.fillStyle = theme === "dark" ? "rgba(255,255,255,0.10)" : "rgba(17,24,39,0.06)";
    ctx.fillRect(L.gridX, y, L.gridW, L.cellH);
    ctx.fillRect(x, L.gridY, L.cellW, L.gridH);
    ctx.strokeStyle = theme === "dark" ? "#e6e9ef" : "#111827";
    ctx.lineWidth = 1;
    ctx.strokeRect(x - 1.5, y - 1.5, L.cellW + 3, L.cellH + 3);
  }, [theme]);

  const renderCalendar = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || width <= 0) return;
    const L = computeLayout(width, grid.rows, grid.startYear);
    layoutRef.current = L;
    const ctx = prepareCanvas(canvas, L);
    if (!ctx) return;

    const isDark = theme === "dark";
    const rawRamp = isDark ? RAW_RAMP_DARK : RAW_RAMP_LIGHT;
    const emptyRgb = isDark ? EMPTY_DARK : EMPTY_LIGHT;
    const gridLine = isDark ? "rgba(255,255,255,0.08)" : "rgba(220,220,220,0.85)";
    const guideLine = isDark ? "rgba(255,255,255,0.10)" : "rgba(196,196,196,0.55)";
    const monthLabel = isDark ? "#7b8494" : "#6b7280";
    const yearLabel = isDark ? "#9aa3b2" : "#4b5563";
    const labelBg = isDark ? "rgba(18,22,31,0.94)" : "rgba(255,255,255,0.94)";

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
        px[o] = emptyRgb[0];
        px[o + 1] = emptyRgb[1];
        px[o + 2] = emptyRgb[2];
        continue;
      }
      const useRaw = !(flag & FLAG_FORECAST) && idx % DAY_COLUMNS < curtainCol;
      const v = useRaw ? grid.raw[idx] * rawScale : grid.harm[idx] * harmScale;
      const lutIdx = Math.round(Math.pow(Math.min(1, v), 0.6) * 255) * 3;
      const lut = useRaw ? rawRamp : HARM_RAMP;
      px[o] = lut[lutIdx];
      px[o + 1] = lut[lutIdx + 1];
      px[o + 2] = lut[lutIdx + 2];
    }
    octx.putImageData(image, 0, 0);
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(offscreen, L.gridX, L.gridY, L.gridW, L.gridH);
    if (selectedMonth !== null) {
      ctx.fillStyle = isDark ? "rgba(0,0,0,0.60)" : "rgba(255,255,255,0.65)";
      for (let row = 0; row < grid.rows; row++) {
        const year = grid.startYear + row;
        const offset = Date.UTC(year, 0, 1);
        const left = (Date.UTC(year, selectedMonth - 1, 1) - offset) / 86400000;
        const right = (Date.UTC(year, selectedMonth, 1) - offset) / 86400000;
        ctx.fillRect(L.gridX, L.gridY + row * L.cellH, left * L.cellW, L.cellH);
        ctx.fillRect(L.gridX + right * L.cellW, L.gridY + row * L.cellH, (DAY_COLUMNS - right) * L.cellW, L.cellH);
      }
    }

    if (L.cellH >= 6) {
      ctx.fillStyle = gridLine;
      for (let r = 1; r < L.rows; r++) ctx.fillRect(L.gridX, L.gridY + r * L.cellH - 0.5, L.gridW, 1);
    }
    ctx.font = `9px ${FONT}`;
    ctx.textAlign = "left";
    const monthStarts = MONTH_START_DOY.map((_, m) => 1 + (Date.UTC(selectedYear, m, 1) - Date.UTC(selectedYear, 0, 1)) / 86400000);
    monthStarts.forEach((doy, m) => {
      const x = L.gridX + (doy - 1) * L.cellW;
      ctx.fillStyle = guideLine;
      ctx.fillRect(x, L.gridY, 1, L.gridH);
      ctx.fillStyle = monthLabel;
      ctx.fillText(MONTH_LABELS[m], x + 2, PAD.top - 7);
    });

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

    const step = L.cellH >= 9 ? 1 : 2;
    for (let r = 0; r < L.rows; r++) {
      const year = L.startYear + r;
      const isSelected = year === selectedYear;
      if (r % step !== 0 && !isSelected && year !== VIIRS_MARKER.year && year !== SNPP_MARKER.year) continue;
      ctx.font = `${isSelected ? "bold " : ""}9px ${FONT}`;
      ctx.fillStyle = isSelected ? "#b30000" : yearLabel;
      ctx.textAlign = "right";
      ctx.fillText(String(year), L.gridX - 6, L.gridY + r * L.cellH + L.cellH / 2 + 3);
    }
    ctx.textAlign = "left";
    const selRow = selectedYear - L.startYear;
    if (selRow >= 0 && selRow < L.rows) {
      ctx.strokeStyle = "#b30000";
      ctx.lineWidth = 1.5;
      ctx.setLineDash([]);
      ctx.strokeRect(L.gridX - 0.75, L.gridY + selRow * L.cellH - 0.75, L.gridW + 1.5, L.cellH + 1.5);
    }

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
      labelBox(ctx, VIIRS_MARKER.label, L.gridX + L.gridW - 2, y - 2, VIIRS_MARKER.color, labelBg, "right");
    }
    const snppRow = SNPP_MARKER.year - L.startYear;
    if (snppRow >= 0 && snppRow < L.rows) {
      const x = L.gridX + (SNPP_MARKER.startDoy - 1) * L.cellW;
      const w = (SNPP_MARKER.endDoy - SNPP_MARKER.startDoy + 1) * L.cellW;
      const y = L.gridY + snppRow * L.cellH;
      ctx.strokeStyle = SNPP_MARKER.color;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([3, 2]);
      ctx.strokeRect(x - 2, y - 2, w + 4, L.cellH + 4);
      ctx.setLineDash([]);
      ctx.font = `9px ${FONT}`;
      const labelWidth = ctx.measureText(SNPP_MARKER.label).width + 8;
      const fitsRight = x + w + 6 + labelWidth < L.gridX + L.gridW;
      labelBox(ctx, SNPP_MARKER.label, fitsRight ? x + w + 6 : x - 6, y + L.cellH / 2 + 3, SNPP_MARKER.color, labelBg, fitsRight ? "left" : "right");
    }

    if (viewMode === "HARMONIZED") {
      const cx = L.gridX + (L.gridW * splitCurtainPct) / 100;
      ctx.setLineDash([]);
      ctx.strokeStyle = "#1d4ed8";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(cx, L.gridY - 4);
      ctx.lineTo(cx, L.gridY + L.gridH + 2);
      ctx.stroke();
      ctx.font = `bold 8px ${FONT}`;
      const tagY = L.gridY + L.gridH + 12;
      if (splitCurtainPct > 6) {
        ctx.fillStyle = isDark ? "#9aa3b2" : "#475569";
        ctx.textAlign = "right";
        ctx.fillText("◀ RAW COUNTS", cx - 4, tagY);
      }
      if (splitCurtainPct < 94) {
        ctx.fillStyle = "#b30000";
        ctx.textAlign = "left";
        ctx.fillText("HARMONIZED ENERGY ▶", cx + 4, tagY);
      }
      ctx.textAlign = "left";
    }

    if (!grid.hasData) {
      ctx.fillStyle = monthLabel;
      ctx.font = `11px ${FONT}`;
      ctx.textAlign = "center";
      ctx.fillText("Waiting for the analysis…", L.gridX + L.gridW / 2, L.gridY + L.gridH / 2);
      ctx.textAlign = "left";
    }

    const base = (baseRef.current ??= document.createElement("canvas"));
    base.width = canvas.width; base.height = canvas.height;
    base.getContext("2d")?.drawImage(canvas, 0, 0);
    drawOverlay(useAnalysisStore.getState().hoveredDay);
  }, [grid, viewMode, splitCurtainPct, selectedYear, selectedMonth, width, drawOverlay, theme]);

  useEffect(() => {
    renderCalendar();
  }, [renderCalendar]);

  useEffect(
    () =>
      useAnalysisStore.subscribe((state, prev) => {
        if (state.hoveredDay !== prev.hoveredDay || state.hoveredCell !== prev.hoveredCell || state.selectedDate !== prev.selectedDate || state.isDatePinned !== prev.isDatePinned) drawOverlay(state.hoveredDay);
      }),
    [drawOverlay]
  );

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
    const point = loc ? { ...loc, clientX: e.clientX, clientY: e.clientY } : null;
    if (hoverFrame.current !== null) cancelAnimationFrame(hoverFrame.current);
    hoverFrame.current = requestAnimationFrame(() => {
      hoverFrame.current = null;
      setHoveredDay(point && useAnalysisStore.getState().yearDoyIndex.has(`${point.year}-${point.doy}`) ? point : null);
    });
  };
  useEffect(() => () => { if (hoverFrame.current !== null) cancelAnimationFrame(hoverFrame.current); }, []);

  const handleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const L = layoutRef.current;
    const rect = e.currentTarget.getBoundingClientRect();
    const state = useAnalysisStore.getState();
    if (L) {
      const x = (e.clientX - rect.left) * L.width / rect.width;
      const y = (e.clientY - rect.top) * L.height / rect.height;
      if (y < L.gridY && x >= L.gridX && x < L.gridX + L.gridW) {
        const doy = Math.floor((x - L.gridX) / L.cellW) + 1;
        const month = new Date(Date.UTC(selectedYear, 0, doy)).getUTCMonth() + 1;
        state.setSelectedMonth(state.selectedMonth === month ? null : month);
        return;
      }
    }
    const loc = locate(e);
    const cell = loc ? state.yearDoyIndex.get(`${loc.year}-${loc.doy}`) : null;
    if (!cell) return;
    const unpin = state.isDatePinned && state.selectedDate === cell.date;
    state.setSelectedDate(null);
    state.setHoveredDay({ year: cell.year, doy: cell.doy, clientX: e.clientX, clientY: e.clientY });
    if (!unpin) state.setSelectedDate(cell.date, true);
  };

  const curtainDisabled = viewMode === "RAW";

  return (
    <div className="border border-rule bg-panel p-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-2xl">
          <h3 className="font-serif text-lg text-ink">
            Burning activity calendar ({startYear}–{endYear})
          </h3>
          <p className="mt-1 text-sm leading-relaxed text-muted">
            Each row is a year, each column a day. Drag the curtain to put raw hot-spot counts on the
            left against harmonized fire energy on the right.
          </p>
        </div>

        <label
          className={`flex items-center gap-2 border border-rule px-3 py-1.5 text-xs ${curtainDisabled ? "opacity-50" : ""}`}
          title={curtainDisabled ? "Switch to Harmonized to use the curtain" : "Left: raw counts · right: harmonized energy"}
        >
          <span className="text-muted">2012 curtain</span>
          <input
            type="range"
            min={0}
            max={100}
            value={splitCurtainPct}
            disabled={curtainDisabled}
            onChange={(e) => setSplitCurtainPct(Number(e.target.value))}
            className="w-28 cursor-pointer accent-[#1d4ed8] disabled:cursor-not-allowed"
            aria-label="2012 curtain position"
          />
          <span className="w-9 text-right text-ink tnum">{splitCurtainPct}%</span>
        </label>
      </div>

      <div ref={containerRef} className="relative w-full border border-rule" style={{ height: CANVAS_CSS_HEIGHT }}>
        <canvas
          ref={canvasRef}
          tabIndex={0}
          role="img"
          aria-label={`Burning activity calendar ${startYear}–${endYear}, ${viewMode === "RAW" ? "raw" : "harmonized"} view`}
          onClick={handleClick}
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setHoveredDay(null)}
          className="absolute inset-0 h-full w-full cursor-crosshair bg-panel focus:outline-none focus-visible:ring-2 focus-visible:ring-reference"
        />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-[11px] text-muted">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-8" style={{ background: "linear-gradient(90deg, rgb(229,231,235), rgb(71,85,105))" }} />
          Raw hot-spot count
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-8" style={{ background: "linear-gradient(90deg, rgb(254,240,217), rgb(253,190,133), rgb(230,85,13), rgb(179,0,0))" }} />
          Harmonized energy (MJ/km²)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-4 border border-rule" style={{ background: hatchCss("gapFilled") }} />
          Repaired (Kalman)
        </span>
        {(analysisData?.forecast_series?.length ?? 0) > 0 && (
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-4 border border-rule" style={{ background: hatchCss("forecast") }} />
            14-day forecast
          </span>
        )}
      </div>
    </div>
  );
}
