import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";
import { PRESET_REGIONS, selectedMapPeriod, useAnalysisStore } from "../../store/useAnalysisStore";
import { summarizeMappedYear } from "./mapMetrics";

const DESCRIPTIONS: Record<string, string> = {
  chilecito_la_rioja: "Local FIRMS observations around Chilecito and La Rioja, Argentina.",
  iberia_med: "The supplied Iberian rectangle includes Spain, Portugal and adjacent areas; it is not a country boundary.",
  orlando_florida: "Local FIRMS observations around Orlando, Florida, USA.",
  amazonas_manaus: "The supplied Manaus-area rectangle, rather than the entire Amazon basin.",
  CUSTOM: "A custom selected area, intersected with the available local FIRMS coverage."
};
function fmt(value: number, digits = 0): string {
  return Number.isFinite(value) ? value.toLocaleString("en-US", { maximumFractionDigits: digits }) : "—";
}
export function MapInfo() {
  const { analysisData, selectedPreset, requestedPeriod, mapHexagons, mapPeriod, mapLoading, mapError, excludeIndustrial, loading } = useAnalysisStore(
    useShallow((s) => ({ analysisData: s.analysisData, selectedPreset: s.selectedPreset,
      requestedPeriod: selectedMapPeriod(s), mapHexagons: s.mapHexagons, mapPeriod: s.mapPeriod,
      mapLoading: s.mapLoading, mapError: s.mapError, excludeIndustrial: s.excludeIndustrial, loading: s.loading }))
  );
  const mapped = useMemo(() => summarizeMappedYear(mapHexagons, excludeIndustrial), [mapHexagons, excludeIndustrial]);
  const ready = !loading && !mapLoading && !mapError && mapPeriod === requestedPeriod;
  const cells = analysisData?.calendar_series ?? [];
  const [rangeStart, rangeEnd] = requestedPeriod.split("..");
  const periodCells=cells.filter(c=>(rangeEnd ? c.date >= rangeStart && c.date <= rangeEnd : c.date.startsWith(requestedPeriod)) && !c.is_forecast);
  const regionalBiomass=periodCells.reduce((sum,c)=>sum+c.biomass_burned_tonnes,0);
  const regionalEnergy=regionalBiomass/.368;
  const filledDays=periodCells.filter(c=>c.is_gap_filled).length;
  const totalDetections = cells.reduce((sum, c) => sum + c.raw_hotspot_count, 0);
  const countsByYear = new Map<number, number>();
  for (const day of cells) countsByYear.set(day.year, (countsByYear.get(day.year) ?? 0) + day.raw_hotspot_count);
  const peak = Array.from(countsByYear).reduce((best, entry) => entry[1] > best[1] ? entry : best, [0, 0]);
  // 1 GJ = 1000 MJ; Wooster 0.368 kg/MJ; 1 kt = 1,000,000 kg.
  const mappedBiomassKt = mapped.energyGJ * 0.000368;
  const value = (number: number, suffix = "") => ready ? `${fmt(number)}${suffix}` : "—";
  return (
    <div className="p-4">
      <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-faint">About this area</p>
      <h3 className="mt-2 font-serif text-lg text-ink">{selectedPreset === "CUSTOM" ? "Selected area" : PRESET_REGIONS[selectedPreset].label}</h3>
      <p className="mt-2 text-xs leading-relaxed text-muted">{DESCRIPTIONS[selectedPreset] ?? DESCRIPTIONS.CUSTOM}</p>
      <p className="mt-3 text-xs text-muted">{analysisData?.data_source === "real" ? "Source: local FIRMS observations" : analysisData?.data_source === "synthetic" ? "Source: synthetic demonstration" : "Source: awaiting analysis"}</p>
      <h4 className="mt-4 text-xs font-medium text-ink">Visible map · {requestedPeriod}</h4>
      {mapError && <p role="status" className="text-xs text-terracotta">Map period unavailable</p>}
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-rule pt-3">
        <div><dt className="text-[10px] text-faint">Mapped detections</dt><dd className="font-serif text-lg text-ink tnum">{value(mapped.detections)}</dd></div>
        <div><dt className="text-[10px] text-faint">Active grid cells</dt><dd className="font-serif text-lg text-ink tnum">{value(mapped.hexagons.length)}</dd></div>
        <div><dt className="text-[10px] text-faint">Mapped energy proxy</dt><dd className="font-serif text-lg text-ink tnum">{value(mapped.energyGJ, " GJ")}</dd></div>
        <div><dt className="text-[10px] text-faint">Observed cell footprint</dt><dd className="font-serif text-lg text-ink tnum">{value(mapped.footprintKm2, " km²")}</dd></div>
        <div><dt className="text-[10px] text-faint">Estimated dry biomass</dt><dd className="font-serif text-lg text-ink tnum">{ready ? `${fmt(mappedBiomassKt, 2)} kt` : "—"}</dd></div>
        <div><dt className="text-[10px] text-faint">PM2.5 estimate</dt><dd className="font-serif text-lg text-ink tnum">Not computed</dd></div>
      </dl>
      <p className="mt-2 text-[10px] leading-relaxed text-muted">Detections are satellite pixels, not separate fires. Energy uses the calibrated one-hour proxy; biomass applies 0.368 kg/MJ to that same energy and is not an independent measurement. Cell footprint is not burned area. Missing cells are not proof of zero fire. The first satellite detection is not necessarily the ignition date.</p>
      <h4 className="mt-4 text-xs font-medium text-ink">Regional model · {requestedPeriod}</h4>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-rule pt-3">
        <div><dt className="text-[10px] text-faint">Regional model energy</dt><dd className="font-serif text-lg text-ink tnum">{ready && periodCells.length ? `${fmt(regionalEnergy)} GJ` : '—'}</dd></div>
        <div><dt className="text-[10px] text-faint">Regional model biomass</dt><dd className="font-serif text-lg text-ink tnum">{ready && periodCells.length ? `${fmt(regionalBiomass/1000,2)} kt` : '—'}</dd></div>
      </dl>
      <p className="mt-2 text-[10px] text-faint">Selected query area: {ready && analysisData ? `${fmt(analysisData.aoi_area_km2)} km²` : '—'}. This is distinct from the observed footprint above.</p>
      <p className="mt-2 text-[10px] leading-relaxed text-muted">The chat's regional model aggregates sensor densities before optional reconstruction. The map integrates observations per cell, so these estimates can differ even with reconstruction off. {ready && periodCells.length ? `${periodCells.length} available days; ${filledDays} marked as reconstructed. Data through ${periodCells.at(-1)?.date}.` : ''} A full-year selection does not add future observations.</p>
      <h4 className="mt-4 text-xs font-medium text-ink">Full record · {cells[0]?.year ?? "—"}–{cells[cells.length - 1]?.year ?? "—"}</h4>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-rule pt-3">
        <div><dt className="text-[10px] text-faint">Recorded detections</dt><dd className="font-serif text-lg text-ink tnum">{loading || !analysisData ? "—" : fmt(totalDetections)}</dd></div>
        <div><dt className="text-[10px] text-faint">Peak detection year</dt><dd className="font-serif text-lg text-ink tnum">{loading ? "—" : peak[0] || "—"}</dd></div>
      </dl>
      <p className="mt-2 text-[10px] leading-relaxed text-muted">Full-record counts use the current industrial filter. Detection counts depend on sensor availability. Neither the regional Kalman estimate nor its gap-filled energy is used for these mapped totals.</p>

    </div>
  );
}
