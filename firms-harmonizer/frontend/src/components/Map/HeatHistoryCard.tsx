import { useMemo, useState } from "react";
import { X } from "lucide-react";
import { useShallow } from "zustand/react/shallow";
import { summarizeMappedYear } from "./mapMetrics";
import { useAnalysisStore } from "../../store/useAnalysisStore";

/** Single-row annual record docked across the bottom of the map workspace. */
export function HeatHistoryCard({ onClose }: { onClose: () => void }) {
  const { analysisData, selectedYear, setSelectedYear, loading, error, mapHexagons, mapYear, mapLoading, mapError, excludeIndustrial } = useAnalysisStore(
    useShallow((s) => ({ analysisData: s.analysisData, selectedYear: s.selectedYear,
      setSelectedYear: s.setSelectedYear, loading: s.loading, error: s.error, mapHexagons: s.mapHexagons, mapYear: s.mapYear, mapLoading: s.mapLoading, mapError: s.mapError, excludeIndustrial: s.excludeIndustrial }))
  );
  const [hovered, setHovered] = useState<number | null>(null);
  const annual = useMemo(() => {
    const counts = new Map<number, number>();
    for (const day of analysisData?.calendar_series ?? []) counts.set(day.year, (counts.get(day.year) ?? 0) + day.raw_hotspot_count);
    return Array.from(counts, ([year, detections]) => ({ year, detections }));
  }, [analysisData]);
  const mapped = useMemo(() => summarizeMappedYear(mapHexagons, excludeIndustrial), [mapHexagons, excludeIndustrial]);
  const max = Math.max(1, ...annual.map((year) => year.detections));
  const inspected = annual.find((year) => year.year === (hovered ?? selectedYear)) ?? annual[annual.length - 1];
  const format = (value: number) => value.toLocaleString("en-US", { maximumFractionDigits: 0 });

  return (
    <section aria-label="Heat history for selected area" className="flex h-16 w-full items-center gap-2 border-t border-rule bg-panel px-3 text-ink sm:gap-4 sm:px-4">
      <h2 className="shrink-0 font-serif text-sm font-semibold" title="Bars show annual satellite detections. The number is the mapped annual energy proxy.">Heat History</h2>
      {error || loading || !inspected ? (
        <p role="status" className="min-w-0 flex-1 text-[11px] text-muted">{error ? "History unavailable" : loading ? "Loading…" : "No fire history"}</p>
      ) : <>
        <span className="shrink-0 font-mono text-xs text-terracotta tnum" aria-label="Inspected year">{inspected.year}</span>
        <div className="hidden min-w-0 flex-[2] min-[540px]:block">
          <svg viewBox={`0 0 ${annual.length * 10} 32`} preserveAspectRatio="none" className="h-7 w-full overflow-visible" role="group" aria-label="Satellite detections by year" onPointerLeave={() => setHovered(null)}>
            {annual.map((year, index) => {
              const height = Math.max(2, year.detections / max * 28);
              return <rect key={year.year} x={index * 10 + 1} y={30 - height} width={8} height={height} rx={1}
                fill={year.year === inspected.year ? "var(--color-thermal-4)" : "var(--color-rule-strong)"}
                className="cursor-pointer outline-offset-2" tabIndex={0} role="button"
                aria-label={`${year.year}: ${format(year.detections)} detections`} aria-pressed={year.year === selectedYear}
                onPointerEnter={() => { setHovered(year.year); setSelectedYear(year.year); }} onFocus={() => { setHovered(year.year); setSelectedYear(year.year); }} onBlur={() => setHovered(null)}
                onClick={() => setSelectedYear(year.year)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelectedYear(year.year); } }} />;
            })}
          </svg>
        </div>
        <input aria-label="Inspect heat history year" type="range" min={annual[0]?.year} max={annual[annual.length - 1]?.year} value={selectedYear} onChange={(e) => { setHovered(null); setSelectedYear(Number(e.target.value)); }} className="h-3 min-w-10 flex-1 accent-[#b30000]" />
        <p className="w-40 shrink-0 whitespace-nowrap text-right font-serif text-base tnum" aria-label="Mapped annual energy" title="Sum of visible cell energy density times exact cell area. Calibrated one-hour observation proxy, without regional Kalman gap filling.">
          {mapError ? "Unavailable" : mapLoading || mapYear !== inspected.year ? "Loading…" : format(mapped.energyGJ)} <span className="font-sans text-[10px] text-muted">GJ</span>
        </p>
      </>}
      <button type="button" onClick={onClose} aria-label="Hide heat history" className="ml-auto shrink-0 rounded-full p-1.5 text-muted hover:bg-paper"><X className="h-4 w-4" /></button>
    </section>
  );
}
