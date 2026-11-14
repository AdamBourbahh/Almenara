import { create } from "zustand";
import type {
  AnalyzeRequest,
  AnalyzeResponse,
  ChaosMonkeyResponse,
  DailyCalendarCell,
  ExplainSpikeResponse,
  GeoJSONPolygon,
  H3MapSummaryHex,
  ViewMode
} from "../api/types";
import { analyzeAoi, explainSpike, runChaosMonkey } from "../api/client";

// ============================================================================
// Official pilot regions for the jury demo
// ============================================================================

export interface PresetRegion {
  label: string;
  context: string;
  coordinates: number[][][];
}

export const PRESET_REGIONS = {
  CERRADO: {
    label: "Cerrado & Pantanal",
    context: "Brazil: the 2012 sensor jump",
    coordinates: [[[-57.2, -17.8], [-55.2, -17.8], [-55.2, -16.0], [-57.2, -16.0], [-57.2, -17.8]]]
  },
  SIERRA_NEVADA: {
    label: "Sierra Nevada",
    context: "California: when the season starts earlier",
    coordinates: [[[-121.2, 38.0], [-119.5, 38.0], [-119.5, 40.2], [-121.2, 40.2], [-121.2, 38.0]]]
  },
  IBERIA: {
    label: "Iberian Peninsula",
    context: "Spain and Portugal: coast and mountain detail",
    coordinates: [[[-6.5, 37.2], [-3.2, 37.2], [-3.2, 39.8], [-6.5, 39.8], [-6.5, 37.2]]]
  },
  NIGER_DELTA: {
    label: "Niger Delta",
    context: "Nigeria: oil flares versus wildfires",
    coordinates: [[[5.6, 4.6], [7.2, 4.6], [7.2, 5.8], [5.6, 5.8], [5.6, 4.6]]]
  }
} satisfies Record<string, PresetRegion>;

export type PresetKey = keyof typeof PRESET_REGIONS;
export type RegionSelection = PresetKey | "CUSTOM";
export const PRESET_ORDER: PresetKey[] = ["CERRADO", "SIERRA_NEVADA", "IBERIA", "NIGER_DELTA"];

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

export interface CopilotMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  response?: ExplainSpikeResponse;
}

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

  // Fire Copilot (Physics-First Web Grounding)
  isCopilotOpen: boolean;
  copilotLoading: boolean;
  copilotError: string | null;
  copilotMessages: CopilotMessage[];
  activeSpikeDay: DailyCalendarCell | null;
  activeSpikeHex: H3MapSummaryHex | null;

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
  openCopilot: (spike?: { day?: DailyCalendarCell | null; hex?: H3MapSummaryHex | null }) => void;
  closeCopilot: () => void;
  toggleCopilot: () => void;
  askCopilot: (question: string) => Promise<void>;
  clearCopilotMessages: () => void;
}

// Request bookkeeping lives outside the state: it never drives rendering.
let analysisController: AbortController | null = null;
let analysisSeq = 0;
let chaosController: AbortController | null = null;
let chaosSeq = 0;

export const useAnalysisStore = create<AnalysisState>((set, get) => ({
  viewMode: "HARMONIZED",
  selectedPreset: "CERRADO",
  currentAoi: polygonFromPreset("CERRADO"),
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

  isCopilotOpen: false,
  copilotLoading: false,
  copilotError: null,
  copilotMessages: [],
  activeSpikeDay: null,
  activeSpikeHex: null,

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
      const { data, isSynthetic } = await analyzeAoi(requestPayload, controller.signal);
      if (seq !== analysisSeq) return; // a newer request superseded this one
      set({ analysisData: data, calendarIndex: buildCalendarIndex(data), isSynthetic, loading: false, hoveredDay: null });
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
      const { data, isSynthetic } = await runChaosMonkey(
        { aoi: state.currentAoi, target_year: state.selectedYear, drop_fraction: 0.25, random_seed: 42 },
        controller.signal
      );
      if (seq !== chaosSeq) return;
      set({ chaosData: data, chaosIsSynthetic: isSynthetic, chaosLoading: false });
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
  },

  openCopilot: (spike) => {
    const state = get();
    const day = spike?.day !== undefined ? spike.day : state.activeSpikeDay;
    const hex = spike?.hex !== undefined ? spike.hex : state.activeSpikeHex;
    set({
      isCopilotOpen: true,
      activeSpikeDay: day,
      activeSpikeHex: hex,
      copilotError: null
    });

    if (spike && (spike.day || spike.hex)) {
      const regionName =
        state.selectedPreset !== "CUSTOM" && state.selectedPreset in PRESET_REGIONS
          ? PRESET_REGIONS[state.selectedPreset as PresetKey].label
          : "Analyzed Area of Interest";

      const promptLabel = spike.day
        ? `Explain thermal spike on ${spike.day.date} (${spike.day.harmonized_fre_mj_km2.toFixed(1)} MJ/km²)`
        : `Explain thermal characteristics of selected H3 hex`;

      const userMsg: CopilotMessage = {
        id: `user-${Date.now()}`,
        role: "user",
        content: promptLabel,
        timestamp: Date.now()
      };

      set((s) => ({
        copilotMessages: [...s.copilotMessages, userMsg],
        copilotLoading: true,
        copilotError: null
      }));

      explainSpike({
        region_name: regionName,
        selected_day: day,
        selected_hex: hex,
        user_question: promptLabel
      })
        .then((res) => {
          const assistantMsg: CopilotMessage = {
            id: `assistant-${Date.now()}`,
            role: "assistant",
            content: res.data.explanation_markdown,
            timestamp: Date.now(),
            response: res.data
          };
          set((s) => ({
            copilotMessages: [...s.copilotMessages, assistantMsg],
            copilotLoading: false
          }));
        })
        .catch((err: unknown) => {
          set({
            copilotLoading: false,
            copilotError: err instanceof Error ? err.message : "Failed to explain thermal spike."
          });
        });
    }
  },

  closeCopilot: () => set({ isCopilotOpen: false }),

  toggleCopilot: () => set((s) => ({ isCopilotOpen: !s.isCopilotOpen })),

  askCopilot: async (question: string) => {
    const trimmed = question.trim();
    if (!trimmed) return;
    const state = get();
    const regionName =
      state.selectedPreset !== "CUSTOM" && state.selectedPreset in PRESET_REGIONS
        ? PRESET_REGIONS[state.selectedPreset as PresetKey].label
        : "Analyzed Area of Interest";

    const userMsg: CopilotMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: trimmed,
      timestamp: Date.now()
    };

    set((s) => ({
      copilotMessages: [...s.copilotMessages, userMsg],
      copilotLoading: true,
      copilotError: null
    }));

    try {
      const res = await explainSpike({
        region_name: regionName,
        selected_day: state.activeSpikeDay,
        selected_hex: state.activeSpikeHex,
        user_question: trimmed
      });

      const assistantMsg: CopilotMessage = {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: res.data.explanation_markdown,
        timestamp: Date.now(),
        response: res.data
      };

      set((s) => ({
        copilotMessages: [...s.copilotMessages, assistantMsg],
        copilotLoading: false
      }));
    } catch (err: unknown) {
      set({
        copilotLoading: false,
        copilotError: err instanceof Error ? err.message : "Failed to obtain AI explanation."
      });
    }
  },

  clearCopilotMessages: () => set({ copilotMessages: [], copilotError: null })
}));
