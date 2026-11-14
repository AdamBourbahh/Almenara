import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";
import { PRESET_REGIONS, useAnalysisStore } from "../../store/useAnalysisStore";

const DESCRIPTIONS: Record<string, string> = {
  CERRADO:
    "The Brazilian Cerrado and Pantanal burn in a sharp dry-season peak. This is where the 2012 sensor change is easiest to spot: raw hot-spot counts jump while the harmonized energy record stays continuous.",
  SIERRA_NEVADA:
    "California's Sierra Nevada has a summer fire season that now starts earlier and lasts longer. Compare the peak date across years to see the shift.",
  IBERIA:
    "The Iberian Peninsula mixes coastal and mountain fuels. The H3 grid keeps fine detail along the coast and ridges, where fires behave very differently.",
  NIGER_DELTA:
    "The Niger Delta combines oil and gas flaring with real vegetation fires. The industrial filter separates the year-round flares from seasonal burning.",
  CUSTOM: "A custom area. Draw a box or enter coordinates to analyse it."
};

function fmt(value: number, digits = 0): string {
  if (!Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function MapInfo() {
  const { analysisData, selectedPreset } = useAnalysisStore(
    useShallow((s) => ({
      analysisData: s.analysisData,
      selectedPreset: s.selectedPreset,
    }))
  );

  const cells = analysisData?.calendar_series ?? [];
  const annual = useMemo(
    () => (analysisData?.phenology_by_year ?? []).map((p) => ({ year: p.year, fre: p.total_annual_fre_gj })),
    [analysisData]
  );

  const totalFires = cells.reduce((sum, c) => sum + c.raw_hotspot_count, 0);
  const area = analysisData?.aoi_area_km2 ?? 0;
  const biomass = analysisData?.audit_metrics?.total_biomass_burned_kt;
  const pm25 = analysisData?.audit_metrics?.total_pm25_emitted_tonnes;

  const peak = annual.reduce((best, a) => (a.fre > best.fre ? a : best), { year: 0, fre: 0 });

  return (
    <div className="p-4">
      <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-faint">About this area</p>
      <h3 className="mt-2 font-serif text-lg text-ink">{selectedPreset === "CUSTOM" ? "Selected area" : PRESET_REGIONS[selectedPreset].label}</h3>
      <p className="mt-2 text-xs leading-relaxed text-muted">
        {DESCRIPTIONS[selectedPreset] ?? DESCRIPTIONS.CUSTOM}
      </p>

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-rule pt-3">
        <div>
          <dt className="text-[10px] text-faint">Fires detected</dt>
          <dd className="font-serif text-lg text-ink tnum">{fmt(totalFires)}</dd>
        </div>
        <div>
          <dt className="text-[10px] text-faint">Peak year</dt>
          <dd className="font-serif text-lg text-ink tnum">{peak.year || "—"}</dd>
        </div>
        <div>
          <dt className="text-[10px] text-faint">Area analysed</dt>
          <dd className="font-serif text-lg text-ink tnum">{fmt(area)} km²</dd>
        </div>
        <div>
          <dt className="text-[10px] text-faint">Dry biomass</dt>
          <dd className="font-serif text-lg text-ink tnum">{biomass == null ? "—" : `${fmt(biomass, 1)} kt`}</dd>
        </div>
        <div>
          <dt className="text-[10px] text-faint">PM2.5 emitted</dt>
          <dd className="font-serif text-lg text-ink tnum">{pm25 == null ? "—" : `${fmt(pm25, 1)} t`}</dd>
        </div>
        <div>
          <dt className="text-[10px] text-faint">Years on record</dt>
          <dd className="font-serif text-lg text-ink tnum">{annual.length || "—"}</dd>
        </div>
      </dl>

    </div>
  );
}
