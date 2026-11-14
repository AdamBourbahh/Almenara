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
    [-57.2, -17.8], [-55.2, -17.8], [-55.2, -16.0], [-57.2, -16.0], [-57.2, -17.8]
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


def test_risk_route_empty_area_and_bad_date(client):
    ocean = {"type": "Polygon", "coordinates": [[
        [-30, -30], [-29, -30], [-29, -29], [-30, -29], [-30, -30]
    ]]}
    unavailable = client.post("/api/predict-risk", json={"aoi": ocean})
    assert unavailable.status_code == 200
    assert unavailable.json()["assessment"] is None
    assert unavailable.json()["unavailable_reason"]
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
