import { useEffect, useMemo, useRef, useState } from "react";
import { locationBounds, searchLocations } from "./locationSearch";
import type { ApprovedRegion, LocationResult } from "./locationSearch";
import type { FormEvent } from "react";
import { useShallow } from "zustand/react/shallow";
import { Edit3, XCircle, Search, MapPin, ChevronDown } from "lucide-react";
import { PRESET_ORDER, PRESET_REGIONS, useAnalysisStore } from "../../store/useAnalysisStore";

const APPROVED_REGIONS: ApprovedRegion[] = PRESET_ORDER.map(key => {
  const ring = PRESET_REGIONS[key].coordinates[0];
  return {label:PRESET_REGIONS[key].label,bounds:[Math.min(...ring.map(p=>p[0])),Math.min(...ring.map(p=>p[1])),Math.max(...ring.map(p=>p[0])),Math.max(...ring.map(p=>p[1]))]};
});

/**
 * Area-of-interest controls for the map panel: case-study tabs, drag-to-draw,
 * latitude/longitude entry and the industrial-heat filter.
 */
export function AoiDrawControl({ placement = "explore" }: { placement?: "search" | "explore" }) {
  const {
    currentAoi,
    loadPresetRegion,
    isDrawingAoi,
    setDrawingAoi,
    setCustomBbox,
  } = useAnalysisStore(
    useShallow((s) => ({
      currentAoi: s.currentAoi,
      loadPresetRegion: s.loadPresetRegion,
      isDrawingAoi: s.isDrawingAoi,
      setDrawingAoi: s.setDrawingAoi,
      setCustomBbox: s.setCustomBbox,
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

  const searchContainer = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const closeOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !searchContainer.current?.contains(event.target)) setSearchOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, []);
  const [showCoords, setShowCoords] = useState(false);
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [locations, setLocations] = useState<LocationResult[]>([]);
  const [searching, setSearching] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setLocations([]);
    setSearching(false);
    if (placement !== "search" || !searchOpen || query.trim().length < 3 || /^[\d.,\s-]+$/.test(query)) return;
    const timer = setTimeout(() => {
      setSearching(true);
      void searchLocations(query.trim(), APPROVED_REGIONS, controller.signal).then(results => {
        if (!controller.signal.aborted) setLocations(results);
      }).catch(() => {
        if (!controller.signal.aborted) setSearchError("Location search unavailable. Choose a region or enter coordinates.");
      }).finally(() => { if (!controller.signal.aborted) setSearching(false); });
    },600);
    return () => { clearTimeout(timer); controller.abort(); };
  },[query,searchOpen,placement]);
  const chooseLocation = (location: LocationResult) => {
    const bounds = locationBounds(location.longitude,location.latitude,.08,APPROVED_REGIONS);
    if (bounds) void setCustomBbox(...bounds);
    setSearchOpen(false); setQuery(""); setSearchError("");
  };
  const matches = PRESET_ORDER.filter((key) => `${PRESET_REGIONS[key].label} ${PRESET_REGIONS[key].context}`.toLowerCase().includes(query.toLowerCase()));
  const applySearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const pair = query.trim().split(/[,\s]+/).map(Number);
    if (query.trim() && pair.length === 2 && pair.every(Number.isFinite) && Math.abs(pair[0]) + .2 <= 85 && Math.abs(pair[1]) + .2 <= 180) {
      const bounds = locationBounds(pair[1],pair[0],.2,APPROVED_REGIONS);
      if (!bounds) { setSearchError("Coordinates must be within Iberia, Chilecito, Orlando or Amazonas / Manaus."); setSearchOpen(true); return; }
      void setCustomBbox(...bounds);
      setSearchOpen(false); setQuery(""); setSearchError("");
    } else if (locations.length === 1) {
      chooseLocation(locations[0]);
    } else if (matches.length === 1) {
      void loadPresetRegion(matches[0]); setSearchOpen(false); setQuery(""); setSearchError("");
    } else {
      setSearchError("Choose a location within the four approved regions, or enter latitude, longitude."); setSearchOpen(true);
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
    const bounds = locationBounds(longitude,latitude,half,APPROVED_REGIONS);
    if (!bounds) { setSearchError("Coordinates must be within the four approved regions."); return; }
    void setCustomBbox(...bounds);
    setShowCoords(false);
  };

  if (placement === "search") return (
    <div ref={searchContainer} className="pointer-events-auto">
      <div className="flex items-center overflow-hidden rounded-full border border-rule bg-panel text-ink shadow-xl">
        <form role="search" onSubmit={applySearch} className="flex min-w-0 flex-1 items-center">
          <button aria-label="Search selected area" type="submit" className="p-3"><Search className="h-4 w-4 text-muted" /></button>
          <input type="search" aria-label="Search locations within the four approved regions" placeholder="Search places in 4 approved regions" maxLength={120}
            value={query} onChange={(e) => { setQuery(e.target.value); setSearchOpen(true); setSearchError(""); }} onFocus={() => setSearchOpen(true)}
            onKeyDown={(e) => { if (e.key === "Escape") setSearchOpen(false); }} className="min-w-0 flex-1 rounded-sm bg-transparent py-3 text-xs focus-visible:outline-2 focus-visible:outline-reference focus-visible:-outline-offset-2" />
        </form>
        <button type="button" onClick={() => { setShowCoords((value) => !value); setSearchOpen(false); }} aria-expanded={showCoords} aria-label="Area of interest controls"
          className="flex shrink-0 items-center gap-1 border-l border-rule px-3 py-3 text-xs text-muted hover:bg-paper"><MapPin className="h-4 w-4" /><span className="hidden sm:inline">Area of interest</span><ChevronDown className="h-3 w-3" /></button>
      </div>
      {searchOpen && <>
        <div className="mt-2 overflow-hidden rounded-2xl border border-rule bg-panel p-2 shadow-xl">
          <p className="px-3 py-2 text-[10px] uppercase tracking-widest text-faint">Iberia · Chilecito · Orlando · Amazonas / Manaus</p>
          {matches.map((key) => <button key={key} type="button" onClick={() => { void loadPresetRegion(key); setSearchOpen(false); setQuery(""); }} className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-xs text-ink hover:bg-paper"><MapPin className="h-4 w-4 text-muted" /><span>{PRESET_REGIONS[key].label}<span className="block text-[10px] text-faint">{PRESET_REGIONS[key].context}</span></span></button>)}
          {locations.map((location) => <button key={`${location.longitude},${location.latitude},${location.label}`} type="button" onClick={() => chooseLocation(location)} className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-xs text-ink hover:bg-paper"><MapPin className="h-4 w-4 shrink-0 text-muted" /><span>{location.label}<span className="block text-[10px] text-faint">{location.region.label}</span></span></button>)}
          {searching && <p role="status" className="px-3 py-2 text-xs text-muted">Searching within the four approved regions…</p>}
          <p className="px-3 py-1 text-[10px] text-faint">Place names © OpenStreetMap contributors · Photon</p>
          {searchError && <p role="status" className="px-3 py-2 text-xs text-terracotta">{searchError}</p>}
          {!matches.length && !locations.length && !searching && !searchError && <p className="px-3 py-2 text-xs text-muted">No matching locations. Search within the four approved regions or enter coordinates.</p>}
        </div>
      </>}
      {showCoords && <div className="mt-2 rounded-2xl border border-rule bg-panel p-3 shadow-xl">
        <div className="mb-2 flex items-center justify-between"><span className="text-xs font-medium text-ink">Area of interest</span><button type="button" onClick={() => setShowCoords(false)} aria-label="Close area controls" className="p-1 text-muted"><XCircle className="h-4 w-4" /></button></div>
        <button type="button" aria-pressed={isDrawingAoi} onClick={() => { setDrawingAoi(!isDrawingAoi); setShowCoords(false); }} className="flex w-full items-center justify-center gap-2 rounded-lg border border-rule px-3 py-2 text-xs text-ink hover:bg-paper"><Edit3 className="h-4 w-4" />{isDrawingAoi ? "Cancel drawing" : "Draw an area on the map"}</button>
        {searchError && <p role="status" className="mt-2 text-xs text-terracotta">{searchError}</p>}
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

  return null;
}
