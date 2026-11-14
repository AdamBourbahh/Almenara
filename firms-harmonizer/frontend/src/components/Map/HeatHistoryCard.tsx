import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent } from "react";
import { LayoutGrid, Minus, Plus } from "lucide-react";
import { useShallow } from "zustand/react/shallow";
import { isoDate, selectedMapPeriod, useAnalysisStore } from "../../store/useAnalysisStore";

type Precision = "day" | "month" | "year";
type Period = { key: string; detections: number };
const KEY_LENGTH = { day: 10, month: 7, year: 4 };

/** One chronology dock for every view, including exact spatial map periods. */
export function HeatHistoryCard() {
  const state = useAnalysisStore(useShallow((s) => ({
    data: s.analysisData, year: s.selectedYear, month: s.selectedMonth, date: s.selectedDate,
    loading: s.loading, error: s.error, setYear: s.setSelectedYear,
    setMonth: s.setSelectedMonth, setDate: s.setSelectedDate, min: s.minDate, max: s.maxDate,
    mapPeriod: selectedMapPeriod(s)
  })));
  const [view, setView] = useState<"blocks" | "slider">("blocks");
  const [precision, setPrecision] = useState<Precision>(state.date ? "day" : "year");
  const trackRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(400);
  useEffect(() => {
    const node = trackRef.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(1, entry.contentRect.width)));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  const periods = useMemo(() => {
    const grouped = new Map<string, Period>();
    for (const cell of state.data?.calendar_series ?? []) {
      const key = cell.date.slice(0, KEY_LENGTH[precision]);
      const entry = grouped.get(key);
      if (entry) entry.detections += cell.raw_hotspot_count;
      else grouped.set(key, { key, detections: cell.raw_hotspot_count });
    }
    return [...grouped.values()].sort((a, b) => a.key.localeCompare(b.key));
  }, [state.data, precision]);
  const anchor = state.date ?? `${state.year}-${String(state.month ?? 1).padStart(2, "0")}-01`;
  const key = anchor.slice(0, KEY_LENGTH[precision]);
  const positionByKey = useMemo(() => new Map(periods.map((p, i) => [p.key, i])), [periods]);
  const position = positionByKey.get(key) ?? 0;
  const selected = periods[position];
  const unavailable = state.loading || Boolean(state.error) || !periods.length;
  const canStepBack = !unavailable && (!state.min || anchor > state.min);
  const canStepForward = !unavailable && (!state.max || anchor < state.max);
  const label = selected ? precision === "day"
    ? new Date(`${selected.key}T00:00:00Z`).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" })
    : precision === "month" ? new Date(`${selected.key}-01T00:00:00Z`).toLocaleDateString("en-US", { year: "numeric", month: "long", timeZone: "UTC" }) : selected.key : "No dates";

  function selectKey(value: string, unit: Precision, pin = true) {
    if (!value) return;
    const length = KEY_LENGTH[unit];
    if (value.length !== length) return;
    const lower = state.min?.slice(0, length);
    const upper = state.max?.slice(0, length);
    if (lower && value < lower || upper && value > upper) return;
    useAnalysisStore.getState().setHoveredDay(null);
    if (unit === "day") state.setDate(value, pin);
    else {
      state.setDate(null, pin);
      state.setMonth(null, pin);
      state.setYear(Number(value.slice(0, 4)), pin);
      if (unit === "month") state.setMonth(Number(value.slice(5, 7)), pin);
    }
  }
  function selectPosition(index: number, pin = true) {
    const period = periods[Math.max(0, Math.min(periods.length - 1, index))];
    if (period && (period.key !== state.mapPeriod || pin && !useAnalysisStore.getState().isDatePinned && precision === "day")) selectKey(period.key, precision, pin);
  }
  function changePrecision(unit: Precision) {
    setPrecision(unit);
    selectKey(anchor.slice(0, KEY_LENGTH[unit]), unit);
  }
  function stepDate(delta: -1 | 1) {
    if (!(delta === -1 ? canStepBack : canStepForward)) return;
    const date = new Date(`${anchor}T00:00:00Z`);
    if (precision === "day") {
      date.setUTCDate(date.getUTCDate() + delta);
      state.setDate(date.toISOString().slice(0, 10));
      return;
    }
    const year = date.getUTCFullYear() + (precision === "year" ? delta : 0);
    const month = date.getUTCMonth() + (precision === "month" ? delta : 0);
    const first = new Date(Date.UTC(year, month, 1));
    state.setDate(isoDate(first.getUTCFullYear(), first.getUTCMonth() + 1, date.getUTCDate()));
  }
  function onDateKey(e: KeyboardEvent<HTMLDivElement>) {
    if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    if (e.key === "ArrowUp" || e.key === "ArrowRight") {
      e.preventDefault();
      stepDate(1);
    } else if (e.key === "ArrowDown" || e.key === "ArrowLeft") {
      e.preventDefault();
      stepDate(-1);
    }
  }
  function point(e: PointerEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    return Math.min(periods.length - 1, Math.max(0, Math.floor((e.clientX - rect.left) / rect.width * periods.length)));
  }
  function onKey(e: KeyboardEvent<SVGSVGElement>) {
    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) {
      e.preventDefault();
      selectPosition(e.key === "Home" ? 0 : e.key === "End" ? periods.length - 1 : position + (e.key === "ArrowLeft" ? -1 : 1));
    }
  }
  const bins = useMemo(() => {
    const count = Math.min(periods.length, Math.max(1, Math.floor(width / 10)));
    return Array.from({ length: count }, (_, i) => {
      const start = Math.floor(i * periods.length / count);
      const end = Math.floor((i + 1) * periods.length / count);
      let detections = 0;
      for (let j = start; j < end; j++) detections += periods[j].detections;
      return { start, end, detections };
    });
  }, [periods, width]);
  const maximum = bins.reduce((m, bin) => Math.max(m, bin.detections), 1);
  const inputClass = "h-8 min-w-0 rounded-md border border-rule bg-paper px-2 text-xs text-ink focus-visible:outline-2 focus-visible:outline-reference [color-scheme:light_dark]";
  const stepButtonClass = "flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-rule text-muted hover:bg-paper hover:text-ink focus-visible:outline-2 focus-visible:outline-reference aria-disabled:opacity-40";

  return (
    <section aria-label="Chronology timeline" className="relative z-30 flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-t border-rule bg-panel px-3 py-2 text-ink sm:px-4">
      <button type="button" aria-label={view === "blocks" ? "Switch to slider timeline" : "Switch to blocks timeline"} title={view === "blocks" ? "Use a continuous slider" : "Use blocks"} onClick={() => setView(view === "blocks" ? "slider" : "blocks")} className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-rule text-muted hover:bg-paper focus-visible:outline-2 focus-visible:outline-reference">
        {view === "blocks" ? <LayoutGrid className="h-4 w-4" /> : <Minus className="h-4 w-4" />}
      </button>
      <div ref={trackRef} className="min-w-24 flex-1">
        {unavailable ? <p role="status" className="h-7 text-xs text-muted">{state.loading ? "Loading history…" : state.error ? "History unavailable" : "No daily data"}</p> : view === "slider" ? (
          <input type="range" aria-label="Chronology slider" aria-valuetext={label} min={0} max={Math.max(0, periods.length - 1)} step={1} value={position} onChange={(e) => selectPosition(Number(e.target.value))} className="h-7 w-full cursor-pointer accent-[#b30000]" />
        ) : (
          <svg role="slider" aria-label="Chronology blocks" aria-valuemin={0} aria-valuemax={periods.length - 1} aria-valuenow={position} aria-valuetext={label} tabIndex={0} viewBox={`0 0 ${Math.max(1, bins.length) * 10} 28`} preserveAspectRatio="none" className="h-7 w-full cursor-crosshair touch-none rounded-sm focus-visible:outline-2 focus-visible:outline-reference" onKeyDown={onKey} onPointerMove={(e) => selectPosition(point(e), e.buttons === 1)} onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); selectPosition(point(e)); }}>
            <title>Bar height shows satellite detections. Taller and warmer bars mean more detections. The underline marks selection. Dates are grouped when space is limited; arrow keys select each {precision}.</title>
            {bins.map((bin, i) => {
              const ratio = bin.detections / maximum;
              const height = Math.max(2, ratio * 22);
              const warmth = Math.sqrt(ratio);
              const low = [109, 124, 142], high = [179, 0, 0];
              const color = low.map((value, channel) => Math.round(value + (high[channel] - value) * warmth));
              const active = position >= bin.start && position < bin.end;
              return <g key={i}>
                <rect data-detections={bin.detections} x={i * 10 + 1} y={24 - height} width={8} height={height} rx={1} fill={`rgb(${color.join(",")})`} opacity={.55 + ratio * .45}>
                  <title>{periods[bin.start]?.key}{bin.end - bin.start > 1 ? ` to ${periods[bin.end - 1]?.key}` : ""}: {bin.detections.toLocaleString("en-US")} detections</title>
                </rect>
                {active && <rect x={i * 10 + 1} y={26} width={8} height={2} rx={1} fill="var(--color-reference)" />}
              </g>;
            })}
          </svg>
        )}
        <p aria-live="polite" aria-label="Timeline selection" className="flex h-4 justify-between gap-2 truncate text-[10px] text-muted tnum"><span>{label}</span><span className="hidden sm:inline">{selected?.detections.toLocaleString("en-US") ?? "—"} detections · Height: detections · Map: {state.mapPeriod}</span></p>
      </div>
      <div className="ml-auto flex w-full items-center justify-end gap-1.5 sm:w-auto">
        <select aria-label="Timeline precision" value={precision} disabled={unavailable} onChange={(e) => changePrecision(e.target.value as Precision)} className={inputClass}>
          <option value="year">Year</option><option value="month">Month</option><option value="day">Day</option>
        </select>
        <div className="flex min-w-0 items-center gap-1.5" onKeyDown={onDateKey}>
          <button type="button" aria-label={`Previous ${precision}`} title={`Previous ${precision} (↓ or ←)`} aria-disabled={!canStepBack} onClick={() => stepDate(-1)} className={stepButtonClass}>
            <Minus aria-hidden="true" className="h-4 w-4" />
          </button>
          <button type="button" aria-label={`Next ${precision}`} title={`Next ${precision} (↑ or →)`} aria-disabled={!canStepForward} onClick={() => stepDate(1)} className={stepButtonClass}>
            <Plus aria-hidden="true" className="h-4 w-4" />
          </button>
          <input type="date" lang="en-US" aria-label="Go to date" title={`Inspect an exact day. Arrow keys move one ${precision}.`} value={anchor} min={state.min ?? undefined} max={state.max ?? undefined} disabled={unavailable} onChange={(e) => {
            const input = e.currentTarget;
            const date = input.value;
            if (!date || !input.validity.valid) return;
            const store = useAnalysisStore.getState();
            store.setSelectedDate(date, true);
            if (useAnalysisStore.getState().selectedDate === date) {
              const rect = input.getBoundingClientRect();
              store.showDateRiskPrompt(date, rect.right - 14, rect.top);
            }
          }} className={inputClass + " w-40"} />
        </div>
      </div>
    </section>
  );
}
