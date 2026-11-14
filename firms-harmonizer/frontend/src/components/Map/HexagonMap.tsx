import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import DeckGL from "@deck.gl/react";
import { FlyToInterpolator, type MapViewState, type PickingInfo } from "@deck.gl/core";
import { PathLayer, PolygonLayer } from "@deck.gl/layers";
import { H3HexagonLayer } from "@deck.gl/geo-layers";
import MapLibreMap from "react-map-gl/maplibre";
import { setWorkerUrl } from "maplibre-gl";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";
import { useShallow } from "zustand/react/shallow";
import { Box, Square } from "lucide-react";
import type { GeoJSONPolygon, H3MapSummaryHex } from "../../api/types";
import { useAnalysisStore } from "../../store/useAnalysisStore";

// MapLibre v6 resolves its worker relative to its own module URL, which breaks once bundled.
// Let Vite bundle the worker (with its shared chunk) and register the emitted URL explicitly.
setWorkerUrl(maplibreWorkerUrl);

const MAP_STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
const INDUSTRIAL_NEON: [number, number, number, number] = [255, 0, 200, 235];
const MAX_ELEVATION_M = 4000;
const PITCH_3D = 45;

type ViewState = MapViewState & { transitionDuration?: number; transitionInterpolator?: FlyToInterpolator };
type LngLat = [number, number];

interface AoiFeature {
  polygon: number[][][];
}

// Offline fallback: dark 1° graticule drawn by deck.gl itself (no network needed).
const GRATICULE: { path: LngLat[] }[] = [
  ...Array.from({ length: 361 }, (_, i) => ({ path: [[i - 180, -85], [i - 180, 85]] as LngLat[] })),
  ...Array.from({ length: 171 }, (_, i) => ({ path: [[-180, i - 85], [180, i - 85]] as LngLat[] }))
];

function lerpColor(a: readonly number[], b: readonly number[], t: number, alpha: number): [number, number, number, number] {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t, alpha];
}

/** Fit the AOI bounding box into the container (Web Mercator, 512-px world tiles as in MapLibre). */
function viewStateForAoi(aoi: GeoJSONPolygon, width: number, height: number, pitch: number): ViewState {
  const ring = aoi.coordinates[0] ?? [];
  const lngs = ring.map((p) => p[0]);
  const lats = ring.map((p) => p[1]);
  const west = Math.min(...lngs);
  const east = Math.max(...lngs);
  const south = Math.min(...lats);
  const north = Math.max(...lats);
  const mercY = (lat: number) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));
  const spanX = Math.max((east - west) / 360, 1e-6);
  const spanY = Math.max((mercY(north) - mercY(south)) / (2 * Math.PI), 1e-6);
  const usableW = Math.max(200, width) * 0.8;
  const usableH = Math.max(200, height) * 0.7;
  const zoom = Math.min(Math.log2(usableW / (512 * spanX)), Math.log2(usableH / (512 * spanY)));
  return {
    longitude: (west + east) / 2,
    latitude: (south + north) / 2,
    zoom: Math.max(2, Math.min(13, zoom)),
    pitch,
    bearing: 0
  };
}

export const HexagonMap: React.FC = () => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const styleLoadedRef = useRef(false);

  const {
    analysisData,
    viewMode,
    highlightIndustrialOnMap,
    excludeIndustrial,
    splitCurtainPct,
    currentAoi,
    isDrawingAoi,
    setDrawingAoi,
    setCustomBbox,
    isSynthetic
  } = useAnalysisStore(
    useShallow((s) => ({
      analysisData: s.analysisData,
      viewMode: s.viewMode,
      highlightIndustrialOnMap: s.highlightIndustrialOnMap,
      excludeIndustrial: s.excludeIndustrial,
      splitCurtainPct: s.splitCurtainPct,
      currentAoi: s.currentAoi,
      isDrawingAoi: s.isDrawingAoi,
      setDrawingAoi: s.setDrawingAoi,
      setCustomBbox: s.setCustomBbox,
      isSynthetic: s.isSynthetic
    }))
  );

  const [is3D, setIs3D] = useState(true);
  const [basemapAvailable, setBasemapAvailable] = useState(() => typeof navigator === "undefined" || navigator.onLine);
  const [viewState, setViewState] = useState<ViewState>(() => viewStateForAoi(currentAoi, 800, 500, PITCH_3D));
  const [dragBox, setDragBox] = useState<{ start: LngLat; end: LngLat } | null>(null);
  const dragBoxRef = useRef<{ start: LngLat; end: LngLat } | null>(null);
  const updateDragBox = useCallback((box: { start: LngLat; end: LngLat } | null) => {
    dragBoxRef.current = box;
    setDragBox(box);
  }, []);

  // Fly to every new AOI (presets and custom boxes).
  useEffect(() => {
    const el = containerRef.current;
    setViewState((prev) => ({
      ...viewStateForAoi(currentAoi, el?.clientWidth ?? 800, el?.clientHeight ?? 500, prev.pitch ?? 0),
      transitionDuration: 900,
      transitionInterpolator: new FlyToInterpolator()
    }));
  }, [currentAoi]);

  // Basemap fallback when the browser goes offline; retry when it comes back.
  useEffect(() => {
    const goOffline = () => setBasemapAvailable(false);
    const goOnline = () => {
      styleLoadedRef.current = false;
      setBasemapAvailable(true);
    };
    window.addEventListener("offline", goOffline);
    window.addEventListener("online", goOnline);
    return () => {
      window.removeEventListener("offline", goOffline);
      window.removeEventListener("online", goOnline);
    };
  }, []);

  // Esc cancels the AOI drawing tool.
  useEffect(() => {
    if (!isDrawingAoi) {
      dragBoxRef.current = null;
      setDragBox(null);
      return;
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrawingAoi(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isDrawingAoi, setDrawingAoi]);

  const hexagons = analysisData?.map_hexagons ?? [];
  const maxFre = useMemo(() => hexagons.reduce((m, h) => (h.is_industrial_site ? m : Math.max(m, h.mean_annual_fre)), 1), [hexagons]);

  const toggle3D = () => {
    const next = !is3D;
    setIs3D(next);
    setViewState((prev) => ({ ...prev, pitch: next ? PITCH_3D : 0, transitionDuration: 400, transitionInterpolator: undefined }));
  };

  // ---------- Drawing interactions (drag a box while the tool is active) ----------
  const onDragStart = useCallback(
    (info: PickingInfo) => {
      if (!isDrawingAoi || !info.coordinate) return;
      const p: LngLat = [info.coordinate[0], info.coordinate[1]];
      updateDragBox({ start: p, end: p });
    },
    [isDrawingAoi, updateDragBox]
  );

  const onDrag = useCallback(
    (info: PickingInfo) => {
      if (!isDrawingAoi || !info.coordinate) return;
      const p: LngLat = [info.coordinate[0], info.coordinate[1]];
      const box = dragBoxRef.current;
      if (box) updateDragBox({ ...box, end: p });
    },
    [isDrawingAoi, updateDragBox]
  );

  const onDragEnd = useCallback(() => {
    if (!isDrawingAoi) return;
    const box = dragBoxRef.current;
    updateDragBox(null);
    if (box) void setCustomBbox(box.start[0], box.start[1], box.end[0], box.end[1]);
  }, [isDrawingAoi, setCustomBbox, updateDragBox]);

  // ---------- Layers: one DeckGL instance, only data/updateTriggers change ----------
  const layers = useMemo(() => {
    const aoiData: AoiFeature[] = [{ polygon: currentAoi.coordinates }];
    const previewData: AoiFeature[] = dragBox
      ? [
          {
            polygon: [
              [
                dragBox.start,
                [dragBox.end[0], dragBox.start[1]],
                dragBox.end,
                [dragBox.start[0], dragBox.end[1]],
                dragBox.start
              ]
            ]
          }
        ]
      : [];

    return [
      new PathLayer<{ path: LngLat[] }>({
        id: "offline-graticule",
        data: GRATICULE,
        visible: !basemapAvailable,
        getPath: (d) => d.path,
        getColor: [56, 189, 248, 28],
        widthUnits: "pixels",
        getWidth: 1
      }),
      new H3HexagonLayer<H3MapSummaryHex>({
        id: "h3-hexagon-layer",
        data: hexagons,
        pickable: true,
        wireframe: false,
        filled: true,
        extruded: is3D,
        coverage: 0.92,
        getHexagon: (d) => d.h3_index, // hex string straight from the API (never a JS number)
        getFillColor: (d) => {
          if (highlightIndustrialOnMap && d.is_industrial_site) return INDUSTRIAL_NEON;
          const t = Math.sqrt(Math.min(1, d.mean_annual_fre / maxFre));
          const alpha = 70 + 170 * t;
          return viewMode === "RAW" ? lerpColor([90, 20, 15], [255, 90, 40], t, alpha) : lerpColor([12, 40, 80], [56, 189, 248], t, alpha);
        },
        getElevation: (d) => (d.is_industrial_site && highlightIndustrialOnMap ? MAX_ELEVATION_M : Math.sqrt(Math.min(1, d.mean_annual_fre / maxFre)) * MAX_ELEVATION_M),
        elevationScale: 1,
        updateTriggers: {
          getFillColor: [viewMode, highlightIndustrialOnMap, maxFre],
          getElevation: [highlightIndustrialOnMap, maxFre]
        }
      }),
      new PolygonLayer<AoiFeature>({
        id: "aoi-outline",
        data: aoiData,
        filled: false,
        stroked: true,
        getPolygon: (d) => d.polygon,
        getLineColor: [34, 211, 238, 220],
        lineWidthUnits: "pixels",
        getLineWidth: 2
      }),
      new PolygonLayer<AoiFeature>({
        id: "aoi-draw-preview",
        data: previewData,
        filled: true,
        stroked: true,
        getPolygon: (d) => d.polygon,
        getFillColor: [34, 211, 238, 40],
        getLineColor: [34, 211, 238, 255],
        lineWidthUnits: "pixels",
        getLineWidth: 2
      })
    ];
  }, [hexagons, maxFre, viewMode, highlightIndustrialOnMap, is3D, currentAoi, dragBox, basemapAvailable]);

  const getTooltip = useCallback(({ object }: PickingInfo<H3MapSummaryHex>) => {
    if (!object) return null;
    const lines = [
      `H3 ${object.h3_index}`,
      `Mean annual FRE: ${object.mean_annual_fre.toFixed(1)} MJ/km²`,
      `Trend: ${object.trend_slope >= 0 ? "+" : ""}${object.trend_slope.toFixed(2)} %/yr`
    ];
    if (object.is_industrial_site) lines.push(excludeIndustrial ? "⚠ Industrial gas flaring (excluded)" : "⚠ Industrial gas flaring");
    return { text: lines.join("\n") };
  }, [excludeIndustrial]);

  const controller = useMemo(
    () => (isDrawingAoi ? { dragPan: false, dragRotate: false, doubleClickZoom: false } : { dragRotate: is3D }),
    [isDrawingAoi, is3D]
  );

  const industrialCount = useMemo(() => hexagons.filter((h) => h.is_industrial_site).length, [hexagons]);

  return (
    <div ref={containerRef} className="relative w-full h-full min-h-[400px] bg-[#070B14] rounded-lg overflow-hidden border border-slate-800">
      <DeckGL
        viewState={viewState}
        onViewStateChange={({ viewState: next }) => setViewState(next as ViewState)}
        controller={controller}
        layers={layers}
        onDragStart={onDragStart}
        onDrag={onDrag}
        onDragEnd={onDragEnd}
        getTooltip={getTooltip}
        getCursor={({ isDragging, isHovering }) => (isDrawingAoi ? "crosshair" : isDragging ? "grabbing" : isHovering ? "pointer" : "grab")}
      >
        {basemapAvailable && (
          <MapLibreMap
            mapStyle={MAP_STYLE}
            reuseMaps
            onLoad={() => {
              styleLoadedRef.current = true;
            }}
            onError={() => {
              // Only a style/initial-load failure disables the basemap; isolated tile errors are ignored.
              if (!styleLoadedRef.current) setBasemapAvailable(false);
            }}
          />
        )}
      </DeckGL>

      {isDrawingAoi && (
        <div className="absolute top-20 left-1/2 -translate-x-1/2 z-10 bg-cyan-950/90 border border-cyan-500 text-cyan-200 text-xs font-mono px-3 py-1.5 rounded-lg shadow-lg pointer-events-none">
          Drag on the map to draw the AOI box · Esc to cancel
        </div>
      )}

      <div className="absolute bottom-3 left-3 z-10 bg-slate-900/80 backdrop-blur-md px-3 py-1.5 rounded border border-slate-700 text-xs text-slate-200 font-mono shadow-lg pointer-events-none">
        <span className="text-cyan-400 font-bold">MODE:</span> {viewMode} | <span className="text-amber-400 font-bold">SPLIT:</span> {splitCurtainPct}% |{" "}
        <span className="text-slate-400">{hexagons.length.toLocaleString("en-US")} hex</span>
        {highlightIndustrialOnMap && <span className="text-pink-400"> | {industrialCount} flaring</span>}
        {!basemapAvailable && <span className="text-amber-400"> | OFFLINE GRID</span>}
        {isSynthetic && <span className="text-amber-400"> | SYNTHETIC</span>}
      </div>

      <button
        type="button"
        onClick={toggle3D}
        className="absolute bottom-3 right-3 z-10 flex items-center gap-1.5 bg-slate-900/80 hover:bg-slate-800 backdrop-blur-md px-2.5 py-1.5 rounded border border-slate-700 text-xs text-slate-200 font-mono shadow-lg"
        title={is3D ? "Switch to flat 2D view" : "Switch to extruded 3D view"}
      >
        {is3D ? <Square className="w-3.5 h-3.5 text-cyan-400" /> : <Box className="w-3.5 h-3.5 text-cyan-400" />}
        {is3D ? "2D" : "3D"}
      </button>
    </div>
  );
};
