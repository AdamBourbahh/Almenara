import React, { useState } from "react";
import { useAnalysisStore, PRESET_REGIONS } from "../../store/useAnalysisStore";
import { Flame, Layers, MapPin, Edit3, Activity, RefreshCw } from "lucide-react";

export const AoiDrawControl: React.FC = () => {
  const {
    selectedPreset,
    loadPresetRegion,
    setCustomAoi,
    excludeIndustrial,
    setExcludeIndustrial,
    highlightIndustrialOnMap,
    setHighlightIndustrialOnMap,
    analysisData,
    loading,
    executeAnalysis
  } = useAnalysisStore();

  const [isDrawingCustom, setIsDrawingCustom] = useState(false);

  // Simulador interactivo de dibujo manual de Bounding Box para pruebas rápidas
  const handleToggleDrawBox = () => {
    if (!isDrawingCustom) {
      setIsDrawingCustom(true);
      // Definir un AOI personalizado de prueba (ej: área sobre Córdoba / San Juan)
      const customCoords = [[
        [-68.5, -30.0],
        [-67.0, -30.0],
        [-67.0, -31.0],
        [-68.5, -31.0],
        [-68.5, -30.0]
      ]];
      setCustomAoi(customCoords);
    } else {
      setIsDrawingCustom(false);
    }
  };

  return (
    <div className="absolute top-4 left-4 right-4 z-20 flex flex-wrap items-center justify-between gap-3 bg-slate-950/90 backdrop-blur-md px-4 py-3 rounded-xl border border-slate-800 shadow-2xl text-slate-200">
      
      {/* Selector de Regiones Preset */}
      <div className="flex items-center gap-2">
        <MapPin className="w-4 h-4 text-cyan-400 shrink-0" />
        <span className="text-xs font-semibold tracking-wide text-slate-400 uppercase hidden sm:inline">Region:</span>
        <select
          value={selectedPreset}
          onChange={(e) => loadPresetRegion(e.target.value as keyof typeof PRESET_REGIONS)}
          className="bg-slate-900 border border-slate-700 text-xs text-slate-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-cyan-500 font-medium"
        >
          <option value="CHILECITO">Chilecito, La Rioja (Jul 2026)</option>
          <option value="AMAZONAS">Amazonas / Pantanal (Brazil)</option>
          <option value="CALIFORNIA">California / Western US</option>
          <option value="IBERIA">Mediterranean / Iberia</option>
          {selectedPreset === "CUSTOM" && <option value="CUSTOM">Custom Bounding Box</option>}
        </select>
      </div>

      {/* Herramienta de Dibujo Custom AOI */}
      <button
        onClick={handleToggleDrawBox}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
          isDrawingCustom 
            ? "bg-cyan-600 text-white shadow-lg shadow-cyan-900/50 ring-2 ring-cyan-400" 
            : "bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-300"
        }`}
        title="Draw custom spatial bounding box"
      >
        <Edit3 className="w-3.5 h-3.5 text-cyan-400" />
        <span>{isDrawingCustom ? "Custom Box Active" : "Draw Custom AOI"}</span>
      </button>

      {/* Interruptor Industrial Gas Flaring Inspector */}
      <div className="flex items-center gap-4 bg-slate-900/80 px-3 py-1.5 rounded-lg border border-slate-800">
        <label className="flex items-center gap-2 cursor-pointer text-xs">
          <input
            type="checkbox"
            checked={excludeIndustrial}
            onChange={(e) => setExcludeIndustrial(e.target.checked)}
            className="rounded bg-slate-800 border-slate-700 text-cyan-500 focus:ring-cyan-500 h-3.5 w-3.5"
          />
          <span className="font-medium text-slate-300">Exclude Industrial Flaring ($H_{temp} > 0.75$)</span>
        </label>

        <label className="flex items-center gap-2 cursor-pointer text-xs border-l border-slate-700 pl-3">
          <input
            type="checkbox"
            checked={highlightIndustrialOnMap}
            onChange={(e) => setHighlightIndustrialOnMap(e.target.checked)}
            className="rounded bg-slate-800 border-slate-700 text-pink-500 focus:ring-pink-500 h-3.5 w-3.5"
          />
          <span className="font-medium text-pink-400">Highlight Neon Flaring</span>
        </label>
      </div>

      {/* Badges de Estado y Latencia de Ejecución en Vivo */}
      <div className="flex items-center gap-3">
        {loading ? (
          <div className="flex items-center gap-1.5 text-xs text-amber-400 font-mono">
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            <span>Computing...</span>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-xs font-mono bg-slate-900 px-2.5 py-1 rounded border border-slate-800 text-slate-300">
            <Activity className="w-3.5 h-3.5 text-emerald-400" />
            <span>Latency: <strong className="text-emerald-400">{analysisData?.execution_time_ms ?? 4.2} ms</strong></span>
            <span className="text-slate-600">|</span>
            <span className="text-cyan-400">{analysisData?.total_h3_cells ?? 48} H3 Cells</span>
          </div>
        )}

        <button
          onClick={() => executeAnalysis()}
          className="p-1.5 bg-slate-900 hover:bg-slate-800 border border-slate-700 rounded-lg text-slate-300 transition-colors"
          title="Force Re-run Analysis"
        >
          <RefreshCw className="w-3.5 h-3.5 text-cyan-400" />
        </button>
      </div>

    </div>
  );
};
