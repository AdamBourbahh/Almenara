import { useMemo, useState } from "react";
import DeckGL from "@deck.gl/react";
import { Map } from "react-map-gl/maplibre";
import { H3HexagonLayer } from "@deck.gl/geo-layers";
import type { PickingInfo } from "@deck.gl/core";
import {
  Compass,
  Grid3x3,
  Moon,
  Satellite,
  Sun,
} from "lucide-react";
import { useAnalysisStore } from "../../store/useAnalysisStore";

const INITIAL_VIEW_STATE = {
  longitude: -67.4,
  latitude: -29.5,
  zoom: 10.5,
  pitch: 32,
  bearing: 0,
};

const HARMONIZED_STOPS = ["#1A1F2B", "#7A2D1E", "#D95F18", "#F2A93B", "#FFE29A"];
const RAW_STOPS = ["#241016", "#6E1621", "#B6212F", "#E5484D", "#FF9AA0"];

const DARK_STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
const LIGHT_STYLE = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";

const SATELLITE_STYLE = {
  version: 8,
  sources: {
    satellite: {
      type: "raster",
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
      attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
    },
  },
  layers: [{ id: "satellite", type: "raster", source: "satellite" }],
};

const OFFLINE_STYLE = {
  version: 8,
  sources: {},
  layers: [
    {
      id: "background",
      type: "background",
      paint: { "background-color": "#0A0D13" },
    },
  ],
};

type BasemapKey = "dark" | "satellite" | "light" | "offline";

const BASEMAPS: Record<
  BasemapKey,
  { label: string; icon: typeof Moon; style: string | object }
> = {
  dark: { label: "Dark basemap", icon: Moon, style: DARK_STYLE },
  satellite: { label: "Satellite", icon: Satellite, style: SATELLITE_STYLE },
  light: { label: "Light basemap", icon: Sun, style: LIGHT_STYLE },
  offline: { label: "Grid (offline)", icon: Grid3x3, style: OFFLINE_STYLE },
};

interface HexDatum {
  h3: string;
  meanAnnualFre: number;
  rawPixelCount: number;
  trendSlope: number;
  isIndustrial: boolean;
}

function hexToRgb(hex: string): [number, number, number] {
  const value = hex.replace("#", "");
  return [
    parseInt(value.slice(0, 2), 16),
    parseInt(value.slice(2, 4), 16),
    parseInt(value.slice(4, 6), 16),
  ];
}

function rampColor(
  stops: string[],
  t: number,
): [number, number, number, number] {
  const clamped = Math.max(0, Math.min(1, t));
  const scaled = clamped * (stops.length - 1);
  const index = Math.min(stops.length - 2, Math.floor(scaled));
  const fraction = scaled - index;
  const a = hexToRgb(stops[index]);
  const b = hexToRgb(stops[index + 1]);
  return [
    Math.round(a[0] + (b[0] - a[0]) * fraction),
    Math.round(a[1] + (b[1] - a[1]) * fraction),
    Math.round(a[2] + (b[2] - a[2]) * fraction),
    232,
  ];
}

interface HoverState {
  datum: HexDatum;
  x: number;
  y: number;
}

export function HexagonMap() {
  const analysisData = useAnalysisStore((state) => state.analysisData);
  const viewMode = useAnalysisStore((state) => state.viewMode);
  const highlightIndustrialOnMap = useAnalysisStore(
    (state) => state.highlightIndustrialOnMap,
  );
  const [basemap, setBasemap] = useState<BasemapKey>("dark");
  const [mapKey, setMapKey] = useState(0);
  const [hover, setHover] = useState<HoverState | null>(null);

  const hexData = useMemo<HexDatum[]>(() => {
    const hexes = analysisData?.map_hexagons ?? [];
    return hexes
      .filter((hex) => Boolean(hex.h3_index))
      .map((hex) => ({
        h3: hex.h3_index as string,
        meanAnnualFre: hex.mean_annual_fre,
        rawPixelCount: hex.raw_pixel_count,
        trendSlope: hex.trend_slope,
        isIndustrial: hex.is_industrial_site,
      }));
  }, [analysisData]);

  const { maxFre, maxRaw, avgFre } = useMemo(() => {
    let freMax = 1;
    let rawMax = 1;
    let total = 0;
    for (const hex of hexData) {
      freMax = Math.max(freMax, hex.meanAnnualFre);
      rawMax = Math.max(rawMax, hex.rawPixelCount);
      total += hex.meanAnnualFre;
    }
    return {
      maxFre: freMax,
      maxRaw: rawMax,
      avgFre: hexData.length > 0 ? total / hexData.length : 0,
    };
  }, [hexData]);

  const layers = useMemo(() => {
    const palette = viewMode === "RAW" ? RAW_STOPS : HARMONIZED_STOPS;
    return [
      new H3HexagonLayer<HexDatum>({
        id: "h3-hexagon-layer",
        data: hexData,
        pickable: true,
        wireframe: false,
        filled: true,
        extruded: true,
        getHexagon: (d) => d.h3,
        getFillColor: (d) => {
          if (highlightIndustrialOnMap && d.isIndustrial) {
            return [255, 43, 214, 240];
          }
          if (viewMode === "RAW") {
            return rampColor(palette, d.rawPixelCount / maxRaw);
          }
          return rampColor(palette, d.meanAnnualFre / maxFre);
        },
        getElevation: (d) => Math.min(d.meanAnnualFre * 0.6, 900),
        elevationScale: 1,
        updateTriggers: {
          getFillColor: [viewMode, highlightIndustrialOnMap, maxRaw, maxFre],
        },
      }),
    ];
  }, [hexData, viewMode, highlightIndustrialOnMap, maxFre, maxRaw]);

  const handleHover = (info: PickingInfo<HexDatum>) => {
    if (info.object) {
      setHover({ datum: info.object, x: info.x, y: info.y });
    } else {
      setHover(null);
    }
  };

  return (
    <div className="relative h-full w-full overflow-hidden bg-base">
      <DeckGL
        key={mapKey}
        initialViewState={INITIAL_VIEW_STATE}
        controller
        layers={layers}
        onHover={handleHover}
        getCursor={({ isHovering }) => (isHovering ? "pointer" : "grab")}
      >
        {basemap !== "offline" && (
          <Map
            reuseMaps
            initialViewState={INITIAL_VIEW_STATE}
            mapStyle={BASEMAPS[basemap].style as never}
          />
        )}
      </DeckGL>
      {/* Basemap + view controls */}
      <div className="absolute right-4 top-4 z-20 flex flex-col gap-2">
        <div className="glass flex flex-col gap-1 rounded-xl p-1">
          {(Object.keys(BASEMAPS) as BasemapKey[]).map((key) => {
            const Icon = BASEMAPS[key].icon;
            const active = basemap === key;
            return (
              <button
                key={key}
                type="button"
                title={BASEMAPS[key].label}
                aria-label={BASEMAPS[key].label}
                aria-pressed={active}
                onClick={() => setBasemap(key)}
                className={`flex h-9 w-9 items-center justify-center rounded-lg transition-colors duration-150 ${
                  active
                    ? "bg-ember/20 text-ember"
                    : "text-dim hover:bg-white/5 hover:text-ink"
                }`}
              >
                <Icon className="h-4 w-4" />
              </button>
            );
          })}
        </div>
        <button
          type="button"
          title="Reset view"
          aria-label="Reset map view"
          onClick={() => setMapKey((value) => value + 1)}
          className="glass flex h-9 w-9 items-center justify-center rounded-xl text-dim transition-colors hover:text-ink"
        >
          <Compass className="h-4 w-4" />
        </button>
      </div>

      {/* Hover card */}
      {hover && (
        <div
          className="pointer-events-none absolute z-30 w-56 rounded-xl border border-line bg-surface/95 p-3 text-xs shadow-float backdrop-blur"
          style={{
            left: Math.min(hover.x + 16, 520),
            top: Math.min(hover.y + 16, 320),
          }}
        >
          <p className="text-[10px] font-medium uppercase tracking-wide text-dim">
            Fire intensity
          </p>
          <p className="font-tabular text-lg font-semibold text-ember">
            {hover.datum.meanAnnualFre.toLocaleString("en-US", {
              maximumFractionDigits: 0,
            })}
            <span className="ml-1 text-[10px] font-normal text-dim">
              MJ/km²
            </span>
          </p>
          <div className="mt-2 space-y-1 border-t border-line pt-2 text-[11px]">
            <p className="flex justify-between text-dim">
              <span>Raw hotspots</span>
              <span className="font-tabular text-ink">
                {hover.datum.rawPixelCount.toLocaleString("en-US")}
              </span>
            </p>
            <p className="flex justify-between text-dim">
              <span>Trend</span>
              <span
                className={
                  hover.datum.trendSlope >= 0
                    ? "font-tabular text-danger"
                    : "font-tabular text-success"
                }
              >
                {hover.datum.trendSlope >= 0 ? "+" : ""}
                {hover.datum.trendSlope.toFixed(2)}/yr
              </span>
            </p>
            {avgFre > 0 && (
              <p className="flex justify-between text-dim">
                <span>vs area average</span>
                <span className="font-tabular text-ink">
                  {hover.datum.meanAnnualFre >= avgFre ? "+" : ""}
                  {(((hover.datum.meanAnnualFre - avgFre) / avgFre) * 100).toFixed(0)}%
                </span>
              </p>
            )}
          </div>
          {hover.datum.isIndustrial && (
            <p className="mt-2 rounded-md bg-[#FF2BD6]/15 px-2 py-1 text-[10px] font-medium text-[#FF7BE4]">
              Industrial heat source (gas flare / refinery)
            </p>
          )}
        </div>
      )}

      {hexData.length === 0 && (
        <div className="absolute inset-0 z-10 flex items-center justify-center">
          <p className="glass rounded-xl px-4 py-2 text-xs text-dim">
            No mapped hexagons for this area yet.
          </p>
        </div>
      )}
    </div>
  );
}
