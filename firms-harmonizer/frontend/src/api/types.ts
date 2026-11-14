/** Frozen API contracts. Dates are ISO YYYY-MM-DD; H3 indices are hex strings. */

export interface GeoJSONPolygon {
  type?: "Polygon";
  coordinates: Array<Array<Array<number>>>;
}

export interface AnalyzeRequest {
  aoi: GeoJSONPolygon;
  start_year?: number;
  end_year?: number;
  exclude_industrial_flaring?: boolean;
  enable_kalman_gap_filling?: boolean;
  forecast_days?: number;
  confidence_level?: "low" | "nominal" | "high";
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
  h3_index?: string;
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

export const PRESET_REGIONS = {
  cerrado_brazil: {
    name: "Brazilian Cerrado",
    center: [-48, -16],
    aoi: { type: "Polygon", coordinates: [[
      [-49, -17], [-47, -17], [-47, -15], [-49, -15], [-49, -17],
    ]] },
  },
  california_usa: {
    name: "California, USA",
    center: [-121, 39],
    aoi: { type: "Polygon", coordinates: [[
      [-122, 38], [-120, 38], [-120, 40], [-122, 40], [-122, 38],
    ]] },
  },
  iberia_med: {
    name: "Mediterranean Iberia",
    center: [-5, 39],
    aoi: { type: "Polygon", coordinates: [[
      [-6, 38], [-4, 38], [-4, 40], [-6, 40], [-6, 38],
    ]] },
  },
  niger_delta_flaring: {
    name: "Niger Delta flaring",
    center: [6, 5],
    aoi: { type: "Polygon", coordinates: [[
      [5, 4], [7, 4], [7, 6], [5, 6], [5, 4],
    ]] },
  },
} as const satisfies Record<string, {
  name: string;
  center: [number, number];
  aoi: GeoJSONPolygon;
}>;
