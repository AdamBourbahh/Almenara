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
