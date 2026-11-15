import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, ChevronLeft, ChevronRight, X } from "lucide-react";

export type DatePrecision = "day" | "month" | "year";

export interface DateSelection {
  precision: DatePrecision;
  start: string;
  end: string;
}

interface DateSelectionPopoverProps {
  precision: DatePrecision;
  anchor: string;
  min: string | null;
  max: string | null;
  countsByDate: Map<string, number>;
  onApply: (selection: DateSelection) => void;
  onClose: () => void;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const COMPACT = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const parseDay = (value: string) => new Date(`${value}T00:00:00Z`);
const isoDay = (date: Date) => date.toISOString().slice(0, 10);
const monthKey = (value: string) => value.slice(0, 7);
const yearKey = (value: string) => Number(value.slice(0, 4));
const daysInMonth = (key: string) => new Date(Date.UTC(yearKey(key), Number(key.slice(5, 7)), 0)).getUTCDate();
const lastDay = (key: string) => `${key}-${String(daysInMonth(key)).padStart(2, "0")}`;
const monthLabel = (key: string) =>
  parseDay(`${key}-01`).toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
const formatDay = (value: string) =>
  parseDay(value).toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

function monthCells(month: string): Array<string | null> {
  const first = parseDay(`${month}-01`);
  const offset = (first.getUTCDay() + 6) % 7; // Monday-first calendar
  const total = daysInMonth(month);
  const cells: Array<string | null> = Array.from({ length: offset }, () => null);
  for (let day = 1; day <= total; day += 1) cells.push(`${month}-${String(day).padStart(2, "0")}`);
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}

interface MonthGridProps {
  month: string;
  selected: string | null;
  minDay: string;
  maxDay: string;
  counts: Map<string, number>;
  onPick: (date: string) => void;
}

function MonthGrid({ month, selected, minDay, maxDay, counts, onPick }: MonthGridProps) {
  const cells = useMemo(() => monthCells(month), [month]);
  const maximum = useMemo(() => {
    let value = 1;
    for (const date of cells) if (date) value = Math.max(value, counts.get(date) ?? 0);
    return value;
  }, [cells, counts]);
  const today = isoDay(new Date());
  return (
    <div>
      <div className="grid grid-cols-7 text-center text-[10px] font-medium uppercase tracking-wide text-faint">
        {WEEKDAYS.map((day) => <span key={day} className="py-1">{day}</span>)}
      </div>
      <div className="grid grid-cols-7 gap-0.5">
        {cells.map((date, index) => {
          if (!date) return <span key={`empty-${index}`} aria-hidden="true" />;
          const count = counts.get(date) ?? 0;
          const disabled = date < minDay || date > maxDay;
          const isSelected = selected === date;
          const dotHeight = count > 0 ? 2 + Math.round((count / maximum) * 4) : 0;
          return (
            <button
              key={date}
              type="button"
              disabled={disabled}
              onClick={() => onPick(date)}
              aria-label={`${formatDay(date)}${count > 0 ? `, ${count.toLocaleString("en-US")} detections` : ""}`}
              aria-pressed={isSelected}
              title={`${formatDay(date)} · ${count.toLocaleString("en-US")} detections`}
              className={`relative flex h-8 items-center justify-center rounded-md text-xs transition-colors ${
                disabled ? "cursor-not-allowed text-faint opacity-35"
                  : isSelected ? "bg-reference font-semibold text-white shadow-sm"
                  : "text-ink hover:bg-paper"
              } ${!isSelected && date === today ? "ring-1 ring-inset ring-reference/50" : ""}`}
            >
              <span>{Number(date.slice(8, 10))}</span>
              {count > 0 && <span aria-hidden="true" className="absolute bottom-1 left-1/2 -translate-x-1/2 rounded-full"
                style={{ width: 10, height: Math.max(2, dotHeight), backgroundColor: "var(--color-thermal-3)", opacity: isSelected ? .9 : .55 }} />}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function DateSelectionPopover({
  precision, anchor, min, max, countsByDate, onApply, onClose
}: DateSelectionPopoverProps) {
  const minDay = min ?? "0001-01-01";
  const maxDay = max ?? "9999-12-31";
  const minMonth = min ? monthKey(min) : "0001-01";
  const maxMonth = max ? monthKey(max) : "9999-12";
  const minYear = min ? yearKey(min) : 2000;
  const maxYear = max ? yearKey(max) : new Date().getUTCFullYear();
  const anchorYear = yearKey(anchor);
  const anchorMonth = monthKey(anchor);

  // The wizard always starts at the year. The current selection is highlighted,
  // but a user who only wants another day can jump via the step breadcrumb.
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [draftYear, setDraftYear] = useState(anchorYear);
  const [draftMonth, setDraftMonth] = useState<string | null>(precision === "year" ? null : anchorMonth);
  const [draftDate, setDraftDate] = useState<string | null>(precision === "day" ? anchor : null);
  const [visibleMonth, setVisibleMonth] = useState(anchorMonth);
  const stepContent = useRef<HTMLDivElement>(null);

  useEffect(() => {
    stepContent.current?.focus();
  }, [step]);

  const totals = useMemo(() => {
    const months = new Map<string, number>();
    const years = new Map<string, number>();
    for (const [date, count] of countsByDate) {
      const month = date.slice(0, 7);
      const year = date.slice(0, 4);
      months.set(month, (months.get(month) ?? 0) + count);
      years.set(year, (years.get(year) ?? 0) + count);
    }
    return { months, years };
  }, [countsByDate]);

  const years = useMemo(
    () => Array.from({ length: maxYear - minYear + 1 }, (_, index) => minYear + index),
    [maxYear, minYear]
  );

  function chooseYear(year: number) {
    setDraftYear(year);
    if (year !== anchorYear) {
      setDraftMonth(null);
      setDraftDate(null);
    }
    setStep(2);
  }

  function chooseMonth(key: string) {
    setDraftMonth(key);
    if (draftDate && !draftDate.startsWith(key)) setDraftDate(null);
    setVisibleMonth(key);
  }

  function showMonth(key: string) {
    const clamped = key < minMonth ? minMonth : key > maxMonth ? maxMonth : key;
    setDraftMonth(clamped);
    setVisibleMonth(clamped);
    if (draftDate && !draftDate.startsWith(clamped)) setDraftDate(null);
  }

  const previousMonth = (() => {
    const date = new Date(Date.UTC(yearKey(visibleMonth), Number(visibleMonth.slice(5, 7)) - 2, 1));
    return date.toISOString().slice(0, 7);
  })();
  const nextMonth = (() => {
    const date = new Date(Date.UTC(yearKey(visibleMonth), Number(visibleMonth.slice(5, 7)), 1));
    return date.toISOString().slice(0, 7);
  })();
  const canPrevMonth = previousMonth >= minMonth;
  const canNextMonth = nextMonth <= maxMonth;

  const summary = step === 1
    ? `Year ${draftYear}`
    : step === 2
      ? draftMonth ? monthLabel(draftMonth) : `Whole year ${draftYear}`
      : draftDate ? formatDay(draftDate) : draftMonth ? `Whole month ${monthLabel(draftMonth)}` : `Whole year ${draftYear}`;
  const summaryCount = step === 1
    ? totals.years.get(String(draftYear)) ?? 0
    : step === 2
      ? draftMonth ? totals.months.get(draftMonth) ?? 0 : totals.years.get(String(draftYear)) ?? 0
      : draftDate ? countsByDate.get(draftDate) ?? 0 : draftMonth ? totals.months.get(draftMonth) ?? 0 : totals.years.get(String(draftYear)) ?? 0;

  function applyYear() {
    onApply({ precision: "year", start: `${draftYear}-01-01`, end: `${draftYear}-12-31` });
  }

  function applyMonth() {
    if (draftMonth) onApply({ precision: "month", start: `${draftMonth}-01`, end: lastDay(draftMonth) });
  }

  function applyDay() {
    if (draftDate) onApply({ precision: "day", start: draftDate, end: draftDate });
  }

  const stepClass = (active: boolean, disabled = false) =>
    `inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] transition-colors ${
      active ? "bg-reference font-medium text-white shadow-sm"
        : disabled ? "cursor-not-allowed border border-rule/60 text-faint opacity-45"
        : "border border-rule bg-paper text-ink hover:border-reference"
    }`;

  return (
    <section
      id="chronology-picker"
      role="dialog"
      aria-label="Choose time period"
      className="fixed bottom-2 right-2 z-50 max-h-[75dvh] w-[min(340px,calc(100vw-1rem))] overflow-y-auto rounded-xl border border-rule bg-panel p-3 text-ink shadow-xl sm:absolute sm:bottom-full sm:right-0 sm:mb-2"
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="font-serif text-base">Choose a time period</h2>
        <button type="button" aria-label="Close date picker" onClick={onClose} className="rounded-full p-1.5 text-muted hover:bg-paper hover:text-ink">
          <X className="h-4 w-4" />
        </button>
      </div>

      <nav aria-label="Selection steps" className="mb-2 flex flex-wrap items-center gap-1">
        <button type="button" onClick={() => setStep(1)} aria-current={step === 1 ? "step" : undefined} className={stepClass(step === 1)}>
          Year
        </button>
        <ChevronRight className="h-3 w-3 text-faint" />
        <button type="button" disabled={!draftYear} onClick={() => setStep(2)} aria-current={step === 2 ? "step" : undefined}
          className={stepClass(step === 2, !draftYear)}>
          Month
        </button>
        <ChevronRight className="h-3 w-3 text-faint" />
        <button type="button" disabled={!draftYear || !draftMonth} onClick={() => setStep(3)} aria-current={step === 3 ? "step" : undefined}
          className={stepClass(step === 3, !draftYear || !draftMonth)}>
          Day
        </button>
      </nav>

      <div ref={stepContent} tabIndex={-1} className="focus:outline-none">
        {step === 1 && (
          <div>
            <div className="mb-2 flex items-center justify-between">
              <p className="text-sm font-medium">Select a year</p>
              <p className="text-[11px] text-faint">{minYear} – {maxYear}</p>
            </div>
            <div className="grid grid-cols-4 gap-1">
              {years.map((year) => {
                const selected = draftYear === year;
                const count = totals.years.get(String(year)) ?? 0;
                return (
                  <button key={year} type="button" aria-pressed={selected} onClick={() => chooseYear(year)} title={count.toLocaleString("en-US") + " detections"}
                    className={`flex min-h-9 flex-col items-center justify-center rounded-md border px-1 py-0.5 text-xs transition-colors ${
                      selected ? "border-reference bg-reference text-white shadow-sm"
                        : "border-rule bg-paper text-ink hover:border-reference"
                    }`}>
                    <span className="text-xs font-semibold">{year}</span>
                    <span className={`text-[10px] ${selected ? "text-white/75" : "text-faint"}`}>{COMPACT.format(count)}</span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {step === 2 && (
          <div>
            <button type="button" onClick={applyYear}
              className="mb-2 flex w-full items-center justify-between gap-2 rounded-md border border-rule bg-paper px-2 py-1.5 text-left transition-colors hover:border-reference">
              <span>
                <span className="block text-xs font-semibold text-ink">Use the whole year</span>
              </span>
              <ArrowRight className="h-4 w-4 shrink-0 text-reference" />
            </button>
            <div className="mb-2 flex items-center justify-between">
              <p className="text-sm font-medium">Which month in {draftYear}?</p>
              <button type="button" onClick={() => setStep(1)} className="text-[11px] text-muted underline-offset-2 hover:text-ink hover:underline">Change year</button>
            </div>
            <div className="grid grid-cols-4 gap-1">
              {MONTHS.map((label, index) => {
                const key = `${draftYear}-${String(index + 1).padStart(2, "0")}`;
                const disabled = key < minMonth || key > maxMonth;
                const selected = draftMonth === key;
                const count = totals.months.get(key) ?? 0;
                return (
                  <button key={key} type="button" disabled={disabled} aria-pressed={selected} onClick={() => chooseMonth(key)} title={count.toLocaleString("en-US") + " detections"}
                    className={`flex min-h-9 flex-col items-center justify-center rounded-md border px-1 py-0.5 text-xs transition-colors ${
                      selected ? "border-reference bg-reference text-white shadow-sm"
                        : disabled ? "cursor-not-allowed border-rule bg-paper text-faint opacity-35"
                        : "border-rule bg-paper text-ink hover:border-reference"
                    }`}>
                    <span className="font-medium">{label}</span>
                    <span className={`text-[10px] ${selected ? "text-white/75" : "text-faint"}`}>{COMPACT.format(count)}</span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {step === 3 && draftMonth && (
          <div>
            <button type="button" onClick={applyMonth}
              className="mb-2 flex w-full items-center justify-between gap-2 rounded-md border border-rule bg-paper px-2 py-1.5 text-left transition-colors hover:border-reference">
              <span>
                <span className="block text-xs font-semibold text-ink">Use the whole month</span>
              </span>
              <ArrowRight className="h-4 w-4 shrink-0 text-reference" />
            </button>
            <div className="mb-2 flex items-center justify-between">
              <button type="button" aria-label="Previous month" disabled={!canPrevMonth} onClick={() => showMonth(previousMonth)}
                className="rounded-md border border-rule p-2 text-muted hover:bg-paper hover:text-ink disabled:opacity-30"><ChevronLeft className="h-4 w-4" /></button>
              <div className="text-center">
                <p className="text-sm font-medium">{monthLabel(visibleMonth)}</p>
                <button type="button" onClick={() => setStep(2)} className="text-[10px] text-muted underline-offset-2 hover:text-ink hover:underline">Change month</button>
              </div>
              <button type="button" aria-label="Next month" disabled={!canNextMonth} onClick={() => showMonth(nextMonth)}
                className="rounded-md border border-rule p-2 text-muted hover:bg-paper hover:text-ink disabled:opacity-30"><ChevronRight className="h-4 w-4" /></button>
            </div>
            <MonthGrid month={visibleMonth} selected={draftDate} minDay={minDay} maxDay={maxDay} counts={countsByDate} onPick={setDraftDate} />
          </div>
        )}
      </div>

      <div className="mt-2 flex flex-col gap-1.5 border-t border-rule pt-2">
        <p className="text-[11px] text-muted">
          <span className="font-medium text-ink">{summary}</span>
          {" · "}{summaryCount.toLocaleString("en-US")} detections
        </p>
        <div className="flex flex-wrap justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg border border-rule px-2 py-1.5 text-xs text-ink hover:bg-paper">Cancel</button>
          {step > 1 && (
            <button type="button" onClick={() => setStep(step === 3 ? 2 : 1)}
              className="rounded-lg border border-rule px-2 py-1.5 text-xs text-ink hover:bg-paper">Back</button>
          )}
          {step === 2 && draftMonth && (
            <button type="button" onClick={applyMonth}
              className="rounded-lg border border-rule px-2 py-1.5 text-xs text-ink hover:bg-paper">
              Use this month
            </button>
          )}
          {step === 2 && (
            <button type="button" disabled={!draftMonth} onClick={() => setStep(3)}
              className="inline-flex items-center gap-1 rounded-lg bg-reference px-2.5 py-1.5 text-xs font-semibold text-white shadow-sm hover:opacity-90 disabled:opacity-40">
              Continue to day <ChevronRight className="h-3.5 w-3.5" />
            </button>
          )}
          {step === 3 && (
            <button type="button" disabled={!draftDate} onClick={applyDay}
              className="rounded-lg bg-reference px-2.5 py-1.5 text-xs font-semibold text-white shadow-sm hover:opacity-90 disabled:opacity-40">
              Use this day
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
