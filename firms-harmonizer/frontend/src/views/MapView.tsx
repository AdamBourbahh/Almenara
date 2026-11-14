import { HexagonMap } from "../components/Map/HexagonMap";
import { AoiDrawControl } from "../components/Map/AoiDrawControl";
import { RampLegend } from "../components/ui/RampLegend";
import { useAnalysisStore } from "../store/useAnalysisStore";

const HARMONIZED_STOPS = ["#1A1F2B", "#7A2D1E", "#D95F18", "#F2A93B", "#FFE29A"];
const RAW_STOPS = ["#241016", "#6E1621", "#B6212F", "#E5484D", "#FF9AA0"];

export function MapView() {
  const viewMode = useAnalysisStore((state) => state.viewMode);
  const isRaw = viewMode === "RAW";

  return (
    <div className="relative h-full w-full">
      <HexagonMap />
      <AoiDrawControl />

      <div className="pointer-events-none absolute bottom-4 left-4 z-20">
        <RampLegend
          label={isRaw ? "Raw pixel count" : "Fire intensity (FRE)"}
          stops={isRaw ? RAW_STOPS : HARMONIZED_STOPS}
          low="Low"
          high="High"
        />
      </div>

      <div className="pointer-events-none absolute bottom-4 right-4 z-20 max-w-[220px]">
        <div className="glass rounded-xl px-3 py-2 text-[10px] leading-relaxed text-dim">
          {isRaw
            ? "Raw counts include the artificial 2012 sensor jump."
            : "Comparable, gap-filled fire energy. Sensor of origin no longer matters."}
        </div>
      </div>
    </div>
  );
}
