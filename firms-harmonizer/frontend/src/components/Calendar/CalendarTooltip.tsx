import React from "react";
import { createPortal } from "react-dom";
import { useShallow } from "zustand/react/shallow";
import { Activity, CloudOff, Satellite, ShieldCheck, TrendingUp, Zap } from "lucide-react";
import type { GapReason } from "../../api/types";
import { calendarKey, useAnalysisStore } from "../../store/useAnalysisStore";

const TOOLTIP_WIDTH = 320;
const TOOLTIP_EST_HEIGHT = 300;
const OFFSET = 16;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const GAP_REASON_LABEL: Record<GapReason, string> = {
  NONE: "None",
  SENSOR_OUTAGE: "Sensor outage",
  CLOUD_OCCLUSION: "Cloud occlusion",
  SWATH_GAP: "Swath gap",
  MULTI_FACTOR: "Multi-factor"
};

function formatDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return Number.isFinite(y) && m >= 1 && m <= 12 ? `${MONTHS[m - 1]} ${d}, ${y}` : iso;
}

const fmt = (value: number | undefined, digits = 1) => (value === undefined || !Number.isFinite(value) ? "—" : value.toFixed(digits));

/**
 * Floating scientific tooltip for the Burning Calendar. Follows the pointer (position: fixed,
 * rendered in a portal so transformed / backdrop-filtered ancestors cannot offset it).
 * Lookup is O(1) through the store's calendarIndex.
 */
export const CalendarTooltip: React.FC = () => {
  const { hoveredDay, calendarIndex } = useAnalysisStore(
    useShallow((s) => ({ hoveredDay: s.hoveredDay, calendarIndex: s.calendarIndex }))
  );

  if (!hoveredDay || typeof document === "undefined") return null;
  const cell = calendarIndex.get(calendarKey(hoveredDay.year, hoveredDay.doy));
  if (!cell) return null;

  const viewportW = window.innerWidth;
  const viewportH = window.innerHeight;
  let left = hoveredDay.clientX + OFFSET;
  if (left + TOOLTIP_WIDTH > viewportW - 8) left = hoveredDay.clientX - OFFSET - TOOLTIP_WIDTH;
  let top = hoveredDay.clientY + OFFSET;
  if (top + TOOLTIP_EST_HEIGHT > viewportH - 8) top = hoveredDay.clientY - OFFSET - TOOLTIP_EST_HEIGHT;
  left = Math.max(8, left);
  top = Math.max(8, top);

  const isForecast = cell.is_forecast === true;
  const zHigh = Math.abs(cell.z_score_anomaly) > 2;

  return createPortal(
    <div
      role="tooltip"
      style={{ left, top, width: TOOLTIP_WIDTH }}
      className="fixed z-50 bg-slate-900/95 backdrop-blur-md p-4 rounded-xl border border-slate-700 shadow-2xl text-slate-200 text-xs pointer-events-none"
    >
      <div className="flex items-center justify-between border-b border-slate-800 pb-2 mb-2">
        <div className="flex items-center gap-1.5 font-mono text-cyan-400 font-bold">
          <Activity className="w-4 h-4" />
          <span>{formatDate(cell.date)}</span>
        </div>
        <span className="text-[10px] bg-slate-800 px-2 py-0.5 rounded text-slate-400 font-mono">DOY {cell.doy}</span>
      </div>

      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="bg-slate-950/60 p-2 rounded border border-slate-800">
          <span className="text-slate-400 text-[10px] block">{isForecast ? "Forecast FRE" : "Harmonized FRE"}</span>
          <span className="text-sm font-bold text-cyan-300 font-mono">
            {fmt(cell.harmonized_fre_mj_km2)} <span className="text-[10px] font-normal text-slate-400">MJ/km²</span>
          </span>
        </div>
        <div className="bg-slate-950/60 p-2 rounded border border-slate-800">
          <span className="text-slate-400 text-[10px] block">Raw Hotspots</span>
          <span className="text-sm font-bold text-red-400 font-mono">
            {isForecast ? "—" : cell.raw_hotspot_count}{" "}
            <span className="text-[10px] font-normal text-slate-400">{isForecast ? "" : `· ${fmt(cell.raw_frp_mw, 0)} MW`}</span>
          </span>
        </div>
      </div>

      <div className="space-y-1 mb-3 bg-slate-950/40 p-2 rounded border border-slate-800/80 font-mono text-[11px]">
        <div className="flex justify-between text-slate-300">
          <span>95% CI range:</span>
          <span className="text-emerald-400">
            [{fmt(cell.ci_95_lower)} – {fmt(cell.ci_95_upper)}]
          </span>
        </div>
        <div className="flex justify-between text-slate-300">
          <span>Uncertainty (±1.96σ):</span>
          <span className="text-amber-400">{fmt(cell.uncertainty_pct)}%</span>
        </div>
        <div className="flex justify-between text-slate-300">
          <span>Z-score anomaly:</span>
          <span className={zHigh ? "text-red-400 font-bold" : "text-cyan-400"}>{fmt(cell.z_score_anomaly, 2)}σ</span>
        </div>
        {cell.historical_cross_prior_fre !== undefined && (
          <div className="flex justify-between text-slate-300">
            <span>Cross-guard prior:</span>
            <span className="text-amber-300">{fmt(cell.historical_cross_prior_fre)} MJ/km²</span>
          </div>
        )}
        {(cell.total_biomass_burned_kt !== undefined || cell.pm25_emitted_kg !== undefined) && (
          <div className="flex justify-between text-slate-300">
            <span>Biomass · PM2.5:</span>
            <span className="text-orange-300">
              {fmt(cell.total_biomass_burned_kt, 2)} kt · {fmt(cell.pm25_emitted_kg, 0)} kg
            </span>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-1.5 mb-2">
        {isForecast ? (
          <span className="inline-flex items-center gap-1 bg-amber-950 text-amber-300 border border-amber-800 px-2 py-0.5 rounded text-[10px] font-medium">
            <TrendingUp className="w-3 h-3 text-amber-400" />
            14-day operational forecast
          </span>
        ) : cell.is_gap_filled ? (
          <span className="inline-flex items-center gap-1 bg-cyan-950 text-cyan-300 border border-cyan-800 px-2 py-0.5 rounded text-[10px] font-medium">
            <Zap className="w-3 h-3 text-cyan-400" />
            Gap-filled · {GAP_REASON_LABEL[cell.gap_reason]}
          </span>
        ) : cell.gap_reason !== "NONE" ? (
          <span className="inline-flex items-center gap-1 bg-red-950 text-red-300 border border-red-800 px-2 py-0.5 rounded text-[10px] font-medium">
            <CloudOff className="w-3 h-3 text-red-400" />
            Unfilled gap · {GAP_REASON_LABEL[cell.gap_reason]}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 bg-emerald-950 text-emerald-300 border border-emerald-800 px-2 py-0.5 rounded text-[10px] font-medium">
            <ShieldCheck className="w-3 h-3 text-emerald-400" />
            Clean observation
          </span>
        )}

        {cell.active_sensors.length > 0 && (
          <div className="flex items-center gap-1 text-[10px] text-slate-400 font-mono bg-slate-800/80 px-2 py-0.5 rounded ml-auto">
            <Satellite className="w-3 h-3" />
            {cell.active_sensors.join(" | ")}
          </div>
        )}
      </div>

      {cell.tooltip_narrative && (
        <p className="text-[11px] text-slate-300 italic border-t border-slate-800 pt-2 leading-relaxed">“{cell.tooltip_narrative}”</p>
      )}
    </div>,
    document.body
  );
};
