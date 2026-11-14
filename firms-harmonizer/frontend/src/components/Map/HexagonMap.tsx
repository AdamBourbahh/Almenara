import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import DeckGL from "@deck.gl/react";
import { FlyToInterpolator, MapView, type MapViewState, type PickingInfo } from "@deck.gl/core";
import { PathLayer, PolygonLayer } from "@deck.gl/layers";
import { H3HexagonLayer } from "@deck.gl/geo-layers";
import MapLibreMap from "react-map-gl/maplibre";
import { setWorkerUrl } from "maplibre-gl";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";
import { useShallow } from "zustand/react/shallow";
import { Box, Eye, EyeOff, Square } from "lucide-react";
import type { GeoJSONPolygon, H3MapSummaryHex } from "../../api/types";
import { selectedMapPeriod, useAnalysisStore } from "../../store/useAnalysisStore";
import { summarizeMappedYear, colorIntensity } from "./mapMetrics";
import { useTheme } from "../../lib/theme";

setWorkerUrl(maplibreWorkerUrl);

// Keep the deck.gl canvas transparent so the satellite basemap shows through.
const DECK_VIEW = new MapView({ clear: false });

// ---------------------------------------------------------------------------
// Basemaps — open raster tiles (satellite imagery + relief)
// ---------------------------------------------------------------------------

const ESRI_IMAGERY =
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
const ESRI_HILLSHADE =
  "https://server.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}";
const OPENTOPO = "https://a.tile.opentopomap.org/{z}/{x}/{y}.png";
const CARTO_LIGHT = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";
const CARTO_DARK = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

type BasemapKey = "satelliteRelief" | "satellite" | "terrain" | "streets";

const IMAGERY_SOURCE = {
  type: "raster",
  tiles: [ESRI_IMAGERY],
  tileSize: 256,
  attribution: "Imagery © Esri, Maxar, Earthstar Geographics"
};
const HILLSHADE_SOURCE = {
  type: "raster",
  tiles: [ESRI_HILLSHADE],
  tileSize: 256,
  attribution: "Relief © Esri"
};

const BASEMAPS: Record<BasemapKey, { label: string; style: unknown }> = {
  satelliteRelief: {
    label: "Satellite + relief",
    style: {
      version: 8,
      sources: { imagery: IMAGERY_SOURCE, hillshade: HILLSHADE_SOURCE },
      layers: [
        { id: "imagery", type: "raster", source: "imagery" },
        { id: "hillshade", type: "raster", source: "hillshade", paint: { "raster-opacity": 0.35 } }
      ]
    }
  },
  satellite: {
    label: "Satellite",
    style: {
      version: 8,
      sources: { imagery: IMAGERY_SOURCE },
      layers: [{ id: "imagery", type: "raster", source: "imagery" }]
    }
  },
  terrain: {
    label: "Terrain",
    style: {
      version: 8,
      sources: {
        topo: {
          type: "raster",
          tiles: [OPENTOPO],
          tileSize: 256,
          maxzoom: 17,
          attribution: "© OpenTopoMap (CC-BY-SA)"
        }
      },
      layers: [{ id: "topo", type: "raster", source: "topo" }]
    }
  },
  streets: { label: "Streets", style: CARTO_LIGHT }
};

const INDUSTRIAL_PURPLE: [number, number, number, number] = [106, 61, 154, 235];
const MAX_ELEVATION_M = 1250;
const PITCH_3D = 35;

type LngLat = [number, number];

interface AoiFeature {
  polygon: number[][][];
}

const GRATICULE: { path: LngLat[] }[] = [
  ...Array.from({ length: 361 }, (_, i) => ({ path: [[i - 180, -85], [i - 180, 85]] as LngLat[] })),
  ...Array.from({ length: 171 }, (_, i) => ({ path: [[-180, i - 85], [180, i - 85]] as LngLat[] }))
];

function rampColor(stops: ReadonlyArray<readonly [number, number, number]>, t: number, alpha: number): [number, number, number, number] {
  const clamped = Math.max(0, Math.min(1, t));
  const scaled = clamped * (stops.length - 1);
  const k = Math.min(stops.length - 2, Math.floor(scaled));
  const f = scaled - k;
  return [
    stops[k][0] + (stops[k + 1][0] - stops[k][0]) * f,
    stops[k][1] + (stops[k + 1][1] - stops[k][1]) * f,
    stops[k][2] + (stops[k + 1][2] - stops[k][2]) * f,
    alpha
  ];
}

const THERMAL_LIGHT: ReadonlyArray<readonly [number, number, number]> = [
  [254, 240, 217],
  [253, 190, 133],
  [230, 85, 13],
  [179, 0, 0]
];
const RAW_LIGHT: ReadonlyArray<readonly [number, number, number]> = [
  [229, 231, 235],
  [156, 163, 175],
  [71, 85, 105]
];
const RAW_DARK: ReadonlyArray<readonly [number, number, number]> = [
  [42, 47, 58],
  [107, 114, 128],
  [203, 213, 225]
];

function viewStateForAoi(aoi: GeoJSONPolygon, width: number, height: number, pitch: number): MapViewState {
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
  const usableH = Math.max(120, height - 290) * 0.88;
  const zoom = Math.min(Math.log2(usableW / (512 * spanX)), Math.log2(usableH / (512 * spanY)));
  return {
    longitude: (west + east) / 2,
    latitude: (south + north) / 2,
    zoom: Math.max(2, Math.min(13, zoom)),
    pitch,
    bearing: 0
  };
}

type ViewState = MapViewState;

export function HexagonMap() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const styleLoadedRef = useRef(false);
  const pointerOverMap = useRef(false);
  const reducedMotion = useMemo(() => window.matchMedia("(prefers-reduced-motion: reduce)"), []);
  const {
    analysisData, mapHexagons, mapPeriod, mapLoading, mapError, requestedPeriod, startYear, endYear,
    viewMode,
    highlightIndustrialOnMap,
    excludeIndustrial,
    currentAoi,
    isDrawingAoi,
    setDrawingAoi,
    setCustomBbox,
    isSynthetic
  } = useAnalysisStore(
    useShallow((s) => ({
      analysisData: s.analysisData,
      mapHexagons: s.mapHexagons, mapPeriod: s.mapPeriod, mapLoading: s.mapLoading, mapError: s.mapError,
      requestedPeriod: selectedMapPeriod(s), startYear: s.startYear, endYear: s.endYear,
      viewMode: s.viewMode,
      highlightIndustrialOnMap: s.highlightIndustrialOnMap,
      excludeIndustrial: s.excludeIndustrial,
      currentAoi: s.currentAoi,
      isDrawingAoi: s.isDrawingAoi,
      setDrawingAoi: s.setDrawingAoi,
      setCustomBbox: s.setCustomBbox,
      isSynthetic: s.isSynthetic
    }))
  );

  const theme = useTheme((s) => s.theme);
  const [basemap, setBasemap] = useState<BasemapKey>("satelliteRelief");
  const [is3D, setIs3D] = useState(false);
  const [showHeat, setShowHeat] = useState(true);
  const [basemapAvailable, setBasemapAvailable] = useState(() => typeof navigator === "undefined" || navigator.onLine);
  const [viewState, setViewState] = useState<ViewState>(() => viewStateForAoi(currentAoi, 900, 600, 0));
  const [dragBox, setDragBox] = useState<{ start: LngLat; end: LngLat } | null>(null);
  const dragBoxRef = useRef<{ start: LngLat; end: LngLat } | null>(null);
  const updateDragBox = useCallback((box: { start: LngLat; end: LngLat } | null) => {
    dragBoxRef.current = box;
    setDragBox(box);
  }, []);

  useEffect(() => {
    const onMotionChange = () => {
      if (reducedMotion.matches) setViewState((prev) => ({ ...prev, transitionDuration: 0 }));
    };
    reducedMotion.addEventListener("change", onMotionChange);
    return () => reducedMotion.removeEventListener("change", onMotionChange);
  }, [reducedMotion]);

  useEffect(() => {
    const el = containerRef.current;
    setViewState((prev) => ({
      ...viewStateForAoi(currentAoi, el?.clientWidth ?? 900, el?.clientHeight ?? 600, prev.pitch ?? 0),
      transitionDuration: reducedMotion.matches ? 0 : 900,
      transitionInterpolator: new FlyToInterpolator()
    }));
  }, [currentAoi, reducedMotion]);

  useEffect(() => {
    const node = containerRef.current;
    if (!node) return;
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey || (event.target instanceof Element && event.target.closest("[data-map-ui]"))) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? node.clientHeight : 1);
      setViewState((prev) => ({ ...prev, zoom: Math.max(1, Math.min(18, prev.zoom - delta * .004)), transitionDuration: 0 }));
    };
    const onKey = (event: KeyboardEvent) => {
      if (!pointerOverMap.current || !(event.ctrlKey || event.metaKey)) return;
      const target = event.target;
      if (target instanceof HTMLElement && (target.matches("input, textarea, select") || target.isContentEditable)) return;
      if (!["+", "=", "-", "_", "0"].includes(event.key)) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      setViewState((prev) => event.key === "0"
        ? { ...viewStateForAoi(currentAoi, node.clientWidth, node.clientHeight, prev.pitch ?? 0), transitionDuration: 0 }
        : { ...prev, zoom: Math.max(1, Math.min(18, prev.zoom + (["-", "_"].includes(event.key) ? -.5 : .5))), transitionDuration: 0 });
    };
    node.addEventListener("wheel", onWheel, { passive: false, capture: true });
    window.addEventListener("keydown", onKey, true);
    return () => {
      node.removeEventListener("wheel", onWheel, true);
      window.removeEventListener("keydown", onKey, true);
    };
  }, [currentAoi]);

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

  // Keyboard shortcut: H toggles the heat layer.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable)) {
        return;
      }
      if (e.key === "h" || e.key === "H") {
        e.preventDefault();
        setShowHeat((value) => !value);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const hexagons = useMemo(() => summarizeMappedYear(mapHexagons, excludeIndustrial).hexagons, [mapHexagons, excludeIndustrial]);
  // Keep the same scale across days, months and years; never normalize each frame.
  const reference = analysisData?.map_hexagons;
  const span = Math.max(1, endYear - startYear + 1);
  const maxRaw = useMemo(() => (reference ?? []).reduce((m, h) => Math.max(m, h.raw_pixel_count), 1), [reference]);
  const maxFre = useMemo(
    () => (reference ?? []).reduce((m, h) => Math.max(m, h.mean_annual_fre * span), 1),
    [reference, span]
  );

  const toggle3D = () => {
    const next = !is3D;
    setIs3D(next);
    setViewState((prev) => ({ ...prev, pitch: next ? PITCH_3D : 0, transitionDuration: reducedMotion.matches ? 0 : 400, transitionInterpolator: undefined }));
  };

  const onDragStart = useCallback(
    (info: PickingInfo) => {
      useAnalysisStore.getState().dismissDateRiskPrompt();
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
  const onDragEnd = useCallback((info: PickingInfo) => {
    if (!isDrawingAoi) return;
    const box = dragBoxRef.current;
    updateDragBox(null);
    const end = info.coordinate ?? box?.end;
    if (box && end) void setCustomBbox(box.start[0], box.start[1], end[0], end[1]);
  }, [isDrawingAoi, setCustomBbox, updateDragBox]);

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
        getColor: [148, 163, 184, 80],
        widthUnits: "pixels",
        getWidth: 1
      }),
      new H3HexagonLayer<H3MapSummaryHex>({
        id: "h3-hexagon-layer",
        data: hexagons,
        visible: showHeat,
        pickable: true,
        onClick: ({ object }, event) => {
          const state = useAnalysisStore.getState();
          if (event.srcEvent instanceof MouseEvent && event.srcEvent.button !== 0) return;
          if (object && !state.isDrawingAoi) state.openCopilot({ hex: object });
        },
        wireframe: false,
        filled: true,
        extruded: is3D,
        coverage: 1,
        stroked: true,
        getLineColor: [255, 255, 255, 90],
        lineWidthUnits: "pixels",
        getLineWidth: 0.6,
        autoHighlight: true,
        highlightColor: [255, 255, 255, 110],
        getHexagon: (d) => d.h3_index,
        getFillColor: (d) => {
          if (highlightIndustrialOnMap && d.is_industrial_site) return INDUSTRIAL_PURPLE;
          const t = colorIntensity(viewMode === "RAW" ? d.raw_pixel_count : d.mean_annual_fre, viewMode === "RAW" ? maxRaw : maxFre);
          const alpha = 120 + 130 * t;
          if (viewMode === "RAW") return rampColor(theme === "dark" ? RAW_DARK : RAW_LIGHT, t, alpha);
          return rampColor(THERMAL_LIGHT, t, alpha);
        },
        getElevation: (d) => colorIntensity(viewMode === "RAW" ? d.raw_pixel_count : d.mean_annual_fre, viewMode === "RAW" ? maxRaw : maxFre) * MAX_ELEVATION_M,
        elevationScale: 1,
        updateTriggers: {
          getFillColor: [viewMode, highlightIndustrialOnMap, maxFre, maxRaw, theme, mapPeriod],
          getElevation: [maxFre, maxRaw, viewMode, mapPeriod]
        }
      }),
      new PolygonLayer<AoiFeature>({
        id: "aoi-outline",
        data: aoiData,
        filled: false,
        stroked: true,
        getPolygon: (d) => d.polygon,
        getLineColor: [29, 78, 216, 230],
        lineWidthUnits: "pixels",
        getLineWidth: 2
      }),
      new PolygonLayer<AoiFeature>({
        id: "aoi-draw-preview",
        data: previewData,
        filled: true,
        stroked: true,
        getPolygon: (d) => d.polygon,
        getFillColor: [29, 78, 216, 30],
        getLineColor: [29, 78, 216, 255],
        lineWidthUnits: "pixels",
        getLineWidth: 2
      })
    ];
  }, [hexagons, maxFre, maxRaw, mapPeriod, viewMode, highlightIndustrialOnMap, is3D, showHeat, theme, currentAoi, dragBox, basemapAvailable, isDrawingAoi]);

  const getTooltip = useCallback(
    ({ object }: PickingInfo<H3MapSummaryHex>) => {
      if (!object) return null;
      const lines = [
        `H3 ${object.h3_index}`,
        `Period: ${mapPeriod}`,
        `Period fire energy: ${object.mean_annual_fre.toFixed(1)} MJ/km²`,
        `Period detections: ${object.raw_pixel_count.toLocaleString("en-US")}`,
        "Click to attach this hexagon to Fire Copilot.",
        "Color: logarithmic scale, fixed across dates",
        "Satellite observations do not establish the exact ignition time."
      ];
      if (object.is_industrial_site) {
        lines.push(excludeIndustrial ? "Industrial gas flare (excluded)" : "Industrial gas flare");
      }
      return { text: lines.join("\n") };
    },
    [excludeIndustrial, mapPeriod]
  );

  const controller = useMemo(
    () => (isDrawingAoi ? { dragPan: false, dragRotate: false, doubleClickZoom: false } : { dragRotate: is3D }),
    [isDrawingAoi, is3D]
  );

  // Keep the dock contextual: selections must occupy a meaningful visible
  // area. A large region can remain relevant even at a low absolute zoom.

  const mapStyle = basemap === "streets" ? (theme === "dark" ? CARTO_DARK : CARTO_LIGHT) : BASEMAPS[basemap].style;

  return (
    <div ref={containerRef} data-map-viewport className="relative h-full w-full overflow-hidden bg-paper"
      onPointerMove={(event) => { pointerOverMap.current = !(event.target instanceof Element && event.target.closest("[data-map-ui]")); }}
      onPointerEnter={() => { pointerOverMap.current = true; }}
      onPointerLeave={() => { pointerOverMap.current = false; }}
      onContextMenuCapture={(event) => {
        if (event.target instanceof Element && event.target.closest("[data-map-ui], .maplibregl-control-container")) return;
        event.preventDefault();
        event.stopPropagation();
        updateDragBox(null);
        setDrawingAoi(true);
      }}
    >
      {basemapAvailable && (
        <MapLibreMap
          longitude={viewState.longitude}
          latitude={viewState.latitude}
          zoom={viewState.zoom}
          pitch={viewState.pitch}
          bearing={viewState.bearing}
          mapStyle={mapStyle as never}
          reuseMaps
          onLoad={() => {
            styleLoadedRef.current = true;
          }}
          onError={() => {
            if (!styleLoadedRef.current) setBasemapAvailable(false);
          }}
          style={{ position: "absolute", inset: 0 }}
        />
      )}

      <DeckGL
        style={{ position: "absolute", inset: "0" }}
        views={DECK_VIEW}
        viewState={reducedMotion.matches ? { ...viewState, transitionDuration: 0 } : viewState}
        onViewStateChange={({ viewState: next }) => setViewState(next as ViewState)}
        controller={controller}
        layers={layers}
        onDragStart={onDragStart}
        onDrag={onDrag}
        onDragEnd={onDragEnd}
        getTooltip={getTooltip}
        getCursor={({ isDragging, isHovering }) =>
          isDrawingAoi ? "crosshair" : isDragging ? "grabbing" : isHovering ? "pointer" : "grab"
        }
      />

      {isDrawingAoi && (
        <div role="status" className="absolute left-1/2 bottom-20 z-10 -translate-x-1/2 border border-reference bg-panel px-3 py-1.5 text-xs text-reference pointer-events-none">
          Drag on the map to draw the area. Esc to cancel.
        </div>
      )}

      {/* Basemap and layer controls remain clear of the explorer. */}
      <div data-map-ui className="absolute left-3 z-20 flex flex-wrap items-center gap-2 transition-[bottom] duration-200" style={{ bottom: 24 }}>
        <select
          value={basemap}
          onChange={(e) => setBasemap(e.target.value as BasemapKey)}
          aria-label="Basemap"
          className="border border-rule bg-panel/95 px-2 py-1.5 text-xs text-ink shadow-sm"
        >
          {(Object.keys(BASEMAPS) as BasemapKey[]).map((key) => (
            <option key={key} value={key}>
              {BASEMAPS[key].label}
            </option>
          ))}
        </select>

        <button
          type="button"
          onClick={toggle3D}
          aria-pressed={is3D}
          className="flex items-center gap-1.5 border border-rule bg-panel/95 px-2.5 py-1.5 text-xs text-ink hover:bg-paper"
          title={is3D ? "Switch to flat 2D" : "Switch to 3D relief"}
        >
          {is3D ? <Box className="h-3.5 w-3.5" /> : <Square className="h-3.5 w-3.5" />}
          {is3D ? "3D" : "2D"}
        </button>

        <button
          type="button"
          onClick={() => setShowHeat((value) => !value)}
          aria-pressed={showHeat}
          className={`flex items-center gap-1.5 border px-2.5 py-1.5 text-xs hover:bg-paper ${
            showHeat ? "border-rule bg-panel/95 text-ink" : "border-rule bg-paper text-muted"
          }`}
          title="Toggle heat layer (H)"
        >
          {showHeat ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
          Heat
          <kbd className="ml-0.5 border border-rule px-1 text-[9px] text-faint">H</kbd>
        </button>
      </div>

      {/* Legend below the Google Maps-style search toolbar. */}
      <div data-map-ui className="absolute left-3 top-[76px] z-10 max-w-[280px] rounded-xl shadow-lg border border-rule bg-panel/95 px-3 py-2">
        {showHeat && (
          <div className="mb-2 space-y-1.5">
            <div className="flex items-center gap-2">
              <span className="inline-block h-2.5 w-24" style={{ background: `linear-gradient(90deg, ${(viewMode === "RAW" ? (theme === "dark" ? RAW_DARK : RAW_LIGHT) : THERMAL_LIGHT).map((color) => `rgb(${color.join(",")})`).join(",")})` }} />
              <span className="text-[10px] text-muted">{viewMode === "RAW" ? `Detections: 0–${Math.round(maxRaw).toLocaleString("en-US")}+` : `Period energy: 0–${Math.round(maxFre).toLocaleString("en-US")}+ MJ/km²`}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="inline-block h-3 w-3" style={{ background: "#6A3D9A" }} />
              <span className="text-[10px] text-muted">Industrial gas flares</span>
            </div>
          </div>
        )}
        <p className="text-[10px] text-muted tnum">
          {mapLoading ? `Loading ${requestedPeriod}…` : mapError ? "Map period unavailable" : `${mapPeriod ?? requestedPeriod} · ${viewMode === "RAW" ? "Raw counts" : "Calibrated energy"} · ${hexagons.length.toLocaleString("en-US")} cells`}
          {isSynthetic && <span className="text-terracotta"> · synthetic data</span>}
        </p>
        {!mapLoading && !mapError && hexagons.length === 0 && <p className="mt-1 text-[10px] text-muted">No mapped observations in this period. Missing observations do not rule out fire.</p>}
      </div>
    </div>
  );
}
