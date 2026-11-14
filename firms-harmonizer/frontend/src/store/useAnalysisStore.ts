import { create } from "zustand";
import { cellToLatLng } from "h3-js";
import type {
  AnalyzeRequest,
  AnalyzeResponse,
  AIRiskAssessment,
  ChaosMonkeyResponse,
  CubeSyncStatusState,
  DailyCalendarCell,
  GeoJSONPolygon,
  H3MapSummaryHex,
  RiskPredictionRequest,
  RiskPredictionResponse,
  ViewMode,
  ExplainSpikeResponse
} from "../api/types";
import {
  analyzeAoi,
  fetchMapPeriod,
  fetchRiskPrediction,
  explainSpike,
  runChaosMonkey,
  triggerCubeSync,
  fetchCubeSyncStatus
} from "../api/client";

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

export const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function isoDate(year: number, month: number, day: number): string {
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return `${year}-${String(month).padStart(2, "0")}-${String(Math.min(day, last)).padStart(2, "0")}`;
}
export function dateSelection(iso: string) {
  const date = new Date(`${iso}T00:00:00Z`);
  return { selectedDate: iso, selectedYear: date.getUTCFullYear(), selectedMonth: date.getUTCMonth() + 1,
    selectedDay: date.getUTCDate(), selectedDoy: Math.round((date.getTime() - Date.UTC(date.getUTCFullYear(), 0, 1)) / 86400000) + 1 };
}
export function selectedMapPeriod(state: { selectedYear: number; selectedMonth: number | null; selectedDate: string | null }): string {
  return state.selectedDate ?? (state.selectedMonth === null ? String(state.selectedYear)
    : `${state.selectedYear}-${String(state.selectedMonth).padStart(2, "0")}`);
}
function chronologyIndexes(data: AnalyzeResponse) {
  const dateIndex = new Map<string, DailyCalendarCell>();
  const yearDoyIndex = new Map<string, DailyCalendarCell>();
  for (const cell of data.calendar_series) {
    dateIndex.set(cell.date, cell);
    yearDoyIndex.set(`${cell.year}-${cell.doy}`, cell);
  }
  const dates = [...dateIndex.keys()].sort();
  for (const cell of data.forecast_series ?? []) {
    if (!dateIndex.has(cell.date)) dateIndex.set(cell.date, cell);
    if (!yearDoyIndex.has(`${cell.year}-${cell.doy}`)) yearDoyIndex.set(`${cell.year}-${cell.doy}`, cell);
  }
  return { dateIndex, yearDoyIndex, minDate: dates[0] ?? null, maxDate: dates[dates.length - 1] ?? null };
}

const polygonFromPreset = (key: PresetKey): GeoJSONPolygon => ({ type: "Polygon", coordinates: PRESET_REGIONS[key].coordinates });

const isAbortError = (error: unknown) => error instanceof DOMException && error.name === "AbortError";

// ============================================================================
// State
// ============================================================================

export interface CopilotMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  response?: ExplainSpikeResponse;
  context?: CopilotSelection;
}

export interface CopilotSelection {
  label: string;
  aoi: GeoJSONPolygon;
  start: string;
  end: string;
  day: DailyCalendarCell | null;
  hex: H3MapSummaryHex | null;
  excludeIndustrial: boolean;
  enableKalman: boolean;
}

function areaLocationLabel(aoi: GeoJSONPolygon): string {
  const ring = aoi.coordinates[0];
  const lng = (Math.min(...ring.map((p) => p[0])) + Math.max(...ring.map((p) => p[0]))) / 2;
  const lat = (Math.min(...ring.map((p) => p[1])) + Math.max(...ring.map((p) => p[1]))) / 2;
  return `Selected area at ${lat.toFixed(3)}°, ${lng.toFixed(3)}°`;
}

export function liveCopilotSelection(state: AnalysisState): CopilotSelection {
  return {
    label: state.selectedPreset === "CUSTOM" ? areaLocationLabel(state.currentAoi) : PRESET_REGIONS[state.selectedPreset].label,
    aoi: state.currentAoi,
    start: state.selectedDate ?? isoDate(state.selectedYear, state.selectedMonth ?? 1, 1),
    end: state.selectedDate ?? isoDate(state.selectedYear, state.selectedMonth ?? 12, 31),
    day: state.selectedDate ? state.dateIndex.get(state.selectedDate) ?? null : null,
    hex: null,
    excludeIndustrial: state.excludeIndustrial,
    enableKalman: state.enableKalman
  };
}

export interface SelectionPoint { x: number; y: number }

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
  selectedMonth: number | null;
  selectedDay: number | null;
  selectedDoy: number | null;
  selectedDate: string | null;
  hoveredDate: string | null;
  hoveredCell: DailyCalendarCell | null;
  isDatePinned: boolean;
  dateIndex: Map<string, DailyCalendarCell>;
  yearDoyIndex: Map<string, DailyCalendarCell>;
  minDate: string | null;
  maxDate: string | null;
  setSelectedMonth: (month: number | null, pin?: boolean) => void;
  setSelectedDate: (date: string | null, pin?: boolean) => void;
  setHoveredCell: (cell: DailyCalendarCell | null) => void;
  stepChronology: (unit: "day" | "month" | "year", delta: -1 | 1) => void;

  // API data
  loading: boolean;
  error: string | null;
  analysisData: AnalyzeResponse | null;
  mapHexagons: H3MapSummaryHex[];
  mapYear: number | null;
  mapPeriod: string | null;
  mapLoading: boolean;
  mapError: string | null;
  loadMapYear: () => Promise<void>;
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
  copilotContext: CopilotSelection | null;
  copilotContextKey: string | null;
  copilotContextStart: number;
  attachCopilotContext: (selection?: { day?: DailyCalendarCell | null; hex?: H3MapSummaryHex | null }) => void;
  removeCopilotContext: () => void;

  openCopilot: (spike?: { day?: DailyCalendarCell | null; hex?: H3MapSummaryHex | null }) => void;
  closeCopilot: () => void;
  toggleCopilot: () => void;
  askCopilot: (question: string) => Promise<void>;
  clearCopilotMessages: () => void;

  // Actions
  setViewMode: (mode: ViewMode) => void;
  toggleViewMode: () => void;
  setSplitCurtainPct: (pct: number) => void;
  setSelectedYear: (year: number, pin?: boolean) => void;
  setHoveredDay: (day: HoveredDay | null) => void;
  setExcludeIndustrial: (exclude: boolean) => Promise<void>;
  setEnableKalman: (enable: boolean) => Promise<void>;
  setHighlightIndustrialOnMap: (highlight: boolean) => void;
  setDrawingAoi: (drawing: boolean) => void;
  loadPresetRegion: (presetKey: PresetKey, point?: SelectionPoint) => Promise<void>;
  setCustomAoi: (coordinates: number[][][], point?: SelectionPoint) => Promise<void>;
  setCustomBbox: (west: number, south: number, east: number, north: number, point?: SelectionPoint) => Promise<void>;
  executeAnalysis: (preserveSelection?: boolean) => Promise<void>;
  triggerChaosMonkey: () => Promise<void>;
  resetChaosMonkey: () => void;

  // Cube Live Sync (NASA FIRMS -> Master Cube)
  syncStatus: CubeSyncStatusState;
  lastSyncedUtc: string | null;
  coverageDateEnd: string | null;
  syncSource: "real" | "synthetic" | null;
  syncError: string | null;
  fetchSyncStatus: () => Promise<void>;
  triggerSync: () => Promise<void>;

  // Classical AI Risk Prediction
  riskResponse: RiskPredictionResponse | null;
  riskAssessment: AIRiskAssessment | null;
  isRiskLoading: boolean;
  riskError: string | null;
  fetchRiskPredictionForAoi: (asOfDate?: string) => Promise<void>;
  clearRiskPrediction: () => void;
  aoiPromptPopup: (SelectionPoint & { aoiLabel: string }) | null;
  dismissAoiPrompt: () => void;
}

// Request bookkeeping lives outside the state: it never drives rendering.
let analysisController: AbortController | null = null;
let analysisSeq = 0;
let syncStatusSeq = 0;
let manualSyncPending = false;
let mapController: AbortController | null = null;
let mapSeq = 0;
let mapTimer: ReturnType<typeof setTimeout> | undefined;
const annualMapCache = new Map<string, H3MapSummaryHex[]>();
let chaosController: AbortController | null = null;
let chaosSeq = 0;
let copilotController: AbortController | null = null;
let copilotSeq = 0;
let riskController: AbortController | null = null;
let riskSeq = 0;
let riskRequestKey: string | null = null;

function scheduleMapLoad() {
  mapController?.abort();
  mapSeq++;
  clearTimeout(mapTimer);
  useAnalysisStore.setState({ mapHexagons: [], mapYear: null, mapPeriod: null, mapLoading: true, mapError: null });
  mapTimer = setTimeout(() => { void useAnalysisStore.getState().loadMapYear(); }, 120);
}

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
  selectedYear: 2022, // Critical year by default (VIIRS SNPP outage, Jul-Aug 2022)
  hoveredDay: null,
  selectedMonth: null, selectedDay: null, selectedDoy: null, selectedDate: null,
  hoveredDate: null, hoveredCell: null, isDatePinned: false,
  dateIndex: new Map(), yearDoyIndex: new Map(), minDate: null, maxDate: null,

  loading: false,
  error: null,
  analysisData: null,
  mapHexagons: [],
  mapYear: null,
  mapPeriod: null,
  mapLoading: false,
  mapError: null,
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
  copilotContext: null,
  copilotContextKey: null,
  copilotContextStart: 0,

  // Cube Live Sync
  syncStatus: "idle",
  lastSyncedUtc: null,
  coverageDateEnd: null,
  syncSource: null,
  syncError: null,

  // Classical AI Risk Prediction
  riskResponse: null,
  riskAssessment: null,
  isRiskLoading: false,
  riskError: null,
  aoiPromptPopup: null,
  dismissAoiPrompt: () => set({ aoiPromptPopup: null }),

  setViewMode: (mode) => set({ viewMode: mode }),

  toggleViewMode: () => set((s) => ({ viewMode: s.viewMode === "RAW" ? "HARMONIZED" : "RAW" })),

  setSplitCurtainPct: (pct) => set({ splitCurtainPct: Math.min(100, Math.max(0, Math.round(pct))) }),

  setSelectedYear: (year, pin = true) => {
    const { startYear, endYear, selectedYear, minDate, maxDate } = get();
    const lo = Math.max(startYear, Number(minDate?.slice(0, 4) ?? startYear));
    const hi = Math.min(endYear, Number(maxDate?.slice(0, 4) ?? endYear));
    const clamped = Math.min(hi, Math.max(lo, Math.round(year)));
    if (!Number.isFinite(clamped)) return;
    if (clamped === selectedYear) { if (pin) get().attachCopilotContext(); return; }
    const previous = get().selectedDate;
    const candidate = isoDate(clamped, get().selectedMonth ?? 1, get().selectedDay ?? 1);
    const bounded = candidate < (minDate ?? candidate) ? minDate! : candidate > (maxDate ?? candidate) ? maxDate! : candidate;
    const selection = previous ? dateSelection(bounded) : {};
    set({ ...selection, hoveredDate: null, hoveredCell: null, hoveredDay: null, selectedYear: clamped, chaosData: null });
    if (pin) get().attachCopilotContext();
    scheduleMapLoad();
  },

  setSelectedMonth: (month, pin = true) => {
    if (month !== null && (!Number.isInteger(month) || month < 1 || month > 12)) return;
    if (month === get().selectedMonth && !get().selectedDate) { if (pin) get().attachCopilotContext(); return; }
    set({ selectedMonth: month, selectedDay: null, selectedDoy: null, selectedDate: null,
      isDatePinned: false, hoveredCell: null, hoveredDate: null, hoveredDay: null });
    if (pin) get().attachCopilotContext();
    scheduleMapLoad();
  },
  setSelectedDate: (iso, pin = true) => {
    if (iso === null) {
      if (!get().selectedDate) return;
      set({ selectedDate: null, selectedDay: null, selectedDoy: null, isDatePinned: false, hoveredDay: null, hoveredCell: null, hoveredDate: null });
      if (pin) get().attachCopilotContext();
      scheduleMapLoad();
      return;
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return;
    const parsed = new Date(`${iso}T00:00:00Z`);
    if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== iso) return;
    const { minDate, maxDate, startYear, endYear } = get();
    const bounded = [iso, minDate ?? `${startYear}-01-01`].sort()[1];
    const date = [bounded, maxDate ?? `${endYear}-12-31`].sort()[0];
    const changed = get().selectedDate !== date;
    set({ ...dateSelection(date), isDatePinned: pin, hoveredDay: null, hoveredCell: null, hoveredDate: null, chaosData: null });
    if (pin) get().attachCopilotContext();
    if (changed) scheduleMapLoad();
  },
  stepChronology: (unit, delta) => {
    const state = get();
    const base = state.selectedDate ?? state.hoveredDate ?? isoDate(state.selectedYear, state.selectedMonth ?? 1, 1);
    const date = new Date(`${base}T00:00:00Z`);
    let next: string;
    if (unit === "day") {
      date.setUTCDate(date.getUTCDate() + delta);
      next = date.toISOString().slice(0, 10);
    } else {
      const first = new Date(Date.UTC(date.getUTCFullYear() + (unit === "year" ? delta : 0), date.getUTCMonth() + (unit === "month" ? delta : 0), 1));
      next = isoDate(first.getUTCFullYear(), first.getUTCMonth() + 1, date.getUTCDate());
    }
    get().setSelectedDate(next, true);
  },
  setHoveredCell: (cell) => {
    if (get().isDatePinned || get().hoveredCell === cell) return;
    set({ hoveredCell: cell, hoveredDate: cell?.date ?? null });
  },
  setHoveredDay: (day) => {
    if (get().isDatePinned) return;
    const cell = day ? get().yearDoyIndex.get(`${day.year}-${day.doy}`) ?? null : null;
    set({ hoveredDay: day, hoveredCell: cell, hoveredDate: cell?.date ?? null });
  },

  setExcludeIndustrial: async (exclude) => {
    if (get().excludeIndustrial === exclude) return;
    set({ excludeIndustrial: exclude });
    if (get().copilotContext) get().attachCopilotContext();
    await get().executeAnalysis();
  },

  setEnableKalman: async (enable) => {
    if (get().enableKalman === enable) return;
    set({ enableKalman: enable });
    if (get().copilotContext) get().attachCopilotContext();
    await get().executeAnalysis();
  },

  setHighlightIndustrialOnMap: (highlight) => set({ highlightIndustrialOnMap: highlight }),

  setDrawingAoi: (drawing) => set(drawing ? { isDrawingAoi: true, aoiPromptPopup: null } : { isDrawingAoi: false }),

  loadPresetRegion: async (presetKey, point) => {
    if (!(presetKey in PRESET_REGIONS)) return;
    set({ selectedPreset: presetKey, currentAoi: polygonFromPreset(presetKey), isDrawingAoi: false, chaosData: null,
      aoiPromptPopup: point ? { ...point, aoiLabel: PRESET_REGIONS[presetKey].label } : null });
    get().attachCopilotContext({ day: null, hex: null });
    await get().executeAnalysis();
  },

  setCustomAoi: async (coordinates, point) => {
    const ring = coordinates[0];
    if (!ring || ring.length < 4) {
      set({ error: "Custom AOI must be a closed polygon with at least 3 vertices." });
      return;
    }
    set({ selectedPreset: "CUSTOM", currentAoi: { type: "Polygon", coordinates }, isDrawingAoi: false, chaosData: null,
      aoiPromptPopup: point ? { ...point, aoiLabel: "Custom area" } : null });
    get().attachCopilotContext({ day: null, hex: null });
    await get().executeAnalysis();
  },

  setCustomBbox: async (west, south, east, north, point) => {
    const w = Math.max(-180, Math.min(west, east));
    const e = Math.min(180, Math.max(west, east));
    const s = Math.max(-85, Math.min(south, north));
    const n = Math.min(85, Math.max(south, north));
    if (e - w < MIN_BBOX_SIDE_DEG || n - s < MIN_BBOX_SIDE_DEG) {
      set({ isDrawingAoi: false });
      return;
    }
    // Counter-clockwise exterior ring (RFC 7946), closed.
    await get().setCustomAoi([[[w, s], [e, s], [e, n], [w, n], [w, s]]], point);
  },

  loadMapYear: async () => {
    clearTimeout(mapTimer);
    const state = get();
    if (state.loading || !state.analysisData) return;
    mapController?.abort();
    const controller = new AbortController();
    mapController = controller;
    const seq = ++mapSeq;
    const year = state.selectedYear;
    const period = selectedMapPeriod(state);
    const request: AnalyzeRequest = {
      aoi: state.currentAoi, start_year: year, end_year: year,
      exclude_industrial_flaring: state.excludeIndustrial,
      enable_kalman_gap_filling: state.enableKalman, confidence_level: "nominal"
    };
    const key = JSON.stringify({ ...request, period });
    const cached = annualMapCache.get(key);
    if (cached) {
      set({ mapHexagons: cached, mapYear: year, mapPeriod: period, mapLoading: false, mapError: null });
      return;
    }
    set({ mapLoading: true, mapError: null });
    try {
      const start = period.length === 10 ? period : `${period}-01`;
      const end = period.length === 10 ? period : isoDate(year, state.selectedMonth!, 31);
      const { data } = period.length === 4 ? await analyzeAoi(request, controller.signal)
        : await fetchMapPeriod(request, start, end, controller.signal);
      if (seq !== mapSeq) return;
      const hexagons = data.map_hexagons ?? [];
      if (annualMapCache.size >= 32) annualMapCache.delete(annualMapCache.keys().next().value!);
      annualMapCache.set(key, hexagons);
      set({ mapHexagons: hexagons, mapYear: year, mapPeriod: period, mapLoading: false,
        isSynthetic: data.data_source === "synthetic" });
    } catch (err: unknown) {
      if (seq !== mapSeq || isAbortError(err)) return;
      set({ mapHexagons: [], mapYear: null, mapPeriod: null, mapLoading: false,
        mapError: err instanceof Error ? err.message : "Map period unavailable" });
    }
  },

  executeAnalysis: async (preserveSelection = true) => {
    get().clearRiskPrediction();
    mapController?.abort();
    mapSeq++;
    clearTimeout(mapTimer);
    annualMapCache.clear();
    set({
      mapHexagons: [], mapYear: null, mapPeriod: null, mapLoading: true, mapError: null,
      hoveredDay: null, hoveredDate: null, hoveredCell: null,
      ...(preserveSelection ? {} : { isDatePinned: false, selectedDate: null, selectedMonth: null, selectedDay: null, selectedDoy: null })
    });
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
      set({ ...chronologyIndexes(data), analysisData: data, calendarIndex: buildCalendarIndex(data), isSynthetic: data.data_source === "synthetic", loading: false, hoveredDay: null });
      await get().loadMapYear();
    } catch (err: unknown) {
      if (seq !== analysisSeq || isAbortError(err)) return;
      set({ error: err instanceof Error ? err.message : "Spatial analysis failed", loading: false, mapLoading: false });
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
  } ,
  attachCopilotContext: (selection) => {
    const state = get();
    const context = structuredClone(liveCopilotSelection(state));
    const sameArea = JSON.stringify(state.copilotContext?.aoi) === JSON.stringify(context.aoi);
    context.hex = selection?.hex !== undefined ? selection.hex : sameArea ? state.copilotContext?.hex ?? null : null;
    context.day = selection?.day !== undefined ? selection.day : state.loading ? null : context.day;
    if (selection?.day) context.start = context.end = selection.day.date;
    if (context.hex) {
      const [lat, lng] = cellToLatLng(context.hex.h3_index);
      context.label = `Map cell at ${lat.toFixed(3)}°, ${lng.toFixed(3)}°`;
    }
    set({ copilotContext: context, activeSpikeDay: context.day, activeSpikeHex: context.hex,
      copilotContextKey: null, copilotError: null });
  },
  removeCopilotContext: () => set({ copilotContext: null, activeSpikeDay: null, activeSpikeHex: null,
    copilotContextKey: null, copilotContextStart: get().copilotMessages.length }),
  openCopilot: (selection) => {
    if (selection?.day || selection?.hex) get().attachCopilotContext(selection);
    set({ isCopilotOpen: true, copilotError: null });
  },
  closeCopilot: () => set({ isCopilotOpen: false }),
  toggleCopilot: () => set((s) => ({ isCopilotOpen: !s.isCopilotOpen })),

  askCopilot: async (question: string) => {
    const trimmed = question.trim();
    if (!trimmed || get().copilotLoading) return;
    const state = get();
    const sequence = ++copilotSeq;
    copilotController?.abort();
    copilotController = new AbortController();
    const signal = copilotController.signal;
    const context = state.copilotContext ? structuredClone(state.copilotContext) : null;
    const key = JSON.stringify(context);
    const contextChanged = key !== state.copilotContextKey;
    const historyStart = contextChanged ? state.copilotMessages.length : state.copilotContextStart;

    const userMsg: CopilotMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: trimmed,
      timestamp: Date.now(),
      context: context ?? undefined
    };

    set((s) => ({
      copilotMessages: [...s.copilotMessages, userMsg],
      copilotLoading: true,
      copilotError: null,
      copilotContextKey: key,
      copilotContextStart: historyStart
    }));

    try {
      const res = await explainSpike({
        region_name: context?.label ?? "No attached location",
        selected_day: context?.day ?? null,
        selected_hex: context?.hex ?? null,
        aoi: context?.aoi ?? null,
        period_start: context?.start ?? null,
        period_end: context?.end ?? null,
        prefer_map_context: contextChanged,
        exclude_industrial_flaring: context?.excludeIndustrial ?? state.excludeIndustrial,
        enable_kalman_gap_filling: context?.enableKalman ?? state.enableKalman,
        previous_context: contextChanged ? null : [...state.copilotMessages].reverse().find((m) => m.role === "assistant")?.response?.map_context ?? null,
        conversation: state.copilotMessages.slice(historyStart).slice(-10).map(({ role, content }) => ({ role, content: content.slice(0, 6000) })),
        user_question: trimmed
      }, signal);
      if (sequence !== copilotSeq) return;

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
      if (sequence !== copilotSeq || isAbortError(err)) return;
      set({
        copilotLoading: false,
        copilotError: err instanceof Error ? err.message : "Failed to obtain AI explanation."
      });
    }
  },

  clearCopilotMessages: () => {
    copilotController?.abort();
    copilotSeq++;
    set({ copilotMessages: [], copilotError: null, copilotLoading: false,
      activeSpikeDay: null, activeSpikeHex: null, copilotContext: null, copilotContextKey: null, copilotContextStart: 0 });
  },

  fetchSyncStatus: async () => {
    if (manualSyncPending) return;
    const seq = ++syncStatusSeq;
    try {
      const res = await fetchCubeSyncStatus();
      if (seq !== syncStatusSeq) return;
      const state = get();
      const updated = res.status === "success" && res.data_source === "real"
        && Boolean(res.last_synced_utc && res.last_synced_utc !== state.lastSyncedUtc);
      set({
        syncStatus: res.status,
        lastSyncedUtc: res.last_synced_utc,
        coverageDateEnd: res.date_coverage_end ?? null,
        syncSource: res.data_source ?? null,
        syncError: res.error ?? null
      });
      if (updated && state.analysisData && res.new_detections_count > 0) await get().executeAnalysis(true);
    } catch {
      // Status requests are best effort. Keep the last confirmed coverage while offline.
    }
  },

  triggerSync: async () => {
    const state = get();
    if (manualSyncPending || state.syncStatus === "in_progress" || state.syncSource === "synthetic") return;
    manualSyncPending = true;
    syncStatusSeq++;
    set({ syncStatus: "in_progress", syncError: null });

    try {
      const res = await triggerCubeSync();
      set({
        syncStatus: res.status,
        lastSyncedUtc: res.last_synced_utc,
        coverageDateEnd: res.date_coverage_end ?? null,
        syncSource: res.data_source ?? null,
        syncError: res.error ?? null
      });
      if (res.status === "success" && res.data_source === "real" && res.new_detections_count > 0) {
        await get().executeAnalysis(true);
      }
    } catch (err: unknown) {
      set({
        syncStatus: "error",
        syncError: err instanceof Error ? err.message : "FIRMS update failed."
      });
    } finally {
      manualSyncPending = false;
    }
  },

  clearRiskPrediction: () => {
    riskController?.abort();
    riskSeq++;
    riskRequestKey = null;
    set({ riskResponse: null, riskAssessment: null, isRiskLoading: false, riskError: null });
  },

  fetchRiskPredictionForAoi: async (asOfDate?: string) => {
    const state = get();
    const selected = asOfDate ?? state.selectedDate;
    const targetDate = selected && selected >= isoDate(state.startYear, 1, 1) &&
      selected <= isoDate(state.endYear, 12, 31) ? selected : undefined;
    const request: RiskPredictionRequest = {
      aoi: state.currentAoi,
      start_year: state.startYear,
      end_year: state.endYear,
      ...(targetDate ? { as_of_date: targetDate } : {})
    };
    const key = JSON.stringify(request);
    if (key === riskRequestKey && (state.isRiskLoading || state.riskResponse)) return;
    riskController?.abort();
    const controller = new AbortController();
    riskController = controller;
    const seq = ++riskSeq;
    riskRequestKey = key;
    set({ isRiskLoading: true, riskError: null, riskResponse: null, riskAssessment: null });

    try {
      const response = await fetchRiskPrediction(request, controller.signal);
      if (seq !== riskSeq) return;
      set({
        riskResponse: response,
        riskAssessment: response.assessment ?? null,
        isRiskLoading: false,
        riskError: null
      });
    } catch (err: unknown) {
      if (seq !== riskSeq || isAbortError(err)) return;
      set({
        riskResponse: null,
        riskAssessment: null,
        isRiskLoading: false,
        riskError: err instanceof Error ? err.message : "Failed to compute fire risk prediction"
      });
    } finally {
      if (riskController === controller) riskController = null;
    }
  }

}));
