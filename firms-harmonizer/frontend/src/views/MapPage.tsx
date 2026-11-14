import { useState } from "react";
import { PanelRightClose, PanelRightOpen } from "lucide-react";
import { HexagonMap } from "../components/Map/HexagonMap";
import { AoiDrawControl } from "../components/Map/AoiDrawControl";
import { MapInfo } from "../components/Map/MapInfo";

export function MapPage() {
  const [open, setOpen] = useState(() => window.innerWidth >= 900);
  return (
    <div className="flex h-full w-full overflow-hidden">
      <div className="relative min-w-0 flex-1" aria-label="Map workspace">
        <HexagonMap />
        <div data-map-ui className="pointer-events-none absolute left-3 top-3 z-40 w-[min(440px,calc(100%-84px))]">
          <AoiDrawControl placement="search" />
        </div>
        {!open && <button data-map-ui type="button" onClick={() => setOpen(true)} className="absolute right-3 top-3 z-30 flex items-center gap-2 rounded-full border border-rule bg-panel px-3 py-3 text-xs font-medium text-ink shadow-lg" aria-label="Open explore panel"><PanelRightOpen className="h-4 w-4" /><span className="hidden sm:inline">Explore</span></button>}
      </div>
      {open && (
        <aside aria-label="Explore the map" className="z-30 flex h-full w-[min(300px,65vw)] shrink-0 flex-col border-l border-rule bg-panel">
          <div className="flex items-center justify-between border-b border-rule px-4 py-3">
            <h2 className="text-sm font-medium text-ink">Explore the map</h2>
            <button type="button" onClick={() => setOpen(false)} aria-label="Hide explore panel" className="rounded-full p-2 text-muted hover:bg-paper"><PanelRightClose className="h-4 w-4" /></button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto"><AoiDrawControl /><MapInfo /></div>
        </aside>
      )}
    </div>
  );
}
