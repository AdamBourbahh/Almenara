import { create } from "zustand";
import type { AnalyzeRequest, AnalyzeResponse, ChaosMonkeyResponse, DailyCalendarCell, GeoJSONPolygon, H3MapSummaryHex, ViewMode, ExplainSpikeResponse } from "../api/types";
import { analyzeAoi, fetchMapPeriod, explainSpike, runChaosMonkey } from "../api/client";

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
}

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
  setSelectedMonth: (month: number | null) => void;
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

  openCopilot: (spike?: { day?: DailyCalendarCell | null; hex?: H3MapSummaryHex | null }) => void;
  closeCopilot: () => void;
  toggleCopilot: () => void;
  askCopilot: (question: string) => Promise<void>;
  clearCopilotMessages: () => void;

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
let mapController: AbortController | null = null;
let mapSeq = 0;
let mapTimer: ReturnType<typeof setTimeout> | undefined;
const annualMapCache = new Map<string, H3MapSummaryHex[]>();
let chaosController: AbortController | null = null;
let chaosSeq = 0;
let copilotController: AbortController | null = null;
let copilotSeq = 0;

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

  setViewMode: (mode) => set({ viewMode: mode }),

  toggleViewMode: () => set((s) => ({ viewMode: s.viewMode === "RAW" ? "HARMONIZED" : "RAW" })),

  setSplitCurtainPct: (pct) => set({ splitCurtainPct: Math.min(100, Math.max(0, Math.round(pct))) }),

  setSelectedYear: (year) => {
    const { startYear, endYear, selectedYear, minDate, maxDate } = get();
    const lo = Math.max(startYear, Number(minDate?.slice(0, 4) ?? startYear));
    const hi = Math.min(endYear, Number(maxDate?.slice(0, 4) ?? endYear));
    const clamped = Math.min(hi, Math.max(lo, Math.round(year)));
    if (!Number.isFinite(clamped)) return;
    if (clamped === selectedYear) return;
    const previous = get().selectedDate;
    const candidate = isoDate(clamped, get().selectedMonth ?? 1, get().selectedDay ?? 1);
    const bounded = candidate < (minDate ?? candidate) ? minDate! : candidate > (maxDate ?? candidate) ? maxDate! : candidate;
    const selection = previous ? dateSelection(bounded) : {};
    set({ ...selection, hoveredDate: null, hoveredCell: null, hoveredDay: null, selectedYear: clamped, chaosData: null });
    scheduleMapLoad();
  },

  setSelectedMonth: (month) => {
    if (month !== null && (!Number.isInteger(month) || month < 1 || month > 12)) return;
    if (month === get().selectedMonth && !get().selectedDate) return;
    set({ selectedMonth: month, selectedDay: null, selectedDoy: null, selectedDate: null,
      isDatePinned: false, hoveredCell: null, hoveredDate: null, hoveredDay: null });
    scheduleMapLoad();
  },
  setSelectedDate: (iso, pin = true) => {
    if (iso === null) {
      if (!get().selectedDate) return;
      set({ selectedDate: null, selectedDay: null, selectedDoy: null, isDatePinned: false, hoveredDay: null, hoveredCell: null, hoveredDate: null });
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

  executeAnalysis: async () => {
    mapController?.abort();
    mapSeq++;
    clearTimeout(mapTimer);
    annualMapCache.clear();
    set({ mapHexagons: [], mapYear: null, mapPeriod: null, mapLoading: true, mapError: null, hoveredDay: null, hoveredDate: null, hoveredCell: null, isDatePinned: false, selectedDate: null, selectedMonth: null, selectedDay: null, selectedDoy: null });
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
  openCopilot: (spike) => {
    if (spike?.day || spike?.hex) {
      get().clearCopilotMessages();
      set({ isCopilotOpen: true, activeSpikeDay: spike.day ?? null, activeSpikeHex: spike.hex ?? null });
      void get().askCopilot(spike.day
        ? `Explain the selected satellite data on ${spike.day.date}. What can we verify?`
        : "Explain the selected H3 cell for the selected period. What can we verify?");
    } else {
      set({ isCopilotOpen: true, copilotError: null });
    }
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
        selected_day: state.activeSpikeDay ?? (state.selectedDate ? state.dateIndex.get(state.selectedDate) ?? null : null),
        selected_hex: state.activeSpikeHex,
        aoi: state.currentAoi,
        period_start: state.selectedDate ?? isoDate(state.selectedYear, state.selectedMonth ?? 1, 1),
        period_end: state.selectedDate ?? isoDate(state.selectedYear, state.selectedMonth ?? 12, 31),
        conversation: state.copilotMessages.slice(-10).map(({ role, content }) => ({ role, content: content.slice(0, 6000) })),
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
    set({ copilotMessages: [], copilotError: null, copilotLoading: false, activeSpikeDay: null, activeSpikeHex: null });
  }

}));
