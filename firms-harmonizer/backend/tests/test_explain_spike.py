"""Tests for POST /api/explain-spike and Physics-First Web Grounding."""

import inspect
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.api import routes
from backend.api.main import app
from backend.api.schemas import (CitationReference, DailyCalendarCell, ExplainSpikeRequest,
                                 ExplainSpikeResponse, H3MapSummaryHex)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_explain_spike_is_sync_def():
    assert inspect.isfunction(routes.explain_spike)
    assert not inspect.iscoroutinefunction(routes.explain_spike)


def test_gatekeeper_filters_industrial_gas_flaring(client):
    body = {
        "region_name": "Niger Delta gas flaring",
        "selected_hex": {
            "h3_index": "872830828ffffff",
            "mean_annual_fre": 120.0,
            "raw_pixel_count": 850,
            "trend_slope": 0.01,
            "is_industrial_site": True,
            "shannon_entropy": 0.88,
        },
        "user_question": "",
    }
    r = client.post("/api/explain-spike", json=body)
    assert r.status_code == 200, r.text
    resp = ExplainSpikeResponse.model_validate(r.json())
    assert resp.physical_classification == "INDUSTRIAL_GAS_FLARING"
    assert resp.web_search_used is False
    assert resp.search_query_executed is None
    assert "Shannon" in resp.explanation_markdown
    assert "hydrocarbon" in resp.explanation_markdown or "flaring" in resp.explanation_markdown
    assert any(c.id == "[1]" for c in resp.citations)


def test_gatekeeper_filters_kalman_gap_filled_blackout(client):
    body = {
        "region_name": "Cerrado & Pantanal, Brazil",
        "selected_day": {
            "date": "2022-08-16",
            "year": 2022,
            "doy": 228,
            "raw_hotspot_count": 0,
            "raw_frp_mw": 0.0,
            "harmonized_fre_mj_km2": 45.2,
            "historical_cross_prior_fre": 40.0,
            "ci_95_lower": 32.1,
            "ci_95_upper": 58.3,
            "uncertainty_pct": 28.5,
            "biomass_burned_tonnes": 85.0,
            "pm25_emitted_kg": None,
            "z_score_anomaly": 0.35,
            "is_gap_filled": True,
            "is_forecast": False,
            "gap_reason": "Sensor outage; Cloud cover >80%",
            "active_sensors": [],
            "tooltip_narrative": None,
        },
        "user_question": "",
    }
    r = client.post("/api/explain-spike", json=body)
    assert r.status_code == 200, r.text
    resp = ExplainSpikeResponse.model_validate(r.json())
    assert resp.physical_classification == "KALMAN_GAP_FILLED"
    assert resp.web_search_used is False
    assert "Kalman" in resp.explanation_markdown
    assert "Sensor outage" in resp.explanation_markdown


def test_gatekeeper_filters_historical_2012_sensor_split(client):
    body = {
        "region_name": "Cerrado & Pantanal, Brazil",
        "selected_day": {
            "date": "2012-01-10",
            "year": 2012,
            "doy": 10,
            "raw_hotspot_count": 350,
            "raw_frp_mw": 2400.0,
            "harmonized_fre_mj_km2": 12.0,
            "historical_cross_prior_fre": 11.5,
            "ci_95_lower": 8.0,
            "ci_95_upper": 16.0,
            "uncertainty_pct": 15.0,
            "biomass_burned_tonnes": 22.0,
            "pm25_emitted_kg": None,
            "z_score_anomaly": 0.1,
            "is_gap_filled": False,
            "is_forecast": False,
            "gap_reason": None,
            "active_sensors": ["Terra", "Aqua", "VIIRS"],
            "tooltip_narrative": None,
        },
        "user_question": "Why did raw hotspots jump in 2012?",
    }
    r = client.post("/api/explain-spike", json=body)
    assert r.status_code == 200, r.text
    resp = ExplainSpikeResponse.model_validate(r.json())
    assert resp.physical_classification == "HISTORICAL_SENSOR_SPLIT_2012"
    assert resp.web_search_used is False
    assert "Chow" in resp.explanation_markdown
    assert "VIIRS" in resp.explanation_markdown


def test_extreme_fire_triggers_web_search_and_remote_burn_fallback(client):
    body = {
        "region_name": "Cerrado & Pantanal, Brazil",
        "selected_day": {
            "date": "2020-08-25",
            "year": 2020,
            "doy": 238,
            "raw_hotspot_count": 1420,
            "raw_frp_mw": 18500.0,
            "harmonized_fre_mj_km2": 185.0,
            "historical_cross_prior_fre": 35.0,
            "ci_95_lower": 170.0,
            "ci_95_upper": 200.0,
            "uncertainty_pct": 8.1,
            "biomass_burned_tonnes": 340.4,
            "pm25_emitted_kg": None,
            "z_score_anomaly": 4.25,
            "is_gap_filled": False,
            "is_forecast": False,
            "gap_reason": None,
            "active_sensors": ["Terra", "Aqua", "VIIRS"],
            "tooltip_narrative": None,
        },
        "user_question": "",
    }
    r = client.post("/api/explain-spike", json=body)
    assert r.status_code == 200, r.text
    resp = ExplainSpikeResponse.model_validate(r.json())
    assert resp.physical_classification == "EXTREME_VEGETATION_FIRE"
    assert resp.web_search_used is True
    assert resp.search_query_executed is not None
    assert "August 2020" in resp.search_query_executed
    assert "Cerrado" in resp.search_query_executed
    assert "Wooster" in resp.explanation_markdown or "biomass" in resp.explanation_markdown.lower()
    # Citations include [1]..[5]
    assert any(c.id == "[1]" and "Wooster" in c.authors_or_agency for c in resp.citations)
    assert any(c.id == "[2]" and "Schroeder" in c.authors_or_agency for c in resp.citations)
    assert any(c.id == "[5]" and "FIRMS" in c.dataset_or_doi for c in resp.citations)


def test_web_search_with_mocked_results(client, monkeypatch):
    mock_results = [
        {
            "title": "Massive Wildfire Engulfs Pantanal Wetlands in August 2020",
            "href": "https://www.reuters.com/article/pantanal-wildfire-2020",
            "body": "Record fires fueled by severe drought swept across the Brazilian Pantanal wetland in August 2020.",
        },
        {
            "title": "Satellite Observations Reveal Unprecedented Fire Radiative Energy",
            "href": "https://news.mongabay.com/2020/08/pantanal-burns",
            "body": "NASA FIRMS data confirmed extreme thermal hotspots across the state of Mato Grosso.",
        },
    ]

    def mock_search(query, max_results=3):
        return mock_results

    # Patch DDGS text search
    monkeypatch.setattr(routes, "_search_fire_web_context", lambda reg, day, hx, q: (
        [
            CitationReference(
                id=f"[W{i+1}]",
                source_type="WEB_NEWS_REPORT",
                title=res["title"],
                authors_or_agency="reuters.com" if "reuters" in res["href"] else "mongabay.com",
                year=2020,
                dataset_or_doi="Live Web Grounding",
                url=res["href"],
                relevance_note=res["body"],
            )
            for i, res in enumerate(mock_results)
        ],
        f"{reg} wildfire OR forest fire OR prescribed burn August 2020",
    ))

    body = {
        "region_name": "Cerrado & Pantanal, Brazil",
        "selected_day": {
            "date": "2020-08-25",
            "year": 2020,
            "doy": 238,
            "raw_hotspot_count": 800,
            "raw_frp_mw": 8000.0,
            "harmonized_fre_mj_km2": 95.0,
            "historical_cross_prior_fre": 30.0,
            "ci_95_lower": 85.0,
            "ci_95_upper": 105.0,
            "uncertainty_pct": 10.0,
            "biomass_burned_tonnes": 175.0,
            "pm25_emitted_kg": None,
            "z_score_anomaly": 3.1,
            "is_gap_filled": False,
            "is_forecast": False,
            "gap_reason": None,
            "active_sensors": ["Aqua", "VIIRS"],
            "tooltip_narrative": None,
        },
        "user_question": "What caused this extreme fire spike?",
    }
    r = client.post("/api/explain-spike", json=body)
    assert r.status_code == 200, r.text
    resp = ExplainSpikeResponse.model_validate(r.json())
    assert resp.web_search_used is True
    assert any(c.id == "[W1]" for c in resp.citations)
    assert any(c.id == "[W2]" for c in resp.citations)
    assert any("reuters.com" in c.authors_or_agency for c in resp.citations)
    assert "[W1]" in resp.explanation_markdown
    assert "https://www.reuters.com/article/pantanal-wildfire-2020" in resp.explanation_markdown


def test_airplane_mode_resilience_on_network_timeout(client, monkeypatch):
    # Simulate network blackout (no LLM, no external DNS)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    def timeout_search(*args, **kwargs):
        raise TimeoutError("Simulated DNS / network blackout on stage")

    monkeypatch.setattr(routes, "_search_fire_web_context", timeout_search)

    body = {
        "region_name": "Sierra Nevada, California",
        "selected_day": {
            "date": "2021-08-15",
            "year": 2021,
            "doy": 227,
            "raw_hotspot_count": 500,
            "raw_frp_mw": 6000.0,
            "harmonized_fre_mj_km2": 80.0,
            "historical_cross_prior_fre": 20.0,
            "ci_95_lower": 70.0,
            "ci_95_upper": 90.0,
            "uncertainty_pct": 12.0,
            "biomass_burned_tonnes": 147.2,
            "pm25_emitted_kg": None,
            "z_score_anomaly": 3.8,
            "is_gap_filled": False,
            "is_forecast": False,
            "gap_reason": None,
            "active_sensors": ["Terra", "Aqua"],
            "tooltip_narrative": None,
        },
        "user_question": "Explain this spike",
    }
    # Must not raise 500 or crash; must gracefully fall back to deterministic science
    r = client.post("/api/explain-spike", json=body)
    assert r.status_code == 200, r.text
    resp = ExplainSpikeResponse.model_validate(r.json())
    assert resp.physical_classification == "EXTREME_VEGETATION_FIRE"
    assert resp.model_used in ("deterministic-offline-science", "deterministic-fallback")
    assert "Wooster" in resp.explanation_markdown or "biomass" in resp.explanation_markdown.lower()
