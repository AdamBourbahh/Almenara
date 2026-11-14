import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { useShallow } from "zustand/react/shallow";
import { Edit3, RefreshCw, XCircle } from "lucide-react";
import { PRESET_ORDER, PRESET_REGIONS, useAnalysisStore } from "../../store/useAnalysisStore";

/**
 * Area-of-interest controls for the map panel: case-study tabs, drag-to-draw,
 * latitude/longitude entry and the industrial-heat filter.
 */
export function AoiDrawControl() {
  const {
    selectedPreset,
    currentAoi,
    loadPresetRegion,
    isDrawingAoi,
    setDrawingAoi,
    setCustomBbox,
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
      currentAoi: s.currentAoi,
      loadPresetRegion: s.loadPresetRegion,
      isDrawingAoi: s.isDrawingAoi,
      setDrawingAoi: s.setDrawingAoi,
      setCustomBbox: s.setCustomBbox,
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

  const center = useMemo(() => {
    const ring = currentAoi.coordinates[0] ?? [];
    if (ring.length === 0) return { lat: 0, lng: 0 };
    const lats = ring.map((p) => p[1]);
    const lngs = ring.map((p) => p[0]);
    return {
      lat: (Math.min(...lats) + Math.max(...lats)) / 2,
      lng: (Math.min(...lngs) + Math.max(...lngs)) / 2
    };
  }, [currentAoi]);

  const [showCoords, setShowCoords] = useState(false);
  const [lat, setLat] = useState(center.lat.toFixed(2));
  const [lng, setLng] = useState(center.lng.toFixed(2));
  const [radius, setRadius] = useState("0.4");

  useEffect(() => {
    setLat(center.lat.toFixed(2));
    setLng(center.lng.toFixed(2));
  }, [center.lat, center.lng]);

  const applyCoords = (event: FormEvent) => {
    event.preventDefault();
    const latitude = Number(lat);
    const longitude = Number(lng);
    const half = Math.min(Math.abs(Number(radius)) || 0.4, 5);
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return;
    void setCustomBbox(longitude - half, latitude - half, longitude + half, latitude + half);
  };

  return (
    <div className="border-b border-rule p-4">
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-faint">Area of interest</p>
        <span className="font-mono text-[10px] text-faint tnum">
          {analysisData ? analysisData.total_h3_cells.toLocaleString("en-US") : "—"} cells
        </span>
      </div>

      <div role="tablist" aria-label="Case studies" className="mt-3 grid grid-cols-2 gap-1.5">
        {PRESET_ORDER.map((key) => {
          const active = selectedPreset === key;
          return (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => void loadPresetRegion(key)}
              className={`border px-2 py-2 text-left ${active ? "border-ink bg-paper" : "border-rule hover:bg-paper"}`}
            >
              <span className={`block text-xs font-medium ${active ? "text-ink" : "text-muted"}`}>
                {PRESET_REGIONS[key].label}
              </span>
              <span className="mt-0.5 block text-[10px] leading-snug text-faint">
                {PRESET_REGIONS[key].context}
              </span>
            </button>
          );
        })}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setDrawingAoi(!isDrawingAoi)}
          aria-pressed={isDrawingAoi}
          className={`flex items-center gap-1.5 border px-2.5 py-1.5 text-xs ${
            isDrawingAoi ? "border-reference bg-reference/10 text-reference" : "border-rule text-muted hover:bg-paper"
          }`}
        >
          {isDrawingAoi ? <XCircle className="h-3.5 w-3.5" /> : <Edit3 className="h-3.5 w-3.5" />}
          {isDrawingAoi ? "Drawing (Esc)" : "Draw area"}
        </button>
        <button
          type="button"
          onClick={() => setShowCoords((value) => !value)}
          aria-expanded={showCoords}
          className="border border-rule px-2.5 py-1.5 text-xs text-muted hover:bg-paper"
        >
          {showCoords ? "Hide coordinates" : "Enter coordinates"}
        </button>
      </div>

      {showCoords && (
        <form onSubmit={applyCoords} className="mt-2 border border-rule p-2">
          <div className="grid grid-cols-3 gap-2">
            <label className="flex flex-col gap-0.5">
              <span className="text-[10px] text-faint">Latitude</span>
              <input
                type="number"
                step="0.1"
                value={lat}
                onChange={(e) => setLat(e.target.value)}
                className="h-8 border border-rule bg-paper px-2 font-mono text-xs text-ink"
              />
            </label>
            <label className="flex flex-col gap-0.5">
              <span className="text-[10px] text-faint">Longitude</span>
              <input
                type="number"
                step="0.1"
                value={lng}
                onChange={(e) => setLng(e.target.value)}
                className="h-8 border border-rule bg-paper px-2 font-mono text-xs text-ink"
              />
            </label>
            <label className="flex flex-col gap-0.5">
              <span className="text-[10px] text-faint">± degrees</span>
              <input
                type="number"
                step="0.1"
                min="0.1"
                max="5"
                value={radius}
                onChange={(e) => setRadius(e.target.value)}
                className="h-8 border border-rule bg-paper px-2 font-mono text-xs text-ink"
              />
            </label>
          </div>
          <button
            type="submit"
            className="mt-2 h-8 w-full bg-ink text-xs font-medium text-paper hover:opacity-90"
          >
            Analyse this area
          </button>
        </form>
      )}

      <div className="mt-3 space-y-1.5 border-t border-rule pt-3">
        <label className="flex cursor-pointer items-start gap-2 text-[11px] text-muted">
          <input
            type="checkbox"
            checked={excludeIndustrial}
            onChange={(e) => void setExcludeIndustrial(e.target.checked)}
            className="mt-0.5 h-3.5 w-3.5 accent-industrial"
          />
          <span>
            Hide industrial heat (refineries and flares)
            <span className="block text-[10px] text-faint">Shannon temporal entropy H &gt; 0.75</span>
          </span>
        </label>
        <label className="flex cursor-pointer items-center gap-2 text-[11px] text-muted">
          <input
            type="checkbox"
            checked={highlightIndustrialOnMap}
            onChange={(e) => setHighlightIndustrialOnMap(e.target.checked)}
            className="h-3.5 w-3.5 accent-industrial"
          />
          Highlight flares on the map
        </label>
      </div>

      <div className="mt-3 flex items-center justify-between border-t border-rule pt-2 text-[10px] text-faint">
        {isSynthetic && !loading ? (
          <span className="text-terracotta">synthetic data</span>
        ) : error ? (
          <span className="max-w-[14rem] truncate text-bias" title={error}>
            {error}
          </span>
        ) : (
          <span className="tnum">
            {analysisData && analysisData.execution_time_ms !== undefined
              ? `${analysisData.execution_time_ms.toFixed(0)} ms`
              : "—"}
          </span>
        )}
        <button
          type="button"
          onClick={() => void executeAnalysis()}
          disabled={loading}
          aria-label="Refresh analysis"
          className="border border-rule p-1 text-muted hover:bg-paper disabled:opacity-40"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>
    </div>
  );
}
