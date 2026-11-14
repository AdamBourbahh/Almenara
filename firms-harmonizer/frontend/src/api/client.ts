import type {
  AnalyzeRequest,
  AnalyzeResponse,
  ChaosMonkeyRequest,
  ChaosMonkeyResponse,
  DailyCalendarCell,
} from "./types";

const API_BASE_URL = "http://localhost:8000/api";

/**
 * Typed HTTP client for firms-harmonizer with a deterministic offline fallback.
 * If the FastAPI backend is unreachable the dashboard still renders a complete,
 * schema-valid synthetic response so an airplane-mode demo never breaks.
 */
export async function analyzeAoi(request: AnalyzeRequest): Promise<AnalyzeResponse> {
  try {
    const response = await fetch(`${API_BASE_URL}/analyze`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status} - ${response.statusText}`);
    }

    return (await response.json()) as AnalyzeResponse;
  } catch (error) {
    console.warn(
      "Backend unreachable. Activating deterministic offline fallback.",
      error,
    );
    return generateSyntheticAnalyzeResponse(request);
  }
}

export async function runChaosMonkey(
  request: ChaosMonkeyRequest,
): Promise<ChaosMonkeyResponse> {
  try {
    const response = await fetch(`${API_BASE_URL}/chaos-monkey`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status} - ${response.statusText}`);
    }

    return (await response.json()) as ChaosMonkeyResponse;
  } catch (error) {
    console.warn(
      "Backend unreachable for Chaos Monkey. Generating synthetic sabotage.",
      error,
    );
    return generateSyntheticChaosResponse(request);
  }
}

/**
 * Export the analyzed series as an IPCC-ready CSV file.
 */
export function exportToIpccCsv(data: AnalyzeResponse): void {
  const headers = [
    "date",
    "year",
    "doy",
    "raw_hotspot_count",
    "raw_frp_mw",
    "harmonized_fre_mj_km2",
    "historical_cross_prior_fre",
    "ci_95_lower",
    "ci_95_upper",
    "uncertainty_pct",
    "biomass_burned_tonnes",
    "pm25_emitted_kg",
    "z_score_anomaly",
    "is_gap_filled",
    "is_forecast",
    "gap_reason",
    "active_sensors",
    "tooltip_narrative",
  ];

  const escapeCell = (value: unknown): string => {
    const text = String(value ?? "");
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };

  const rows = [...data.calendar_series, ...data.forecast_series].map((cell) =>
    [
      cell.date,
      cell.year,
      cell.doy,
      cell.raw_hotspot_count,
      cell.raw_frp_mw,
      cell.harmonized_fre_mj_km2,
      cell.historical_cross_prior_fre,
      cell.ci_95_lower,
      cell.ci_95_upper,
      cell.uncertainty_pct,
      cell.biomass_burned_tonnes,
      cell.pm25_emitted_kg,
      cell.z_score_anomaly,
      cell.is_gap_filled,
      cell.is_forecast,
      cell.gap_reason ?? "",
      cell.active_sensors.join("|"),
      cell.tooltip_narrative,
    ]
      .map(escapeCell)
      .join(","),
  );

  const csvContent = [headers.join(","), ...rows].join("\n");
  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);

  const link = document.createElement("a");
  link.setAttribute("href", url);
  link.setAttribute(
    "download",
    `IPCC_Fire_Harmonized_Report_${data.query_hash.substring(0, 8)}.csv`,
  );
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

// ============================================================================
// Deterministic offline fallback (schema-valid AnalyzeResponse)
// ============================================================================

function mulberry32(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function isoDate(year: number, doy: number): string {
  return new Date(Date.UTC(year, 0, doy)).toISOString().slice(0, 10);
}

function daysInYear(year: number): number {
  return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0 ? 366 : 365;
}

function generateSyntheticAnalyzeResponse(
  request: AnalyzeRequest,
): AnalyzeResponse {
  const startYear = request.start_year ?? 2001;
  const endYear = request.end_year ?? 2026;
  const areaKm2 = 1420.5;
  const rng = mulberry32(42);

  const buildCell = (
    year: number,
    doy: number,
    isForecast: boolean,
  ): DailyCalendarCell => {
    const seasonal = Math.exp(
      4 * (Math.cos((2 * Math.PI * (doy - 215)) / 365.25) - 1),
    );
    const fre = Math.max(0, (10 + 640 * seasonal) * (1 + (rng() - 0.5) * 0.08));
    const prior = 12 + 520 * seasonal;
    const margin = fre * (isForecast ? 0.25 : 0.12);
    const isGap =
      !isForecast &&
      year === 2022 &&
      ((doy >= 213 && doy <= 228) || (doy >= 234 && doy <= 238));
    const biomass = (0.368 * fre * areaKm2) / 1000;

    return {
      date: isoDate(year, doy),
      year,
      doy,
      raw_hotspot_count: Math.round(fre / 18),
      raw_frp_mw: fre * 7.5,
      harmonized_fre_mj_km2: fre,
      historical_cross_prior_fre: prior,
      ci_95_lower: Math.max(0, fre - margin),
      ci_95_upper: fre + margin,
      uncertainty_pct: (margin / Math.max(fre, 1e-8)) * 100,
      biomass_burned_tonnes: biomass,
      pm25_emitted_kg: biomass * 9.5,
      z_score_anomaly: (fre - prior) / 25,
      is_gap_filled: isGap,
      is_forecast: isForecast,
      gap_reason: isGap ? "SENSOR_OUTAGE" : null,
      active_sensors: isGap ? [] : ["Terra", "Aqua", "VIIRS"],
      tooltip_narrative: isForecast
        ? "Synthetic 14-day forecast from circular climatology."
        : isGap
          ? "RTS Kalman reconstruction during the August 2022 dual-sensor blackout."
          : "Synthetic harmonized fire radiative energy.",
    };
  };

  const calendar_series: DailyCalendarCell[] = [];
  for (let year = startYear; year <= endYear; year += 1) {
    const totalDays = daysInYear(year);
    for (let doy = 1; doy <= totalDays; doy += 1) {
      calendar_series.push(buildCell(year, doy, false));
    }
  }

  const forecast_series: DailyCalendarCell[] = Array.from(
    { length: 14 },
    (_unused, index) => buildCell(2027, index + 1, true),
  );

  const phenology_by_year = Array.from(
    { length: endYear - startYear + 1 },
    (_unused, index) => {
      const year = startYear + index;
      const peak = 215 + (year - 2001) * 0.28;
      return {
        year,
        peak_doy_mu: peak,
        peak_date_label: isoDate(year, Math.round(peak)),
        concentration_kappa: 3.2,
        season_width_days: 46,
        total_annual_fre_gj: 125400.8 + index * 120,
      };
    },
  );

  return {
    query_hash: "offline_fallback_hash_9981abc",
    execution_time_ms: 4.2,
    aoi_area_km2: areaKm2,
    total_h3_cells: 48,
    calendar_series,
    forecast_series,
    phenology_by_year,
    audit_metrics: {
      chow_test_f_stat_raw: 142.8,
      chow_test_p_val_raw: 1.2e-18,
      chow_test_f_stat_harm: 0.94,
      chow_test_p_val_harm: 0.41,
      wasserstein_w1_raw: 38.4,
      wasserstein_w1_harm: 2.1,
      burned_area_r2_raw: 0.51,
      burned_area_r2_harm: 0.91,
      phenology_shift_days_per_decade: 8.4,
      mann_kendall_p_value: 0.003,
      industrial_false_positives_removed: 142,
      total_biomass_burned_kt: 20.2,
      total_pm25_emitted_tonnes: 191.6,
      executive_verdict_en:
        "Synthetic offline fallback: the harmonized Chow gate passes (p = 0.41) while raw pixel counts show a structural break. Diagnostics are simulated, not measured.",
    },
    map_hexagons: [
      {
        h3_index: "87b254db3ffffff",
        mean_annual_fre: 820.4,
        raw_pixel_count: 2100,
        trend_slope: 3.1,
        is_industrial_site: false,
        shannon_entropy: 0.21,
      },
      {
        h3_index: "87b254db2ffffff",
        mean_annual_fre: 640.8,
        raw_pixel_count: 1650,
        trend_slope: 2.4,
        is_industrial_site: false,
        shannon_entropy: 0.19,
      },
      {
        h3_index: "87b254d94ffffff",
        mean_annual_fre: 1020.2,
        raw_pixel_count: 2800,
        trend_slope: 4.6,
        is_industrial_site: false,
        shannon_entropy: 0.24,
      },
      {
        h3_index: "87b254d95ffffff",
        mean_annual_fre: 380.5,
        raw_pixel_count: 980,
        trend_slope: 1.2,
        is_industrial_site: false,
        shannon_entropy: 0.17,
      },
      {
        h3_index: "87b254d86ffffff",
        mean_annual_fre: 1460.9,
        raw_pixel_count: 3600,
        trend_slope: 5.9,
        is_industrial_site: true,
        shannon_entropy: 0.91,
      },
      {
        h3_index: "87b254db1ffffff",
        mean_annual_fre: 540.1,
        raw_pixel_count: 1420,
        trend_slope: 2.1,
        is_industrial_site: false,
        shannon_entropy: 0.2,
      },
      {
        h3_index: "87b254db0ffffff",
        mean_annual_fre: 730.7,
        raw_pixel_count: 1900,
        trend_slope: 3.3,
        is_industrial_site: false,
        shannon_entropy: 0.22,
      },
    ],
  };
}

function generateSyntheticChaosResponse(
  request: ChaosMonkeyRequest,
): ChaosMonkeyResponse {
  const rng = mulberry32(request.random_seed ?? 42);
  const targetYear = request.target_year ?? 2022;
  const seriesLength = 120;
  const dropStart = 40;
  const dropEnd = 55;

  const dates = Array.from({ length: seriesLength }, (_unused, index) => {
    const doy = targetYear === 2022 ? 200 + index : index + 1;
    return isoDate(targetYear, doy);
  });

  const trueHarmonized = Array.from({ length: seriesLength }, (_unused, index) => {
    const phase = (2 * Math.PI * index) / seriesLength;
    return 40 + 900 * Math.exp(4 * (Math.cos(phase - Math.PI / 2) - 1)) + rng() * 20;
  });

  const corruptedNaive = trueHarmonized.map((value, index) =>
    index >= dropStart && index <= dropEnd ? 0 : value,
  );
  const historicalCrossGuard = trueHarmonized.map((value, index) =>
    index >= dropStart && index <= dropEnd ? value * 0.55 : value,
  );
  const kalmanReconstructed = corruptedNaive.map((value, index) =>
    value === 0 ? trueHarmonized[index] * 0.93 : value,
  );

  const rmse = (estimate: number[], truth: number[]): number => {
    const total = estimate.reduce(
      (acc, value, index) => acc + (value - (truth[index] ?? 0)) ** 2,
      0,
    );
    return Math.sqrt(total / Math.max(1, estimate.length));
  };

  const truthEnergy = trueHarmonized.reduce((acc, value) => acc + value, 0);
  const recoveredEnergy = kalmanReconstructed.reduce((acc, value) => acc + value, 0);

  return {
    dropped_days_count: dropEnd - dropStart + 1,
    dropped_dates: dates.slice(dropStart, dropEnd + 1),
    dates,
    true_harmonized_fre: trueHarmonized,
    corrupted_naive_fre: corruptedNaive,
    historical_cross_guard_fre: historicalCrossGuard,
    kalman_reconstructed_fre: kalmanReconstructed,
    reconstructed_ci_lower: kalmanReconstructed.map((value) => value * 0.85),
    reconstructed_ci_upper: kalmanReconstructed.map((value) => value * 1.15),
    naive_rmse: rmse(corruptedNaive, trueHarmonized),
    kalman_rmse: rmse(kalmanReconstructed, trueHarmonized),
    seasonal_energy_recovered_pct:
      (recoveredEnergy / Math.max(1, truthEnergy)) * 100,
  };
}
