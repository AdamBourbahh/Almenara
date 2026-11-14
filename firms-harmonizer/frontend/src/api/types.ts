/** Frozen API contracts. Dates are ISO YYYY-MM-DD; H3 indices are hex strings. */

/** UI-only helpers (not part of the wire contract). */
export type ViewMode = "RAW" | "HARMONIZED";
export type ConfidenceLevel = "low" | "nominal" | "high";
/** Codes used by the frontend's offline generator. The API itself sends `gap_reason` as free text or null. */
export type GapReason = "NONE" | "SENSOR_OUTAGE" | "CLOUD_OCCLUSION" | "SWATH_GAP" | "MULTI_FACTOR";

export interface GeoJSONPolygon {
  type?: "Polygon";
  coordinates: Array<Array<Array<number>>>;
}

export interface RiskPredictionRequest {
  aoi: GeoJSONPolygon;
  start_year?: number;
  end_year?: number;
  as_of_date?: string;
}

export interface RiskValidation {
  samples: number;
  positives: number;
  brier_score: number | null;
  roc_auc: number | null;
  reliability: { samples: number; mean_predicted_pct: number; observed_pct: number }[];
}

export interface RiskHorizon {
  days: 1 | 7 | 14;
  wildfire_prob_pct: number | null;
  accident_prob_pct: number | null;
  combined_risk_pct: number | null;
  wildfire_validation: RiskValidation;
  accident_validation: RiskValidation;
  combined_validation: RiskValidation;
  prior_targets?: ("wildfire" | "accident" | "combined")[];
}

export interface RiskFactor {
  feature: string;
  impact_pct: number;
  direction: "raises" | "lowers";
  description: string;
}

export interface AIRiskAssessment {
  as_of_date: string;
  last_observation_date?: string | null;
  validation_start_date: string;
  wildfire_prob_24h_pct: number | null;
  wildfire_prob_7d_pct: number | null;
  industrial_accident_prob_pct: number | null;
  combined_risk_pct: number | null;
  overall_hazard_level: "LOW" | "MODERATE" | "HIGH" | "CRITICAL" | null;
  vegetation_event_threshold_mw: number;
  horizons: RiskHorizon[];
  model_metrics: RiskValidation & { model_weights: Record<string, number> };
  top_risk_factors: RiskFactor[];
  industrial_risk_factors: RiskFactor[];
  daily_probability_series: { date: string; wildfire_prob_pct: number | null; accident_prob_pct: number | null }[];
}

export interface RiskPredictionResponse {
  data_source: "real" | "synthetic";
  target: "satellite_thermal_event_proxy";
  assessment: AIRiskAssessment | null;
  unavailable_reason: string | null;
  model_time_ms: number;
  execution_time_ms: number;
}

export interface AnalyzeRequest {
  aoi: GeoJSONPolygon;
  start_year?: number;
  end_year?: number;
  exclude_industrial_flaring?: boolean;
  enable_kalman_gap_filling?: boolean;
  forecast_days?: number;
  confidence_level?: ConfidenceLevel;
}

export interface DailyCalendarCell {
  date: string;
  year: number;
  doy: number;
  raw_hotspot_count: number;
  raw_frp_mw: number;
  harmonized_fre_mj_km2: number;
  historical_cross_prior_fre: number;
  ci_95_lower: number;
  ci_95_upper: number;
  uncertainty_pct: number;
  biomass_burned_tonnes: number;
  pm25_emitted_kg: number | null;
  z_score_anomaly: number;
  is_gap_filled: boolean;
  is_forecast: boolean;
  gap_reason: string | null;
  active_sensors: Array<string>;
  tooltip_narrative: string | null;
}

export interface VonMisesPhenologyYear {
  year: number;
  peak_doy_mu: number;
  peak_date_label: string;
  concentration_kappa: number;
  season_width_days: number;
  total_annual_fre_gj: number;
}

export interface ScientificAuditMetrics {
  chow_test_f_stat_raw: number;
  chow_test_p_val_raw: number;
  chow_test_f_stat_harm: number;
  chow_test_p_val_harm: number;
  wasserstein_w1_raw: number;
  wasserstein_w1_harm: number;
  burned_area_r2_raw: number | null;
  burned_area_r2_harm: number | null;
  phenology_shift_days_per_decade: number;
  mann_kendall_p_value: number;
  industrial_false_positives_removed: number;
  total_biomass_burned_kt: number;
  total_pm25_emitted_tonnes: number | null;
  executive_verdict_en: string;
}

export interface H3MapSummaryHex {
  h3_index: string;
  mean_annual_fre: number;
  raw_pixel_count: number;
  trend_slope: number;
  is_industrial_site: boolean;
  shannon_entropy: number;
}

export interface AnalyzeResponse {
  data_source: "real" | "synthetic";
  query_hash: string;
  execution_time_ms: number;
  aoi_area_km2: number;
  total_h3_cells: number;
  calendar_series: Array<DailyCalendarCell>;
  forecast_series: Array<DailyCalendarCell> | null;
  phenology_by_year: Array<VonMisesPhenologyYear>;
  audit_metrics: ScientificAuditMetrics | null;
  map_hexagons: Array<H3MapSummaryHex>;
}

export interface ChaosMonkeyRequest {
  aoi: GeoJSONPolygon;
  target_year?: number;
  drop_fraction?: number;
  simulate_dual_blackout?: boolean;
  random_seed?: number;
}

export interface ChaosMonkeyResponse {
  data_source: "real" | "synthetic";
  dropped_days_count: number;
  dropped_dates: Array<string>;
  dates: Array<string>;
  true_harmonized_fre: Array<number>;
  corrupted_naive_fre: Array<number>;
  historical_cross_guard_fre: Array<number>;
  kalman_reconstructed_fre: Array<number>;
  reconstructed_ci_lower: Array<number>;
  reconstructed_ci_upper: Array<number>;
  naive_rmse: number;
  kalman_rmse: number;
  seasonal_energy_recovered_pct: number;
}

export interface CitationReference {
  id: string;
  source_type: "NASA_DATASET" | "PEER_REVIEWED" | "WEB_NEWS_REPORT";
  title: string;
  authors_or_agency: string;
  year: number;
  dataset_or_doi: string;
  url?: string | null;
  relevance_note: string;
}

export interface CopilotTurn {
  role: "user" | "assistant";
  content: string;
}

export interface ExplainSpikeRequest {
  region_name?: string;
  selected_day?: DailyCalendarCell | null;
  selected_hex?: H3MapSummaryHex | null;
  user_question?: string;
  aoi?: GeoJSONPolygon | null;
  confidence_level?: ConfidenceLevel;
  conversation?: CopilotTurn[];
  period_start?: string | null;
  period_end?: string | null;
}

export interface ExplainSpikeResponse {
  physical_classification: string;
  explanation_markdown: string;
  citations: Array<CitationReference>;
  web_search_used: boolean;
  search_query_executed?: string | null;
  model_used?: string;
  data_source?: "real" | "synthetic";
}

/** Pilot regions = SPECS.md §5.3 bounds (the synthetic cube places its cells inside them). */
export const PRESET_REGIONS = {
  cerrado_brazil: {
    name: "Cerrado & Pantanal, Brazil",
    center: [-56.2, -16.9],
    aoi: { type: "Polygon", coordinates: [[
      [-57.2, -17.8], [-55.2, -17.8], [-55.2, -16], [-57.2, -16], [-57.2, -17.8],
    ]] },
  },
  california_usa: {
    name: "Sierra Nevada, California",
    center: [-120.35, 39.1],
    aoi: { type: "Polygon", coordinates: [[
      [-121.2, 38], [-119.5, 38], [-119.5, 40.2], [-121.2, 40.2], [-121.2, 38],
    ]] },
  },
  iberia_med: {
    name: "Mediterranean Iberia",
    center: [-4.85, 38.5],
    aoi: { type: "Polygon", coordinates: [[
      [-6.5, 37.2], [-3.2, 37.2], [-3.2, 39.8], [-6.5, 39.8], [-6.5, 37.2],
    ]] },
  },
  niger_delta_flaring: {
    name: "Niger Delta gas flaring",
    center: [6.4, 5.2],
    aoi: { type: "Polygon", coordinates: [[
      [5.6, 4.6], [7.2, 4.6], [7.2, 5.8], [5.6, 5.8], [5.6, 4.6],
    ]] },
  },
} as const satisfies Record<string, {
  name: string;
  center: [number, number];
  aoi: GeoJSONPolygon;
}>;

// ============================================================================
// Cube Synchronization (Live NASA FIRMS -> Master Parquet/DuckDB Cube)
// ============================================================================

export type CubeSyncStatusState = "idle" | "in_progress" | "success" | "error";

export interface CubeSyncRequest {
  days?: number;
  sync_full_month?: boolean;
  regions?: string[];
}

export interface CubeSyncStatusResponse {
  status: CubeSyncStatusState;
  last_synced_utc: string | null;
  new_detections_count: number;
  date_coverage_start?: string;
  date_coverage_end?: string;
  regions_updated?: string[];
  message?: string;
  data_source?: "real" | "synthetic";
  error?: string | null;
}

