import React from "react";
import { useShallow } from "zustand/react/shallow";
import { Activity, AlertTriangle, Edit3, Flame, MapPin, RefreshCw, WifiOff, XCircle } from "lucide-react";
import { PRESET_ORDER, PRESET_REGIONS, useAnalysisStore, type PresetKey } from "../../store/useAnalysisStore";

/** Latency budget for the full /api/analyze round trip (backend contract test: < 250 ms). */
const LATENCY_BUDGET_MS = 250;

const isPresetKey = (value: string): value is PresetKey => value in PRESET_REGIONS;

export const AoiDrawControl: React.FC = () => {
  const {
    selectedPreset,
    loadPresetRegion,
    isDrawingAoi,
    setDrawingAoi,
    excludeIndustrial,
    setExcludeIndustrial,
    highlightIndustrialOnMap,
    setHighlightIndustrialOnMap,
    analysisData,
    loading,
    error,
    isSynthetic,
    executeAnalysis
  } = useAnalysisStore(
    useShallow((s) => ({
      selectedPreset: s.selectedPreset,
      loadPresetRegion: s.loadPresetRegion,
      isDrawingAoi: s.isDrawingAoi,
      setDrawingAoi: s.setDrawingAoi,
      excludeIndustrial: s.excludeIndustrial,
      setExcludeIndustrial: s.setExcludeIndustrial,
      highlightIndustrialOnMap: s.highlightIndustrialOnMap,
      setHighlightIndustrialOnMap: s.setHighlightIndustrialOnMap,
      analysisData: s.analysisData,
      loading: s.loading,
      error: s.error,
      isSynthetic: s.isSynthetic,
      executeAnalysis: s.executeAnalysis
    }))
  );

  const latency = analysisData?.execution_time_ms;
  const withinBudget = latency !== undefined && latency < LATENCY_BUDGET_MS;
  const drawLabel = isDrawingAoi ? "Drawing… (Esc to cancel)" : selectedPreset === "CUSTOM" ? "Redraw Custom AOI Box" : "Draw Custom AOI Box";

  return (
    <div className="absolute top-4 left-4 right-4 z-20 flex flex-wrap items-center justify-between gap-3 bg-slate-950/90 backdrop-blur-md px-4 py-3 rounded-xl border border-slate-800 shadow-2xl text-slate-200">
      {/* Pilot region selector */}
      <label className="flex items-center gap-2">
        <MapPin className="w-4 h-4 text-cyan-400 shrink-0" />
        <span className="text-xs font-semibold tracking-wide text-slate-400 uppercase hidden sm:inline">Region:</span>
        <select
          value={selectedPreset}
          onChange={(e) => {
            if (isPresetKey(e.target.value)) void loadPresetRegion(e.target.value);
          }}
          className="bg-slate-900 border border-slate-700 text-xs text-slate-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-cyan-500 font-medium"
          aria-label="Pilot region"
        >
          {PRESET_ORDER.map((key) => (
            <option key={key} value={key}>
              {PRESET_REGIONS[key].label}
            </option>
          ))}
          {selectedPreset === "CUSTOM" && <option value="CUSTOM">Custom Bounding Box</option>}
        </select>
      </label>

      {/* Interactive custom AOI box tool */}
      <button
        type="button"
        onClick={() => setDrawingAoi(!isDrawingAoi)}
        aria-pressed={isDrawingAoi}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
          isDrawingAoi
            ? "bg-cyan-600 text-white shadow-lg shadow-cyan-900/50 ring-2 ring-cyan-400"
            : "bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-300"
        }`}
        title="Drag a bounding box on the map to define a custom area of interest"
      >
        {isDrawingAoi ? <XCircle className="w-3.5 h-3.5" /> : <Edit3 className="w-3.5 h-3.5 text-cyan-400" />}
        <span>{drawLabel}</span>
      </button>

      {/* Industrial gas-flaring filter & inspector */}
      <div className="flex items-center gap-4 bg-slate-900/80 px-3 py-1.5 rounded-lg border border-slate-800">
        <label className="flex items-center gap-2 cursor-pointer text-xs">
          <input
            type="checkbox"
            checked={excludeIndustrial}
            onChange={(e) => void setExcludeIndustrial(e.target.checked)}
            className="rounded bg-slate-800 border-slate-700 text-cyan-500 focus:ring-cyan-500 h-3.5 w-3.5"
          />
          <span className="font-medium text-slate-300">Exclude Industrial Flaring</span>
        </label>

        <label className="flex items-center gap-2 cursor-pointer text-xs border-l border-slate-700 pl-3">
          <input
            type="checkbox"
            checked={highlightIndustrialOnMap}
            onChange={(e) => setHighlightIndustrialOnMap(e.target.checked)}
            className="rounded bg-slate-800 border-slate-700 text-pink-500 focus:ring-pink-500 h-3.5 w-3.5"
          />
          <Flame className="w-3.5 h-3.5 text-pink-400" />
          <span className="font-medium text-pink-400">
            Inspect Industrial Gas Flaring (H<sub>temp</sub> &gt; 0.75)
          </span>
        </label>
      </div>

      {/* Live status & latency badges */}
      <div className="flex items-center gap-2">
        {isSynthetic && !loading && (
          <span
            className="flex items-center gap-1 text-[10px] font-mono bg-amber-950 text-amber-300 border border-amber-800 px-2 py-1 rounded"
            title="Backend unreachable: showing the deterministic offline synthetic dataset"
          >
            <WifiOff className="w-3 h-3" />
            OFFLINE SYNTHETIC
          </span>
        )}

        {loading ? (
          <div className="flex items-center gap-1.5 text-xs text-amber-400 font-mono" role="status">
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            <span>Computing…</span>
          </div>
        ) : error ? (
          <div
            className="flex items-center gap-1.5 text-xs font-mono bg-red-950 border border-red-800 text-red-300 px-2.5 py-1 rounded max-w-[16rem]"
            title={error}
            role="alert"
          >
            <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
            <span className="truncate">{error}</span>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-xs font-mono bg-slate-900 px-2.5 py-1 rounded border border-slate-800 text-slate-300">
            <Activity className={`w-3.5 h-3.5 ${withinBudget ? "text-emerald-400" : "text-amber-400"}`} />
            <span>
              Latency:{" "}
              <strong className={withinBudget ? "text-emerald-400" : "text-amber-400"}>
                {latency !== undefined ? `${latency.toFixed(1)} ms` : "—"}
              </strong>
            </span>
            <span className="text-slate-600">|</span>
            <span className="text-cyan-400">{analysisData ? analysisData.total_h3_cells.toLocaleString("en-US") : "—"} H3 cells</span>
          </div>
        )}

        <button
          type="button"
          onClick={() => void executeAnalysis()}
          disabled={loading}
          className="p-1.5 bg-slate-900 hover:bg-slate-800 border border-slate-700 rounded-lg text-slate-300 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          title="Force re-run analysis"
          aria-label="Force re-run analysis"
        >
          <RefreshCw className="w-3.5 h-3.5 text-cyan-400" />
        </button>
      </div>
    </div>
  );
};
