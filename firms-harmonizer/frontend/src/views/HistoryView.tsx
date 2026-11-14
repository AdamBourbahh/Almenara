import { CalendarDays } from "lucide-react";
import { BurningCalendarCanvas } from "../components/Calendar/BurningCalendarCanvas";
import { CalendarTooltip } from "../components/Calendar/CalendarTooltip";
import { InsightCard, MiniStat } from "./common";
import { useAnalysisStore } from "../store/useAnalysisStore";
import { fmtInt } from "../lib/format";

export function HistoryView() {
  const analysisData = useAnalysisStore((state) => state.analysisData);
  const cells = analysisData?.calendar_series ?? [];

  const years = analysisData?.phenology_by_year.map((entry) => entry.year) ?? [];
  const yearMin = years.length > 0 ? Math.min(...years) : 2001;
  const yearMax = years.length > 0 ? Math.max(...years) : 2026;

  let totalHotspots = 0;
  let gapDays = 0;
  const byYear = new Map<number, number>();
  for (const cell of cells) {
    totalHotspots += cell.raw_hotspot_count;
    if (cell.is_gap_filled) gapDays += 1;
    byYear.set(cell.year, (byYear.get(cell.year) ?? 0) + cell.harmonized_fre_mj_km2);
  }

  let peakYear = yearMin;
  let peakValue = -1;
  for (const [year, value] of byYear) {
    if (value > peakValue) {
      peakValue = value;
      peakYear = year;
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1320px] space-y-5 px-6 py-7">
        <div className="flex flex-wrap items-start justify-between gap-6">
          <p className="max-w-xl text-sm leading-relaxed text-dim">
            Every row is a year, every column a day. Warm bands show when fire
            activity peaks; the vertical curtain compares raw pixel counts with
            the harmonized record.
          </p>
          <div className="flex flex-wrap gap-7">
            <MiniStat label="Years covered" value={`${yearMin}–${yearMax}`} />
            <MiniStat label="Total hotspots" value={fmtInt(totalHotspots)} />
            <MiniStat
              label="Peak year"
              value={String(peakYear)}
              tone="text-ember"
            />
            <MiniStat
              label="Auto-repaired days"
              value={fmtInt(gapDays)}
              tone="text-info"
            />
          </div>
        </div>

        <div className="relative">
          <BurningCalendarCanvas />
          <CalendarTooltip />
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          <InsightCard
            title="Read the seasons"
            icon={<CalendarDays className="h-4 w-4 text-ember" />}
          >
            Horizontal warm bands mark the months when a region burns. Compare
            any year against the others to see whether a season started earlier,
            lasted longer, or burned harder.
          </InsightCard>
          <InsightCard
            title="Raw vs comparable"
            icon={<CalendarDays className="h-4 w-4 text-info" />}
          >
            Drag the curtain: the left side shows raw detections (with the 2012
            jump), the right side the harmonized series where the sensor no
            longer changes the pattern.
          </InsightCard>
          <InsightCard
            title="Repaired, not erased"
            icon={<CalendarDays className="h-4 w-4 text-success" />}
          >
            Hatched cells are days where a satellite gap was reconstructed with a
            statistically guarded model — never silently set to zero.
          </InsightCard>
        </div>
      </div>
    </div>
  );
}
