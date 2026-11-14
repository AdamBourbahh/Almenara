import { create } from "zustand";
import type { AnalyzeRequest, AnalyzeResponse, ChaosMonkeyResponse } from "../api/types";
import { analyzeAoi, runChaosMonkey } from "../api/client";

/** UI-only regime selector; not part of the frozen API contract. */
export type ViewMode = "RAW" | "HARMONIZED";

// Regiones preset oficiales para demostración rápida ante el jurado
export const PRESET_REGIONS = {
  AMAZONAS: {
    name: "Amazonas / Pantanal (Brazil)",
    coordinates: [[
      [-55.5, -12.5],
      [-53.0, -12.5],
      [-53.0, -15.0],
      [-55.5, -15.0],
      [-55.5, -12.5]
    ]]
  },
  CALIFORNIA: {
    name: "California / Western US",
    coordinates: [[
      [-122.4, 37.7],
      [-120.0, 37.7],
      [-120.0, 39.5],
      [-122.4, 39.5],
      [-122.4, 37.7]
    ]]
  },
  IBERIA: {
    name: "Mediterranean Basin / Iberia",
    coordinates: [[
      [-6.0, 37.0],
      [-3.0, 37.0],
      [-3.0, 39.5],
      [-6.0, 39.5],
      [-6.0, 37.0]
    ]]
  },
  CHILECITO: {
    name: "Chilecito, La Rioja (Argentina - Julio 2026)",
    coordinates: [[
      [-67.6, -29.3],
      [-67.2, -29.3],
      [-67.2, -29.7],
      [-67.6, -29.7],
      [-67.6, -29.3]
    ]]
  }
};

interface AnalysisState {
  // Estado de parámetros y selección
  viewMode: ViewMode;
  selectedPreset: string;
  currentAoi: { type: "Polygon"; coordinates: number[][][] };
  startYear: number;
  endYear: number;
  excludeIndustrial: boolean;
  enableKalman: boolean;
  highlightIndustrialOnMap: boolean;
  
  // Controles interactivos de UI
  splitCurtainPct: number; // 0 a 100 para la cortina 2012 Time-Machine
  selectedYear: number;
  hoveredDay: string | null;
  
  // Datos y resultados de API
  loading: boolean;
  error: string | null;
  analysisData: AnalyzeResponse | null;
  
  // Chaos Monkey
  chaosLoading: boolean;
  chaosData: ChaosMonkeyResponse | null;

  // Acciones
  setViewMode: (mode: ViewMode) => void;
  setSplitCurtainPct: (pct: number) => void;
  setSelectedYear: (year: number) => void;
  setHoveredDay: (day: string | null) => void;
  setExcludeIndustrial: (exclude: boolean) => void;
  setEnableKalman: (enable: boolean) => void;
  setHighlightIndustrialOnMap: (highlight: boolean) => void;
  loadPresetRegion: (presetKey: keyof typeof PRESET_REGIONS) => Promise<void>;
  setCustomAoi: (coordinates: number[][][]) => Promise<void>;
  executeAnalysis: () => Promise<void>;
  triggerChaosMonkey: () => Promise<void>;
  resetChaosMonkey: () => void;
}

export const useAnalysisStore = create<AnalysisState>((set, get) => ({
  viewMode: "HARMONIZED",
  selectedPreset: "CHILECITO",
  currentAoi: {
    type: "Polygon",
    coordinates: PRESET_REGIONS.CHILECITO.coordinates,
  },
  startYear: 2001,
  endYear: 2026,
  excludeIndustrial: true,
  enableKalman: true,
  highlightIndustrialOnMap: false,
  
  splitCurtainPct: 50,
  selectedYear: 2022, // Año crítico por defecto (Safe Mode Aqua & Outages)
  hoveredDay: null,
  
  loading: false,
  error: null,
  analysisData: null,
  
  chaosLoading: false,
  chaosData: null,

  setViewMode: (mode) => set({ viewMode: mode }),
  
  setSplitCurtainPct: (pct) => set({ splitCurtainPct: pct }),
  
  setSelectedYear: (year) => set({ selectedYear: year }),
  
  setHoveredDay: (day) => set({ hoveredDay: day }),
  
  setExcludeIndustrial: (exclude) => {
    set({ excludeIndustrial: exclude });
    get().executeAnalysis();
  },
  
  setEnableKalman: (enable) => {
    set({ enableKalman: enable });
    get().executeAnalysis();
  },
  
  setHighlightIndustrialOnMap: (highlight) => set({ highlightIndustrialOnMap: highlight }),

  loadPresetRegion: async (presetKey) => {
    const preset = PRESET_REGIONS[presetKey];
    if (!preset) return;
    
    set({
      selectedPreset: presetKey,
      currentAoi: { type: "Polygon", coordinates: preset.coordinates },
      chaosData: null
    });
    
    await get().executeAnalysis();
  },

  setCustomAoi: async (coordinates) => {
    set({
      selectedPreset: "CUSTOM",
      currentAoi: { type: "Polygon", coordinates },
      chaosData: null
    });
    
    await get().executeAnalysis();
  },

  executeAnalysis: async () => {
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
      const response = await analyzeAoi(requestPayload);
      set({ analysisData: response, loading: false });
    } catch (err: any) {
      set({ error: err.message || "Error al ejecutar el análisis espacial", loading: false });
    }
  },

  triggerChaosMonkey: async () => {
    const state = get();
    set({ chaosLoading: true });

    try {
      const response = await runChaosMonkey({
        aoi: state.currentAoi,
        target_year: state.selectedYear,
        drop_fraction: 0.25,
        random_seed: 42
      });
      set({ chaosData: response, chaosLoading: false });
    } catch (err: any) {
      console.error("Error ejecutando Chaos Monkey:", err);
      set({ chaosLoading: false });
    }
  },

  resetChaosMonkey: () => set({ chaosData: null })
}));
