import React, { useMemo } from "react";
import DeckGL from "@deck.gl/react";
import { Map } from "react-map-gl/maplibre";
import { H3HexagonLayer } from "@deck.gl/geo-layers";
import { useAnalysisStore } from "../../store/useAnalysisStore";

const MAP_STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

export const HexagonMap: React.FC = () => {
  const {
    analysisData,
    viewMode,
    highlightIndustrialOnMap,
    splitCurtainPct
  } = useAnalysisStore();

  const initialViewState = {
    longitude: -67.4,
    latitude: -29.5,
    zoom: 9,
    pitch: 30,
    bearing: 0
  };

  const hexagonData = useMemo(() => {
    if (!analysisData || !analysisData.map_hexagons) return [];

    return analysisData.map_hexagons.map((hex) => ({
      h3: hex.h3_index, // Se pasa el string hexadecimal directo a Deck.gl
      meanAnnualFre: hex.mean_annual_fre,
      trendSlope: hex.trend_slope,
      isIndustrial: hex.is_industrial_site
    }));
  }, [analysisData]);

  const layers = useMemo(() => {
    return [
      new H3HexagonLayer({
        id: "h3-hexagon-layer",
        data: hexagonData,
        pickable: true,
        wireframe: false,
        filled: true,
        extruded: true,
        getHexagon: (d: any) => d.h3,
        getFillColor: (d: any) => {
          if (highlightIndustrialOnMap && d.isIndustrial) {
            return [255, 0, 200, 235]; 
          }
          const intensity = Math.min(255, Math.max(20, (d.meanAnnualFre / 1500) * 255));
          return viewMode === "RAW" 
            ? [220, 50, 30, intensity] 
            : [30, 144, 255, intensity];
        },
        getElevation: (d: any) => d.meanAnnualFre * 1.5,
        elevationScale: 10,
        updateTriggers: {
          getFillColor: [viewMode, highlightIndustrialOnMap, hexagonData],
          getElevation: [hexagonData]
        }
      })
    ];
  }, [hexagonData, viewMode, highlightIndustrialOnMap]);

  return (
    <div className="relative w-full h-full min-h-[400px] bg-[#070B14] rounded-lg overflow-hidden border border-slate-800">
      <DeckGL
        initialViewState={initialViewState}
        controller={true}
        layers={layers}
        getCursor={({ isHovering }) => (isHovering ? "pointer" : "default")}
      >
      </DeckGL>

      <div className="absolute top-3 left-3 z-10 bg-slate-900/80 backdrop-blur-md px-3 py-1.5 rounded border border-slate-700 text-xs text-slate-200 font-mono shadow-lg">
        <span className="text-cyan-400 font-bold">MODE:</span> {viewMode} |{" "}
        <span className="text-amber-400 font-bold">SPLIT:</span> {splitCurtainPct}%
      </div>
    </div>
  );
};
