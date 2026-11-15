"""HTTP routes. CPU-bound endpoints are synchronous `def` so FastAPI runs them in its thread pool.

/api/analyze returns pre-serialized JSON (validated with AnalyzeResponse first) and a Server-Timing header.
All calls into Adam's core go through core_contract.call (resolution + output validation).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from time import perf_counter

from dotenv import load_dotenv

load_dotenv()

import h3.api.basic_int as h3i
import numpy as np
from fastapi import APIRouter, HTTPException, Response, Query
from fastapi.responses import JSONResponse

from backend.api.science_adapter import KalmanInput
from backend.api import core_contract, fire_copilot, copilot_agent
from backend.api.cache import ANALYZE_CACHE, GEOMETRY_CACHE, CachedJSON, LRUCache, geometry_key, make_cache_key
from backend.api.schemas import (AnalyzeRequest, AnalyzeResponse, ChaosMonkeyRequest, ChaosMonkeyResponse,
                                 CubeSyncRequest, CubeSyncStatusResponse,
                                 ExplainSpikeRequest, ExplainSpikeResponse,
                                 GeoJSONPolygon, H3MapSummaryHex, MapPeriodResponse, RiskPredictionRequest, RiskPredictionResponse)
from backend.core.risk_predictor import predict_risk as fit_risk_predictor, with_observation_gap
from backend.db import duckdb_engine, nrt_poller, queries
from backend.db.queries import (OBS_COLUMNS, AoiAggregate, fetch_aoi_aggregated_data,
                                get_hierarchical_h3_filter, validate_polygon_topology)

router = APIRouter(prefix="/api")
RISK_CACHE = LRUCache(16)

WOOSTER_KG_PER_MJ = 0.368          # biomass combustion factor (Wooster et al. 2005)
CI_Z_95 = 1.96
CHOW_P_GATE = 0.10                 # AGENTS.md acceptance gate
W1_REDUCTION_GATE_PCT = 88.0       # AGENTS.md acceptance gate
GAP_LABELS = ((1, "Sensor outage"), (2, "Cloud cover >80%"), (4, "Swath gap"), (8, "Dual-sensor blackout"))
SENSOR_BITS = ((1, "Terra"), (2, "Aqua"), (4, "SNPP"), (8, "NOAA-20"), (16, "NOAA-21"))
FULL_RANGE = (2000, 2026)
JSON_MEDIA_TYPE = "application/json"
MAX_QUESTION_CHARS = 6000
MAX_REGION_NAME_CHARS = 200

# Lookup tables (built once): gap reason per gap mask, sensor list per five-bit code.
GAP_REASON_BY_MASK = {m: "; ".join(label for bit, label in GAP_LABELS if m & bit) or None for m in range(256)}
SENSORS_BY_CODE = [[name for bit, name in SENSOR_BITS if code & bit] for code in range(32)]
NO_OBS_REASON = "No valid observations"


class StageTimer:
    """Accumulates per-stage durations and renders them as a Server-Timing header."""

    def __init__(self) -> None:
        self.stages: dict[str, float] = {}
        self._mark = perf_counter()

    def lap(self, stage: str) -> None:
        now = perf_counter()
        self.stages[stage] = self.stages.get(stage, 0.0) + (now - self._mark) * 1000
        self._mark = now

    def header(self) -> str:
        return ", ".join(f"{name};dur={ms:.2f}" for name, ms in self.stages.items())


# ---------------------------------------------------------------- helpers

def _filter_or_422(coords: list) -> tuple[list[int], list[int], float]:
    key = geometry_key(coords)
    cached = GEOMETRY_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        validate_polygon_topology(coords)
        result = get_hierarchical_h3_filter(coords)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    GEOMETRY_CACHE.put(key, result)
    return result


def _call(timer: StageTimer, name: str, *args):
    """Run a core function through the contract; missing -> 503, contract violation -> 500."""
    timer.lap("build")
    try:
        value, _ = core_contract.call(name, *args)
    except core_contract.CoreMissingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except core_contract.CoreContractViolation as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    timer.lap("core")
    return value


def _naive_mean(obs: np.ndarray) -> np.ndarray:
    count = np.isfinite(obs).sum(axis=1)
    return np.where(count > 0, np.nansum(obs, axis=1) / np.maximum(count, 1), 0.0)


def _peak_label(year: int, mu: float) -> str:
    start = np.datetime64(f"{year}-01-01", "D")
    days_in_year = int((np.datetime64(f"{year + 1}-01-01", "D") - start).astype(int))
    offset = min(max(int(round(mu)) - 1, 0), days_in_year - 1)
    return str(start + np.timedelta64(offset, "D"))


def _verdict(source: str, chow_raw, chow_harm, w_raw, w_harm, missing: list[str], spans_2012: bool) -> str:
    parts = []
    if source == "synthetic":
        parts.append("SYNTHETIC fixture cube — not scientific validation.")
    if spans_2012:
        gate = "PASS" if chow_harm[1] > CHOW_P_GATE else "FAIL"
        parts.append(f"Chow break test at 2012-01-01: raw p={chow_raw[1]:.3g}, harmonized p={chow_harm[1]:.3g} "
                     f"({gate} against the p>{CHOW_P_GATE} gate).")
    else:
        parts.append("Chow test not applicable: the requested years do not span 2012.")
    if w_raw > 0:
        reduction = 100.0 * (1.0 - w_harm / w_raw)
        gate = "PASS" if reduction > W1_REDUCTION_GATE_PCT else "FAIL"
        parts.append(f"Wasserstein-1 {w_raw:.4g} -> {w_harm:.4g} ({reduction:.1f}% reduction; "
                     f"{gate} against the >{W1_REDUCTION_GATE_PCT:.0f}% gate).")
    else:
        parts.append(f"Wasserstein-1 raw={w_raw:.4g}, harmonized={w_harm:.4g}; reduction not defined.")
    parts.append("Burned-area R² values are descriptive squared correlations, not out-of-sample validation.")
    parts.append("Coverage, emissions inputs and forecast skill determine availability; missing inputs remain unavailable.")
    if missing:
        parts.append("Cube columns unavailable (served as null): " + ", ".join(missing) + ".")
    return " ".join(parts)


def _json_response(body: bytes, cache_state: str, timer: StageTimer) -> Response:
    return Response(content=body, media_type=JSON_MEDIA_TYPE,
                    headers={"X-Cache": cache_state, "Server-Timing": timer.header()})


def _finish(key: str, payload: dict, t0: float, timer: StageTimer) -> Response:
    """Validate with the frozen schema, serialize once, cache the bytes and respond."""
    timer.lap("build")
    payload["execution_time_ms"] = (perf_counter() - t0) * 1000
    model = AnalyzeResponse.model_validate(payload)
    timer.lap("validate")
    body = model.model_dump_json().encode()
    ANALYZE_CACHE.put(key, CachedJSON(body))
    timer.lap("serialize")
    return _json_response(body, "MISS", timer)


def _empty_payload(key: str, agg: AoiAggregate) -> dict:
    return dict(data_source=duckdb_engine.data_source(), query_hash=key, aoi_area_km2=0.0,
                total_h3_cells=len(agg.hexagons), calendar_series=[], forecast_series=None,
                phenology_by_year=[], audit_metrics=None, map_hexagons=[h.model_dump() for h in agg.hexagons])


# ---------------------------------------------------------------- routes

@router.post("/predict-risk", response_model=RiskPredictionResponse)
def predict_risk(req: RiskPredictionRequest) -> Response:
    """Train and validate on local AOI history and issue a dated thermal proxy forecast."""
    t0 = perf_counter()
    timer = StageTimer()
    cutoff = req.as_of_date or date(req.end_year, 12, 31)
    cube = duckdb_engine.cube_path()
    key = f"{geometry_key(req.aoi.coordinates)}:{req.start_year}:{req.end_year}:{cutoff}:{cube.stat().st_mtime_ns}:{cube}"
    cached = RISK_CACHE.get(key)
    if cached is not None:
        timer.lap("cache")
        return _json_response(cached.render((perf_counter() - t0) * 1000), "HIT", timer)
    r4, r7, _ = _filter_or_422(req.aoi.coordinates)
    timer.lap("h3")
    cutoff_epoch = (cutoff - date(1970, 1, 1)).days
    daily = queries.fetch_risk_daily(r4, r7, req.start_year, req.end_year, cutoff_epoch)
    timer.lap("db")
    model_start = perf_counter()
    result = None
    if daily:
        last_record = str(queries.EPOCH + np.timedelta64(int(daily["epoch_day"][-1]), "D"))
        series = with_observation_gap(daily, cutoff_epoch) if req.as_of_date else daily
        result = fit_risk_predictor(series)
        if result:
            result["last_observation_date"] = last_record
            if isinstance(result.get("intensity"), dict):
                ratio = queries.fetch_risk_diurnal_ratio(r4, cutoff.month)
                result["intensity"]["diurnal_amplification_ratio"] = None if ratio is None else round(ratio, 2)
    model_time = (perf_counter() - model_start) * 1000
    timer.lap("model")
    reason = None
    if not daily:
        reason = "No local observations in the selected area and date range."
    elif result is None:
        reason = "Insufficient historical coverage or event examples to calibrate a forecast."
    payload = RiskPredictionResponse(
        data_source=duckdb_engine.data_source(), assessment=result, unavailable_reason=reason,
        model_time_ms=model_time, execution_time_ms=(perf_counter() - t0) * 1000,
    )
    body = payload.model_dump_json().encode()
    RISK_CACHE.put(key, CachedJSON(body))
    return _json_response(body, "MISS", timer)


@router.post("/map-period", response_model=MapPeriodResponse)
def map_period(req: AnalyzeRequest, start_date: date, end_date: date) -> Response:
    """Return actual cube rows for a day, month or other inclusive single-year range."""
    if (start_date > end_date or start_date.year != end_date.year
            or not req.start_year <= start_date.year <= req.end_year):
        raise HTTPException(status_code=422, detail="Dates must be ordered, within one year and inside the requested years.")
    t0 = perf_counter()
    timer = StageTimer()
    r4, r7, _ = _filter_or_422(req.aoi.coordinates)
    key = make_cache_key(r7, {"endpoint": "map-period", "start_date": start_date.isoformat(),
                             "end_date": end_date.isoformat(),
                             "confidence_level": req.confidence_level,
                             "exclude_industrial": req.exclude_industrial_flaring},
                         duckdb_engine.cube_path().stat().st_mtime_ns)
    timer.lap("h3")
    cached = ANALYZE_CACHE.get(key)
    if cached is not None:
        return _json_response(cached.render((perf_counter() - t0) * 1000), "HIT", timer)
    epoch = date(1970, 1, 1)
    try:
        hexagons = queries.fetch_map_period(r4, r7, start_date.year,
            ((start_date - epoch).days, (end_date - epoch).days), req.exclude_industrial_flaring, req.confidence_level)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    timer.lap("db")
    payload = MapPeriodResponse(data_source=duckdb_engine.data_source(), start_date=start_date,
        end_date=end_date, map_hexagons=hexagons, execution_time_ms=(perf_counter() - t0) * 1000)
    body = payload.model_dump_json().encode()
    ANALYZE_CACHE.put(key, CachedJSON(body))
    return _json_response(body, "MISS", timer)


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> Response:
    t0 = perf_counter()
    timer = StageTimer()
    r4, r7, _ = _filter_or_422(req.aoi.coordinates)
    artifacts = [duckdb_engine.ROOT / name for name in ('data/processed/observation_coverage',
                 'data/lookup/igbp_cells.parquet', 'data/lookup/cell_day_ancillary.parquet')]
    artifacts += list((duckdb_engine.ROOT / 'data/processed/observation_coverage').glob('preset_*.npz'))
    artifacts += list((duckdb_engine.ROOT / 'data/processed/observation_coverage').glob('land_*.npz'))
    if req.confidence_level != 'nominal':
        artifacts.append(duckdb_engine.cube_path().with_name('fire_cube_' + req.confidence_level + '.parquet'))
    revision = ([path.stat().st_mtime_ns if path.exists() else 0 for path in artifacts]
                if duckdb_engine.data_source() == 'real' else [])
    key = make_cache_key(r7, {"endpoint": "analyze", "geometry": geometry_key(req.aoi.coordinates),
                             "science_revision": revision,
                             **req.model_dump(exclude={"aoi"})},
                         duckdb_engine.cube_path().stat().st_mtime_ns)
    timer.lap("h3")
    cached = ANALYZE_CACHE.get(key)
    if cached is not None:
        body = cached.render((perf_counter() - t0) * 1000)
        timer.lap("cache")
        return _json_response(body, "HIT", timer)

    area = queries.polygon_area_km2(req.aoi.coordinates)
    try:
        agg = fetch_aoi_aggregated_data(r4, r7, req.start_year, req.end_year,
                                       req.exclude_industrial_flaring, area, req.confidence_level)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    timer.lap("db")
    daily = agg.daily
    if len(daily["epoch_day"]) == 0:
        empty = _empty_payload(key, agg)
        empty['aoi_area_km2'] = area
        return _finish(key, empty, t0, timer)

    missing = duckdb_engine.missing_columns()
    years, doy = daily["year"], daily["doy"]
    obs = np.column_stack([daily[c] for c in OBS_COLUMNS])
    observed_density = daily['observed_energy_mj'] / area
    # Fuse within each cell before the spatial sum, rather than averaging disjoint
    # regional sensor footprints. All available channels reference that same sum.
    obs = np.where(np.isfinite(obs), observed_density[:, None], np.nan)
    prior366 = _call(timer, "compute_cross_prior", doy, obs)
    prior_t = prior366[doy - 1]
    smoothed = _call(timer, "kalman_rts_smooth", obs, daily["neighbor_fre_lag1"],
                     KalmanInput(doy, daily["cloud_cover_pct"]))

    finite = np.isfinite(obs)
    no_obs = ~finite.any(axis=1)
    if req.enable_kalman_gap_filling:
        explicit_gap = (daily['gap_status_mask'] > 0) & no_obs
        # Unknown observation coverage is not evidence of an outage. Reconstruct
        # only explicitly evidenced gaps; retain actual zeros as observations.
        x = np.where(explicit_gap, smoothed.x_smooth, observed_density)
        sd = np.sqrt(smoothed.p_smooth)
        lower, upper = np.maximum(0.0, x - CI_Z_95 * sd), x + CI_Z_95 * sd
        unc = np.clip(100.0 * CI_Z_95 * sd / (x + 1.0), 1.0, 99.9)
        filled = explicit_gap
    else:
        x = observed_density
        lower = upper = x
        unc = np.zeros(len(x))
        filled = np.zeros(len(x), dtype=bool)

    biomass_t = WOOSTER_KG_PER_MJ * x * area / 1000.0
    resid = x - prior_t
    resid_sd = float(resid.std())
    z = resid / resid_sd if resid_sd > 1e-12 else np.zeros(len(x))
    raw_count = daily["raw_modis_cnt"] + daily["raw_viirs_cnt"]
    gap_mask = daily["gap_status_mask"]
    if "sensor_obs_mask" in missing:  # derive the sensor code from observation availability
        sensor_code = finite[:, 0] * 1 + finite[:, 1] * 2 + finite[:, 2] * 4
    else:
        sensor_code = daily["sensor_obs_mask"] & 31
    dates = np.datetime_as_string(queries.EPOCH + daily["epoch_day"].astype("timedelta64[D]")).tolist()

    calendar = [
        dict(date=date, year=yr, doy=d, raw_hotspot_count=cnt, raw_frp_mw=frp, harmonized_fre_mj_km2=xv,
             historical_cross_prior_fre=pv, ci_95_lower=lo, ci_95_upper=hi, uncertainty_pct=un,
             biomass_burned_tonnes=bt, pm25_emitted_kg=(float(pm) if np.isfinite(pm) and not fl else None),
             pm25_factor_sd_kg=(float(psd) if np.isfinite(psd) and not fl else None),
             z_score_anomaly=zv, is_gap_filled=fl,
             is_forecast=False,
             gap_reason=GAP_REASON_BY_MASK[gm] if gm > 0 else (NO_OBS_REASON if nob else None),
             active_sensors=SENSORS_BY_CODE[sc],
             observation_status='reconstructed' if fl else 'observed_zero' if oz else 'detected' if not nob else 'unknown',
             tooltip_narrative=('Observed energy is a sampling proxy. Zero reported energy does not establish no fire.'
                                if not fl else 'Reconstruction across an evidenced observation gap.'))
        for date, yr, d, cnt, frp, xv, pv, lo, hi, un, bt, zv, fl, gm, nob, sc, oz, pm, psd in zip(
            dates, years.tolist(), doy.tolist(), raw_count.tolist(), daily["raw_frp_mw"].tolist(), x.tolist(),
            prior_t.tolist(), lower.tolist(), upper.tolist(), unc.tolist(), biomass_t.tolist(), z.tolist(),
            filled.tolist(), gap_mask.tolist(), no_obs.tolist(), sensor_code.tolist(), daily['observed_zero'].tolist(),
            daily['pm25_emitted_kg'].tolist(), daily['pm25_factor_sd_kg'].tolist())
    ]
    phenology, peaks, pheno_years = [], [], []
    for yr in range(req.start_year, req.end_year + 1):
        sel = years == yr
        if not sel.any():
            continue
        mu, kappa, width = _call(timer, "fit_von_mises_year", doy[sel], x[sel])
        phenology.append(dict(year=yr, peak_doy_mu=mu, peak_date_label=_peak_label(yr, mu),
                              concentration_kappa=kappa, season_width_days=width,
                              total_annual_fre_gj=float(x[sel].sum() * area / 1000.0)))
        days_in_year = int((np.datetime64(f'{yr + 1}-01-01') - np.datetime64(f'{yr}-01-01')).astype(int))
        if np.sum(x[sel]) > 0 and kappa > 1e-12 and int(sel.sum()) == days_in_year:
            peaks.append(mu)
            pheno_years.append(yr)
    slope, mk_p = _call(timer, "phenology_trend", np.asarray(pheno_years), np.asarray(peaks))

    annual_years = np.unique(years)
    audit_available = (len(annual_years) > 4 and np.sum(annual_years < 2012) >= 2
                       and np.sum(annual_years >= 2012) >= 2)
    source = duckdb_engine.data_source()
    audit = None
    if audit_available:
        raw_f = raw_count.astype(np.float64)
        chow_raw = _call(timer, "chow_test", raw_f, years, doy)
        chow_harm = _call(timer, "chow_test", x, years, doy)
        w_raw = _call(timer, "wasserstein_w1_normalized", raw_f, years)
        w_harm = _call(timer, "wasserstein_w1_normalized", x, years)
        from backend.db.burned_area import annual_totals
        with duckdb_engine.get_db_cursor() as cursor:
            burned = (annual_totals(duckdb_engine.ROOT, cursor, req.aoi.coordinates, r7, annual_years)
                      if source == 'real' else np.full(len(annual_years), np.nan))
        _, annual_index = np.unique(years, return_inverse=True)
        annual_raw = np.bincount(annual_index, weights=raw_f)
        annual_harm = np.bincount(annual_index, weights=x)
        r2_raw = _call(timer, "descriptive_r2", annual_raw, burned) if np.isfinite(burned).sum() >= 3 else None
        r2_harm = _call(timer, "descriptive_r2", annual_harm, burned) if np.isfinite(burned).sum() >= 3 else None

        spans_2012 = bool((years < 2012).any() and (years >= 2012).any())
        audit = dict(
            chow_test_f_stat_raw=chow_raw[0], chow_test_p_val_raw=chow_raw[1],
            chow_test_f_stat_harm=chow_harm[0], chow_test_p_val_harm=chow_harm[1],
            wasserstein_w1_raw=w_raw, wasserstein_w1_harm=w_harm,
            burned_area_r2_raw=r2_raw, burned_area_r2_harm=r2_harm,
            phenology_shift_days_per_decade=slope, mann_kendall_p_value=mk_p,
            industrial_false_positives_removed=agg.industrial_false_positives_removed,
            total_biomass_burned_kt=float(biomass_t.sum() / 1000.0),
            total_pm25_emitted_tonnes=(sum(c['pm25_emitted_kg'] or 0 for c in calendar) / 1000
                if all(c['pm25_emitted_kg'] is not None for c in calendar if c['observation_status'] != 'unknown') else None),
            executive_verdict_en=_verdict(source, chow_raw, chow_harm, w_raw, w_harm, missing, spans_2012))
    payload = dict(
        data_source=source, query_hash=key, aoi_area_km2=area, total_h3_cells=len(agg.hexagons),
        calendar_series=calendar, forecast_series=None, phenology_by_year=phenology,
        audit_metrics=audit, map_hexagons=[h.model_dump() for h in agg.hexagons])
    if req.forecast_days:
        from backend.core.energy_forecast import project
        from backend.core.coverage_policy import assess
        from backend.db.land_coverage import load
        training = np.where(daily['observation_known'] | filled, x, np.nan)
        coverage = (load(duckdb_engine.ROOT, r7, daily['epoch_day']) if source == 'real'
                    else daily['coverage_complete'].astype(float))
        policy = assess(dates, training, coverage)
        threshold = policy['selected_threshold']
        payload['coverage_note'] = ('Terrestrial area weighted union of qualified cells across sensors; '
            'sampled coverage proxy using preceding-year measured land/water pixels. '
            'Unknown land fractions remain unavailable. Coverage threshold selected on temporal validation.')
        if threshold is None:
            payload['forecast_unavailable_reason'] = policy['reason']
        else:
            chosen = next(c for c in policy['candidates'] if c['threshold'] == threshold)
            validation = [{k:v for k,v in m.items() if k != 'bias'} for m in chosen['holdout']['metrics']]
            payload['forecast_validation'] = validation
            supported = len(validation) == 3 and all(m['samples'] >= 12 and
                m['mae'] <= min(m['persistence_mae'], m['climatology_mae']) + 1e-12
                and m['interval_coverage_pct'] >= 90 for m in validation)
            prediction = project(dates, np.where(coverage>=threshold,training,np.nan), req.forecast_days) if supported else None
            if prediction is None:
                payload['forecast_unavailable_reason'] = 'Rolling-origin forecast has insufficient samples or does not outperform both baselines.'
            else:
                forecast = []
                for k, day in enumerate(prediction['dates']):
                    date_value = date.fromisoformat(str(day))
                    value = float(prediction['predicted'][k])
                    forecast.append(dict(date=str(day), year=date_value.year, doy=date_value.timetuple().tm_yday,
                        raw_hotspot_count=0, raw_frp_mw=0, harmonized_fre_mj_km2=value,
                        historical_cross_prior_fre=float(prediction['seasonal'][k]),
                        ci_95_lower=float(prediction['lower'][k]), ci_95_upper=float(prediction['upper'][k]),
                        uncertainty_pct=float(min(100, 100 * (prediction['upper'][k] - value) / (value + 1))),
                        biomass_burned_tonnes=WOOSTER_KG_PER_MJ * value * area / 1000,
                        pm25_emitted_kg=None, z_score_anomaly=0, is_gap_filled=False, is_forecast=True,
                        gap_reason=None, active_sensors=[], observation_status='forecast',
                        tooltip_narrative='Causal seasonal/AR forecast of sampled thermal energy, not an ignition prediction.'))
                payload['forecast_series'] = forecast
    return _finish(key, payload, t0, timer)


@router.post("/chaos-monkey", response_model=ChaosMonkeyResponse)
def chaos_monkey(req: ChaosMonkeyRequest) -> ChaosMonkeyResponse:
    r4, r7, _ = _filter_or_422(req.aoi.coordinates)
    agg = fetch_aoi_aggregated_data(r4, r7, FULL_RANGE[0], FULL_RANGE[1], True)
    if len(agg.daily["epoch_day"]) == 0:
        raise HTTPException(status_code=404, detail="No non-industrial fire data inside the AOI")
    if not np.any(agg.daily["year"] == req.target_year):
        raise HTTPException(status_code=404, detail="No fire data in the requested target year")
    out = _call(StageTimer(), "run_chaos_monkey_simulation", agg.daily, req.target_year, req.drop_fraction,
                req.simulate_dual_blackout, req.random_seed)
    return ChaosMonkeyResponse.model_validate({**out, "data_source": duckdb_engine.data_source()})


@router.get("/health")
def health():
    try:
        return {"status": "ok", "duckdb": "ok", "row_count": duckdb_engine.get_row_count(),
                "data_source": duckdb_engine.data_source(), "cube_path": str(duckdb_engine.cube_path()),
                "missing_columns": duckdb_engine.missing_columns(), "core": core_contract.core_status(),
                "core_signatures": core_contract.signature_issues(), "nrt": nrt_poller.get_nrt_status()}
    except Exception as exc:  # report, never hide, engine failures
        return JSONResponse(status_code=503, content={"status": "degraded", "duckdb": str(exc)})


@router.post('/observations')
def observations(aoi: GeoJSONPolygon, offset: Annotated[int, Query(ge=0)] = 0,
                 limit: Annotated[int, Query(ge=1, le=1000)] = 366):
    """Observed detections only; no Kalman, climatology, forecast or emissions."""
    t0 = perf_counter()
    r4, r7, _ = _filter_or_422(aoi.coordinates)
    try:
        data = queries.fetch_observed_detections(r4, r7, 2000, 2026)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {**data, 'daily': data['daily'][offset:offset + limit], 'map_hexagons': [],
            'offset': offset, 'limit': limit, 'total_days': len(data['daily']),
            'data_source': 'real', 'execution_time_ms': (perf_counter()-t0)*1000,
            'total_detections': sum(d['detection_count'] for d in data['daily']),
            'first_observed_date': data['daily'][0]['date'] if data['daily'] else None,
            'last_observed_date': data['daily'][-1]['date'] if data['daily'] else None,
            'method': 'Accepted, deduplicated FIRMS detection centers. FRP is instantaneous MW summed across detections; it is not energy. Missing days have no reported detections and do not establish zero fire activity. No gap filling or prediction.'}


@router.post("/explain-spike", response_model=ExplainSpikeResponse)
def explain_spike(req: ExplainSpikeRequest) -> ExplainSpikeResponse:
    """Answer using retrieved observations and explicitly attributed reports."""
    if req.aoi is not None:
        _filter_or_422(req.aoi.coordinates)
    return copilot_agent.answer(req)


@router.post("/cube/sync", response_model=CubeSyncStatusResponse)
def trigger_cube_sync(req: CubeSyncRequest = CubeSyncRequest()) -> CubeSyncStatusResponse:
    """Synchronize live NASA FIRMS detections for preset regions into the master cube."""
    if req.regions and any(name not in nrt_poller.get_configured_regions() for name in req.regions):
        raise HTTPException(status_code=422, detail='Choose only registered study regions.')
    result = nrt_poller.schedule_sync(
        days=req.days,
        sync_full_month=req.sync_full_month,
        regions=req.regions,
    )
    return CubeSyncStatusResponse.model_validate(result)


@router.get("/cube/sync-status", response_model=CubeSyncStatusResponse)
def get_cube_sync_status() -> CubeSyncStatusResponse:
    """Return the current synchronization status and latest sync metrics."""
    result = nrt_poller.get_sync_status()
    return CubeSyncStatusResponse.model_validate(result)

