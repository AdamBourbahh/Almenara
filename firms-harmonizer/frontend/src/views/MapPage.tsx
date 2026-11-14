import { useState } from "react";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { HexagonMap } from "../components/Map/HexagonMap";
import { AoiDrawControl } from "../components/Map/AoiDrawControl";
import { MapInfo } from "../components/Map/MapInfo";

/**
 * Map-first landing: the map fills the screen; a collapsible panel on the left
 * carries the region chooser, the area controls and the area's history.
 */
export function MapPage() {
  const [open, setOpen] = useState(true);

  return (
    <div className="relative h-full w-full overflow-hidden">
      <HexagonMap />

      {open ? (
        <aside className="absolute inset-y-0 left-0 z-30 flex w-[350px] max-w-[85vw] flex-col border-r border-rule bg-panel">
          <div className="flex items-center justify-between border-b border-rule px-4 py-3">
            <span className="text-sm font-medium text-ink">Explore the map</span>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Hide panel"
              className="border border-rule p-1.5 text-muted hover:bg-paper"
            >
              <PanelLeftClose className="h-4 w-4" />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <AoiDrawControl />
            <MapInfo />
          </div>
        </aside>
      ) : (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="absolute left-3 top-3 z-30 flex items-center gap-1.5 border border-rule bg-panel px-3 py-2 text-xs font-medium text-ink hover:bg-paper"
        >
          <PanelLeftOpen className="h-4 w-4" />
          Explore
        </button>
      )}
    </div>
  );
}
