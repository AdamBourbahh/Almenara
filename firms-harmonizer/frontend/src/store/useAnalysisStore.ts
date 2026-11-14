import { create } from "zustand";
import type { AnalyzeRequest, AnalyzeResponse, ChaosMonkeyResponse, DailyCalendarCell, GeoJSONPolygon, ViewMode } from "../api/types";
import { analyzeAoi, runChaosMonkey } from "../api/client";

// ============================================================================
// Official pilot regions for the jury demo
// ============================================================================

export interface PresetRegion {
  label: string;
  context: string;
  coordinates: number[][][];
}

export const PRESET_REGIONS = {
  chilecito_la_rioja: { label: "Chilecito, La Rioja (Argentina)", context: "Argentina: real FIRMS observations", coordinates: [[[-69.5, -31], [-65.5, -31], [-65.5, -27.5], [-69.5, -27.5], [-69.5, -31]]] },
  iberia_med: { label: "Iberian Peninsula / Mediterranean (Spain)", context: "Spain and Portugal: real FIRMS observations", coordinates: [[[-9.5, 36], [4, 36], [4, 44], [-9.5, 44], [-9.5, 36]]] },
  orlando_florida: { label: "Orlando, Florida (USA)", context: "Florida: real FIRMS observations", coordinates: [[[-82.0, 28.0], [-80.7, 28.0], [-80.7, 29.3], [-82.0, 29.3], [-82.0, 28.0]]] },
  amazonas_manaus: { label: "Amazonas / Manaus (Brazil)", context: "Brazil: real FIRMS observations", coordinates: [[[-62.0, -5.0], [-58.0, -5.0], [-58.0, -1.0], [-62.0, -1.0], [-62.0, -5.0]]] }
} satisfies Record<string, PresetRegion>;

export type PresetKey = keyof typeof PRESET_REGIONS;
export type RegionSelection = PresetKey | "CUSTOM";
export const PRESET_ORDER = Object.keys(PRESET_REGIONS) as PresetKey[];

/** Minimum side of a custom bounding box (degrees) to avoid accidental click-sized AOIs. */
export const MIN_BBOX_SIDE_DEG = 0.02;

export interface HoveredDay {
  year: number;
  doy: number;
  /** Viewport coordinates of the pointer, used to float the tooltip. */
  clientX: number;
  clientY: number;
}

/** O(1) key for calendar lookups: 2022 / 226 -> 2022226. */
export const calendarKey = (year: number, doy: number) => year * 1000 + doy;

function buildCalendarIndex(data: AnalyzeResponse): Map<number, DailyCalendarCell> {
  const index = new Map<number, DailyCalendarCell>();
  for (const cell of data.calendar_series) index.set(calendarKey(cell.year, cell.doy), cell);
  for (const cell of data.forecast_series ?? []) {
    const key = calendarKey(cell.year, cell.doy);
    if (!index.has(key)) index.set(key, { ...cell, is_forecast: true });
  }
  return index;
}

const polygonFromPreset = (key: PresetKey): GeoJSONPolygon => ({ type: "Polygon", coordinates: PRESET_REGIONS[key].coordinates });

const isAbortError = (error: unknown) => error instanceof DOMException && error.name === "AbortError";

// ============================================================================
// State
// ============================================================================

interface AnalysisState {
  // Parameters & selection
  viewMode: ViewMode;
  selectedPreset: RegionSelection;
  currentAoi: GeoJSONPolygon;
  startYear: number;
  endYear: number;
  excludeIndustrial: boolean;
  enableKalman: boolean;
  highlightIndustrialOnMap: boolean;
  isDrawingAoi: boolean;

  // Interactive UI controls
  splitCurtainPct: number; // 0..100, "2012 Time-Machine" curtain
  selectedYear: number;
  hoveredDay: HoveredDay | null;

  // API data
  loading: boolean;
  error: string | null;
  analysisData: AnalyzeResponse | null;
  /** year/doy -> cell (observed + forecast). Rebuilt once per response; used for O(1) hover. */
  calendarIndex: Map<number, DailyCalendarCell>;
  isSynthetic: boolean;

  // Chaos Monkey
  chaosLoading: boolean;
  chaosError: string | null;
  chaosData: ChaosMonkeyResponse | null;
  chaosIsSynthetic: boolean;

  // Actions
  setViewMode: (mode: ViewMode) => void;
  toggleViewMode: () => void;
  setSplitCurtainPct: (pct: number) => void;
  setSelectedYear: (year: number) => void;
  setHoveredDay: (day: HoveredDay | null) => void;
  setExcludeIndustrial: (exclude: boolean) => Promise<void>;
  setEnableKalman: (enable: boolean) => Promise<void>;
  setHighlightIndustrialOnMap: (highlight: boolean) => void;
  setDrawingAoi: (drawing: boolean) => void;
  loadPresetRegion: (presetKey: PresetKey) => Promise<void>;
  setCustomAoi: (coordinates: number[][][]) => Promise<void>;
  setCustomBbox: (west: number, south: number, east: number, north: number) => Promise<void>;
  executeAnalysis: () => Promise<void>;
  triggerChaosMonkey: () => Promise<void>;
  resetChaosMonkey: () => void;
}

// Request bookkeeping lives outside the state: it never drives rendering.
let analysisController: AbortController | null = null;
let analysisSeq = 0;
let chaosController: AbortController | null = null;
let chaosSeq = 0;

export const useAnalysisStore = create<AnalysisState>((set, get) => ({
  viewMode: "HARMONIZED",
  selectedPreset: "chilecito_la_rioja",
  currentAoi: polygonFromPreset("chilecito_la_rioja"),
  startYear: 2001,
  endYear: 2026,
  excludeIndustrial: true,
  enableKalman: true,
  highlightIndustrialOnMap: false,
  isDrawingAoi: false,

  splitCurtainPct: 50,
  selectedYear: 2022, // Critical year by default (MODIS Aqua safe mode)
  hoveredDay: null,

  loading: false,
  error: null,
  analysisData: null,
  calendarIndex: new Map(),
  isSynthetic: false,

  chaosLoading: false,
  chaosError: null,
  chaosData: null,
  chaosIsSynthetic: false,

  setViewMode: (mode) => set({ viewMode: mode }),

  toggleViewMode: () => set((s) => ({ viewMode: s.viewMode === "RAW" ? "HARMONIZED" : "RAW" })),

  setSplitCurtainPct: (pct) => set({ splitCurtainPct: Math.min(100, Math.max(0, Math.round(pct))) }),

  setSelectedYear: (year) => {
    const { startYear, endYear, selectedYear } = get();
    const clamped = Math.min(endYear, Math.max(startYear, Math.round(year)));
    if (clamped !== selectedYear) set({ selectedYear: clamped, chaosData: null });
  },

  // Called on every pointer move: only notify subscribers when the hovered cell actually changes.
  setHoveredDay: (day) => {
    const prev = get().hoveredDay;
    if (prev === day) return;
    if (prev && day && prev.year === day.year && prev.doy === day.doy) return;
    set({ hoveredDay: day });
  },

  setExcludeIndustrial: async (exclude) => {
    if (get().excludeIndustrial === exclude) return;
    set({ excludeIndustrial: exclude });
    await get().executeAnalysis();
  },

  setEnableKalman: async (enable) => {
    if (get().enableKalman === enable) return;
    set({ enableKalman: enable });
    await get().executeAnalysis();
  },

  setHighlightIndustrialOnMap: (highlight) => set({ highlightIndustrialOnMap: highlight }),

  setDrawingAoi: (drawing) => set({ isDrawingAoi: drawing }),

  loadPresetRegion: async (presetKey) => {
    if (!(presetKey in PRESET_REGIONS)) return;
    set({ selectedPreset: presetKey, currentAoi: polygonFromPreset(presetKey), isDrawingAoi: false, chaosData: null });
    await get().executeAnalysis();
  },

  setCustomAoi: async (coordinates) => {
    const ring = coordinates[0];
    if (!ring || ring.length < 4) {
      set({ error: "Custom AOI must be a closed polygon with at least 3 vertices." });
      return;
    }
    set({ selectedPreset: "CUSTOM", currentAoi: { type: "Polygon", coordinates }, isDrawingAoi: false, chaosData: null });
    await get().executeAnalysis();
  },

  setCustomBbox: async (west, south, east, north) => {
    const w = Math.max(-180, Math.min(west, east));
    const e = Math.min(180, Math.max(west, east));
    const s = Math.max(-85, Math.min(south, north));
    const n = Math.min(85, Math.max(south, north));
    if (e - w < MIN_BBOX_SIDE_DEG || n - s < MIN_BBOX_SIDE_DEG) {
      set({ isDrawingAoi: false });
      return;
    }
    // Counter-clockwise exterior ring (RFC 7946), closed.
    await get().setCustomAoi([[[w, s], [e, s], [e, n], [w, n], [w, s]]]);
  },

  executeAnalysis: async () => {
    analysisController?.abort();
    const controller = new AbortController();
    analysisController = controller;
    const seq = ++analysisSeq;

    const state = get();
    set({ loading: true, error: null });

    const requestPayload: AnalyzeRequest = {
      aoi: state.currentAoi,
      start_year: state.startYear,
      end_year: state.endYear,
      exclude_industrial_flaring: state.excludeIndustrial,
      enable_kalman_gap_filling: state.enableKalman,
      confidence_level: "nominal"
    };

    try {
      const { data } = await analyzeAoi(requestPayload, controller.signal);
      if (seq !== analysisSeq) return; // a newer request superseded this one
      set({ analysisData: data, calendarIndex: buildCalendarIndex(data), isSynthetic: data.data_source === "synthetic", loading: false, hoveredDay: null });
    } catch (err: unknown) {
      if (seq !== analysisSeq || isAbortError(err)) return;
      set({ error: err instanceof Error ? err.message : "Spatial analysis failed", loading: false });
    } finally {
      if (analysisController === controller) analysisController = null;
    }
  },

  triggerChaosMonkey: async () => {
    chaosController?.abort();
    const controller = new AbortController();
    chaosController = controller;
    const seq = ++chaosSeq;

    const state = get();
    set({ chaosLoading: true, chaosError: null });

    try {
      const { data } = await runChaosMonkey(
        { aoi: state.currentAoi, target_year: state.selectedYear, drop_fraction: 0.25, random_seed: 42 },
        controller.signal
      );
      if (seq !== chaosSeq) return;
      set({ chaosData: data, chaosIsSynthetic: data.data_source === "synthetic", chaosLoading: false });
    } catch (err: unknown) {
      if (seq !== chaosSeq || isAbortError(err)) return;
      set({ chaosError: err instanceof Error ? err.message : "Chaos Monkey simulation failed", chaosLoading: false });
    } finally {
      if (chaosController === controller) chaosController = null;
    }
  },

  resetChaosMonkey: () => {
    chaosController?.abort();
    chaosSeq++;
    set({ chaosData: null, chaosLoading: false, chaosError: null });
  }
}));
