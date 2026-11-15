"""Comprehensive unit, integration, and contract tests for the classical AI fire risk model.

Covers:
- Causal feature engineering (build_causal_features) and edge cases
  (NaN inputs, zero FRP, high cloud cover, sensor gaps, quiet spell interactions, boundary lengths)
- Base classifiers (LogisticHazardModel, BoostedTreesHazardModel, IndustrialAccidentClassifier)
- Multi-horizon risk predictions (24h, 7d, 14d) and monotonic horizon ordering
- Fréchet probability bounds on combined hazard
- Model ensemble weights dictionary (logistic, boosted_stumps, gaussian_naive_bayes)
- Validation metrics (Brier score, ROC-AUC, reliability calibration bins)
- Top risk factor drivers and directionality
- /api/predict-risk HTTP endpoint contract, caching behavior, and unavailable reason handling.
"""

from datetime import date
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import routes
from backend.api.main import app
from backend.api.schemas import RiskPredictionResponse
from backend.core.risk_predictor import (
    FEATURES,
    HORIZONS,
    MIN_DAYS,
    MAX_DAYS,
    MODEL_NAMES,
    BoostedTreesHazardModel,
    IndustrialAccidentClassifier,
    LogisticHazardModel,
    build_causal_features,
    predict_risk,
)

AOI_TEST = {
    "type": "Polygon",
    "coordinates": [[
        [-57.2, -17.8], [-55.2, -17.8], [-55.2, -16.0], [-57.2, -16.0], [-57.2, -17.8]
    ]]
}


def _make_daily_fixture(n: int = 1800, seed: int = 42) -> dict[str, np.ndarray]:
    """Generate a realistic synthetic daily time series with seasonal cycles and excursions."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    # Annual seasonal pattern with peak around DOY 240
    phase = (t % 365.25) / 365.25
    seasonal = np.maximum(0, np.cos(2 * np.pi * (phase - 240 / 365.25)))
    vegetation = 1.0 + 80.0 * seasonal + rng.uniform(0, 8.0, n)
    neighbor = vegetation * 0.85 + rng.normal(0, 2.0, n)
    neighbor = np.maximum(0, neighbor)

    # Sporadic industrial thermal excursions
    excursions = np.where((t % 61 < 5) & (rng.uniform(0, 1, n) > 0.4), 6.5, 0.0)

    # Occasional cloud cover and sensor gaps
    cloud = np.where(rng.uniform(0, 1, n) > 0.8, rng.uniform(0.5, 1.0, n), np.nan)
    gap = np.where(rng.uniform(0, 1, n) > 0.95, 1, 0)

    return {
        "epoch_day": 18628 + t,
        "vegetation_frp": vegetation,
        "neighbor_frp": neighbor,
        "industrial_z": excursions,
        "persistent_share": np.full(n, 0.08),
        "cloud": cloud,
        "gap": gap,
    }


# =====================================================================
# 1. Feature Builder (build_causal_features) Edge Cases & Invariance
# =====================================================================

def test_feature_builder_output_shape_and_finiteness():
    daily = _make_daily_fixture(1000)
    features = build_causal_features(daily)
    assert features.shape == (1000, len(FEATURES))
    assert np.isfinite(features).all()
    assert len(FEATURES) == 14


def test_feature_builder_strict_causal_prefix_invariance():
    """Row t of features must depend strictly on observations at or before day t."""
    daily = _make_daily_fixture(1200)
    full_features = build_causal_features(daily)

    # Check multiple prefixes
    for prefix_len in (365, 500, 800, 1100):
        sub_daily = {k: v[:prefix_len] for k, v in daily.items()}
        prefix_features = build_causal_features(sub_daily)
        np.testing.assert_allclose(
            prefix_features,
            full_features[:prefix_len],
            rtol=1e-7,
            atol=1e-7,
            err_msg=f"Causal leakage detected for prefix length {prefix_len}"
        )


def test_feature_builder_nan_and_infinite_resilience():
    """Model must remain robust when inputs contain heavy NaNs or infinite values."""
    daily = _make_daily_fixture(800)
    # Inject NaNs and Infs across various channels
    daily["vegetation_frp"][50:100] = np.nan
    daily["vegetation_frp"][200:220] = np.inf
    daily["neighbor_frp"][10:30] = np.nan
    daily["neighbor_frp"][150:160] = -np.inf
    daily["industrial_z"][300:350] = np.nan
    daily["cloud"][:] = np.nan
    daily["persistent_share"][400:450] = np.nan

    features = build_causal_features(daily)
    assert features.shape == (800, 14)
    assert np.isfinite(features).all()
    assert not np.isnan(features).any()
    assert not np.isinf(features).any()


def test_feature_builder_zero_frp_everywhere():
    """Complete absence of fire (all zero FRP) should not divide by zero."""
    n = 500
    daily = {
        "epoch_day": 18628 + np.arange(n),
        "vegetation_frp": np.zeros(n),
        "neighbor_frp": np.zeros(n),
        "industrial_z": np.zeros(n),
        "persistent_share": np.zeros(n),
        "cloud": np.zeros(n),
        "gap": np.zeros(n),
    }
    features = build_causal_features(daily)
    assert features.shape == (n, 14)
    assert np.isfinite(features).all()
    # Thermal anomaly and buildup should be cleanly zeroed or bounded
    assert np.all(features[:, 0] == 0)  # neighbor contagion = log1p(0) = 0
    assert np.all(features[:, 1] == 0)  # 3-day buildup = 0
    assert np.all(features[:, 2] == 0)  # 7-day buildup = 0


def test_feature_builder_high_cloud_cover_and_missing_ancillary():
    """Verify cloud cover feature handling for overcast conditions and missing ancillary data."""
    daily = _make_daily_fixture(600)
    # Day 0-299: 100% overcast cloud cover (1.0)
    daily["cloud"][:300] = 1.0
    # Day 300-599: Completely missing cloud data (NaN)
    daily["cloud"][300:] = np.nan

    features = build_causal_features(daily)
    cloud_col = features[:, 10]
    np.testing.assert_allclose(cloud_col[:300], 1.0)
    np.testing.assert_allclose(cloud_col[300:], 0.0)  # nan_to_num converts NaN cloud to 0


def test_feature_builder_sensor_gap_and_uncertainty_metric():
    """Sensor gaps (gap != 0) or unobserved days must raise trailing observation uncertainty."""
    daily = _make_daily_fixture(500)
    daily["gap"][:] = 0
    daily["vegetation_frp"][:] = 10.0

    # Feature 11 is 'Observation uncertainty' = rolling 7-day mean of (~seen | gap != 0)
    f_clean = build_causal_features(daily)
    np.testing.assert_allclose(f_clean[:, 11], 0.0)

    # Introduce a 7-day contiguous gap
    daily["gap"][100:107] = 1
    f_gapped = build_causal_features(daily)
    assert f_gapped[106, 11] == pytest.approx(1.0)  # 7 out of 7 trailing days uncertain
    assert f_gapped[110, 11] == pytest.approx(3 / 7)  # moving past gap


def test_feature_builder_quiet_spell_and_rising_heat_interaction():
    """Interaction feature: quiet spell preceded by rising neighbor heat."""
    n = 400
    daily = {
        "epoch_day": 18628 + np.arange(n),
        "vegetation_frp": np.full(n, 1.0),  # quiet: 1.0 < log1p(5) ~ 1.79
        "neighbor_frp": np.zeros(n),
        "industrial_z": np.zeros(n),
        "persistent_share": np.zeros(n),
        "cloud": np.zeros(n),
        "gap": np.zeros(n),
    }
    # Before day 50: no rising heat
    # At day 50: neighbor heat spikes from 0 to 50
    daily["neighbor_frp"][50] = 50.0

    features = build_causal_features(daily)
    # Feature 9: "Quiet spell and rising heat" = log1p(quiet_before) * rising
    assert features[49, 9] == 0.0
    assert features[50, 9] > 0.0  # Spike after 49 quiet days
    assert features[51, 9] == 0.0  # Delta is 0 on day 51


# =====================================================================
# 2. Base Classifiers Unit Tests
# =====================================================================

def test_logistic_hazard_model_regularization_and_bounds():
    """L2-regularized logistic regression converges and yields valid logits."""
    rng = np.random.default_rng(123)
    x = rng.normal(0, 1, size=(200, 5))
    # Synthetic label with positive association to x[:, 0]
    p_true = 1.0 / (1.0 + np.exp(-1.5 * x[:, 0]))
    y = rng.uniform(0, 1, size=200) < p_true

    model = LogisticHazardModel().fit(x, y, penalty=2.0, iterations=8)
    logits = model.predict_logits(x)
    assert logits.shape == (200,)
    assert np.isfinite(logits).all()
    # Weights should not blow up
    assert np.abs(model.weights).max() < 10.0


def test_boosted_trees_hazard_model_fitting():
    """Boosted decision stumps fit threshold masks and predict logits."""
    rng = np.random.default_rng(456)
    x = rng.uniform(0, 10, size=(300, 3))
    y = (x[:, 0] > 5.0) & (rng.uniform(0, 1, size=300) > 0.3)

    # Build masks at quantiles
    quantiles = np.quantile(x, [0.25, 0.5, 0.75], axis=0)
    thresholds = [(col, q) for col in range(3) for q in quantiles[:, col]]
    columns = np.array([col for col, _ in thresholds], dtype=int)
    cuts = np.array([q for _, q in thresholds])
    masks = x[:, columns] <= cuts

    model = BoostedTreesHazardModel().fit(masks, thresholds, y)
    logits = model.predict_logits(x)
    assert logits.shape == (300,)
    assert np.isfinite(logits).all()
    assert len(model.stumps) <= 8


def test_industrial_accident_classifier_shrinkage():
    """Gaussian Naive Bayes with variance shrinkage avoids zero-variance singularities."""
    rng = np.random.default_rng(789)
    x = rng.normal(0, 1, size=(250, 4))
    # Make feature 1 identical for all samples (zero variance)
    x[:, 1] = 3.14
    y = rng.uniform(0, 1, size=250) > 0.7

    model = IndustrialAccidentClassifier().fit(x, y)
    assert np.all(model.variances > 0.1)  # 0.85 * var + 0.15 >= 0.15
    logits = model.predict_logits(x)
    assert logits.shape == (250,)
    assert np.isfinite(logits).all()


# =====================================================================
# 3. Multi-Horizon Risk Predictor & Monotonic Behavior
# =====================================================================

def test_predict_risk_horizons_structure_and_monotonicity():
    """Test 24h, 7d, and 14d horizon structure and cumulative monotonic probability ordering."""
    daily = _make_daily_fixture(2000, seed=101)
    result = predict_risk(daily)
    assert result is not None

    horizons = result["horizons"]
    assert len(horizons) == 3
    assert [h["days"] for h in horizons] == list(HORIZONS)

    for h in horizons:
        assert isinstance(h["days"], int) and h["days"] in (1, 7, 14)
        for key in ("wildfire_prob_pct", "accident_prob_pct", "combined_risk_pct"):
            val = h[key]
            if val is not None:
                assert 0.0 <= val <= 100.0

    # Cumulative hazard monotonicity: P(event in 14d) >= P(event in 7d) >= P(event in 24h)
    wildfire_probs = [h["wildfire_prob_pct"] for h in horizons if h["wildfire_prob_pct"] is not None]
    if len(wildfire_probs) == 3:
        assert wildfire_probs[0] <= wildfire_probs[1] <= wildfire_probs[2] + 1e-6

    accident_probs = [h["accident_prob_pct"] for h in horizons if h["accident_prob_pct"] is not None]
    if len(accident_probs) == 3:
        assert accident_probs[0] <= accident_probs[1] <= accident_probs[2] + 1e-6

    combined_probs = [h["combined_risk_pct"] for h in horizons if h["combined_risk_pct"] is not None]
    if len(combined_probs) == 3:
        assert combined_probs[0] <= combined_probs[1] <= combined_probs[2] + 1e-6


def test_predict_risk_frechet_bounds_on_combined_hazard():
    """Combined risk must obey Fréchet probability bounds: max(P1, P2) <= P(1 or 2) <= P1 + P2."""
    daily = _make_daily_fixture(2200, seed=202)
    result = predict_risk(daily)
    assert result is not None

    for h in result["horizons"]:
        wf = h["wildfire_prob_pct"]
        acc = h["accident_prob_pct"]
        comb = h["combined_risk_pct"]
        if wf is not None and acc is not None and comb is not None:
            assert comb >= max(wf, acc) - 1e-6
            assert comb <= min(100.0, wf + acc) + 1e-6


def test_predict_risk_model_ensemble_weights_dictionary():
    """Model ensemble weights must include logistic, boosted_stumps, and gaussian_naive_bayes."""
    daily = _make_daily_fixture(1800, seed=303)
    result = predict_risk(daily)
    assert result is not None

    weights = result["model_metrics"]["model_weights"]
    assert isinstance(weights, dict)
    assert set(weights.keys()) == set(MODEL_NAMES)
    for model_name, weight in weights.items():
        assert isinstance(weight, float)
        assert np.isfinite(weight)


def test_predict_risk_calibration_and_reliability_bins():
    """Validation metrics must compute Brier score, ROC-AUC, and properly partitioned reliability bins."""
    daily = _make_daily_fixture(2000, seed=404)
    result = predict_risk(daily)
    assert result is not None

    metrics = result["model_metrics"]
    assert metrics["samples"] > 0
    assert 0.0 <= metrics["brier_score"] <= 1.0
    if metrics["roc_auc"] is not None:
        assert 0.0 <= metrics["roc_auc"] <= 1.0

    reliability = metrics["reliability"]
    assert isinstance(reliability, list)
    for bin_info in reliability:
        assert bin_info["samples"] >= 1
        assert 0.0 <= bin_info["mean_predicted_pct"] <= 100.0
        assert 0.0 <= bin_info["observed_pct"] <= 100.0


def test_predict_risk_overall_hazard_level_thresholds():
    """Overall hazard level corresponds strictly to LOW / MODERATE / HIGH / CRITICAL intervals."""
    daily = _make_daily_fixture(1800, seed=505)
    result = predict_risk(daily)
    assert result is not None

    level = result["overall_hazard_level"]
    risk = result["combined_risk_pct"]
    assert level in ("LOW", "MODERATE", "HIGH", "CRITICAL")
    if risk < 20:
        assert level == "LOW"
    elif risk < 50:
        assert level == "MODERATE"
    elif risk < 75:
        assert level == "HIGH"
    else:
        assert level == "CRITICAL"


def test_predict_risk_top_drivers_structure_and_directionality():
    """Top risk factors must provide up to 4 drivers with normalized positive impact and valid directions."""
    daily = _make_daily_fixture(1800, seed=606)
    result = predict_risk(daily)
    assert result is not None

    drivers = result["top_risk_factors"]
    assert len(drivers) <= 4
    if drivers:
        total_impact = sum(d["impact_pct"] for d in drivers)
        assert total_impact <= 100.001
        for d in drivers:
            assert d["direction"] in ("raises", "lowers")
            assert 0.0 <= d["impact_pct"] <= 100.0
            assert any(d["feature"] == name for name, _ in FEATURES)


def test_predict_risk_boundary_lengths_and_exceptions():
    """Test boundary lengths: MIN_DAYS (365), below MIN_DAYS, MAX_DAYS (9500), and non-consecutive days."""
    # Under minimum: use only the causal fallback.
    short_daily = _make_daily_fixture(MIN_DAYS - 1)
    assert predict_risk(short_daily)["horizons"][0]["prior_targets"] == ["wildfire", "accident", "combined"]

    # Exceeding maximum: 9501 days raises ValueError
    too_long = _make_daily_fixture(MAX_DAYS + 1)
    with pytest.raises(ValueError, match="at most 9,500"):
        predict_risk(too_long)

    # Non-consecutive epoch days raises ValueError
    non_consec = _make_daily_fixture(500)
    non_consec["epoch_day"][200] += 5  # gap in epoch_day sequence
    with pytest.raises(ValueError, match="consecutive UTC days"):
        predict_risk(non_consec)


def test_predict_risk_empty_reference_frp():
    """An empty reference uses the declared 1 MW threshold."""
    daily = _make_daily_fixture(800)
    daily["vegetation_frp"][:200] = 0.0  # First 20% has zero positive reference
    assert predict_risk(daily)["vegetation_event_threshold_mw"] == 1.0


# =====================================================================
# 4. HTTP API Endpoint Integration & Caching (/api/predict-risk)
# =====================================================================

@pytest.fixture
def api_client():
    routes.RISK_CACHE.clear()
    with TestClient(app) as client:
        yield client


def test_api_predict_risk_contract_and_schema_validation(api_client):
    """Ensure the API response adheres 100% to the frozen RiskPredictionResponse schema."""
    resp = api_client.post("/api/predict-risk", json={"aoi": AOI_TEST, "as_of_date": "2023-08-01"})
    assert resp.status_code == 200, resp.text
    parsed = RiskPredictionResponse.model_validate(resp.json())

    assert parsed.data_source in ("real", "synthetic")
    assert parsed.target == "satellite_thermal_event_proxy"
    assert parsed.execution_time_ms >= 0
    assert parsed.model_time_ms >= 0

    if parsed.assessment:
        assert parsed.assessment.as_of_date == date(2023, 8, 1)
        assert len(parsed.assessment.horizons) == 3
        assert parsed.assessment.model_metrics.samples > 0
        assert set(parsed.assessment.model_metrics.model_weights.keys()) == set(MODEL_NAMES)


def test_api_predict_risk_caching_and_invalidation(api_client):
    """Test cache MISS on first call, HIT on identical call, and MISS on parameter changes."""
    payload_a = {"aoi": AOI_TEST, "start_year": 2020, "end_year": 2023, "as_of_date": "2023-07-15"}
    first = api_client.post("/api/predict-risk", json=payload_a)
    assert first.status_code == 200
    assert first.headers["X-Cache"] == "MISS"

    # Second call with identical payload must be a cache HIT
    second = api_client.post("/api/predict-risk", json=payload_a)
    assert second.status_code == 200
    assert second.headers["X-Cache"] == "HIT"

    # Changing as_of_date must cause a cache MISS
    payload_b = {**payload_a, "as_of_date": "2023-07-16"}
    third = api_client.post("/api/predict-risk", json=payload_b)
    assert third.status_code == 200
    assert third.headers["X-Cache"] == "MISS"

    # Changing start_year must cause a cache MISS
    payload_c = {**payload_a, "start_year": 2021}
    fourth = api_client.post("/api/predict-risk", json=payload_c)
    assert fourth.status_code == 200
    assert fourth.headers["X-Cache"] == "MISS"


def test_api_predict_risk_unavailable_reason_empty_region(api_client):
    """An ocean polygon with no observations returns 200 with clear unavailable_reason."""
    ocean_polygon = {
        "type": "Polygon",
        "coordinates": [[
            [-30.0, -30.0], [-29.0, -30.0], [-29.0, -29.0], [-30.0, -29.0], [-30.0, -30.0]
        ]]
    }
    resp = api_client.post("/api/predict-risk", json={"aoi": ocean_polygon})
    assert resp.status_code == 200
    data = resp.json()
    assert data["assessment"] is None
    assert data["unavailable_reason"] == "No local observations in the selected area and date range."


def test_api_predict_risk_invalid_parameters_rejected(api_client):
    """Validate 422 HTTP unprocessable entity errors on malformed parameters."""
    # start_year > end_year
    bad_order = api_client.post("/api/predict-risk", json={"aoi": AOI_TEST, "start_year": 2024, "end_year": 2021})
    assert bad_order.status_code == 422

    # as_of_date outside of start_year - end_year range
    out_of_range = api_client.post(
        "/api/predict-risk",
        json={"aoi": AOI_TEST, "start_year": 2020, "end_year": 2022, "as_of_date": "2025-06-01"}
    )
    assert out_of_range.status_code == 422


def test_sparse_prediction_reports_prior_and_honest_metrics():
    daily = _make_daily_fixture(80)
    daily["vegetation_frp"][:] = 0
    daily["industrial_z"][:] = 0
    result = predict_risk(daily)
    assert result["overall_hazard_level"] == "LOW"
    assert result["model_metrics"]["model_weights"] == {"causal_prior": 1.0}
    assert result["top_risk_factors"]
    assert result["daily_probability_series"]
    for horizon in result["horizons"]:
        assert horizon["prior_targets"] == ["wildfire", "accident", "combined"]
        assert 0 < horizon["wildfire_prob_pct"] <= horizon["combined_risk_pct"] < 20
        assert horizon["accident_prob_pct"] > 0
        assert horizon["wildfire_validation"]["roc_auc"] is None
    assert result["model_metrics"]["brier_score"] is not None


def test_single_day_prior_omits_validation_without_outcomes():
    result = predict_risk(_make_daily_fixture(1))
    assert len(result["daily_probability_series"]) == 1
    assert all(0 <= h["combined_risk_pct"] <= 100 for h in result["horizons"])
    assert result["model_metrics"]["brier_score"] is None


def test_blackout_forecast_ignores_hidden_readings_and_uses_the_requested_origin():
    from backend.core.risk_predictor import with_observation_gap

    daily = _make_daily_fixture(1800)
    visible = {key: values[:-7] for key, values in daily.items()}
    origin = int(daily["epoch_day"][-1])
    blinded = with_observation_gap(visible, origin)
    assert all(np.isnan(blinded[name][-7:]).all()
               for name in ("vegetation_frp", "neighbor_frp", "industrial_z", "persistent_share", "cloud"))
    assert np.all(blinded["gap"][-7:] == 1)
    forecast = predict_risk(blinded)
    daily["vegetation_frp"][-7:] *= 1000
    daily["industrial_z"][-7:] = 1000
    changed = with_observation_gap({key: values[:-7] for key, values in daily.items()}, origin)
    assert predict_risk(changed) == forecast
    assert forecast["daily_probability_series"][-1]["date"] == forecast["as_of_date"]
    for horizon in forecast["horizons"]:
        assert 0 <= horizon["combined_risk_pct"] <= 100


# =====================================================================
# 5. Seasonal base rate, Markov horizons, decomposition and telemetry
# =====================================================================

EPOCH_2012 = 15340  # 2012-01-01
PEAK_DOY = 230


def _seasonal_daily(end_doy: int, years: int = 10, seed: int = 7) -> dict[str, np.ndarray]:
    """Strongly seasonal record: multi-day fire episodes only between DOY 200 and 260.

    Episodes ignite with a seasonal probability, persist from day to day and carry
    an autocorrelated log-intensity, so current heat is informative about tomorrow.
    """
    rng = np.random.default_rng(seed)
    n = 365 * (years - 1) + (years - 1) // 4 + end_doy
    epoch = EPOCH_2012 + np.arange(n)
    dates = np.datetime64("1970-01-01") + epoch.astype("timedelta64[D]")
    doy = (dates - dates.astype("datetime64[Y]")).astype(int) + 1
    bell = np.exp(-0.5 * ((doy - PEAK_DOY) / 12.0) ** 2) * (np.abs(doy - PEAK_DOY) <= 30)
    vegetation = np.zeros(n)
    burning, level = False, 0.0
    for t in range(n):
        if bell[t] <= 0:
            burning = False
        elif burning:
            burning = rng.uniform() < 0.85
            level += rng.normal(0.05, 0.35)
        elif rng.uniform() < 0.35 * bell[t]:
            burning, level = True, np.log(rng.gamma(2.0, 60.0) * (0.3 + bell[t]))
        vegetation[t] = np.exp(level) if burning else 0.0
    return {
        "epoch_day": epoch,
        "vegetation_frp": vegetation,
        "neighbor_frp": np.r_[0.0, 0.4 * vegetation[:-1]] * (vegetation > 0),
        "industrial_z": np.zeros(n),
        "persistent_share": np.zeros(n),
        "cloud": np.full(n, np.nan),
        "gap": np.zeros(n),
    }


def _doy(epoch_day: int) -> int:
    day = np.datetime64("1970-01-01") + np.timedelta64(int(epoch_day), "D")
    return int((day - day.astype("datetime64[Y]")).astype(int)) + 1


def test_seasonal_base_rate_is_causal_bounded_and_seasonal():
    from backend.core.risk_predictor import seasonal_base_rates

    daily = _seasonal_daily(end_doy=300)
    epoch = daily["epoch_day"]
    event = daily["vegetation_frp"] > 0
    valid = np.ones(len(epoch), bool)
    long, recent = seasonal_base_rates(epoch, event[None, :], valid)
    assert long.shape == recent.shape == (1, len(epoch), 15)
    assert np.all((long > 0) & (long < 1)) and np.all((recent > 0) & (recent < 1))
    last_year = slice(len(epoch) - 300, len(epoch))
    doys = np.array([_doy(d) for d in epoch[last_year]])
    peak = long[0, last_year, 0][np.abs(doys - PEAK_DOY) <= 3].mean()
    calm = long[0, last_year, 0][np.abs(doys - 60) <= 3].mean()
    assert peak > 0.2 and calm < 0.01 and peak > 20 * calm
    for cut in (400, 1500, 3000):
        prefix_long, prefix_recent = seasonal_base_rates(epoch[:cut], event[None, :cut], valid[:cut])
        np.testing.assert_array_equal(prefix_long, long[:, :cut])
        np.testing.assert_array_equal(prefix_recent, recent[:, :cut])


def test_markov_horizon_probability_matches_the_documented_formula():
    from backend.core.risk_predictor import markov_horizon_probability

    p1, rho = 0.3, 0.68
    base = np.array([[0.0, 0.1, 0.12, 0.14, 0.16, 0.18, 0.2, 0.22]])
    expected = 1 - (1 - p1) * np.prod([
        1 - (rho ** (k - 1) * p1 + (1 - rho ** (k - 1)) * base[0, k]) * (1 - rho) for k in range(2, 8)
    ])
    got = markov_horizon_probability(np.array([p1]), base, rho, 7)
    assert got[0] == pytest.approx(expected, rel=1e-12)
    assert markov_horizon_probability(np.array([p1]), base, rho, 1)[0] == pytest.approx(p1)


def test_markov_default_persistence_equals_kalman_phi():
    import inspect

    from backend.core.kalman_rts import rts_kalman_smoother_with_cross_guard
    from backend.core.risk_predictor import DEFAULT_MARKOV_PERSISTENCE

    phi = inspect.signature(rts_kalman_smoother_with_cross_guard).parameters["phi"].default
    assert DEFAULT_MARKOV_PERSISTENCE == phi


def test_calm_season_stays_at_the_seasonal_base_rate():
    result = predict_risk(_seasonal_daily(end_doy=60))
    p24 = result["combined_risk_pct"]
    base = result["baseline_climatology_pct"]
    assert base is not None and 0 <= base < 5
    assert p24 <= max(6.0, 1.5 * base)
    p14 = result["horizons"][2]["combined_risk_pct"]
    independent = 100 * (1 - (1 - max(p24, base) / 100) ** 14)
    assert p14 <= 0.6 * independent + 1e-9
    assert result["overall_hazard_level"] == "LOW"


def test_peak_season_with_accelerating_contagious_heat_is_high():
    daily = _seasonal_daily(end_doy=PEAK_DOY + 2)
    ramp = np.array([60.0, 100.0, 160.0, 240.0, 330.0, 450.0, 600.0])
    daily["vegetation_frp"][-7:] = ramp
    daily["neighbor_frp"][-7:] = 0.5 * ramp
    result = predict_risk(daily)
    assert result["combined_risk_pct"] >= 50
    assert result["overall_hazard_level"] in ("HIGH", "CRITICAL")


@pytest.mark.parametrize("end_doy", [60, 150, PEAK_DOY])
def test_horizons_monotone_and_frechet_bounded_for_every_target(end_doy):
    result = predict_risk(_seasonal_daily(end_doy=end_doy))
    horizons = result["horizons"]
    for key in ("wildfire_prob_pct", "accident_prob_pct", "combined_risk_pct"):
        values = [h[key] for h in horizons]
        assert values == sorted(values)
    for h in horizons:
        assert max(h["wildfire_prob_pct"], h["accident_prob_pct"]) - 1e-6 <= h["combined_risk_pct"]
        assert h["combined_risk_pct"] <= min(100.0, h["wildfire_prob_pct"] + h["accident_prob_pct"]) + 1e-6


@pytest.mark.parametrize("end_doy", [60, PEAK_DOY])
def test_decomposition_is_exact_and_signed_impacts_are_consistent(end_doy):
    result = predict_risk(_seasonal_daily(end_doy=end_doy))
    parts = (result["baseline_climatology_pct"], result["multi_year_trend_delta_pct"],
             result["short_term_anomaly_delta_pct"])
    assert all(np.isfinite(part) for part in parts)
    assert abs(sum(parts) - result["combined_risk_pct"]) <= 0.05
    expected = result["combined_risk_pct"] / max(1.0, result["baseline_climatology_pct"])
    assert result["anomaly_multiplier"] == pytest.approx(expected, abs=0.01)
    assert 0.55 <= result["markov_persistence"] <= 0.85
    for factor in result["top_risk_factors"] + result["industrial_risk_factors"]:
        signed = factor["signed_impact_pct"]
        assert np.isfinite(signed) and -100 <= signed <= 100
        assert signed >= 0 if factor["direction"] == "raises" else signed <= 0
        assert factor["observed_value"] is None or np.isfinite(factor["observed_value"])
        assert factor["description"] and "nan" not in factor["description"].lower()


def test_sparse_prior_uses_default_persistence_and_markov_accumulation():
    from backend.core.risk_predictor import DEFAULT_MARKOV_PERSISTENCE

    daily = _make_daily_fixture(80)
    daily["vegetation_frp"][:] = 0
    daily["industrial_z"][:] = 0
    result = predict_risk(daily)
    assert result["markov_persistence"] == DEFAULT_MARKOV_PERSISTENCE
    p1 = result["horizons"][0]["wildfire_prob_pct"] / 100
    p14 = result["horizons"][2]["wildfire_prob_pct"] / 100
    assert p14 < 1 - (1 - p1) ** 14


def test_new_outputs_are_prefix_invariant_and_deterministic():
    daily = _seasonal_daily(end_doy=200, years=8)
    first, second = predict_risk(daily), predict_risk(daily)
    assert first == second
    modified = {k: v.copy() for k, v in daily.items()}
    modified["vegetation_frp"][-30:] *= 10
    modified["neighbor_frp"][-30:] += 50
    revised = predict_risk(modified)
    assert revised["daily_probability_series"][:-30] == first["daily_probability_series"][:-30]
    point = first["daily_probability_series"][-1]
    assert set(point) == {"date", "wildfire_prob_pct", "accident_prob_pct", "baseline_prob_pct", "observed_event"}
    assert isinstance(point["observed_event"], bool)


@pytest.mark.parametrize("case", ["calm", "peak", "sparse", "single", "blackout", "fixture"])
def test_assessment_validates_against_the_contract(case):
    import json

    from backend.api.schemas import AIRiskAssessment
    from backend.core.risk_predictor import with_observation_gap

    if case == "calm":
        daily = _seasonal_daily(end_doy=60)
    elif case == "peak":
        daily = _seasonal_daily(end_doy=PEAK_DOY)
    elif case == "sparse":
        daily = _make_daily_fixture(80)
    elif case == "single":
        daily = _make_daily_fixture(1)
    elif case == "blackout":
        full = _make_daily_fixture(1800)
        daily = with_observation_gap({k: v[:-7] for k, v in full.items()}, int(full["epoch_day"][-1]))
    else:
        daily = _make_daily_fixture(2000, seed=9)
    result = predict_risk(daily)
    AIRiskAssessment.model_validate(result)
    text = json.dumps(result).lower()
    for word in ("dispatcher", "firefighter", "manager", "nan", "infinity"):
        assert word not in text
    outlook = result["outlook_series"]
    assert len(outlook) == 14
    origin = np.datetime64(result["as_of_date"])
    assert [p["date"] for p in outlook] == [str(origin + np.timedelta64(k, "D")) for k in range(1, 15)]
    assert result["horizon_explanation"].endswith(".")


def test_observation_status_tracks_gaps_and_blackouts():
    from backend.core.risk_predictor import with_observation_gap

    daily = _seasonal_daily(end_doy=150, years=5)
    nominal = predict_risk(daily)["observation"]
    assert nominal["status"] == "Nominal multi-sensor coverage"
    assert nominal["coverage_nominal"] is True and nominal["days_since_observation"] == 0
    daily["gap"][-2] = 1
    flagged = predict_risk(daily)["observation"]
    assert flagged["status"] == "Cloud / sensor gap uncertainty (ground reconnaissance advised)"
    assert flagged["coverage_nominal"] is False
    assert 0 < flagged["uncertainty_pct"] <= 100
    visible = {k: v[:-7] for k, v in _seasonal_daily(end_doy=150, years=5).items()}
    blind = predict_risk(with_observation_gap(visible, int(daily["epoch_day"][-1])))["observation"]
    assert blind["days_since_observation"] == 7 and blind["coverage_nominal"] is False


@pytest.mark.parametrize("mw, regime, guidance", [
    (0.0, "Dormant / Low Surface Intensity", "Direct ground attack feasible"),
    (80.0, "Moderate Surface Fire", "Active spread; flank containment required"),
    (200.0, "High-Intensity Crown Transition", "Heavy aerial and mechanical support required"),
    (900.0, "Extreme Convective / Plume-Driven", "Spotting hazard; prioritise perimeter safety"),
])
def test_intensity_regime_bands_use_peak_detection_frp(mw, regime, guidance):
    daily = _seasonal_daily(end_doy=PEAK_DOY, years=5)
    daily["vegetation_frp"][-1] = 5000.0
    daily["neighbor_frp"][-1] = 0.0
    daily["peak_detection_frp"] = np.minimum(daily["vegetation_frp"], 1.0)
    daily["peak_detection_frp"][-1] = mw
    intensity = predict_risk(daily)["intensity"]
    assert intensity["regime"] == regime and intensity["guidance"] == guidance
    assert intensity["intensity_mw"] == pytest.approx(mw)
    assert intensity["diurnal_amplification_ratio"] is None
    assert intensity["contagion_origin"] == ("Isolated ignition inside area" if mw > 0 else "No active heat")


def test_intensity_reports_contagion_from_peak_detection_frp():
    daily = _seasonal_daily(end_doy=PEAK_DOY, years=5)
    daily["vegetation_frp"][-1] = 4000.0
    daily["neighbor_frp"][-1] = 30.0
    daily["peak_detection_frp"] = np.zeros(len(daily["epoch_day"]))
    daily["peak_detection_frp"][-1] = 150.0
    intensity = predict_risk(daily)["intensity"]
    assert intensity["intensity_mw"] == pytest.approx(150.0)
    assert intensity["regime"] == "High-Intensity Crown Transition"
    assert intensity["contagion_origin"] == "Adjacent-cell spread"
    assert intensity["neighbor_frp_mw"] == pytest.approx(30.0)


@pytest.mark.parametrize("legacy_key", [None, "peak_cell_frp"])
def test_intensity_is_withheld_without_a_per_detection_reading(legacy_key):
    """AOI sums (and cell-day sums) are on the wrong scale for the per-detection bands."""
    daily = _seasonal_daily(end_doy=PEAK_DOY, years=5)
    daily["vegetation_frp"][-1] = 150.0
    if legacy_key:
        daily[legacy_key] = np.full(len(daily["epoch_day"]), 6000.0)
    assert predict_risk(daily)["intensity"] is None


def test_sustained_record_contagious_heat_near_peak_is_high():
    """Event-level heat on many consecutive days with adjacent-cell heat near the seasonal peak."""
    daily = _seasonal_daily(end_doy=PEAK_DOY - 3)
    record = 1.5 * float(np.max(daily["vegetation_frp"]))
    daily["vegetation_frp"][-10:] = record
    daily["neighbor_frp"][-10:] = 0.5 * record
    result = predict_risk(daily)
    assert result["wildfire_prob_24h_pct"] >= 70
    assert result["overall_hazard_level"] in ("HIGH", "CRITICAL")
    parts = (result["baseline_climatology_pct"], result["multi_year_trend_delta_pct"],
             result["short_term_anomaly_delta_pct"])
    assert abs(sum(parts) - result["combined_risk_pct"]) <= 0.05
    raising = [f for f in result["top_risk_factors"] if f["direction"] == "raises"]
    assert raising and sum(f["signed_impact_pct"] for f in raising) > 0


def _walk(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)
    else:
        yield value


@pytest.mark.parametrize("end_doy", [60, 150, PEAK_DOY])
def test_no_negative_zero_is_emitted(end_doy):
    import math

    result = predict_risk(_seasonal_daily(end_doy=end_doy))
    zeros = [v for v in _walk(result) if isinstance(v, float) and v == 0.0]
    assert all(math.copysign(1.0, v) > 0 for v in zeros)


def test_phenology_matches_sibling_core_formulas():
    from backend.core.industrial_filter import compute_shannon_temporal_entropy
    from backend.core.risk_predictor import BIOMASS_COMBUSTION_KG_PER_MJ
    from backend.core.von_mises import best_fisher_kappa, compute_circular_phenology, doy_to_date_label

    daily = _seasonal_daily(end_doy=PEAK_DOY - 9, years=10)
    phen = predict_risk(daily)["phenology"]
    epoch, frp = daily["epoch_day"], daily["vegetation_frp"]
    dates = np.datetime64("1970-01-01") + epoch.astype("timedelta64[D]")
    years = dates.astype("datetime64[Y]").astype(int) + 1970
    doy = (dates - dates.astype("datetime64[Y]")).astype(int) + 1
    theta = 2 * np.pi * doy / 365.25
    moment = np.sum(frp * np.exp(1j * theta)) / frp.sum()
    peak = (np.angle(moment) % (2 * np.pi)) * 365.25 / (2 * np.pi)
    kappa = best_fisher_kappa(abs(moment))
    assert phen["kappa"] == pytest.approx(kappa, abs=1e-3)
    assert phen["peak_date_label"] == doy_to_date_label(np.clip(peak, 1, 365.25))
    assert phen["season_width_days"] == pytest.approx(min(365, 365.25 / np.sqrt(max(.15, kappa))), abs=0.01)
    ahead = (peak - doy[-1] + 182.625) % 365.25 - 182.625
    assert phen["days_to_peak"] == int(np.round(ahead)) and phen["days_to_peak"] > 0
    prior = years < years[-1]
    _, shift, _ = compute_circular_phenology(years[prior], doy[prior], frp[prior], 1.0)
    assert phen["decadal_shift_days"] == pytest.approx(shift, abs=0.01)
    window = slice(len(epoch) - 365, len(epoch))
    months = dates[window].astype("datetime64[M]").astype(int) % 12
    energy = np.bincount(months, weights=frp[window], minlength=12)
    assert phen["persistence_entropy"] == pytest.approx(float(compute_shannon_temporal_entropy(energy)), abs=1e-3)
    assert phen["fuel_regime"] == "Vegetative fuel regime"
    assert BIOMASS_COMBUSTION_KG_PER_MJ == 0.368
    expected = 0.368 * frp[-7:].sum() * 3600 / 1000
    assert phen["biomass_exposure_tonnes"] == pytest.approx(expected, rel=1e-3, abs=0.01)


def test_decadal_shift_is_none_with_too_few_years():
    assert predict_risk(_seasonal_daily(end_doy=PEAK_DOY, years=3))["phenology"]["decadal_shift_days"] is None


def test_factor_readouts_describe_observed_physics():
    from backend.core.risk_predictor import factor_readouts

    daily = _seasonal_daily(end_doy=PEAK_DOY - 9, years=6)
    ramp = np.array([10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0])
    daily["vegetation_frp"][-7:] = ramp
    daily["neighbor_frp"][-1] = 48.2
    readouts = factor_readouts(daily)
    assert len(readouts) == len(FEATURES)
    contagion = readouts[0]
    assert contagion["description"].startswith("Adjacent-cell heat at t-1 is 48.2 MW")
    assert "seasonal norm" in contagion["description"] and contagion["unit"] == "MW"
    assert contagion["observed_value"] == pytest.approx(48.2)
    trend = readouts[2]
    assert trend["description"].startswith("7-day non-persistent FRP trend is +10.0 MW/day")
    assert trend["observed_value"] == pytest.approx(10.0) and trend["unit"] == "MW/day"
    assert "before the regional peak burning window" in readouts[7]["description"]
    assert "concentration κ =" in readouts[7]["description"]
    assert readouts[12]["description"].startswith("Temporal persistence entropy H = ")
    assert "vegetative fuel regime" in readouts[12]["description"]
    for item in readouts:
        assert item["description"].endswith(".") or item["description"][-1].isalnum() is False
        assert "nan" not in item["description"].lower()
        assert item["observed_value"] is None or np.isfinite(item["observed_value"])
    daily["neighbor_frp"][-1] = 0.0
    assert factor_readouts(daily)[0]["description"].startswith("No adjacent-cell heat at t-1")


def _year_round_daily(persistent_share: float) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(3)
    n = 3 * 365
    vegetation = rng.gamma(2.0, 20.0, n)
    return {
        "epoch_day": EPOCH_2012 + np.arange(n), "vegetation_frp": vegetation, "neighbor_frp": 0.2 * vegetation,
        "industrial_z": np.zeros(n), "persistent_share": np.full(n, persistent_share),
        "cloud": np.full(n, np.nan), "gap": np.zeros(n),
    }


def test_year_round_heat_is_persistent_only_when_persistent_cells_dominate():
    vegetative = predict_risk(_year_round_daily(0.0))["phenology"]
    assert vegetative["persistence_entropy"] > 0.9
    assert vegetative["fuel_regime"] == "Mixed regime"
    industrial = predict_risk(_year_round_daily(0.7))["phenology"]
    assert industrial["persistence_entropy"] > 0.9
    assert industrial["fuel_regime"] == "Persistent-source regime"


def test_thermal_state_readout_names_the_event_run():
    from backend.core.risk_predictor import factor_readouts

    daily = _seasonal_daily(end_doy=PEAK_DOY, years=4)
    daily["vegetation_frp"][-1] = 0.0
    assert "below the" in factor_readouts(daily)[1]["description"]
    daily["vegetation_frp"][-5] = 0.0
    daily["vegetation_frp"][-4:] = 10_000.0
    assert "event level on 4 consecutive days." in factor_readouts(daily)[1]["description"]
    daily["vegetation_frp"][-2] = 0.0
    assert "event level today." in factor_readouts(daily)[1]["description"]
