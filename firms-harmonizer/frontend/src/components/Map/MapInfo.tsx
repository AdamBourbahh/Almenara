import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";
import { useAnalysisStore } from "../../store/useAnalysisStore";

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
  const { analysisData, selectedPreset, selectedYear, setSelectedYear } = useAnalysisStore(
    useShallow((s) => ({
      analysisData: s.analysisData,
      selectedPreset: s.selectedPreset,
      selectedYear: s.selectedYear,
      setSelectedYear: s.setSelectedYear
    }))
  );

  const cells = analysisData?.calendar_series ?? [];
  const annual = useMemo(
    () => (analysisData?.phenology_by_year ?? []).map((p) => ({ year: p.year, fre: p.total_annual_fre_gj })),
    [analysisData]
  );

  const totalFires = cells.reduce((sum, c) => sum + c.raw_hotspot_count, 0);
  const area = analysisData?.aoi_area_km2 ?? 0;
  const biomass = analysisData?.audit_metrics?.total_biomass_burned_kt ?? 0;
  const pm25 = analysisData?.audit_metrics?.total_pm25_emitted_tonnes ?? 0;

  const maxAnnual = Math.max(1, ...annual.map((a) => a.fre));
  const peak = annual.reduce((best, a) => (a.fre > best.fre ? a : best), { year: 0, fre: 0 });
  const selected = annual.find((a) => a.year === selectedYear);
  const yearMin = annual.length ? annual[0].year : 2001;
  const yearMax = annual.length ? annual[annual.length - 1].year : 2026;

  const barWidth = 6;

  return (
    <div className="p-4">
      <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-faint">About this area</p>
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
          <dd className="font-serif text-lg text-ink tnum">{fmt(biomass, 1)} kt</dd>
        </div>
        <div>
          <dt className="text-[10px] text-faint">PM2.5 emitted</dt>
          <dd className="font-serif text-lg text-ink tnum">{fmt(pm25, 1)} t</dd>
        </div>
        <div>
          <dt className="text-[10px] text-faint">Years on record</dt>
          <dd className="font-serif text-lg text-ink tnum">{annual.length || "—"}</dd>
        </div>
      </dl>

      <div className="mt-4 border-t border-rule pt-3">
        <div className="flex items-baseline justify-between">
          <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-faint">Heat history</p>
          <p className="font-mono text-[10px] text-faint tnum">GJ per year</p>
        </div>

        {annual.length > 0 && (
          <svg
            viewBox={`0 0 ${annual.length * barWidth} 72`}
            preserveAspectRatio="none"
            className="mt-2 h-20 w-full"
            role="img"
            aria-label="Annual fire energy for the selected area"
          >
            {annual.map((a, i) => {
              const h = Math.max(2, (a.fre / maxAnnual) * 66);
              const active = a.year === selectedYear;
              return (
                <rect
                  key={a.year}
                  x={i * barWidth + 0.5}
                  y={70 - h}
                  width={barWidth - 1}
                  height={h}
                  fill={active ? "var(--color-thermal-4)" : "var(--color-rule-strong)"}
                />
              );
            })}
          </svg>
        )}

        <div className="mt-1 flex justify-between text-[10px] text-faint tnum">
          <span>{yearMin}</span>
          <span>{yearMax}</span>
        </div>

        <label className="mt-3 block text-[11px] text-muted">
          Inspect year
          <input
            type="range"
            min={yearMin}
            max={yearMax}
            value={selectedYear}
            onChange={(e) => setSelectedYear(Number(e.target.value))}
            className="mt-1 w-full accent-[#b30000]"
            aria-label="Inspect year"
          />
        </label>

        <p className="mt-1 text-[11px] leading-relaxed text-muted tnum">
          {selected ? (
            <>
              <span className="font-medium text-ink">{selected.year}</span>: {fmt(selected.fre)} GJ
              {peak.year > 0 && selected.year !== peak.year && (
                <span className="text-faint"> · {fmt((selected.fre / peak.fre) * 100)}% of the peak</span>
              )}
            </>
          ) : (
            "No yearly totals for this area."
          )}
        </p>

        <p className="mt-2 text-[10px] leading-relaxed text-faint">
          The map shows the average over the whole period. Year-by-year heat on the map needs the
          per-hexagon yearly data from the full dataset.
        </p>
      </div>
    </div>
  );
}
