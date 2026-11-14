"""HTTP routes. CPU-bound endpoints are synchronous `def` so FastAPI runs them in its thread pool."""

from __future__ import annotations

from time import perf_counter

import h3
import numpy as np
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import JSONResponse

from backend.api import core_contract
from backend.api.cache import ANALYZE_CACHE, make_cache_key
from backend.api.schemas import AnalyzeRequest, AnalyzeResponse, ChaosMonkeyRequest, ChaosMonkeyResponse
from backend.db import duckdb_engine
from backend.db.queries import (OBS_COLUMNS, AoiAggregate, fetch_aoi_aggregated_data,
                                get_hierarchical_h3_filter, validate_polygon_topology)

router = APIRouter(prefix="/api")

WOOSTER_KG_PER_MJ = 0.368          # biomass combustion factor (Wooster et al. 2005)
CI_Z_95 = 1.96
CHOW_P_GATE = 0.10                 # AGENTS.md acceptance gate
W1_REDUCTION_GATE_PCT = 88.0       # AGENTS.md acceptance gate
GAP_LABELS = ((1, "Sensor outage"), (2, "Cloud cover >80%"), (4, "Swath gap"), (8, "Dual-sensor blackout"))
SENSOR_BITS = ((1, "Terra"), (2, "Aqua"), (4, "VIIRS"))
EPOCH = np.datetime64("2000-01-01", "D")
FULL_RANGE = (2001, 2026)


# ---------------------------------------------------------------- helpers

def _filter_or_422(coords: list) -> tuple[list[int], list[int], float]:
    try:
        validate_polygon_topology(coords)
        return get_hierarchical_h3_filter(coords)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _core(name: str):
    try:
        return core_contract.require(name)
    except core_contract.CoreMissingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _finite(values, origin: str) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64)
    if not np.all(np.isfinite(arr)):
        raise RuntimeError(f"{origin} returned non-finite values")
    return arr


def _naive_mean(obs: np.ndarray) -> np.ndarray:
    count = np.isfinite(obs).sum(axis=1)
    return np.where(count > 0, np.nansum(obs, axis=1) / np.maximum(count, 1), 0.0)


def _gap_reason(mask: int, no_obs: bool) -> str | None:
    if mask > 0:
        return "; ".join(label for bit, label in GAP_LABELS if mask & bit)
    return "No valid observations" if no_obs else None


def _active_sensors(mask: int, finite_row: list[bool]) -> list[str]:
    if mask < 0:  # sensor_obs_mask column missing: derive from observation availability
        return [name for (_, name), ok in zip(SENSOR_BITS, finite_row) if ok]
    return [name for bit, name in SENSOR_BITS if mask & bit]


def _peak_label(year: int, mu: float) -> str:
    start = np.datetime64(f"{year}-01-01", "D")
    days_in_year = int((np.datetime64(f"{year + 1}-01-01", "D") - start).astype(int))
    offset = min(max(int(round(mu)) - 1, 0), days_in_year - 1)
    return str(start + np.timedelta64(offset, "D"))


def _empty_response(key: str, agg: AoiAggregate, t0: float) -> AnalyzeResponse:
    return AnalyzeResponse.model_validate(dict(
        data_source=duckdb_engine.data_source(), query_hash=key,
        execution_time_ms=(perf_counter() - t0) * 1000, aoi_area_km2=0.0,
        total_h3_cells=len(agg.hexagons), calendar_series=[], forecast_series=None,
        phenology_by_year=[], audit_metrics=None,
        map_hexagons=[h.model_dump() for h in agg.hexagons]))


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
    parts.append("PM2.5, tooltips and the 14-day forecast are not computed in this MVP.")
    if missing:
        parts.append("Cube columns unavailable (served as null): " + ", ".join(missing) + ".")
    return " ".join(parts)


# ---------------------------------------------------------------- routes

@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest, response: Response) -> AnalyzeResponse:
    t0 = perf_counter()
    coords = req.aoi.coordinates
    r4, r7, _ = _filter_or_422(coords)
    key = make_cache_key(r7, {"endpoint": "analyze", **req.model_dump(exclude={"aoi"})},
                         duckdb_engine.cube_path().stat().st_mtime_ns)
    cached = ANALYZE_CACHE.get(key)
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        return cached.model_copy(update={"execution_time_ms": (perf_counter() - t0) * 1000})
    response.headers["X-Cache"] = "MISS"

    agg = fetch_aoi_aggregated_data(r4, r7, req.start_year, req.end_year, req.exclude_industrial_flaring)
    daily = agg.daily
    if len(daily["epoch_day"]) == 0:
        result = _empty_response(key, agg, t0)
        ANALYZE_CACHE.put(key, result)
        return result

    compute_cross_prior = _core("compute_cross_prior")
    kalman_rts_smooth = _core("kalman_rts_smooth")
    fit_von_mises_year = _core("fit_von_mises_year")
    phenology_trend = _core("phenology_trend")
    chow_test = _core("chow_test")
    wasserstein = _core("wasserstein_w1_normalized")
    descriptive_r2 = _core("descriptive_r2")

    missing = duckdb_engine.missing_columns()
    years, doy = daily["year"], daily["doy"]
    obs = np.column_stack([daily[c] for c in OBS_COLUMNS])
    prior366 = _finite(compute_cross_prior(doy, obs), "compute_cross_prior")
    if prior366.shape != (366,):
        raise RuntimeError(f"compute_cross_prior returned shape {prior366.shape}, expected (366,)")
    prior_t = prior366[doy - 1]
    smoothed = kalman_rts_smooth(obs, daily["neighbor_fre_lag1"], prior_t)
    x_smooth = _finite(smoothed.x_smooth, "kalman_rts_smooth.x_smooth")
    p_smooth = _finite(smoothed.p_smooth, "kalman_rts_smooth.p_smooth")
    if np.any(p_smooth < 0):
        raise RuntimeError("kalman_rts_smooth returned negative variances")

    finite = np.isfinite(obs)
    no_obs = ~finite.any(axis=1)
    if req.enable_kalman_gap_filling:
        x = x_smooth
        sd = np.sqrt(p_smooth)
        lower, upper = np.maximum(0.0, x - CI_Z_95 * sd), x + CI_Z_95 * sd
        unc = np.where(np.abs(x) > 1e-8, 100.0 * CI_Z_95 * sd / np.maximum(np.abs(x), 1e-8), 0.0)
    else:
        x = _naive_mean(obs)
        lower = upper = x
        unc = np.zeros(len(x))

    area = float(sum(h3.cell_area(c, unit="km^2") for c in agg.used_cells))
    biomass_t = WOOSTER_KG_PER_MJ * x * area / 1000.0
    resid = x - prior_t
    resid_sd = float(resid.std())
    z = resid / resid_sd if resid_sd > 1e-12 else np.zeros(len(x))
    raw_count = daily["raw_modis_cnt"] + daily["raw_viirs_cnt"]
    gap_mask = daily["gap_status_mask"]
    sensor_mask = daily["sensor_obs_mask"]
    dates = np.datetime_as_string(EPOCH + daily["epoch_day"].astype("timedelta64[D]"))

    calendar = []
    for (date, yr, d, cnt, frp, xv, pv, lo, hi, un, bt, zv, gm, sm, nob, frow) in zip(
            dates.tolist(), years.tolist(), doy.tolist(), raw_count.tolist(), daily["raw_frp_mw"].tolist(),
            x.tolist(), prior_t.tolist(), lower.tolist(), upper.tolist(), unc.tolist(), biomass_t.tolist(),
            z.tolist(), gap_mask.tolist(), sensor_mask.tolist(), no_obs.tolist(), finite.tolist()):
        filled = bool(req.enable_kalman_gap_filling and (gm > 0 or nob))
        calendar.append(dict(
            date=date, year=yr, doy=d, raw_hotspot_count=cnt, raw_frp_mw=frp,
            harmonized_fre_mj_km2=xv, historical_cross_prior_fre=pv, ci_95_lower=lo, ci_95_upper=hi,
            uncertainty_pct=un, biomass_burned_tonnes=bt, pm25_emitted_kg=None, z_score_anomaly=zv,
            is_gap_filled=filled, is_forecast=False, gap_reason=_gap_reason(gm, nob),
            active_sensors=_active_sensors(sm, frow), tooltip_narrative=None))

    phenology, peaks, pheno_years = [], [], []
    for yr in range(req.start_year, req.end_year + 1):
        sel = years == yr
        if not sel.any():
            continue
        mu, kappa, width = (float(v) for v in fit_von_mises_year(doy[sel], x[sel]))
        phenology.append(dict(year=yr, peak_doy_mu=mu, peak_date_label=_peak_label(yr, mu),
                              concentration_kappa=kappa, season_width_days=width,
                              total_annual_fre_gj=float(x[sel].sum() * area / 1000.0)))
        peaks.append(mu)
        pheno_years.append(yr)
    slope, mk_p = (float(v) for v in phenology_trend(np.asarray(pheno_years), np.asarray(peaks)))

    raw_f = raw_count.astype(np.float64)
    chow_raw = tuple(float(v) for v in chow_test(raw_f, years, doy))
    chow_harm = tuple(float(v) for v in chow_test(x, years, doy))
    w_raw, w_harm = float(wasserstein(raw_f, years)), float(wasserstein(x, years))
    if "burned_area_ha_mcd64" in missing:
        r2_raw = r2_harm = None
    else:
        ok = np.isfinite(daily["burned_area_ha_mcd64"])
        burned = daily["burned_area_ha_mcd64"][ok]
        r2_raw, r2_harm = descriptive_r2(raw_f[ok], burned), descriptive_r2(x[ok], burned)
        r2_raw = None if r2_raw is None else float(r2_raw)
        r2_harm = None if r2_harm is None else float(r2_harm)
    source = duckdb_engine.data_source()
    spans_2012 = bool((years < 2012).any() and (years >= 2012).any())
    audit = dict(
        chow_test_f_stat_raw=chow_raw[0], chow_test_p_val_raw=chow_raw[1],
        chow_test_f_stat_harm=chow_harm[0], chow_test_p_val_harm=chow_harm[1],
        wasserstein_w1_raw=w_raw, wasserstein_w1_harm=w_harm,
        burned_area_r2_raw=r2_raw, burned_area_r2_harm=r2_harm,
        phenology_shift_days_per_decade=slope, mann_kendall_p_value=mk_p,
        industrial_false_positives_removed=agg.industrial_false_positives_removed,
        total_biomass_burned_kt=float(biomass_t.sum() / 1000.0), total_pm25_emitted_tonnes=None,
        executive_verdict_en=_verdict(source, chow_raw, chow_harm, w_raw, w_harm, missing, spans_2012))

    payload = dict(
        data_source=source, query_hash=key, aoi_area_km2=area, total_h3_cells=len(agg.hexagons),
        calendar_series=calendar, forecast_series=None, phenology_by_year=phenology,
        audit_metrics=audit, map_hexagons=[h.model_dump() for h in agg.hexagons])
    payload["execution_time_ms"] = (perf_counter() - t0) * 1000
    result = AnalyzeResponse.model_validate(payload)
    ANALYZE_CACHE.put(key, result)
    return result


@router.post("/chaos-monkey", response_model=ChaosMonkeyResponse)
def chaos_monkey(req: ChaosMonkeyRequest) -> ChaosMonkeyResponse:
    r4, r7, _ = _filter_or_422(req.aoi.coordinates)
    agg = fetch_aoi_aggregated_data(r4, r7, FULL_RANGE[0], FULL_RANGE[1], True)
    if len(agg.daily["epoch_day"]) == 0:
        raise HTTPException(status_code=404, detail="No non-industrial fire data inside the AOI")
    simulate = _core("run_chaos_monkey_simulation")
    out = simulate(agg.daily, req.target_year, req.drop_fraction, req.simulate_dual_blackout, req.random_seed)
    return ChaosMonkeyResponse.model_validate({**out, "data_source": duckdb_engine.data_source()})


@router.get("/health")
def health():
    try:
        return {"status": "ok", "duckdb": "ok", "row_count": duckdb_engine.get_row_count(),
                "data_source": duckdb_engine.data_source(), "cube_path": str(duckdb_engine.cube_path()),
                "missing_columns": duckdb_engine.missing_columns(), "core": core_contract.core_status()}
    except Exception as exc:  # report, never hide, engine failures
        return JSONResponse(status_code=503, content={"status": "degraded", "duckdb": str(exc)})
