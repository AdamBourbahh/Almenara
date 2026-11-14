// ============================================================================
// TypeScript types & interfaces - firms-harmonizer
// Mirror of backend/api/schemas.py (Pydantic v2).
// Fields marked "optional" are extensions agreed for the UI (forecast band,
// cross-guard prior, Wooster accounting). Keep them in sync with the backend.
// ============================================================================

export type ViewMode = "RAW" | "HARMONIZED";

export type ConfidenceLevel = "low" | "nominal" | "high";

export type GapReason = "NONE" | "SENSOR_OUTAGE" | "CLOUD_OCCLUSION" | "SWATH_GAP" | "MULTI_FACTOR";

export interface GeoJSONPolygon {
  type: "Polygon";
  coordinates: number[][][]; // Exterior ring [[lon, lat], ...]
}

export interface AnalyzeRequest {
  aoi: GeoJSONPolygon;
  start_year: number;
  end_year: number;
  exclude_industrial_flaring: boolean;
  enable_kalman_gap_filling: boolean;
  confidence_level: ConfidenceLevel;
}

export interface DailyCalendarCell {
  date: string; // "2022-08-14"
  year: number; // 2022
  doy: number; // 226
  raw_hotspot_count: number;
  raw_frp_mw: number;
  harmonized_fre_mj_km2: number;
  ci_95_lower: number;
  ci_95_upper: number;
  uncertainty_pct: number;
  z_score_anomaly: number;
  is_gap_filled: boolean;
  gap_reason: GapReason;
  active_sensors: string[];
  tooltip_narrative?: string;
  // 14-day operational forecast cells (forecast_series) -> golden hatch
  is_forecast?: boolean;
  // Historical cross-guard prior (climatology for this DOY), MJ/km²
  historical_cross_prior_fre?: number;
  // Wooster biomass (0.368 kg/MJ) & smoke accounting
  total_biomass_burned_kt?: number;
  pm25_emitted_kg?: number;
  total_pm25_emitted_tonnes?: number;
}

export interface VonMisesPhenologyYear {
  year: number;
  peak_doy_mu: number; // Peak day of year [1, 365.25]
  peak_date_label: string; // e.g. "Aug 19"
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
  burned_area_r2_raw: number;
  burned_area_r2_harm: number;
  phenology_shift_days_per_decade: number;
  mann_kendall_p_value: number;
  industrial_false_positives_removed: number;
  executive_verdict_en?: string;
  total_biomass_burned_kt?: number;
  total_pm25_emitted_tonnes?: number;
}

export interface H3MapSummaryHex {
  h3_index: string; // Hex string (e.g. "872830828ffffff"), never an integer (uint64 precision loss in JS)
  mean_annual_fre: number;
  trend_slope: number;
  is_industrial_site: boolean;
}

export interface AnalyzeResponse {
  query_hash: string;
  execution_time_ms: number;
  aoi_area_km2: number;
  total_h3_cells: number;
  calendar_series: DailyCalendarCell[];
  phenology_by_year: VonMisesPhenologyYear[];
  audit_metrics: ScientificAuditMetrics;
  map_hexagons: H3MapSummaryHex[];
  forecast_series?: DailyCalendarCell[];
}

export interface ChaosMonkeyRequest {
  aoi: GeoJSONPolygon;
  target_year: number;
  drop_fraction: number;
  random_seed: number;
}

export interface ChaosMonkeyResponse {
  dropped_days_count: number;
  dropped_dates: string[];
  true_harmonized_fre: number[];
  corrupted_naive_fre: number[];
  kalman_reconstructed_fre: number[];
  reconstructed_ci_lower: number[];
  reconstructed_ci_upper: number[];
  naive_rmse: number;
  kalman_rmse: number;
  seasonal_energy_recovered_pct: number;
  historical_cross_guard_fre?: number[];
}
