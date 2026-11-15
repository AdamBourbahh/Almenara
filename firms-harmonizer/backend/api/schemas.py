"""Frozen, JSON-safe public API contracts; mirrored in frontend/src/api/types.ts."""

from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class GeoJSONPolygon(ContractModel):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[list[float]]]

    @field_validator("coordinates")
    @classmethod
    def validate_rings(cls, rings: list[list[list[float]]]) -> list[list[list[float]]]:
        if not rings:
            raise ValueError("A polygon requires an exterior ring.")
        if len(rings) > 16 or sum(map(len, rings)) > 512:
            raise ValueError("A polygon supports at most 16 rings and 512 positions.")
        for ring in rings:
            if len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("Polygon rings must be closed with at least four positions.")
            for point in ring:
                if len(point) != 2 or not (-180 <= point[0] <= 180 and -90 <= point[1] <= 90):
                    raise ValueError("Positions must contain valid longitude and latitude.")
        return rings


class AnalyzeRequest(ContractModel):
    aoi: GeoJSONPolygon
    start_year: int = Field(default=2001, ge=2000, le=2026)
    end_year: int = Field(default=2026, ge=2000, le=2026)
    exclude_industrial_flaring: bool = True
    enable_kalman_gap_filling: bool = True
    forecast_days: int = Field(default=14, ge=0, le=14)
    confidence_level: Literal["low", "nominal", "high"] = "nominal"

    @model_validator(mode="after")
    def validate_year_order(self) -> "AnalyzeRequest":
        if self.start_year > self.end_year:
            raise ValueError("start_year must not exceed end_year.")
        return self


class RiskPredictionRequest(ContractModel):
    aoi: GeoJSONPolygon
    start_year: int = Field(default=2001, ge=2000, le=2026)
    end_year: int = Field(default=2026, ge=2000, le=2026)
    as_of_date: date | None = None

    @model_validator(mode="after")
    def validate_period(self) -> "RiskPredictionRequest":
        if self.start_year > self.end_year:
            raise ValueError("start_year must not exceed end_year.")
        if self.as_of_date and not self.start_year <= self.as_of_date.year <= self.end_year:
            raise ValueError("as_of_date must fall inside the requested years.")
        if self.as_of_date and self.as_of_date > datetime.now(timezone.utc).date():
            raise ValueError('Forecast origin cannot be in the future.')
        return self


class RiskReliabilityBin(ContractModel):
    samples: int = Field(ge=1)
    mean_predicted_pct: float = Field(ge=0, le=100)
    observed_pct: float = Field(ge=0, le=100)


class RiskValidation(ContractModel):
    samples: int = Field(ge=0)
    positives: int = Field(ge=0)
    brier_score: float | None = Field(ge=0, le=1)
    roc_auc: float | None = Field(ge=0, le=1)
    reliability: list[RiskReliabilityBin]


class RiskModelMetrics(RiskValidation):
    model_weights: dict[str, float]


class RiskDailyProbability(ContractModel):
    date: date
    wildfire_prob_pct: float | None = Field(ge=0, le=100)
    accident_prob_pct: float | None = Field(ge=0, le=100)


class RiskHorizon(ContractModel):
    days: Literal[1, 7, 14]
    wildfire_prob_pct: float | None = Field(ge=0, le=100)
    accident_prob_pct: float | None = Field(ge=0, le=100)
    combined_risk_pct: float | None = Field(ge=0, le=100)
    wildfire_validation: RiskValidation
    accident_validation: RiskValidation
    combined_validation: RiskValidation
    prior_targets: list[Literal["wildfire", "accident", "combined"]] = Field(default_factory=list)


class RiskFactor(ContractModel):
    feature: str
    impact_pct: float = Field(ge=0, le=100)
    direction: Literal["raises", "lowers"]
    description: str


class AIRiskAssessment(ContractModel):
    as_of_date: date
    last_observation_date: date | None = None
    validation_start_date: date
    wildfire_prob_24h_pct: float | None = Field(ge=0, le=100)
    wildfire_prob_7d_pct: float | None = Field(ge=0, le=100)
    industrial_accident_prob_pct: float | None = Field(ge=0, le=100)
    combined_risk_pct: float | None = Field(ge=0, le=100)
    overall_hazard_level: Literal["LOW", "MODERATE", "HIGH", "CRITICAL"] | None
    vegetation_event_threshold_mw: float = Field(gt=0)
    horizons: list[RiskHorizon]
    model_metrics: RiskModelMetrics
    top_risk_factors: list[RiskFactor]
    industrial_risk_factors: list[RiskFactor]
    daily_probability_series: list[RiskDailyProbability]


class RiskPredictionResponse(ContractModel):
    data_source: Literal["real", "synthetic"]
    target: Literal["satellite_thermal_event_proxy"] = "satellite_thermal_event_proxy"
    assessment: AIRiskAssessment | None
    unavailable_reason: str | None = None
    model_time_ms: float = Field(ge=0)
    execution_time_ms: float = Field(ge=0)


class DailyCalendarCell(ContractModel):
    date: str
    year: int
    doy: int
    raw_hotspot_count: int
    raw_frp_mw: float
    harmonized_fre_mj_km2: float
    historical_cross_prior_fre: float
    ci_95_lower: float
    ci_95_upper: float
    uncertainty_pct: float
    biomass_burned_tonnes: float
    pm25_emitted_kg: float | None
    z_score_anomaly: float
    is_gap_filled: bool
    is_forecast: bool
    gap_reason: str | None
    active_sensors: list[str]
    tooltip_narrative: str | None
    observation_status: Literal['detected', 'observed_zero', 'reconstructed', 'unknown', 'forecast'] = 'unknown'
    pm25_factor_sd_kg: float | None = None


class VonMisesPhenologyYear(ContractModel):
    year: int
    peak_doy_mu: float
    peak_date_label: str
    concentration_kappa: float
    season_width_days: float
    total_annual_fre_gj: float


class ScientificAuditMetrics(ContractModel):
    chow_test_f_stat_raw: float
    chow_test_p_val_raw: float
    chow_test_f_stat_harm: float
    chow_test_p_val_harm: float
    wasserstein_w1_raw: float
    wasserstein_w1_harm: float
    burned_area_r2_raw: float | None
    burned_area_r2_harm: float | None
    phenology_shift_days_per_decade: float
    mann_kendall_p_value: float
    industrial_false_positives_removed: int
    total_biomass_burned_kt: float
    total_pm25_emitted_tonnes: float | None
    executive_verdict_en: str


class H3MapSummaryHex(ContractModel):
    h3_index: str = Field(pattern=r"^[0-9a-f]{15}$")
    mean_annual_fre: float
    raw_pixel_count: int
    trend_slope: float
    is_industrial_site: bool
    shannon_entropy: float


class EnergyForecastValidation(ContractModel):
    horizon_days: int
    samples: int
    mae: float
    persistence_mae: float
    climatology_mae: float
    interval_coverage_pct: float


class AnalyzeResponse(ContractModel):
    data_source: Literal["real", "synthetic"]
    query_hash: str
    execution_time_ms: float
    aoi_area_km2: float
    total_h3_cells: int
    calendar_series: list[DailyCalendarCell]
    forecast_series: list[DailyCalendarCell] | None
    phenology_by_year: list[VonMisesPhenologyYear]
    audit_metrics: ScientificAuditMetrics | None
    map_hexagons: list[H3MapSummaryHex]
    coverage_note: str = 'Sparse detections do not establish complete observation coverage.'
    forecast_validation: list[EnergyForecastValidation] = Field(default_factory=list)
    forecast_unavailable_reason: str | None = None


class ChaosMonkeyRequest(ContractModel):
    aoi: GeoJSONPolygon
    target_year: int = Field(default=2022, ge=2000, le=2026)
    drop_fraction: float = Field(default=0.25, ge=0, le=1)
    simulate_dual_blackout: bool = True
    random_seed: int = Field(default=42, ge=0)


class ChaosMonkeyResponse(ContractModel):
    data_source: Literal["real", "synthetic"]
    dropped_days_count: int
    dropped_dates: list[str]
    dates: list[str]
    true_harmonized_fre: list[float]
    corrupted_naive_fre: list[float]
    historical_cross_guard_fre: list[float]
    kalman_reconstructed_fre: list[float]
    reconstructed_ci_lower: list[float]
    reconstructed_ci_upper: list[float]
    naive_rmse: float
    kalman_rmse: float
    seasonal_energy_recovered_pct: float


class CitationReference(ContractModel):
    id: str
    source_type: Literal["NASA_DATASET", "PEER_REVIEWED", "WEB_NEWS_REPORT"] = "PEER_REVIEWED"
    title: str
    authors_or_agency: str
    year: int
    dataset_or_doi: str
    url: str | None = None
    relevance_note: str


class CopilotTurn(ContractModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=6000)


class CopilotMapContext(ContractModel):
    label: str
    aoi: GeoJSONPolygon
    period_start: str
    period_end: str
    h3_index: str | None = None


class ExplainSpikeRequest(ContractModel):
    region_name: str = "Unknown Region"
    selected_day: DailyCalendarCell | None = None
    selected_hex: H3MapSummaryHex | None = None
    user_question: str = Field(default="", max_length=6000)
    aoi: GeoJSONPolygon | None = None
    confidence_level: Literal["low", "nominal", "high"] = "nominal"
    conversation: list[CopilotTurn] = Field(default_factory=list, max_length=10)
    period_start: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    period_end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    prefer_map_context: bool = False
    exclude_industrial_flaring: bool = True
    enable_kalman_gap_filling: bool = True
    previous_context: CopilotMapContext | None = None


class ExplainSpikeResponse(ContractModel):
    physical_classification: str
    explanation_markdown: str
    citations: list[CitationReference] = Field(default_factory=list)
    web_search_used: bool = False
    search_query_executed: str | None = None
    model_used: str = "deterministic-fallback"
    data_source: Literal["real", "synthetic"] = "synthetic"
    map_context: CopilotMapContext | None = None


class CubeSyncRequest(ContractModel):
    days: int | None = Field(default=None, ge=1, le=30)
    sync_full_month: bool = False
    regions: list[str] | None = None


class CubeSyncStatusResponse(ContractModel):
    status: Literal["idle", "in_progress", "success", "error"]
    last_synced_utc: str | None = None
    new_detections_count: int = 0
    date_coverage_start: str | None = None
    date_coverage_end: str | None = None
    regions_updated: list[str] = Field(default_factory=list)
    message: str | None = None
    data_source: Literal["real", "synthetic"] = "real"
    error: str | None = None




class MapPeriodResponse(ContractModel):
    """Spatial observations only; legacy hex energy field is summed over these dates."""

    data_source: Literal["real", "synthetic"]
    start_date: date
    end_date: date
    map_hexagons: list[H3MapSummaryHex]
    execution_time_ms: float


