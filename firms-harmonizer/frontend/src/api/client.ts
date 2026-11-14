import { cellToLatLng, getHexagonAreaAvg, gridDisk, latLngToCell, polygonToCells, UNITS } from "h3-js";
import type {
  AnalyzeRequest,
  AnalyzeResponse,
  ChaosMonkeyRequest,
  ChaosMonkeyResponse,
  DailyCalendarCell,
  ExplainSpikeRequest,
  ExplainSpikeResponse,
  GapReason,
  H3MapSummaryHex,
  ScientificAuditMetrics,
  VonMisesPhenologyYear
} from "./types";

// ============================================================================
// Configuration
// ============================================================================

const API_BASE_URL: string = (import.meta.env.VITE_API_URL ?? "/api").replace(/\/+$/, "");
const REQUEST_TIMEOUT_MS = 60_000;
const ALLOW_SYNTHETIC_FALLBACK = import.meta.env.VITE_ALLOW_SYNTHETIC_FALLBACK === "1";
/** Gateway statuses that mean "backend not up yet" (e.g. behind a reverse proxy). */
const BACKEND_DOWN_STATUSES = new Set([502, 503, 504]);

function isBackendUnavailable(error: unknown): boolean {
  if (error instanceof ApiError) return BACKEND_DOWN_STATUSES.has(error.status);
  if (error instanceof DOMException) return error.name === "TimeoutError";
  return error instanceof TypeError; // fetch network failure: connection refused, DNS, CORS
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

async function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(
    () => controller.abort(new DOMException(`Request timed out after ${REQUEST_TIMEOUT_MS} ms`, "TimeoutError")),
    REQUEST_TIMEOUT_MS
  );
  const forwardAbort = () => controller.abort(signal?.reason);
  if (signal?.aborted) forwardAbort();
  signal?.addEventListener("abort", forwardAbort, { once: true });

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal
    });
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
      throw new ApiError(`HTTP ${response.status}: ${detail}`, response.status);
    }
    return (await response.json()) as T;
  } finally {
    clearTimeout(timeoutId);
    signal?.removeEventListener("abort", forwardAbort);
  }
}

export async function analyzeAoi(request: AnalyzeRequest, signal?: AbortSignal): Promise<ApiResult<AnalyzeResponse>> {
  try {
    const data = await postJson<AnalyzeResponse>("/analyze", request, signal);
    return { data, isSynthetic: data.data_source === "synthetic" };
  } catch (error) {
    if (!ALLOW_SYNTHETIC_FALLBACK || !isBackendUnavailable(error)) throw error;
    console.warn("[firms-harmonizer] Backend unreachable. Using deterministic offline fallback for /analyze.", error);
    return { data: generateSyntheticAnalyzeResponse(request), isSynthetic: true };
  }
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
  execution_time_ms: number; method: string;
}
export async function fetchObservations(aoi: import("./types").GeoJSONPolygon, signal?: AbortSignal): Promise<Observations> {
  const data = await postJson<Observations>("/observations", aoi, signal);
  if (data.data_source !== "real") throw new Error("Real observations are required.");
  return data;
}

export async function explainSpike(
  request: ExplainSpikeRequest,
  signal?: AbortSignal
): Promise<ApiResult<ExplainSpikeResponse>> {
  try {
    return { data: await postJson<ExplainSpikeResponse>("/explain-spike", request, signal), isSynthetic: false };
  } catch (error) {
    if (!isBackendUnavailable(error)) throw error;
    console.warn("[firms-harmonizer] Backend unreachable. Using fallback for /explain-spike.", error);
    return {
      data: {
        physical_classification: "EXTREME_VEGETATION_FIRE",
        explanation_markdown:
          "### Offline Fallback Explanation\n\nThermal spike detected by NASA sensors. Live backend connection currently unreachable; displaying deterministic physics grounding.",
        citations: [
          {
            id: "[1]",
            source_type: "PEER_REVIEWED",
            title: "Retrieval of biomass combustion rates and totals from fire radiative power observations",
            authors_or_agency: "Wooster, M. J., et al.",
            year: 2005,
            dataset_or_doi: "10.1029/2005JD006318",
            url: "https://doi.org/10.1029/2005JD006318",
            relevance_note: "Biomass combustion factor beta = 0.368 kg/MJ.",
          },
          {
            id: "[5]",
            source_type: "NASA_DATASET",
            title: "Fire Information for Resource Management System (FIRMS)",
            authors_or_agency: "NASA EOSDIS LANCE",
            year: 2026,
            dataset_or_doi: "NASA Earthdata / FIRMS",
            url: "https://firms.modaps.eosdis.nasa.gov/",
            relevance_note: "Active fire hot spots and FRP telemetry.",
          },
        ],
        web_search_used: false,
        search_query_executed: null,
        model_used: "deterministic-offline-client",
        data_source: "synthetic",
      },
      isSynthetic: true,
    };
  }
}

// ============================================================================
// IPCC-ready CSV exporter
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
    "Is Forecast",
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
      cell.harmonized_fre_mj_km2,
      cell.ci_95_lower,
      cell.ci_95_upper,
      cell.uncertainty_pct,
      cell.z_score_anomaly,
      cell.is_gap_filled,
      cell.gap_reason,
      cell.active_sensors.join("|"),
      cell.biomass_burned_tonnes / 1000,
      cell.pm25_emitted_kg,
      cell.is_forecast ?? false,
      cell.tooltip_narrative
    ]
      .map(csvField)
      .join(",")
  );

  // BOM so Excel opens UTF-8 (kmÂ², Â±, Ïƒ) correctly.
  const csvContent = "ï»¿" + [headers.join(","), ...rows].join("\r\n");
  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);

  const link = document.createElement("a");
  link.href = url;
  link.download = `IPCC_Fire_Harmonized_Report_${data.query_hash.substring(0, 8)}.csv`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

// ============================================================================
// DETERMINISTIC OFFLINE FALLBACK
// Same request => byte-identical calendar/map/metrics (seeded PRNG, UTC dates).
// Physically plausible: VIIRS detection jump from Jan 2012, MODIS Aqua safe mode
// (31 Jul - 16 Aug 2022), cloud occlusion, swath gaps, phenology drift.
// ============================================================================

const MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

interface DayRef {
  year: number;
  doy: number;
}

const TERRA_START: DayRef = { year: 2000, doy: 306 }; // 2000-11-01
const AQUA_START: DayRef = { year: 2002, doy: 185 }; // 2002-07-04
const SNPP_START: DayRef = { year: 2012, doy: 20 }; // 2012-01-20 (VIIRS 375 m operational)
const NOAA20_START: DayRef = { year: 2018, doy: 5 };
const AQUA_SAFE_MODE = { year: 2022, startDoy: 212, endDoy: 228 }; // 2022-07-31 .. 2022-08-16

const WOOSTER_BIOMASS_KG_PER_MJ = 0.368;
const PM25_EMISSION_FACTOR_G_PER_KG = 7.17; // Representative savanna/grassland emission factor
const PHENOLOGY_SHIFT_DAYS_PER_YEAR = 0.84;
const VON_MISES_KAPPA = 3.2;
const MAX_SYNTHETIC_HEXES = 12_000;
const FORECAST_DAYS = 14;

const GAP_UNCERTAINTY_PCT: Record<GapReason, number> = {
  NONE: 8,
  SENSOR_OUTAGE: 18,
  SWATH_GAP: 16,
  CLOUD_OCCLUSION: 26,
  MULTI_FACTOR: 34
};

// ---------- PRNG & small math helpers ----------

function hashString(text: string): number {
  let h = 0x811c9dc5; // FNV-1a 32-bit
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function gaussian(rng: () => number): number {
  const u = Math.max(rng(), 1e-12);
  const v = rng();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

const round = (value: number, digits = 2) => {
  const f = 10 ** digits;
  return Math.round(value * f) / f;
};

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

function quantileSorted(sorted: number[], q: number): number {
  if (sorted.length === 0) return 0;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

function median(values: number[]): number {
  return quantileSorted([...values].sort((a, b) => a - b), 0.5);
}

function logGamma(x: number): number {
  const c = [76.18009172947146, -86.50532032941677, 24.01409824083091, -1.231739572450155, 0.1208650973866179e-2, -0.5395239384953e-5];
  let y = x;
  const tmp = x + 5.5 - (x + 0.5) * Math.log(x + 5.5);
  let ser = 1.000000000190015;
  for (const ci of c) ser += ci / ++y;
  return -tmp + Math.log((2.5066282746310005 * ser) / x);
}

function betaContinuedFraction(a: number, b: number, x: number): number {
  const EPS = 3e-14;
  const FPMIN = 1e-300;
  let c = 1;
  let d = 1 - ((a + b) * x) / (a + 1);
  if (Math.abs(d) < FPMIN) d = FPMIN;
  d = 1 / d;
  let h = d;
  for (let m = 1; m <= 300; m++) {
    const m2 = 2 * m;
    let aa = (m * (b - m) * x) / ((a + m2 - 1) * (a + m2));
    d = 1 + aa * d;
    if (Math.abs(d) < FPMIN) d = FPMIN;
    c = 1 + aa / c;
    if (Math.abs(c) < FPMIN) c = FPMIN;
    d = 1 / d;
    h *= d * c;
    aa = (-(a + m) * (a + b + m) * x) / ((a + m2) * (a + m2 + 1));
    d = 1 + aa * d;
    if (Math.abs(d) < FPMIN) d = FPMIN;
    c = 1 + aa / c;
    if (Math.abs(c) < FPMIN) c = FPMIN;
    d = 1 / d;
    const delta = d * c;
    h *= delta;
    if (Math.abs(delta - 1) < EPS) break;
  }
  return h;
}

function regularizedIncompleteBeta(x: number, a: number, b: number): number {
  if (x <= 0) return 0;
  if (x >= 1) return 1;
  const bt = Math.exp(logGamma(a + b) - logGamma(a) - logGamma(b) + a * Math.log(x) + b * Math.log(1 - x));
  return x < (a + 1) / (a + b + 2) ? (bt * betaContinuedFraction(a, b, x)) / a : 1 - (bt * betaContinuedFraction(b, a, 1 - x)) / b;
}

/** P(F > f) for an F(d1, d2) distribution. */
function fSurvival(f: number, d1: number, d2: number): number {
  if (!(f > 0)) return 1;
  return Math.max(1e-300, regularizedIncompleteBeta(d2 / (d2 + d1 * f), d2 / 2, d1 / 2));
}

function normalCdf(z: number): number {
  const t = 1 / (1 + 0.3275911 * Math.abs(z) / Math.SQRT2);
  const erf = 1 - t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429)))) * Math.exp(-(z * z) / 2);
  return z >= 0 ? 0.5 * (1 + erf) : 0.5 * (1 - erf);
}

function linearFitSsr(xs: number[], ys: number[]): number {
  const n = xs.length;
  const mx = xs.reduce((s, v) => s + v, 0) / n;
  const my = ys.reduce((s, v) => s + v, 0) / n;
  let sxy = 0;
  let sxx = 0;
  for (let i = 0; i < n; i++) {
    sxy += (xs[i] - mx) * (ys[i] - my);
    sxx += (xs[i] - mx) ** 2;
  }
  const slope = sxx > 0 ? sxy / sxx : 0;
  let ssr = 0;
  for (let i = 0; i < n; i++) ssr += (ys[i] - (my + slope * (xs[i] - mx))) ** 2;
  return ssr;
}

/** Chow structural-break test (linear trend model, k = 2) with the break before `breakYear`. */
function chowTest(years: number[], values: number[], breakYear: number): { f: number; p: number } {
  const k = 2;
  const before = years.map((y, i) => [y, values[i]] as const).filter(([y]) => y < breakYear);
  const after = years.map((y, i) => [y, values[i]] as const).filter(([y]) => y >= breakYear);
  const n = years.length;
  if (before.length < 3 || after.length < 3) return { f: 0, p: 1 };
  const ssrPooled = linearFitSsr(years, values);
  const ssrSplit =
    linearFitSsr(before.map((p) => p[0]), before.map((p) => p[1])) + linearFitSsr(after.map((p) => p[0]), after.map((p) => p[1]));
  const f = ssrSplit > 0 ? ((ssrPooled - ssrSplit) / k) / (ssrSplit / (n - 2 * k)) : 0;
  return { f, p: fSurvival(f, k, n - 2 * k) };
}

/** 1-D Wasserstein-1 distance between two empirical samples (quantile approximation). */
function wasserstein1(a: number[], b: number[]): number {
  if (a.length === 0 || b.length === 0) return 0;
  const sa = [...a].sort((x, y) => x - y);
  const sb = [...b].sort((x, y) => x - y);
  const steps = 200;
  let sum = 0;
  for (let i = 0; i < steps; i++) {
    const q = (i + 0.5) / steps;
    sum += Math.abs(quantileSorted(sa, q) - quantileSorted(sb, q));
  }
  return sum / steps;
}

function pearsonR2(xs: number[], ys: number[]): number {
  const n = xs.length;
  if (n < 3) return 0;
  const mx = xs.reduce((s, v) => s + v, 0) / n;
  const my = ys.reduce((s, v) => s + v, 0) / n;
  let sxy = 0;
  let sxx = 0;
  let syy = 0;
  for (let i = 0; i < n; i++) {
    sxy += (xs[i] - mx) * (ys[i] - my);
    sxx += (xs[i] - mx) ** 2;
    syy += (ys[i] - my) ** 2;
  }
  return sxx > 0 && syy > 0 ? (sxy * sxy) / (sxx * syy) : 0;
}

// ---------- Calendar helpers (always UTC: no timezone off-by-one) ----------

const isLeapYear = (year: number) => (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
const daysInYear = (year: number) => (isLeapYear(year) ? 366 : 365);
const utcDate = (year: number, doy: number) => new Date(Date.UTC(year, 0, doy));
const isoDate = (year: number, doy: number) => utcDate(year, doy).toISOString().slice(0, 10);
const isOnOrAfter = (day: DayRef, ref: DayRef) => day.year > ref.year || (day.year === ref.year && day.doy >= ref.doy);

function dayLabel(year: number, doy: number): string {
  const d = utcDate(year, doy);
  return `${MONTHS_EN[d.getUTCMonth()]} ${d.getUTCDate()}, ${year}`;
}

function addDays(day: DayRef, days: number): DayRef {
  const d = new Date(Date.UTC(day.year, 0, day.doy + days));
  const year = d.getUTCFullYear();
  return { year, doy: Math.round((d.getTime() - Date.UTC(year, 0, 1)) / 86_400_000) + 1 };
}

/** Last observed day: yesterday (UTC) if end_year is current, otherwise 31 Dec of end_year. */
function observationCutoff(endYear: number): DayRef {
  const now = new Date();
  const today: DayRef = {
    year: now.getUTCFullYear(),
    doy: Math.floor((Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()) - Date.UTC(now.getUTCFullYear(), 0, 1)) / 86_400_000) + 1
  };
  const yesterday = addDays(today, -1);
  if (endYear < yesterday.year) return { year: endYear, doy: daysInYear(endYear) };
  return yesterday;
}

function vonMisesShape(doy: number, peakDoy: number, kappa: number, yearLength: number): number {
  const theta = (2 * Math.PI * (doy - peakDoy)) / yearLength;
  return Math.exp(kappa * (Math.cos(theta) - 1));
}

function ringCentroid(ring: number[][]): [number, number] {
  const pts = ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1] ? ring.slice(0, -1) : ring;
  if (pts.length === 0) return [0, 0];
  const lng = pts.reduce((s, p) => s + p[0], 0) / pts.length;
  const lat = pts.reduce((s, p) => s + p[1], 0) / pts.length;
  return [lng, lat];
}

// ---------- Synthetic H3 grid (real H3 cells covering the AOI) ----------

interface SyntheticHex {
  h3: string;
  relativeEnergy: number;
  trend: number;
  industrial: boolean;
}

function buildSyntheticHexes(coordinates: number[][][], lat: number, lng: number, rng: () => number) {
  let resolution = 7;
  let cells: string[] = [];
  for (const res of [7, 6, 5]) {
    resolution = res;
    try {
      cells = polygonToCells(coordinates, res, true);
    } catch {
      cells = [];
    }
    if (cells.length <= MAX_SYNTHETIC_HEXES) break;
  }
  if (cells.length === 0) {
    resolution = 7;
    cells = gridDisk(latLngToCell(lat, lng, resolution), 1);
  }
  cells.sort();

  const phaseA = rng() * Math.PI * 2;
  const phaseB = rng() * Math.PI * 2;
  const hexes: SyntheticHex[] = cells.map((h3) => {
    const [cLat, cLng] = cellToLatLng(h3);
    const field = 0.55 + 0.45 * Math.sin(cLat * 7.3 + phaseA) * Math.cos(cLng * 6.1 + phaseB);
    const industrial = rng() < 0.012;
    const noise = Math.exp(0.5 * gaussian(rng));
    return {
      h3,
      relativeEnergy: industrial ? 1.8 + rng() : Math.max(0.05, field) * noise,
      trend: 0.8 + 1.2 * gaussian(rng),
      industrial
    };
  });
  return { hexes, resolution, areaKm2: cells.length * getHexagonAreaAvg(resolution, UNITS.km2) };
}

// ---------- /analyze generator ----------

function narrativeFor(
  year: number,
  doy: number,
  fre: number,
  unc: number,
  reason: GapReason,
  gapFilled: boolean,
  sensors: string[]
): string {
  const head = `${dayLabel(year, doy)}: harmonized FRE ${fre.toFixed(1)} MJ/kmÂ² (Â±${unc.toFixed(1)}%, 95% CI).`;
  if (!gapFilled) {
    return reason === "NONE"
      ? `${head} Clean multi-sensor observation (${sensors.join(" + ")}).`
      : `${head} ${reason.replace("_", " ").toLowerCase()} detected but Kalman gap-filling is disabled: value reflects observed energy only.`;
  }
  switch (reason) {
    case "SENSOR_OUTAGE":
      return `${head} Reconstructed via RTS Kalman smoother: MODIS Aqua in safe mode; estimated from MODIS Terra (diurnal scaling Îºâ‰ˆ3.1Ã—) + VIIRS.`;
    case "CLOUD_OCCLUSION":
      return `${head} Reconstructed via RTS Kalman + historical cross-guard: >80% cloud cover blocked every optical sensor.`;
    case "SWATH_GAP":
      return `${head} Equatorial swath gap: partial coverage gap-filled from neighboring H3 cells (tâˆ’1).`;
    case "MULTI_FACTOR":
      return `${head} Multi-factor gap (MODIS Aqua safe mode + cloud occlusion): reconstructed from the historical cross-guard prior with widened CI.`;
    default:
      return head;
  }
}

export function generateSyntheticAnalyzeResponse(request: AnalyzeRequest): AnalyzeResponse {
  const t0 = performance.now();
  const seed = hashString(JSON.stringify(request));
  const rng = mulberry32(seed);
  const ring = request.aoi.coordinates[0] ?? [];
  const [lng, lat] = ringCentroid(ring);
  const { hexes, areaKm2 } = buildSyntheticHexes(request.aoi.coordinates, lat, lng, mulberry32(seed ^ 0x9e3779b9));
  const industrialSites = hexes.filter((h) => h.industrial).length;

  const basePeakDoy = lat < 0 ? 245 : 212; // Austral vs boreal fire season
  const tropical = Math.abs(lat) < 25;
  const peakFre = 380 * (0.6 + 0.8 * rng());
  const countScale = request.confidence_level === "low" ? 1.15 : request.confidence_level === "high" ? 0.8 : 1;
  const startYear = request.start_year ?? 2001; // schema defaults
  const endYear = request.end_year ?? 2026;
  const cutoff = observationCutoff(endYear);

  const calendar_series: DailyCalendarCell[] = [];
  const trueAnnualFre = new Map<number, number>();
  let lastAmplitude = 1;
  let falsePositivesRemoved = 0;

  for (let year = Math.max(startYear, TERRA_START.year); year <= Math.min(endYear, cutoff.year); year++) {
    const yearLength = daysInYear(year);
    const amplitude = Math.exp(0.28 * gaussian(rng));
    const climatologyPeak = basePeakDoy + PHENOLOGY_SHIFT_DAYS_PER_YEAR * (year - 2001);
    const yearPeak = climatologyPeak + 6 * gaussian(rng);
    const lastDoy = year === cutoff.year ? cutoff.doy : yearLength;
    lastAmplitude = amplitude;

    for (let doy = 1; doy <= lastDoy; doy++) {
      const day: DayRef = { year, doy };
      if (!isOnOrAfter(day, TERRA_START)) continue;

      const prior = peakFre * vonMisesShape(doy, climatologyPeak, VON_MISES_KAPPA, yearLength) + 0.5;
      const trueFre = peakFre * amplitude * vonMisesShape(doy, yearPeak, VON_MISES_KAPPA, yearLength) * Math.exp(0.35 * gaussian(rng)) + 0.5;
      trueAnnualFre.set(year, (trueAnnualFre.get(year) ?? 0) + trueFre);

      const aquaSafeMode = year === AQUA_SAFE_MODE.year && doy >= AQUA_SAFE_MODE.startDoy && doy <= AQUA_SAFE_MODE.endDoy;
      const aqua = isOnOrAfter(day, AQUA_START) && !aquaSafeMode;
      const snpp = isOnOrAfter(day, SNPP_START);
      const noaa20 = isOnOrAfter(day, NOAA20_START);
      const sensors = ["MODIS_TERRA", ...(aqua ? ["MODIS_AQUA"] : []), ...(snpp ? ["VIIRS_SNPP"] : []), ...(noaa20 ? ["VIIRS_NOAA20"] : [])];

      const r = rng();
      const cloud = r < 0.035;
      const swath = !cloud && tropical && r < 0.05;
      const gapReason: GapReason =
        cloud && aquaSafeMode ? "MULTI_FACTOR" : cloud ? "CLOUD_OCCLUSION" : aquaSafeMode ? "SENSOR_OUTAGE" : swath ? "SWATH_GAP" : "NONE";
      const detectionFactor = cloud ? 0 : swath ? 0.5 : 1;

      // Raw counts: VIIRS 375 m detects ~4.5x more pixels than MODIS 1 km -> artificial jump from Jan 2012.
      const flareActive = !request.exclude_industrial_flaring && industrialSites > 0;
      const modisPerSensor = trueFre / 18;
      const viirsPerSensor = (trueFre / 18) * 4.5;
      const modisCount = modisPerSensor * (1 + (aqua ? 1 : 0));
      const viirsCount = viirsPerSensor * ((snpp ? 1 : 0) + (noaa20 ? 1 : 0));
      const flareCount = industrialSites * 0.15 * sensors.length;
      if (request.exclude_industrial_flaring && detectionFactor > 0) falsePositivesRemoved += Math.round(flareCount);
      const expectedCount = ((modisCount + viirsCount) * countScale + (flareActive ? flareCount : 0)) * detectionFactor;
      const rawCount = Math.max(0, Math.round(expectedCount + Math.sqrt(expectedCount) * gaussian(rng)));
      const rawFrp = (modisCount * 35 + viirsCount * 9 + (flareActive ? flareCount * 20 : 0)) * detectionFactor;

      const flareFre = flareActive ? 6 + 2 * rng() : 0;
      let harmonized: number;
      let uncertainty: number;
      let isGapFilled = false;
      if (gapReason === "NONE") {
        harmonized = (trueFre + flareFre) * (1 + 0.04 * gaussian(rng));
        uncertainty = GAP_UNCERTAINTY_PCT.NONE + 4 * rng();
      } else if (request.enable_kalman_gap_filling) {
        harmonized = (trueFre + flareFre) * (1 + 0.1 * gaussian(rng));
        uncertainty = GAP_UNCERTAINTY_PCT[gapReason] + 6 * rng();
        isGapFilled = true;
      } else {
        const observedShare = gapReason === "SENSOR_OUTAGE" ? 0.85 : gapReason === "SWATH_GAP" ? 0.5 : 0;
        harmonized = (trueFre + flareFre) * observedShare;
        uncertainty = 100;
      }
      harmonized = Math.max(0, harmonized);
      const halfWidth = harmonized * (uncertainty / 100); // uncertainty_pct = 1.96Â·Ïƒ / x Â· 100
      const biomassKg = harmonized * areaKm2 * WOOSTER_BIOMASS_KG_PER_MJ;

      calendar_series.push({
        date: isoDate(year, doy),
        year,
        doy,
        raw_hotspot_count: rawCount,
        raw_frp_mw: round(rawFrp),
        harmonized_fre_mj_km2: round(harmonized),
        ci_95_lower: round(Math.max(0, harmonized - halfWidth)),
        ci_95_upper: round(harmonized + halfWidth),
        uncertainty_pct: round(uncertainty, 1),
        z_score_anomaly: round((harmonized - prior) / (prior * 0.45 + 5)),
        is_gap_filled: isGapFilled,
        gap_reason: gapReason,
        active_sensors: sensors,
        tooltip_narrative: narrativeFor(year, doy, round(harmonized), uncertainty, gapReason, isGapFilled, sensors),
        historical_cross_prior_fre: round(prior),
        is_forecast: false,
        biomass_burned_tonnes: round(biomassKg / 1000, 1),
        pm25_emitted_kg: round((biomassKg * PM25_EMISSION_FACTOR_G_PER_KG) / 1000, 1)
      });
    }
  }

  // ---------- 14-day operational forecast after the last observed day ----------
  const forecast_series: DailyCalendarCell[] = [];
  for (let k = 1; k <= FORECAST_DAYS; k++) {
    const { year, doy } = addDays(cutoff, k);
    const yearLength = daysInYear(year);
    const climatologyPeak = basePeakDoy + PHENOLOGY_SHIFT_DAYS_PER_YEAR * (year - 2001);
    const prior = peakFre * vonMisesShape(doy, climatologyPeak, VON_MISES_KAPPA, yearLength) + 0.5;
    const fre = prior * (0.5 + 0.5 * lastAmplitude);
    const uncertainty = 15 + 2.5 * k;
    const halfWidth = fre * (uncertainty / 100);
    const biomassKg = fre * areaKm2 * WOOSTER_BIOMASS_KG_PER_MJ;
    forecast_series.push({
      date: isoDate(year, doy),
      year,
      doy,
      raw_hotspot_count: 0,
      raw_frp_mw: 0,
      harmonized_fre_mj_km2: round(fre),
      ci_95_lower: round(Math.max(0, fre - halfWidth)),
      ci_95_upper: round(fre + halfWidth),
      uncertainty_pct: round(uncertainty, 1),
      z_score_anomaly: round((fre - prior) / (prior * 0.45 + 5)),
      is_gap_filled: false,
      gap_reason: "NONE",
      active_sensors: [],
      is_forecast: true,
      historical_cross_prior_fre: round(prior),
      biomass_burned_tonnes: round(biomassKg / 1000, 1),
      pm25_emitted_kg: round((biomassKg * PM25_EMISSION_FACTOR_G_PER_KG) / 1000, 1),
      tooltip_narrative: `${dayLabel(year, doy)}: operational forecast day ${k}/${FORECAST_DAYS} from the Kalman state transition. Expected FRE ${fre.toFixed(1)} MJ/kmÂ² (Â±${uncertainty.toFixed(1)}%); CI widens with horizon.`
    });
  }

  // ---------- Von Mises phenology per year ----------
  const byYear = new Map<number, DailyCalendarCell[]>();
  for (const cell of calendar_series) {
    const list = byYear.get(cell.year);
    if (list) list.push(cell);
    else byYear.set(cell.year, [cell]);
  }

  const phenology_by_year: VonMisesPhenologyYear[] = [];
  for (const [year, cells] of byYear) {
    const yearLength = daysInYear(year);
    let c = 0;
    let s = 0;
    let w = 0;
    for (const cell of cells) {
      const theta = (2 * Math.PI * (cell.doy - 1)) / yearLength;
      c += cell.harmonized_fre_mj_km2 * Math.cos(theta);
      s += cell.harmonized_fre_mj_km2 * Math.sin(theta);
      w += cell.harmonized_fre_mj_km2;
    }
    if (w <= 0) continue;
    const mu = Math.atan2(s, c);
    const peakDoy = (((mu / (2 * Math.PI)) * 365.25 + 365.25) % 365.25) + 1;
    const resultant = clamp(Math.hypot(c, s) / w, 1e-6, 0.999999);
    const kappa =
      resultant < 0.53
        ? 2 * resultant + resultant ** 3 + (5 * resultant ** 5) / 6
        : resultant < 0.85
          ? -0.4 + 1.39 * resultant + 0.43 / (1 - resultant)
          : 1 / (resultant ** 3 - 4 * resultant ** 2 + 3 * resultant);
    const circularSdDays = (Math.sqrt(-2 * Math.log(resultant)) * 365.25) / (2 * Math.PI);
    const peakDate = utcDate(year, Math.round(peakDoy));
    phenology_by_year.push({
      year,
      peak_doy_mu: round(peakDoy, 1),
      peak_date_label: `${MONTHS_EN[peakDate.getUTCMonth()]} ${peakDate.getUTCDate()}`,
      concentration_kappa: round(kappa),
      season_width_days: round(2 * circularSdDays, 1),
      total_annual_fre_gj: round((w * areaKm2) / 1000, 1)
    });
  }

  // ---------- Scientific audit metrics computed on the synthetic series ----------
  const fullYears = [...byYear.entries()].filter(([y, cells]) => cells.length >= daysInYear(y) - 1).map(([y]) => y);
  const annualRaw = fullYears.map((y) => byYear.get(y)!.reduce((sum, c) => sum + c.raw_hotspot_count, 0));
  const annualHarm = fullYears.map((y) => byYear.get(y)!.reduce((sum, c) => sum + c.harmonized_fre_mj_km2, 0));
  // Log scale: annual totals have multiplicative (not additive) interannual noise.
  const chowRaw = chowTest(fullYears, annualRaw.map(Math.log1p), 2012);
  const chowHarm = chowTest(fullYears, annualHarm.map(Math.log1p), 2012);

  const preCells = calendar_series.filter((c) => c.year < 2012 && c.raw_hotspot_count > 0);
  const postCells = calendar_series.filter((c) => c.year >= 2012 && c.raw_hotspot_count > 0);
  const meanOf = (vals: number[]) => (vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 1) || 1;
  const preRawMean = meanOf(preCells.map((c) => c.raw_hotspot_count));
  const preHarmMean = meanOf(preCells.map((c) => c.harmonized_fre_mj_km2));
  const w1Raw = wasserstein1(preCells.map((c) => c.raw_hotspot_count / preRawMean), postCells.map((c) => c.raw_hotspot_count / preRawMean));
  const w1Harm = wasserstein1(
    preCells.map((c) => c.harmonized_fre_mj_km2 / preHarmMean),
    postCells.map((c) => c.harmonized_fre_mj_km2 / preHarmMean)
  );

  const baRng = mulberry32(seed ^ 0x5bd1e995);
  const burnedArea = fullYears.map((y) => (trueAnnualFre.get(y) ?? 0) * (1 + 0.08 * gaussian(baRng)));

  const phenoYears = phenology_by_year.filter((p) => fullYears.includes(p.year));
  const slopes: number[] = [];
  let mannKendallS = 0;
  for (let i = 0; i < phenoYears.length; i++) {
    for (let j = i + 1; j < phenoYears.length; j++) {
      const dy = phenoYears[j].peak_doy_mu - phenoYears[i].peak_doy_mu;
      slopes.push(dy / (phenoYears[j].year - phenoYears[i].year));
      mannKendallS += Math.sign(dy);
    }
  }
  const nMk = phenoYears.length;
  const varS = (nMk * (nMk - 1) * (2 * nMk + 5)) / 18;
  const zMk = varS > 0 ? (mannKendallS - Math.sign(mannKendallS)) / Math.sqrt(varS) : 0;

  const totalBiomassKt = calendar_series.reduce((sum, c) => sum + c.biomass_burned_tonnes, 0) / 1000;
  const totalPm25Tonnes = calendar_series.reduce((sum, c) => sum + (c.pm25_emitted_kg ?? 0), 0) / 1000;
  const shiftPerDecade = slopes.length ? median(slopes) * 10 : 0;
  const w1Reduction = w1Raw > 0 ? (1 - w1Harm / w1Raw) * 100 : 0;

  const audit_metrics: ScientificAuditMetrics = {
    chow_test_f_stat_raw: round(chowRaw.f),
    chow_test_p_val_raw: Number(chowRaw.p.toPrecision(3)),
    chow_test_f_stat_harm: round(chowHarm.f),
    chow_test_p_val_harm: Number(chowHarm.p.toPrecision(3)),
    wasserstein_w1_raw: round(w1Raw, 3),
    wasserstein_w1_harm: round(w1Harm, 3),
    burned_area_r2_raw: round(pearsonR2(annualRaw, burnedArea), 3),
    burned_area_r2_harm: round(pearsonR2(annualHarm, burnedArea), 3),
    phenology_shift_days_per_decade: round(shiftPerDecade, 1),
    mann_kendall_p_value: Number((2 * (1 - normalCdf(Math.abs(zMk)))).toPrecision(3)),
    industrial_false_positives_removed: falsePositivesRemoved,
    total_biomass_burned_kt: round(totalBiomassKt, 1),
    total_pm25_emitted_tonnes: round(totalPm25Tonnes, 1),
    executive_verdict_en:
      `[OFFLINE SYNTHETIC] Raw pixel counts show a structural break at Jan 2012 (Chow p=${chowRaw.p.toExponential(1)}); ` +
      `harmonized FRE is homogeneous (p=${chowHarm.p.toFixed(2)}). MODISâ€“VIIRS W1 divergence reduced by ${w1Reduction.toFixed(0)}%. ` +
      `Fire-season peak drifting ${shiftPerDecade >= 0 ? "+" : ""}${shiftPerDecade.toFixed(1)} days/decade.`
  };

  // ---------- Map hexagons ----------
  const meanAnnualTrue = fullYears.length ? fullYears.reduce((s, y) => s + (trueAnnualFre.get(y) ?? 0), 0) / fullYears.length : peakFre * 60;
  const meanRelative = hexes.reduce((s, h) => s + h.relativeEnergy, 0) / Math.max(1, hexes.length);
  const map_hexagons: H3MapSummaryHex[] = hexes.map((h) => ({
    h3_index: h.h3,
    mean_annual_fre: round((meanAnnualTrue * h.relativeEnergy) / meanRelative, 1),
    raw_pixel_count: Math.round(h.relativeEnergy * 40),
    trend_slope: round(h.trend, 2),
    is_industrial_site: h.industrial,
    shannon_entropy: h.industrial ? 0.2 : 1.5 // synthetic placeholder: industrial sites are temporally regular
  }));

  return {
    data_source: "synthetic",
    query_hash: `synthetic_${seed.toString(16).padStart(8, "0")}`,
    execution_time_ms: round(performance.now() - t0, 1),
    aoi_area_km2: round(areaKm2, 1),
    total_h3_cells: map_hexagons.length,
    calendar_series,
    phenology_by_year,
    audit_metrics,
    map_hexagons,
    forecast_series
  };
}

// ---------- /chaos-monkey generator ----------

export function generateSyntheticChaosResponse(request: ChaosMonkeyRequest): ChaosMonkeyResponse {
  const rng = mulberry32(hashString(JSON.stringify(request)));
  const [, lat] = ringCentroid(request.aoi.coordinates[0] ?? []);
  const year = clamp(Math.round(request.target_year ?? 2022), 2001, 2026); // schema defaults
  const n = daysInYear(year);
  const peakDoy = (lat < 0 ? 245 : 212) + PHENOLOGY_SHIFT_DAYS_PER_YEAR * (year - 2001);
  const peakFre = 380 * (0.6 + 0.8 * rng());

  const prior = Array.from({ length: n }, (_, i) => peakFre * vonMisesShape(i + 1, peakDoy, VON_MISES_KAPPA, n) + 0.5);
  const truth = prior.map((p) => p * Math.exp(0.3 * gaussian(rng)));

  // 10-day dual blackout (MODIS + VIIRS) centred on the season peak + random VIIRS drop fraction.
  const dropped = new Set<number>();
  const blackoutStart = clamp(Math.round(peakDoy) - 6, 0, n - 10);
  for (let i = blackoutStart; i < blackoutStart + 10; i++) dropped.add(i);
  const pool = Array.from({ length: n }, (_, i) => i).filter((i) => !dropped.has(i));
  for (let i = pool.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [pool[i], pool[j]] = [pool[j], pool[i]];
  }
  const extra = Math.round(clamp(request.drop_fraction ?? 0.25, 0, 0.9) * n);
  pool.slice(0, extra).forEach((i) => dropped.add(i));

  const naive = truth.map((v, i) => (dropped.has(i) ? 0 : v));

  // RTS-like reconstruction: local observed/prior ratio (Â±15 d) scaled onto the cross-guard prior.
  const reconstructed = truth.map((v, i) => {
    if (!dropped.has(i)) return v;
    let num = 0;
    let den = 0;
    for (let k = Math.max(0, i - 15); k <= Math.min(n - 1, i + 15); k++) {
      if (dropped.has(k)) continue;
      num += truth[k];
      den += prior[k];
    }
    const scale = den > 0 ? num / den : 1;
    return prior[i] * scale;
  });
  const distanceToObservation = (i: number) => {
    let d = 0;
    while (d < n && dropped.has(i - d) && dropped.has(i + d)) d++;
    return d;
  };
  const ciLower = reconstructed.map((v, i) => Math.max(0, v * (1 - (dropped.has(i) ? 0.12 + 0.03 * distanceToObservation(i) : 0.06))));
  const ciUpper = reconstructed.map((v, i) => v * (1 + (dropped.has(i) ? 0.12 + 0.03 * distanceToObservation(i) : 0.06)));

  const droppedIdx = [...dropped].sort((a, b) => a - b);
  const rmse = (series: number[]) =>
    droppedIdx.length ? Math.sqrt(droppedIdx.reduce((s, i) => s + (series[i] - truth[i]) ** 2, 0) / droppedIdx.length) : 0;
  const totalTruth = truth.reduce((a, b) => a + b, 0);
  const totalRecon = reconstructed.reduce((a, b) => a + b, 0);

  return {
    data_source: "synthetic",
    dropped_days_count: droppedIdx.length,
    dropped_dates: droppedIdx.map((i) => isoDate(year, i + 1)),
    dates: Array.from({ length: n }, (_, i) => isoDate(year, i + 1)),
    true_harmonized_fre: truth.map((v) => round(v)),
    corrupted_naive_fre: naive.map((v) => round(v)),
    kalman_reconstructed_fre: reconstructed.map((v) => round(v)),
    reconstructed_ci_lower: ciLower.map((v) => round(v)),
    reconstructed_ci_upper: ciUpper.map((v) => round(v)),
    historical_cross_guard_fre: prior.map((v) => round(v)),
    naive_rmse: round(rmse(naive)),
    kalman_rmse: round(rmse(reconstructed)),
    seasonal_energy_recovered_pct: round(clamp(100 * (1 - Math.abs(totalTruth - totalRecon) / totalTruth), 0, 100), 1)
  };
}
