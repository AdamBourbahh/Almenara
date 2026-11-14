import { Activity, ShieldCheck, Wrench } from "lucide-react";
import { useAnalysisStore } from "../../store/useAnalysisStore";
import { fmt, fmtDate } from "../../lib/format";

export function CalendarTooltip() {
  const analysisData = useAnalysisStore((state) => state.analysisData);
  const hoveredDay = useAnalysisStore((state) => state.hoveredDay);

  if (!hoveredDay || !analysisData) return null;

  const match = hoveredDay.match(/(\d{4})\s+\(DOY:\s+(\d+)\)/);
  if (!match) return null;

  const year = Number.parseInt(match[1], 10);
  const doy = Number.parseInt(match[2], 10);
  const cell = analysisData.calendar_series.find(
    (entry) => entry.year === year && entry.doy === doy,
  );
  if (!cell) return null;

  const anomaly =
    cell.z_score_anomaly > 1
      ? { label: "Above normal", tone: "text-danger" }
      : cell.z_score_anomaly < -1
        ? { label: "Below normal", tone: "text-info" }
        : { label: "Near normal", tone: "text-success" };

  return (
    <div className="pointer-events-none absolute bottom-4 right-4 z-30 w-72 rounded-xl border border-line bg-surface/95 p-4 text-xs shadow-float backdrop-blur">
      <div className="flex items-center justify-between border-b border-line pb-2">
        <span className="flex items-center gap-1.5 font-medium text-ink">
          <Activity className="h-3.5 w-3.5 text-ember" />
          {fmtDate(cell.date)}
        </span>
        <span className="rounded bg-base/70 px-1.5 py-0.5 font-mono text-[10px] text-dim">
          DOY {cell.doy}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <div className="rounded-lg border border-line bg-base/50 p-2">
          <p className="text-[10px] text-dim">Fire intensity</p>
          <p className="font-tabular text-sm font-semibold text-ember">
            {fmt(cell.harmonized_fre_mj_km2)}
            <span className="ml-1 text-[9px] font-normal text-dim">MJ/km²</span>
          </p>
        </div>
        <div className="rounded-lg border border-line bg-base/50 p-2">
          <p className="text-[10px] text-dim">Hotspots</p>
          <p className="font-tabular text-sm font-semibold text-ink">
            {cell.raw_hotspot_count}
          </p>
        </div>
      </div>

      <div className="mt-2 flex items-center justify-between rounded-lg border border-line bg-base/40 px-2 py-1.5 text-[11px]">
        <span className="text-dim">Compared to normal</span>
        <span className={`font-medium ${anomaly.tone}`}>{anomaly.label}</span>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {cell.is_gap_filled ? (
          <span className="inline-flex items-center gap-1 rounded-md border border-info/40 bg-info/10 px-2 py-0.5 text-[10px] font-medium text-info">
            <Wrench className="h-3 w-3" />
            Repaired from {cell.gap_reason ?? "sensor gap"}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-md border border-success/40 bg-success/10 px-2 py-0.5 text-[10px] font-medium text-success">
            <ShieldCheck className="h-3 w-3" />
            Clean observation
          </span>
        )}
        <span className="ml-auto font-mono text-[10px] text-dim">
          {cell.active_sensors.join(" · ") || "no sensors"}
        </span>
      </div>

      <p className="mt-2 border-t border-line pt-2 text-[10px] leading-relaxed text-dim">
        {cell.tooltip_narrative}
      </p>
    </div>
  );
}
