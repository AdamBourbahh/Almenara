"""Frozen, JSON-safe public API contracts; mirrored in frontend/src/api/types.ts."""

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
        for ring in rings:
            if len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("Polygon rings must be closed with at least four positions.")
            for point in ring:
                if len(point) != 2 or not (-180 <= point[0] <= 180 and -90 <= point[1] <= 90):
                    raise ValueError("Positions must contain valid longitude and latitude.")
        return rings


class AnalyzeRequest(ContractModel):
    aoi: GeoJSONPolygon
    start_year: int = Field(default=2001, ge=2001, le=2026)
    end_year: int = Field(default=2026, ge=2001, le=2026)
    exclude_industrial_flaring: bool = True
    enable_kalman_gap_filling: bool = True
    forecast_days: int = Field(default=14, ge=0, le=14)
    confidence_level: Literal["low", "nominal", "high"] = "nominal"

    @model_validator(mode="after")
    def validate_year_order(self) -> "AnalyzeRequest":
        if self.start_year > self.end_year:
            raise ValueError("start_year must not exceed end_year.")
        return self


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


class ChaosMonkeyRequest(ContractModel):
    aoi: GeoJSONPolygon
    target_year: int = Field(default=2022, ge=2001, le=2026)
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
