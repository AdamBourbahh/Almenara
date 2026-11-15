import type {
  AnalyzeRequest,
  AnalyzeResponse,
  ChaosMonkeyRequest,
  ChaosMonkeyResponse,
  CubeSyncRequest,
  CubeSyncStatusResponse,
  ExplainSpikeRequest,
  ExplainSpikeResponse,
  H3MapSummaryHex,
  RiskPredictionRequest,
  RiskPredictionResponse,
} from "./types";

// ============================================================================
// Configuration
// ============================================================================

const API_BASE_URL: string = (import.meta.env.VITE_API_URL ?? "/api").replace(/\/+$/, "");
const REQUEST_TIMEOUT_MS = 60_000;
const ALLOW_SYNTHETIC_FALLBACK = import.meta.env.VITE_ALLOW_SYNTHETIC_FALLBACK === "1";
/** Gateway statuses that mean "backend not up yet" (e.g. behind a reverse proxy). */
const BACKEND_DOWN_STATUSES = new Set([502, 503, 504]);
/** Short retries so a restarting API recovers without a manual reload. */
const BACKEND_RETRY_DELAYS_MS = [700, 1500, 3000];

export function isBackendDown(error: unknown): boolean {
  if (error instanceof ApiError) return BACKEND_DOWN_STATUSES.has(error.status);
  if (error instanceof DOMException) return error.name === "TimeoutError";
  return error instanceof TypeError; // fetch network failure: connection refused, DNS, CORS
}

const BACKEND_UNAVAILABLE_MESSAGE = "Backend unavailable: the API is not reachable. Retrying shortly.";

function isBackendUnavailable(error: unknown): boolean {
  return isBackendDown(error);
}

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(new DOMException("Aborted", "AbortError")); return; }
    const timer = setTimeout(() => { signal?.removeEventListener("abort", onAbort); resolve(); }, ms);
    const onAbort = () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

async function fetchWithBackendRetry(url: string, init: RequestInit, signal: AbortSignal): Promise<Response> {
  for (let attempt = 0; ; attempt += 1) {
    try {
      const response = await fetch(url, init);
      if (!BACKEND_DOWN_STATUSES.has(response.status) || attempt >= BACKEND_RETRY_DELAYS_MS.length) return response;
    } catch (error) {
      if (attempt >= BACKEND_RETRY_DELAYS_MS.length || signal.aborted) throw error;
    }
    await delay(BACKEND_RETRY_DELAYS_MS[attempt], signal);
  }
}


export interface ApiResult<T> {
  data: T;
  /** True when the response declares synthetic provenance. */
  isSynthetic: boolean;
}

export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// ============================================================================
// Typed HTTP client with explicit fixture opt-in
// ============================================================================

async function requestJson<T>(path: string, init: { method: string; headers: Record<string, string>; body?: string }, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(
    () => controller.abort(new DOMException(`Request timed out after ${REQUEST_TIMEOUT_MS} ms`, "TimeoutError")),
    REQUEST_TIMEOUT_MS
  );
  const forwardAbort = () => controller.abort(signal?.reason);
  if (signal?.aborted) forwardAbort();
  signal?.addEventListener("abort", forwardAbort, { once: true });

  try {
    const response = await fetchWithBackendRetry(`${API_BASE_URL}${path}`, { ...init, signal: controller.signal }, controller.signal);
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const payload: unknown = await response.json();
        if (payload && typeof payload === "object" && "detail" in payload) {
          detail = JSON.stringify((payload as { detail: unknown }).detail);
        }
      } catch {
        /* non-JSON error body: keep statusText */
      }
      if (BACKEND_DOWN_STATUSES.has(response.status)) {
        throw new ApiError(BACKEND_UNAVAILABLE_MESSAGE, response.status);
      }
      throw new ApiError(`HTTP ${response.status}: ${detail}`, response.status);
    }
    return (await response.json()) as T;
  } finally {
    clearTimeout(timeoutId);
    signal?.removeEventListener("abort", forwardAbort);
  }
}

function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return requestJson<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }, signal);
}

function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  return requestJson<T>(path, { method: "GET", headers: { Accept: "application/json" } }, signal);
}

export async function triggerCubeSync(
  request: CubeSyncRequest = {},
  signal?: AbortSignal
): Promise<CubeSyncStatusResponse> {
  return postJson<CubeSyncStatusResponse>("/cube/sync", request, signal);
}

export async function fetchCubeSyncStatus(
  signal?: AbortSignal
): Promise<CubeSyncStatusResponse> {
  try {
    return await getJson<CubeSyncStatusResponse>("/cube/sync-status", signal);
  } catch (error) {
    if (!ALLOW_SYNTHETIC_FALLBACK || !isBackendUnavailable(error)) throw error;
    return {
      status: "idle",
      last_synced_utc: null,
      new_detections_count: 0,
      message: "Offline synthetic mode.",
      data_source: "synthetic",
      error: null
    };
  }
}

export function fetchRiskPrediction(request: RiskPredictionRequest, signal?: AbortSignal): Promise<RiskPredictionResponse> {
  return postJson<RiskPredictionResponse>("/predict-risk", request, signal);
}

export async function analyzeAoi(request: AnalyzeRequest, signal?: AbortSignal): Promise<ApiResult<AnalyzeResponse>> {
  try {
    const data = await postJson<AnalyzeResponse>("/analyze", request, signal);
    return { data, isSynthetic: data.data_source === "synthetic" };
  } catch (error) {
    if (!ALLOW_SYNTHETIC_FALLBACK || !isBackendUnavailable(error)) throw error;
    console.warn("[firms-harmonizer] Backend unreachable. Using deterministic offline fallback for /analyze.", error);
    const { generateSyntheticAnalyzeResponse } = await import("./synthetic");
    return { data: generateSyntheticAnalyzeResponse(request), isSynthetic: true };
  }
}

export interface MapPeriodResponse {
  data_source: "real" | "synthetic";
  start_date: string;
  end_date: string;
  /** mean_annual_fre is the integrated density for this period, using the legacy hex shape. */
  map_hexagons: H3MapSummaryHex[];
  execution_time_ms: number;
}

/** Exact spatial observations; never substitute an annual map or regional synthetic series. */
export async function fetchMapPeriod(request: AnalyzeRequest, startDate: string, endDate: string,
  signal?: AbortSignal): Promise<ApiResult<MapPeriodResponse>> {
  const query = new URLSearchParams({ start_date: startDate, end_date: endDate });
  const data = await postJson<MapPeriodResponse>(`/map-period?${query}`, request, signal);
  return { data, isSynthetic: data.data_source === "synthetic" };
}

export async function runChaosMonkey(
  request: ChaosMonkeyRequest,
  signal?: AbortSignal
): Promise<ApiResult<ChaosMonkeyResponse>> {
  try {
    const data = await postJson<ChaosMonkeyResponse>("/chaos-monkey", request, signal);
    return { data, isSynthetic: data.data_source === "synthetic" };
  } catch (error) {
    if (!ALLOW_SYNTHETIC_FALLBACK || !isBackendUnavailable(error)) throw error;
    console.warn("[firms-harmonizer] Backend unreachable. Using deterministic offline fallback for /chaos-monkey.", error);
    const { generateSyntheticChaosResponse } = await import("./synthetic");
    return { data: generateSyntheticChaosResponse(request), isSynthetic: true };
  }
}

export interface ObservedDay {
  date: string; year: number; doy: number; detection_count: number; raw_frp_mw: number; sensors: string[];
}
export interface ObservedHex { h3_index: string; detection_count: number; raw_frp_mw: number; }
export interface Observations {
  data_source: "real"; daily: ObservedDay[]; map_hexagons: ObservedHex[];
  total_detections: number; first_observed_date: string | null; last_observed_date: string | null;
  execution_time_ms: number; method: string; total_days: number; offset: number; limit: number;
}
export async function fetchObservations(aoi: import("./types").GeoJSONPolygon, signal?: AbortSignal, offset = 0, limit = 366): Promise<Observations> {
  const data = await postJson<Observations>(`/observations?offset=${offset}&limit=${limit}`, aoi, signal);
  if (data.data_source !== "real") throw new Error("Real observations are required.");
  return data;
}

export async function explainSpike(
  request: ExplainSpikeRequest,
  signal?: AbortSignal
): Promise<ApiResult<ExplainSpikeResponse>> {
  const data = await postJson<ExplainSpikeResponse>("/explain-spike", request, signal);
  return { data, isSynthetic: data.data_source === "synthetic" };
}

// ============================================================================
// Research CSV exporter
// ============================================================================

function csvField(value: string | number | boolean | null | undefined): string {
  if (value === null || value === undefined) return "";
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function exportToIpccCsv(data: AnalyzeResponse): void {
  const headers = [
    "Date",
    "Year",
    "DOY",
    "Raw Hotspot Count",
    "Raw FRP (MW)",
    "Harmonized FRE (MJ/km2)",
    "CI 95 Lower (MJ/km2)",
    "CI 95 Upper (MJ/km2)",
    "Uncertainty (%)",
    "Z-Score Anomaly",
    "Is Gap Filled",
    "Gap Reason",
    "Active Sensors",
    "Biomass Burned (kt)",
    "PM2.5 Emitted (kg)",
    "PM2.5 Factor SD (kg; excludes sampling bias)",
    "Is Forecast",
    "Observation Status",
    "Narrative"
  ];

  const cells = [...data.calendar_series, ...(data.forecast_series ?? [])];
  const rows = cells.map((cell) =>
    [
      cell.date,
      cell.year,
      cell.doy,
      cell.raw_hotspot_count,
      cell.raw_frp_mw,
      cell.observation_status === "unknown" ? null : cell.harmonized_fre_mj_km2,
      cell.ci_95_lower,
      cell.ci_95_upper,
      cell.uncertainty_pct,
      cell.z_score_anomaly,
      cell.is_gap_filled,
      cell.gap_reason,
      cell.active_sensors.join("|"),
      cell.observation_status === "unknown" ? null : cell.biomass_burned_tonnes / 1000,
      cell.pm25_emitted_kg,
      cell.pm25_factor_sd_kg,
      cell.is_forecast ?? false,
      cell.observation_status,
      cell.tooltip_narrative
    ]
      .map(csvField)
      .join(",")
  );

  // BOM so Excel opens UTF-8 (km², ±, σ) correctly.
  const csvContent = "\uFEFF" + [headers.join(","), ...rows].join("\r\n");
  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);

  const link = document.createElement("a");
  link.href = url;
  link.download = `FIRMS_Energy_Estimates_${data.query_hash.substring(0, 8)}.csv`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
