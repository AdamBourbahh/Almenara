"""Exercise the local risk route without changing the frozen analysis tests."""

from datetime import date

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import routes
from backend.api.main import app
from backend.api.schemas import RiskPredictionResponse
from backend.db import duckdb_engine, queries

AOI = {"type": "Polygon", "coordinates": [[
    [-69.5, -31], [-65.5, -31], [-65.5, -27.5], [-69.5, -27.5], [-69.5, -31]
]]}
EPOCH = date(1970, 1, 1)


@pytest.fixture
def client():
    routes.RISK_CACHE.clear()
    with TestClient(app) as client:
        yield client


def test_risk_route_cutoff_provenance_and_cache(client):
    body = {"aoi": AOI, "as_of_date": "2023-08-01"}
    first = client.post("/api/predict-risk", json=body)
    assert first.status_code == 200, first.text
    assert first.headers["X-Cache"] == "MISS"
    parsed = RiskPredictionResponse.model_validate(first.json())
    assert parsed.data_source == "synthetic"
    assert parsed.target == "satellite_thermal_event_proxy"
    assert parsed.assessment
    assert parsed.assessment.as_of_date <= date(2023, 8, 1)
    assert client.post("/api/predict-risk", json=body).headers["X-Cache"] == "HIT"
    assert client.post("/api/predict-risk", json={**body, "as_of_date": "2023-08-02"}).headers["X-Cache"] == "MISS"
    assert client.post("/api/predict-risk", json={**body, "start_year": 2021}).headers["X-Cache"] == "MISS"


def test_risk_route_empty_area_and_bad_date(client):
    ocean = {"type": "Polygon", "coordinates": [[
        [-30, -30], [-29, -30], [-29, -29], [-30, -29], [-30, -30]
    ]]}
    unavailable = client.post("/api/predict-risk", json={"aoi": ocean})
    assert unavailable.status_code == 200
    assert unavailable.json()["assessment"] is None
    assert unavailable.json()["unavailable_reason"] == "No local observations in the selected area and date range."
    assert client.post("/api/predict-risk", json={"aoi": AOI, "as_of_date": "2030-01-01"}).status_code == 422


def test_risk_cube_features_are_prefix_invariant(client):
    r4, r7, _ = queries.get_hierarchical_h3_filter(AOI["coordinates"])
    start, end = (date(2021, 12, 31) - EPOCH).days, (date(2023, 8, 1) - EPOCH).days
    prefix = queries.fetch_risk_daily(r4, r7, 2020, 2023, start)
    whole = queries.fetch_risk_daily(r4, r7, 2020, 2023, end)
    assert duckdb_engine.data_source() == "synthetic"
    assert len(prefix["epoch_day"]) >= 365
    for name, values in prefix.items():
        np.testing.assert_allclose(values, whole[name][:len(values)], atol=1e-9)


def test_risk_explicit_origin_can_land_after_last_observation(client, monkeypatch):
    from datetime import timedelta

    start = date(2020, 2, 25)
    origin = start + timedelta(days=4)
    daily = {
        "epoch_day": np.arange((start - EPOCH).days, (start - EPOCH).days + 2),
        "vegetation_frp": np.array([10., 20.]),
        "neighbor_frp": np.array([0., 4.]),
        "industrial_z": np.zeros(2),
        "persistent_share": np.zeros(2),
        "cloud": np.full(2, np.nan),
        "gap": np.zeros(2),
    }

    def history(*args):
        assert args[-1] == (origin - EPOCH).days
        return daily

    monkeypatch.setattr(queries, "fetch_risk_daily", history)
    response = client.post("/api/predict-risk", json={"aoi": AOI, "as_of_date": str(origin)})
    assert response.status_code == 200
    result = response.json()["assessment"]
    assert result["as_of_date"] == str(origin)
    assert result["last_observation_date"] == str(start + timedelta(days=1))
    assert result["daily_probability_series"][-1]["date"] == str(origin)


def test_risk_peak_detection_frp_is_causal_and_bounded():
    r4, r7, _ = queries.get_hierarchical_h3_filter(AOI["coordinates"])
    cutoff = (date(2023, 8, 1) - EPOCH).days
    daily = queries.fetch_risk_daily(r4, r7, 2020, 2023, cutoff)
    peak = daily["peak_detection_frp"]
    assert len(peak) == len(daily["epoch_day"])
    assert np.all(np.isfinite(peak)) and np.all(peak >= 0)
    assert np.all(peak <= daily["vegetation_frp"] + 1e-6)
    assert np.any(peak[daily["vegetation_frp"] > 0] > 0)


def test_diurnal_ratio_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(queries, "LOOKUP_DIR", tmp_path)
    assert queries.fetch_risk_diurnal_ratio([1, 2], 8) is None


def test_diurnal_ratio_is_matched_days_weighted_median(tmp_path, monkeypatch):
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table({
        "h3_r4": pa.array([10, 20, 30, 10], type=pa.uint64()),
        "month": pa.array([8, 8, 8, 9], type=pa.uint8()),
        "ratio": pa.array([2.0, 4.0, 9.0, 7.0]),
        "matched_days": pa.array([30, 10, 5, 1], type=pa.int64()),
    })
    pq.write_table(table, tmp_path / "diurnal_ratios.parquet")
    monkeypatch.setattr(queries, "LOOKUP_DIR", tmp_path)
    assert queries.fetch_risk_diurnal_ratio([10, 20], 8) == pytest.approx(2.0)
    assert queries.fetch_risk_diurnal_ratio([10], 9) == pytest.approx(7.0)
    assert queries.fetch_risk_diurnal_ratio([99], 8) is None
    assert queries.fetch_risk_diurnal_ratio([], 8) is None


def test_risk_route_diurnal_ratio_is_null_or_positive(client):
    response = client.post("/api/predict-risk", json={"aoi": AOI, "as_of_date": "2023-08-01"})
    assert response.status_code == 200, response.text
    parsed = RiskPredictionResponse.model_validate(response.json())
    assert parsed.assessment
    if parsed.assessment.intensity is not None:
        ratio = parsed.assessment.intensity.diurnal_amplification_ratio
        assert ratio is None or ratio > 0


def test_risk_route_merges_diurnal_ratio(client, monkeypatch):
    monkeypatch.setattr(queries, "fetch_risk_diurnal_ratio", lambda r4, month: 1.2345)
    response = client.post("/api/predict-risk", json={"aoi": AOI, "as_of_date": "2023-08-01"})
    intensity = response.json()["assessment"].get("intensity")
    if intensity is not None:
        assert intensity["diurnal_amplification_ratio"] == 1.23


def test_diurnal_ratio_ignores_extreme_outlier(tmp_path, monkeypatch):
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table({
        "h3_r4": pa.array([1, 2, 3, 4, 5], type=pa.uint64()),
        "month": pa.array([8] * 5, type=pa.uint8()),
        "ratio": pa.array([1.1, 1.3, 1.5, 1.2, 50000.0]),
        "matched_days": pa.array([20, 25, 15, 30, 1], type=pa.int64()),
    })
    pq.write_table(table, tmp_path / "diurnal_ratios.parquet")
    monkeypatch.setattr(queries, "LOOKUP_DIR", tmp_path)
    value = queries.fetch_risk_diurnal_ratio([1, 2, 3, 4, 5], 8)
    assert 1.1 <= value <= 1.5
