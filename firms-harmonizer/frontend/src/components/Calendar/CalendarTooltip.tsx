import React from "react";
import { useAnalysisStore } from "../../store/useAnalysisStore";
import { Activity, AlertTriangle, ShieldCheck, Zap } from "lucide-react";

export const CalendarTooltip: React.FC = () => {
  const { analysisData, hoveredDay } = useAnalysisStore();

  if (!hoveredDay || !analysisData || !analysisData.calendar_series) {
    return null;
  }

  // Extraer el año y DOY del string de hover (ej: "2022 (DOY: 226)")
  const match = hoveredDay.match(/(\d{4})\s+\(DOY:\s+(\d+)\)/);
  if (!match) return null;

  const year = parseInt(match[1], 10);
  const doy = parseInt(match[2], 10);

  // Buscar la celda correspondiente en el dataset analizado
  const cellData = analysisData.calendar_series.find(
    (c) => c.year === year && c.doy === doy
  );

  if (!cellData) return null;

  return (
    <div className="absolute bottom-4 right-4 z-30 w-80 bg-slate-900/95 backdrop-blur-md p-4 rounded-xl border border-slate-700 shadow-2xl text-slate-200 text-xs pointer-events-none animate-fade-in">
      {/* Cabecera del Tooltip */}
      <div className="flex items-center justify-between border-b border-slate-800 pb-2 mb-2">
        <div className="flex items-center gap-1.5 font-mono text-cyan-400 font-bold">
          <Activity className="w-4 h-4" />
          <span>{cellData.date}</span>
        </div>
        <span className="text-[10px] bg-slate-800 px-2 py-0.5 rounded text-slate-400 font-mono">
          DOY {cellData.doy}
        </span>
      </div>

      {/* Métricas Principales */}
      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="bg-slate-950/60 p-2 rounded border border-slate-800">
          <span className="text-slate-400 text-[10px] block">Harmonized FRE</span>
          <span className="text-sm font-bold text-cyan-300 font-mono">
            {cellData.harmonized_fre_mj_km2.toFixed(1)} <span className="text-[10px] font-normal text-slate-400">MJ/km²</span>
          </span>
        </div>
        <div className="bg-slate-950/60 p-2 rounded border border-slate-800">
          <span className="text-slate-400 text-[10px] block">Raw Hotspots</span>
          <span className="text-sm font-bold text-red-400 font-mono">
            {cellData.raw_hotspot_count} <span className="text-[10px] font-normal text-slate-400">count</span>
          </span>
        </div>
      </div>

      {/* Intervalo de Confianza y Incertidumbre */}
      <div className="space-y-1 mb-3 bg-slate-950/40 p-2 rounded border border-slate-800/80 font-mono text-[11px]">
        <div className="flex justify-between text-slate-300">
          <span>95% CI Range:</span>
          <span className="text-emerald-400">
            [{cellData.ci_95_lower.toFixed(1)} – {cellData.ci_95_upper.toFixed(1)}]
          </span>
        </div>
        <div className="flex justify-between text-slate-300">
          <span>Uncertainty ($\pm 1.96 \sigma$):</span>
          <span className="text-amber-400">{cellData.uncertainty_pct.toFixed(1)}%</span>
        </div>
        <div className="flex justify-between text-slate-300">
          <span>Z-Score Anomaly:</span>
          <span className={cellData.z_score_anomaly > 2 ? "text-red-400 font-bold" : "text-cyan-400"}>
            {cellData.z_score_anomaly.toFixed(2)} $\sigma$
          </span>
        </div>
      </div>

      {/* Estado de Gap Filling y Sensores */}
      <div className="flex flex-wrap items-center gap-1.5 mb-2">
        {cellData.is_gap_filled ? (
          <span className="inline-flex items-center gap-1 bg-cyan-950 text-cyan-300 border border-cyan-800 px-2 py-0.5 rounded text-[10px] font-medium">
            <Zap className="w-3 h-3 text-cyan-400" />
            Gap-Filled ({cellData.gap_reason})
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 bg-emerald-950 text-emerald-300 border border-emerald-800 px-2 py-0.5 rounded text-[10px] font-medium">
            <ShieldCheck className="w-3 h-3 text-emerald-400" />
            Clean Observation
          </span>
        )}

        <div className="text-[10px] text-slate-400 font-mono bg-slate-800/80 px-2 py-0.5 rounded ml-auto">
          {cellData.active_sensors.join(" | ")}
        </div>
      </div>

      {/* Narrativa Científica Exacta */}
      {cellData.tooltip_narrative && (
        <p className="text-[11px] text-slate-300 italic border-t border-slate-800 pt-2 leading-relaxed">
          "{cellData.tooltip_narrative}"
        </p>
      )}
    </div>
  );
};
