import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent } from "react";
import { CalendarDays, ChevronDown, ChevronLeft, ChevronRight, Clock3 } from "lucide-react";
import { useShallow } from "zustand/react/shallow";
import { isoDate, useAnalysisStore } from "../../store/useAnalysisStore";
import { DateSelectionPopover } from "./DateSelectionPopover";
import type { DatePrecision, DateSelection } from "./DateSelectionPopover";

type Period = { key: string; detections: number };
const UNITS: Array<{ value: DatePrecision; label: string }> = [
  { value: "day", label: "Day" }, { value: "month", label: "Month" }, { value: "year", label: "Year" }
];
const formatDay = (date: string) => new Date(`${date}T00:00:00Z`).toLocaleDateString("en-US", {
  day: "numeric", month: "short", year: "numeric", timeZone: "UTC"
});
const formatMonth = (date: string) => new Date(`${date}T00:00:00Z`).toLocaleDateString("en-US", {
  month: "long", year: "numeric", timeZone: "UTC"
});

/** One applied period drives the map, totals and attached chat context. */
export function HeatHistoryCard() {
  const state = useAnalysisStore(useShallow(s => ({
    data: s.analysisData, year: s.selectedYear, month: s.selectedMonth, date: s.selectedDate,
    loading: s.loading, error: s.error, min: s.minDate, max: s.maxDate
  })));
  const precision: DatePrecision = state.date ? "day" : state.month ? "month" : "year";
  const anchor = state.date ?? isoDate(state.year, state.month ?? 1, 1);
  const end = state.date ?? isoDate(state.year, state.month ?? 12, 31);
  const label = precision === "day" ? formatDay(anchor) : precision === "month" ? formatMonth(anchor) : String(state.year);
  const [open, setOpen] = useState(false);
  const [hovered, setHovered] = useState<number | null>(null);
  const container = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(400);
  const unavailable = state.loading || !state.data?.calendar_series.length;
  const histogramUnit = precision;
  const keyLength = precision === "day" ? 10 : precision === "month" ? 7 : 4;

  const countsByDate = useMemo(() => {
    const counts = new Map<string, number>();
    for (const cell of state.data?.calendar_series ?? []) counts.set(cell.date, cell.raw_hotspot_count);
    return counts;
  }, [state.data]);

  const detections = useMemo(() => {
    let total = 0;
    for (const cell of state.data?.calendar_series ?? []) {
      if (cell.date >= anchor && cell.date <= end) total += cell.raw_hotspot_count;
    }
    return total;
  }, [state.data, anchor, end]);

  useEffect(() => {
    const node = trackRef.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(1, entry.contentRect.width)));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!open) return;
    const outside = (event: globalThis.PointerEvent) => {
      if (event.target instanceof Node && !container.current?.contains(event.target)) setOpen(false);
    };
    const escape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") { event.stopPropagation(); setOpen(false); trigger.current?.focus(); }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape, true);
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", escape, true); };
  }, [open]);

  const periods = useMemo(() => {
    const grouped = new Map<string, Period>();
    for (const cell of state.data?.calendar_series ?? []) {
      // Daily bars cover the selected month; monthly bars cover the selected year.
      if (precision === "day" && !cell.date.startsWith(anchor.slice(0, 7))) continue;
      if (precision === "month" && cell.year !== state.year) continue;
      const key = cell.date.slice(0, keyLength);
      const entry = grouped.get(key);
      if (entry) entry.detections += cell.raw_hotspot_count;
      else grouped.set(key, { key, detections: cell.raw_hotspot_count });
    }
    return [...grouped.values()].sort((a, b) => a.key.localeCompare(b.key));
  }, [state.data, state.year, anchor, precision, keyLength]);

  const position = Math.max(0, periods.findIndex(p => p.key === anchor.slice(0, keyLength)));
  const bins = useMemo(() => {
    const count = Math.min(periods.length, Math.max(1, Math.floor(width / 14)));
    return Array.from({ length: count }, (_, i) => {
      const start = Math.floor(i * periods.length / count);
      const finish = Math.floor((i + 1) * periods.length / count);
      return { start, end: finish, detections: periods.slice(start, finish).reduce((sum, p) => sum + p.detections, 0) };
    });
  }, [periods, width]);
  const maximum = bins.reduce((m, bin) => Math.max(m, bin.detections), 1);
  const chartAvailable = !unavailable && periods.length > 0;
  const hoveredBin = hovered !== null ? bins[hovered] : null;

  function axisLabel(key?: string): string {
    if (!key) return "—";
    if (histogramUnit === "day") return new Date(`${key}T00:00:00Z`).toLocaleDateString("en-US", {
      month: "short", day: "numeric", timeZone: "UTC"
    });
    if (histogramUnit === "month") return new Date(`${key}-01T00:00:00Z`).toLocaleDateString("en-US", {
      month: "short", year: "numeric", timeZone: "UTC"
    });
    return key;
  }
  const hoverInfo = hoveredBin
    ? `${axisLabel(periods[hoveredBin.start]?.key)} · ${hoveredBin.detections.toLocaleString("en-US")} detections`
    : "Click a bar to jump";

  function applyPeriod(value: string, unit: DatePrecision) {
    const store = useAnalysisStore.getState();
    if (unit === "day") store.setSelectedDate(value);
    else {
      store.setSelectedDate(null, false);
      store.setSelectedMonth(null, false);
      store.setSelectedYear(Number(value.slice(0, 4)), false);
      if (unit === "month") store.setSelectedMonth(Number(value.slice(5, 7)));
      else store.attachCopilotContext();
    }
  }
  function selectPosition(index: number) {
    const period = periods[Math.max(0, Math.min(periods.length - 1, index))];
    if (period) applyPeriod(period.key, histogramUnit);
  }
  function point(event: PointerEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const count = Math.max(1, periods.length);
    return Math.max(0, Math.min(periods.length - 1, Math.floor((event.clientX - rect.left) / rect.width * count)));
  }
  function onKey(event: KeyboardEvent<SVGSVGElement>) {
    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      event.preventDefault(); event.stopPropagation();
      selectPosition(event.key === "Home" ? 0 : event.key === "End" ? periods.length - 1 : position + (event.key === "ArrowLeft" ? -1 : 1));
    }
  }
  function nextPeriod(delta: number): { start: string; end: string } {
    if (precision === "day") {
      const date = new Date(`${anchor}T00:00:00Z`);
      date.setUTCDate(date.getUTCDate() + delta);
      const start = date.toISOString().slice(0, 10);
      return { start, end: start };
    }
    if (precision === "month") {
      const date = new Date(Date.UTC(state.year, (state.month ?? 1) - 1 + delta, 1));
      return {
        start: isoDate(date.getUTCFullYear(), date.getUTCMonth() + 1, 1),
        end: isoDate(date.getUTCFullYear(), date.getUTCMonth() + 1, 31)
      };
    }
    const year = state.year + delta;
    return { start: `${year}-01-01`, end: `${year}-12-31` };
  }
  function canStep(delta: number) {
    const next = nextPeriod(delta);
    // Partial months/years at the coverage edges remain selectable.
    return !unavailable && next.end >= (state.min ?? next.end) && next.start <= (state.max ?? next.start);
  }
  function step(delta: number) {
    if (!canStep(delta)) return;
    const next = nextPeriod(delta);
    applyPeriod(precision === "day" ? next.start : precision === "month" ? next.start.slice(0, 7) : next.start.slice(0, 4), precision);
  }
  function jumpToLatest() {
    if (!state.max) return;
    if (precision === "day") applyPeriod(state.max, "day");
    else if (precision === "month") applyPeriod(state.max.slice(0, 7), "month");
    else applyPeriod(state.max.slice(0, 4), "year");
  }
  function togglePicker() {
    setOpen(!open);
  }
  function closePicker() {
    setOpen(false);
    requestAnimationFrame(() => trigger.current?.focus());
  }
  function applySelection(selection: DateSelection) {
    if (selection.precision === "day") useAnalysisStore.getState().setSelectedDate(selection.start);
    else if (selection.precision === "month") applyPeriod(selection.start.slice(0, 7), "month");
    else applyPeriod(selection.start.slice(0, 4), "year");
    setOpen(false);
    requestAnimationFrame(() => trigger.current?.focus());
  }

  const buttonClass = "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-rule text-muted hover:bg-paper hover:text-ink disabled:opacity-30 focus-visible:outline-2 focus-visible:outline-reference";
  return <section aria-label="Chronology timeline" className="relative z-30 flex shrink-0 flex-col gap-3 border-t border-rule bg-panel px-4 py-2.5 text-ink lg:flex-row lg:items-end">
    <div ref={trackRef} className="min-w-0 flex-1">
      <div className="mb-1 flex items-center justify-between gap-3">
        <p className="text-[10px] font-medium uppercase tracking-widest text-faint">Timeline</p>
        <p className="truncate text-[10px] text-faint" aria-live="polite">{hoverInfo}</p>
      </div>
      {chartAvailable ? <svg role="slider" aria-label="Chronology blocks" aria-valuemin={0} aria-valuemax={Math.max(0, periods.length - 1)} aria-valuenow={position} aria-valuetext={label} tabIndex={0} viewBox={`0 0 ${Math.max(1, bins.length) * 14} 56`} preserveAspectRatio="none" className="h-16 w-full cursor-pointer touch-none rounded-sm focus-visible:outline-2 focus-visible:outline-reference" onKeyDown={onKey} onPointerLeave={() => setHovered(null)} onPointerMove={e => { const index = point(e); setHovered(index); if (e.buttons === 1) selectPosition(index); }} onPointerDown={e => { e.currentTarget.setPointerCapture(e.pointerId); selectPosition(point(e)); }}>
        <title>Bar height shows satellite detections per {histogramUnit}. Small positive counts remain visible. Click a bar to select that period; arrow keys move between bars.</title>
        <line x1="0" y1="51" x2={Math.max(1, bins.length) * 14} y2="51" stroke="var(--color-rule)" strokeWidth="1" />
        {bins.map((bin, i) => {
          const ratio = bin.detections / maximum;
          const height = bin.detections > 0 ? Math.max(5, ratio * 46) : 1;
          const warmth = Math.sqrt(ratio);
          const color = [109, 124, 142].map((value, channel) => Math.round(value + ([179, 0, 0][channel] - value) * warmth));
          const active = position >= bin.start && position < bin.end;
          return <g key={i}>
            {active && <rect x={i * 14 + 1.5} y={3} width={11} height={47} rx={3} fill="var(--color-reference)" opacity={.09} />}
            <rect data-detections={bin.detections} x={i * 14 + 2} y={50 - height} width={11} height={height} rx={2} fill={`rgb(${color.join(",")})`} opacity={.55 + ratio * .45}><title>{periods[bin.start]?.key}{bin.end - bin.start > 1 ? ` to ${periods[bin.end - 1]?.key}` : ""}: {bin.detections.toLocaleString("en-US")} detections</title></rect>
            {active && <rect x={i * 14 + 2} y={53} width={11} height={2.5} rx={1} fill="var(--color-reference)" />}
          </g>;
        })}
      </svg> : <p role="status" className="flex h-16 items-center text-xs text-muted">{state.loading ? "Loading history…" : state.error ? "History unavailable" : "No daily data in this period"}</p>}
      <div className="mt-1 flex items-center justify-between gap-3 text-[10px] text-faint">
        <span>{axisLabel(periods[0]?.key)}</span>
        <span className="hidden sm:inline">Bar height = satellite detections per {histogramUnit} · not fire duration</span>
        <span>{axisLabel(periods.at(-1)?.key)}</span>
      </div>
    </div>
    <div ref={container} className="relative flex w-full flex-wrap items-center justify-end gap-2 lg:w-auto">
      <button type="button" onClick={jumpToLatest} disabled={unavailable || !state.max}
        className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-muted hover:bg-paper hover:text-ink disabled:opacity-30">
        <Clock3 className="h-3.5 w-3.5" />Latest
      </button>
      <div className="flex items-center gap-1.5">
        <button type="button" aria-label={`Previous ${precision}`} disabled={!canStep(-1)} onClick={() => step(-1)} className={buttonClass}><ChevronLeft className="h-4 w-4" /></button>
        <button ref={trigger} type="button" aria-label="Choose dates" aria-haspopup="dialog" aria-expanded={open} aria-controls="chronology-picker" onClick={togglePicker} disabled={unavailable} className="flex min-h-14 min-w-[190px] items-center gap-3 rounded-xl border border-rule bg-paper px-3 text-left hover:border-reference focus-visible:outline-2 focus-visible:outline-reference disabled:opacity-50">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-reference/10 text-reference"><CalendarDays className="h-4 w-4" /></span>
          <span className="min-w-0">
            <span className="block text-[10px] uppercase tracking-wider text-faint">{UNITS.find(unit => unit.value === precision)?.label} · {detections.toLocaleString("en-US")} detections</span>
            <span aria-label="Timeline selection" aria-live="polite" className="block truncate text-sm font-semibold">{label}</span>
          </span>
          <ChevronDown className="ml-auto h-4 w-4 shrink-0 text-muted" />
        </button>
        <button type="button" aria-label={`Next ${precision}`} disabled={!canStep(1)} onClick={() => step(1)} className={buttonClass}><ChevronRight className="h-4 w-4" /></button>
      </div>
      {open && <DateSelectionPopover precision={precision} anchor={anchor} min={state.min} max={state.max} countsByDate={countsByDate} onApply={applySelection} onClose={closePicker} />}
    </div>
  </section>;
}
