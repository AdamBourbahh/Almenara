import React from "react";
import { createPortal } from "react-dom";
import { useShallow } from "zustand/react/shallow";
import { CloudOff, Satellite, ShieldCheck, TrendingUp, Wrench } from "lucide-react";
import { useAnalysisStore } from "../../store/useAnalysisStore";

const TOOLTIP_WIDTH = 320;
const TOOLTIP_EST_HEIGHT = 380;
const OFFSET = 16;

const GAP_REASON_LABEL: Record<string, string> = {
  NONE: "None",
  SENSOR_OUTAGE: "Sensor outage",
  CLOUD_OCCLUSION: "Cloud cover",
  SWATH_GAP: "Swath gap",
  MULTI_FACTOR: "Multiple causes"
};

function gapLabel(reason: string | null): string {
  if (!reason) return "Unknown";
  return GAP_REASON_LABEL[reason] ?? reason;
}

function formatDate(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

const fmt = (value: number | null | undefined, digits = 1) =>
  value == null || !Number.isFinite(value) ? "—" : value.toFixed(digits);

/**
 * Cell detail card for the burning calendar, rendered in a portal so transformed
 * ancestors cannot offset it. Lookup is O(1) through the store calendar index.
 */
export const CalendarTooltip: React.FC = () => {
  const { hoveredDay, hoveredCell, isDatePinned, selectedDate, dateIndex } = useAnalysisStore(
    useShallow((s) => ({ hoveredDay: s.hoveredDay, hoveredCell: s.hoveredCell, isDatePinned: s.isDatePinned, selectedDate: s.selectedDate, dateIndex: s.dateIndex }))
  );
  const cell = isDatePinned && selectedDate ? dateIndex.get(selectedDate) : hoveredCell;
  if (!cell || typeof document === "undefined") return null;
  const anchor = hoveredDay ?? { clientX: window.innerWidth - TOOLTIP_WIDTH - OFFSET - 8, clientY: 180 };

  const viewportW = window.innerWidth;
  const viewportH = window.innerHeight;
  const width = Math.min(TOOLTIP_WIDTH, viewportW - 16);
  let left = anchor.clientX + OFFSET;
  if (left + width > viewportW - 8) left = anchor.clientX - OFFSET - width;
  let top = anchor.clientY + OFFSET;
  if (top + TOOLTIP_EST_HEIGHT > viewportH - 8) top = anchor.clientY - OFFSET - TOOLTIP_EST_HEIGHT;
  left = Math.max(8, left);
  top = Math.max(8, top);

  const isForecast = cell.is_forecast === true;
  const zHigh = Math.abs(cell.z_score_anomaly) > 2;

  return createPortal(
    <div
      role="tooltip"
      style={{ left, top, width }}
      className="pointer-events-none fixed z-50 border border-rule bg-panel p-4 text-xs text-ink"
    >
      <div className="mb-2 flex items-center justify-between border-b border-rule pb-2">
        <span className="font-serif text-sm text-ink">{formatDate(cell.date)}</span>
        <span className="text-[10px] text-faint tnum">DOY {cell.doy}{isDatePinned ? " · pinned" : ""}</span>
      </div>

      <div className="mb-3 grid grid-cols-2 gap-2">
        <div className="border border-rule p-2">
          <span className="block text-[10px] text-faint">
            {isForecast ? "Forecast energy" : "Harmonized energy"}
          </span>
          <span className="text-sm font-medium text-thermal-4 tnum">
            {fmt(cell.harmonized_fre_mj_km2)}{" "}
            <span className="text-[10px] font-normal text-faint">MJ/km²</span>
          </span>
        </div>
        <div className="border border-rule p-2">
          <span className="block text-[10px] text-faint">Raw hotspots</span>
          <span className="text-sm font-medium text-raw tnum">
            {isForecast ? "—" : cell.raw_hotspot_count}{" "}
            <span className="text-[10px] font-normal text-faint">
              {isForecast ? "" : `· ${fmt(cell.raw_frp_mw, 0)} MW`}
            </span>
          </span>
        </div>
      </div>

      <div className="mb-3 space-y-1 border border-rule p-2 text-[11px] tnum">
        <div className="flex justify-between text-muted">
          <span>95% range</span>
          <span className="text-ink">
            [{fmt(cell.ci_95_lower)} – {fmt(cell.ci_95_upper)}]
          </span>
        </div>
        <div className="flex justify-between text-muted">
          <span>Uncertainty (±1.96σ)</span>
          <span className="text-terracotta">{fmt(cell.uncertainty_pct)}%</span>
        </div>
        <div className="flex justify-between text-muted">
          <span>Anomaly (z)</span>
          <span className={zHigh ? "font-medium text-bias" : "text-ink"}>{fmt(cell.z_score_anomaly, 2)}σ</span>
        </div>
        {cell.historical_cross_prior_fre !== undefined && (
          <div className="flex justify-between text-muted">
            <span>Historical baseline</span>
            <span className="text-ink">{fmt(cell.historical_cross_prior_fre)} MJ/km²</span>
          </div>
        )}
        {(cell.biomass_burned_tonnes > 0 || cell.pm25_emitted_kg != null) && (
          <div className="flex justify-between text-muted">
            <span>Biomass · PM2.5</span>
            <span className="text-ink">
              {fmt(cell.biomass_burned_tonnes, 1)} t · {fmt(cell.pm25_emitted_kg, 0)} kg
            </span>
          </div>
        )}
      </div>

      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        {isForecast ? (
          <span className="inline-flex items-center gap-1 border border-terracotta/40 bg-terracotta/10 px-2 py-0.5 text-[10px] text-terracotta">
            <TrendingUp className="h-3 w-3" />
            14-day operational forecast
          </span>
        ) : cell.is_gap_filled ? (
          <span className="inline-flex items-center gap-1 border border-reference/40 bg-reference/10 px-2 py-0.5 text-[10px] text-reference">
            <Wrench className="h-3 w-3" />
            Repaired · {gapLabel(cell.gap_reason)}
          </span>
        ) : cell.gap_reason && cell.gap_reason !== "NONE" ? (
          <span className="inline-flex items-center gap-1 border border-bias/40 bg-bias/10 px-2 py-0.5 text-[10px] text-bias">
            <CloudOff className="h-3 w-3" />
            Unfilled gap · {gapLabel(cell.gap_reason)}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 border border-validated/40 bg-validated/10 px-2 py-0.5 text-[10px] text-validated">
            <ShieldCheck className="h-3 w-3" />
            Clean observation
          </span>
        )}

        {cell.active_sensors.length > 0 && (
          <span className="ml-auto flex items-center gap-1 text-[10px] text-faint">
            <Satellite className="h-3 w-3" />
            {cell.active_sensors.join(" · ")}
          </span>
        )}
      </div>

      {cell.tooltip_narrative && (
        <p className="border-t border-rule pt-2 text-[11px] leading-relaxed text-muted">{cell.tooltip_narrative}</p>
      )}
    </div>,
    document.body
  );
};
