import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent, PointerEvent } from "react";
import { CalendarDays, ChevronLeft, ChevronRight, X } from "lucide-react";
import { useShallow } from "zustand/react/shallow";
import { isoDate, selectedMapPeriod, useAnalysisStore } from "../../store/useAnalysisStore";

type Precision = "day" | "month" | "year" | "range";
type Period = { key: string; detections: number };
const UNITS: { value: Precision; label: string }[] = [
  { value: "day", label: "Day" }, { value: "month", label: "Month" },
  { value: "year", label: "Year" }, { value: "range", label: "Date range" }
];
const formatDay = (date: string) => new Date(`${date}T00:00:00Z`).toLocaleDateString("en-US", {
  day: "numeric", month: "short", year: "numeric", timeZone: "UTC"
});

/** One applied period drives the map, totals and attached chat context. */
export function HeatHistoryCard() {
  const state = useAnalysisStore(useShallow(s => ({
    data: s.analysisData, year: s.selectedYear, month: s.selectedMonth, date: s.selectedDate,
    range: s.selectedRange, loading: s.loading, error: s.error, min: s.minDate, max: s.maxDate,
    mapPeriod: selectedMapPeriod(s)
  })));
  const precision: Precision = state.range ? "range" : state.date ? "day" : state.month ? "month" : "year";
  const anchor = state.range?.start ?? state.date ?? isoDate(state.year, state.month ?? 1, 1);
  const end = state.range?.end ?? state.date ?? isoDate(state.year, state.month ?? 12, 31);
  const label = state.range ? `${formatDay(anchor)} – ${formatDay(end)}` : precision === "day" ? formatDay(anchor)
    : precision === "month" ? new Date(`${anchor}T00:00:00Z`).toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" }) : String(state.year);
  const [open, setOpen] = useState(false);
  const [draftMode, setDraftMode] = useState<Precision>(precision);
  const [draftStart, setDraftStart] = useState(anchor);
  const [draftEnd, setDraftEnd] = useState(end);
  const container = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const firstInput = useRef<HTMLInputElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(400);
  const unavailable = state.loading || Boolean(state.error) || !state.data?.calendar_series.length;
  const histogramUnit = precision === "range" ? "year" : precision;
  const keyLength = histogramUnit === "day" ? 10 : histogramUnit === "month" ? 7 : 4;
  useEffect(() => {
    const node = trackRef.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(1, entry.contentRect.width)));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!open) return;
    firstInput.current?.focus();
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
      if (histogramUnit === "day" && !cell.date.startsWith(anchor.slice(0, 7))) continue;
      if (histogramUnit === "month" && cell.year !== state.year) continue;
      const key = cell.date.slice(0, keyLength);
      const entry = grouped.get(key);
      if (entry) entry.detections += cell.raw_hotspot_count;
      else grouped.set(key, { key, detections: cell.raw_hotspot_count });
    }
    return [...grouped.values()].sort((a, b) => a.key.localeCompare(b.key));
  }, [state.data, state.year, anchor, histogramUnit, keyLength]);
  const position = Math.max(0, periods.findIndex(p => p.key === anchor.slice(0, keyLength)));
  const detections = (state.data?.calendar_series ?? []).reduce((total, cell) =>
    cell.date >= anchor && cell.date <= end ? total + cell.raw_hotspot_count : total, 0);
  const bins = useMemo(() => {
    const count = Math.min(periods.length, Math.max(1, Math.floor(width / 12)));
    return Array.from({ length: count }, (_, i) => {
      const start = Math.floor(i * periods.length / count);
      const end = Math.floor((i + 1) * periods.length / count);
      return { start, end, detections: periods.slice(start, end).reduce((sum, p) => sum + p.detections, 0) };
    });
  }, [periods, width]);
  const maximum = bins.reduce((m, bin) => Math.max(m, bin.detections), 1);
  function applyPeriod(value: string, unit: Exclude<Precision, "range">) {
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
    return Math.floor((event.clientX - rect.left) / rect.width * periods.length);
  }
  function onKey(event: KeyboardEvent<SVGSVGElement>) {
    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      event.preventDefault(); event.stopPropagation();
      selectPosition(event.key === "Home" ? 0 : event.key === "End" ? periods.length - 1 : position + (event.key === "ArrowLeft" ? -1 : 1));
    }
  }
  function nextPeriod(delta: number): { start: string; end: string } {
    const date = new Date(`${anchor}T00:00:00Z`);
    if (precision === "range") {
      const days = (Date.parse(`${end}T00:00:00Z`) - date.getTime()) / 86400000 + 1;
      return { start: new Date(date.getTime() + delta * days * 86400000).toISOString().slice(0, 10),
        end: new Date(Date.parse(`${end}T00:00:00Z`) + delta * days * 86400000).toISOString().slice(0, 10) };
    }
    if (precision === "day") date.setUTCDate(date.getUTCDate() + delta);
    else if (precision === "month") date.setUTCMonth(date.getUTCMonth() + delta);
    else date.setUTCFullYear(date.getUTCFullYear() + delta);
    const start = date.toISOString().slice(0, 10);
    return { start, end: precision === "day" ? start : isoDate(date.getUTCFullYear(), precision === "month" ? date.getUTCMonth() + 1 : 12, 31) };
  }
  function canStep(delta: number) {
    const next = nextPeriod(delta);
    // Partial months/years at the coverage edges remain selectable.
    return !unavailable && next.end >= (state.min ?? next.end) && next.start <= (state.max ?? next.start)
      && (precision !== "range" || next.start >= (state.min ?? next.start) && next.end <= (state.max ?? next.end));
  }
  function step(delta: number) {
    if (!canStep(delta)) return;
    const next = nextPeriod(delta);
    if (precision === "range") useAnalysisStore.getState().setSelectedRange(next.start, next.end);
    else applyPeriod(next.start, precision);
  }
  function togglePicker() {
    if (!open) { setDraftMode(precision); setDraftStart(anchor); setDraftEnd(end > (state.max ?? end) ? state.max! : end); }
    setOpen(!open);
  }
  const draftValue = draftMode === "year" ? draftStart.slice(0, 4) : draftMode === "month" ? draftStart.slice(0, 7) : draftStart;
  const invalidRange = draftMode === "range" && (!draftStart || !draftEnd || draftStart > draftEnd
    || draftStart < (state.min ?? draftStart) || draftEnd > (state.max ?? draftEnd));
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (invalidRange) return;
    if (draftMode === "range") useAnalysisStore.getState().setSelectedRange(draftStart, draftEnd);
    else applyPeriod(draftValue, draftMode);
    setOpen(false); trigger.current?.focus();
  }
  const fieldClass = "h-10 w-full min-w-0 rounded-md border border-rule bg-paper px-3 text-sm text-ink focus-visible:outline-2 focus-visible:outline-reference";
  const buttonClass = "flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-rule text-muted hover:bg-paper hover:text-ink disabled:opacity-30 focus-visible:outline-2 focus-visible:outline-reference";
  return <section aria-label="Chronology timeline" className="relative z-30 flex shrink-0 flex-wrap items-center gap-3 border-t border-rule bg-panel px-4 py-3 text-ink">
    <div ref={trackRef} className="min-w-40 flex-1">
      {unavailable ? <p role="status" className="h-14 text-xs text-muted">{state.loading ? "Loading history…" : state.error ? "History unavailable" : "No daily data"}</p> : <svg role="slider" aria-label="Chronology blocks" aria-valuemin={0} aria-valuemax={Math.max(0, periods.length - 1)} aria-valuenow={position} aria-valuetext={label} tabIndex={0} viewBox={`0 0 ${Math.max(1, bins.length) * 12} 56`} preserveAspectRatio="none" className="h-14 w-full cursor-crosshair touch-none rounded-sm focus-visible:outline-2 focus-visible:outline-reference" onKeyDown={onKey} onPointerMove={e => { if (e.buttons === 1) selectPosition(point(e)); }} onPointerDown={e => { e.currentTarget.setPointerCapture(e.pointerId); selectPosition(point(e)); }}>
        <title>Bar height shows satellite detections per {histogramUnit}. Small positive counts remain visible. No detections does not establish extinction. Click to select; arrow keys move between bars.</title>
        {bins.map((bin, i) => {
          const ratio = bin.detections / maximum;
          const height = bin.detections > 0 ? Math.max(5, ratio * 48) : 1;
          const warmth = Math.sqrt(ratio);
          const color = [109, 124, 142].map((value, channel) => Math.round(value + ([179, 0, 0][channel] - value) * warmth));
          const active = state.range ? periods[bin.end - 1].key >= anchor.slice(0, keyLength) && periods[bin.start].key <= end.slice(0, keyLength) : position >= bin.start && position < bin.end;
          return <g key={i}><rect data-detections={bin.detections} x={i * 12 + 1} y={50 - height} width={10} height={height} rx={2} fill={`rgb(${color.join(",")})`} opacity={.55 + ratio * .45}><title>{periods[bin.start]?.key}{bin.end - bin.start > 1 ? ` to ${periods[bin.end - 1]?.key}` : ""}: {bin.detections.toLocaleString("en-US")} detections</title></rect>{active && <rect x={i * 12 + 1} y={53} width={10} height={3} rx={1} fill="var(--color-reference)" />}</g>;
        })}
      </svg>}
      <div className="flex justify-between text-[10px] text-faint"><span>{periods[0]?.key ?? "—"}</span><span>Detections / {histogramUnit} · Not fire duration</span><span>{periods.at(-1)?.key ?? "—"}</span></div>
    </div>
    <div ref={container} className="relative ml-auto flex items-center gap-1.5">
      <button type="button" aria-label={`Previous ${precision === "range" ? "date range" : precision}`} disabled={!canStep(-1)} onClick={() => step(-1)} className={buttonClass}><ChevronLeft className="h-4 w-4" /></button>
      <button ref={trigger} type="button" aria-label="Choose dates" aria-expanded={open} aria-controls="chronology-picker" onClick={togglePicker} disabled={unavailable} className="flex min-h-12 items-center gap-3 rounded-md border border-rule bg-paper px-3 text-left hover:border-reference focus-visible:outline-2 focus-visible:outline-reference"><CalendarDays className="h-4 w-4 shrink-0 text-reference" /><span><span className="block text-[10px] text-muted">{UNITS.find(unit => unit.value === precision)?.label} · Change dates</span><span aria-label="Timeline selection" aria-live="polite" className="block text-xs font-medium">{label}</span><span className="block text-[10px] text-muted">{detections.toLocaleString("en-US")} detections</span></span></button>
      <button type="button" aria-label={`Next ${precision === "range" ? "date range" : precision}`} disabled={!canStep(1)} onClick={() => step(1)} className={buttonClass}><ChevronRight className="h-4 w-4" /></button>
      {open && <section id="chronology-picker" aria-label="Choose time period" className="absolute bottom-full right-0 z-50 mb-3 w-[min(420px,calc(100vw-2rem))] rounded-xl border border-rule bg-panel p-4 shadow-xl">
        <div className="mb-3 flex items-center justify-between"><h2 className="font-serif text-lg">Choose time period</h2><button type="button" aria-label="Close date picker" onClick={() => { setOpen(false); trigger.current?.focus(); }} className="p-1"><X className="h-4 w-4" /></button></div>
        <div role="group" aria-label="Period type" className="mb-4 grid grid-cols-4 gap-1 rounded-lg bg-paper p-1">{UNITS.map(unit => <button key={unit.value} type="button" aria-pressed={draftMode === unit.value} onClick={() => setDraftMode(unit.value)} className={`rounded-md px-2 py-2 text-xs ${draftMode === unit.value ? "bg-reference text-white" : "text-muted hover:bg-panel"}`}>{unit.label}</button>)}</div>
        <form onSubmit={submit} className="space-y-3">
          <div className={draftMode === "range" ? "grid grid-cols-2 gap-3" : ""}>
            <label className="block space-y-1 text-xs"><span>{draftMode === "range" ? "From (UTC)" : draftMode === "year" ? "Year" : draftMode === "month" ? "Month" : "Date (UTC)"}</span><input ref={firstInput} required aria-label={draftMode === "range" ? "Start date" : draftMode === "year" ? "Choose year" : draftMode === "month" ? "Choose month" : "Choose day"} type={draftMode === "year" ? "number" : draftMode === "month" ? "month" : "date"} value={draftValue} min={draftMode === "year" ? state.min?.slice(0, 4) : draftMode === "month" ? state.min?.slice(0, 7) : state.min ?? undefined} max={draftMode === "year" ? state.max?.slice(0, 4) : draftMode === "month" ? state.max?.slice(0, 7) : state.max ?? undefined} onChange={e => { const value = e.target.value; setDraftStart(draftMode === "year" ? `${value}-01-01` : draftMode === "month" ? `${value}-01` : value); }} className={fieldClass} /></label>
            {draftMode === "range" && <label className="block space-y-1 text-xs"><span>To (UTC, inclusive)</span><input required aria-label="End date" type="date" value={draftEnd} min={state.min ?? undefined} max={state.max ?? undefined} onChange={e => setDraftEnd(e.target.value)} className={fieldClass} /></label>}
          </div>
          {invalidRange && <p role="alert" className="text-xs text-terracotta">Choose an end date on or after the start, within the available record.</p>}
          <p className="text-[11px] text-muted">Available: {state.min ?? "—"} – {state.max ?? "—"}. Applied dates also update the chat context.</p>
          <div className="flex justify-end gap-2"><button type="button" onClick={() => { setOpen(false); trigger.current?.focus(); }} className="rounded-md border border-rule px-3 py-2 text-xs">Cancel</button><button type="submit" disabled={invalidRange} className="rounded-md bg-reference px-4 py-2 text-xs font-medium text-white disabled:opacity-40">Apply dates</button></div>
        </form>
      </section>}
    </div>
  </section>;
}
