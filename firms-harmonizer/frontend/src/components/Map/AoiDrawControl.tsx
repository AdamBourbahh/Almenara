import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { useShallow } from "zustand/react/shallow";
import { Edit3, XCircle, Search, MapPin, ChevronDown } from "lucide-react";
import { PRESET_ORDER, PRESET_REGIONS, useAnalysisStore } from "../../store/useAnalysisStore";

/**
 * Area-of-interest controls for the map panel: case-study tabs, drag-to-draw,
 * latitude/longitude entry and the industrial-heat filter.
 */
export function AoiDrawControl({ placement = "explore" }: { placement?: "search" | "explore" }) {
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
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchError, setSearchError] = useState("");
  const matches = PRESET_ORDER.filter((key) => `${PRESET_REGIONS[key].label} ${PRESET_REGIONS[key].context}`.toLowerCase().includes(query.toLowerCase()));
  const applySearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const pair = query.trim().split(/[,\s]+/).map(Number);
    if (query.trim() && pair.length === 2 && pair.every(Number.isFinite) && Math.abs(pair[0]) + .2 <= 85 && Math.abs(pair[1]) + .2 <= 180) {
      void setCustomBbox(pair[1] - .2, pair[0] - .2, pair[1] + .2, pair[0] + .2);
      setSearchOpen(false); setQuery(""); setSearchError("");
    } else if (matches.length === 1) {
      void loadPresetRegion(matches[0]); setSearchOpen(false); setQuery(""); setSearchError("");
    } else {
      setSearchError("Choose a pilot region, or enter latitude, longitude."); setSearchOpen(true);
    }
  };
  const [lat, setLat] = useState(center.lat.toFixed(2));
  const [lng, setLng] = useState(center.lng.toFixed(2));
  const [radius, setRadius] = useState("0.4");

  useEffect(() => {
    setLat(center.lat.toFixed(2));
    setLng(center.lng.toFixed(2));
  }, [center.lat, center.lng]);

  const applyCoords = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const latitude = Number(lat);
    const longitude = Number(lng);
    const half = Math.min(Math.abs(Number(radius)) || 0.4, 5);
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude) || Math.abs(latitude) + half > 85 || Math.abs(longitude) + half > 180) return;
    void setCustomBbox(longitude - half, latitude - half, longitude + half, latitude + half);
    setShowCoords(false);
  };

  if (placement === "search") return (
    <div className="pointer-events-auto">
      <div className="flex items-center overflow-hidden rounded-full border border-rule bg-panel text-ink shadow-xl">
        <form role="search" onSubmit={applySearch} className="flex min-w-0 flex-1 items-center">
          <button aria-label="Search selected area" type="submit" className="p-3"><Search className="h-4 w-4 text-muted" /></button>
          <input type="search" aria-label="Search pilot regions or latitude, longitude" placeholder={selectedPreset === "CUSTOM" ? "Search regions or lat, lon" : PRESET_REGIONS[selectedPreset].label}
            value={query} onChange={(e) => { setQuery(e.target.value); setSearchOpen(true); setSearchError(""); }} onFocus={() => setSearchOpen(true)}
            onKeyDown={(e) => { if (e.key === "Escape") setSearchOpen(false); }} className="min-w-0 flex-1 rounded-sm bg-transparent py-3 text-xs focus-visible:outline-2 focus-visible:outline-reference focus-visible:-outline-offset-2" />
        </form>
        <button type="button" onClick={() => { setShowCoords((value) => !value); setSearchOpen(false); }} aria-expanded={showCoords} aria-label="Area of interest controls"
          className="flex shrink-0 items-center gap-1 border-l border-rule px-3 py-3 text-xs text-muted hover:bg-paper"><MapPin className="h-4 w-4" /><span className="hidden sm:inline">Area of interest</span><ChevronDown className="h-3 w-3" /></button>
      </div>
      {searchOpen && <>
        <button aria-label="Close search suggestions" onClick={() => setSearchOpen(false)} className="fixed inset-0 -z-10 cursor-default" />
        <div className="mt-2 overflow-hidden rounded-2xl border border-rule bg-panel p-2 shadow-xl">
          <p className="px-3 py-2 text-[10px] uppercase tracking-widest text-faint">Pilot regions · or search by coordinates</p>
          {matches.map((key) => <button key={key} type="button" onClick={() => { void loadPresetRegion(key); setSearchOpen(false); setQuery(""); }} className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-xs text-ink hover:bg-paper"><MapPin className="h-4 w-4 text-muted" /><span>{PRESET_REGIONS[key].label}<span className="block text-[10px] text-faint">{PRESET_REGIONS[key].context}</span></span></button>)}
          {searchError && <p role="status" className="px-3 py-2 text-xs text-terracotta">{searchError}</p>}
          {!matches.length && !searchError && <p className="px-3 py-2 text-xs text-muted">Enter latitude, longitude and press Enter.</p>}
        </div>
      </>}
      {showCoords && <div className="mt-2 rounded-2xl border border-rule bg-panel p-3 shadow-xl">
        <div className="mb-2 flex items-center justify-between"><span className="text-xs font-medium text-ink">Area of interest</span><button type="button" onClick={() => setShowCoords(false)} aria-label="Close area controls" className="p-1 text-muted"><XCircle className="h-4 w-4" /></button></div>
        <button type="button" aria-pressed={isDrawingAoi} onClick={() => { setDrawingAoi(!isDrawingAoi); setShowCoords(false); }} className="flex w-full items-center justify-center gap-2 rounded-lg border border-rule px-3 py-2 text-xs text-ink hover:bg-paper"><Edit3 className="h-4 w-4" />{isDrawingAoi ? "Cancel drawing" : "Draw an area on the map"}</button>
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
      </div>}
    </div>
  );

  return (
    <div className="border-b border-rule p-4">
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-faint">Pilot regions</p>
        <span className="font-mono text-[10px] text-faint tnum">
          {analysisData ? analysisData.total_h3_cells.toLocaleString("en-US") : "—"} record cells
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

    </div>
  );
}
