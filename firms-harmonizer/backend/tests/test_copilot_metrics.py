"""Database-grounded energy, context precedence and graceful missing-data regressions."""
import math

import h3
import pytest
from fastapi.testclient import TestClient

from backend.api import fire_copilot as copilot
from backend.api.main import app
from backend.api.schemas import ExplainSpikeRequest
from backend.db import duckdb_engine


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("COPILOT_OFFLINE", "1")
    with TestClient(app) as client:
        yield client


def selected_cell_request():
    with duckdb_engine.get_db_cursor() as cursor:
        index = cursor.execute("SELECT printf('%x', h3_r7) FROM fire_cube WHERE year=2022 AND raw_modis_cnt>0 AND industrial_prob<0.75 LIMIT 1").fetchone()[0]
    ring = [[lon, lat] for lat, lon in h3.cell_to_boundary(index)]
    return {"region_name": "Selected test cell", "aoi": {"type": "Polygon", "coordinates": [ring + [ring[0]]]},
            "period_start": "2022-07-01", "period_end": "2022-08-31",
            "user_question": "How much energy in GJ and how many fires in this area?"}


@pytest.mark.parametrize("kalman,industrial", [(True, True), (False, False)])
def test_gj_matches_dashboard_inclusive_dates_and_filters(client, monkeypatch, kalman, industrial):
    def forbidden(*args, **kwargs):
        raise AssertionError("Local metrics must never call a language model or web search")
    monkeypatch.setattr(copilot, "complete", forbidden)
    monkeypatch.setattr(copilot, "search_reports", forbidden)
    payload = selected_cell_request()
    payload.update(enable_kalman_gap_filling=kalman, exclude_industrial_flaring=industrial)
    analysis = client.post("/api/analyze", json={"aoi": payload["aoi"], "start_year": 2000, "end_year": 2026,
        "enable_kalman_gap_filling": kalman, "exclude_industrial_flaring": industrial}).json()
    days = [c for c in analysis["calendar_series"] if payload["period_start"] <= c["date"] <= payload["period_end"]]
    expected_gj = math.fsum(c["biomass_burned_tonnes"] for c in days) / 0.368
    response = client.post("/api/explain-spike", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["physical_classification"] == "LOCAL_ENERGY_SUMMARY"
    assert f"**{expected_gj:,.3f} GJ**" in body["explanation_markdown"]
    assert f"**{len(days)} days**" in body["explanation_markdown"]
    assert body["data_source"] == "synthetic"
    assert "Synthetic demo mode" in body["explanation_markdown"]
    assert body["web_search_used"] is False
    assert {c["id"] for c in body["citations"]} == {"[1]", "[6]"}
    assert body["map_context"]["aoi"] == payload["aoi"]
    assert body["map_context"]["period_end"] == "2022-08-31"


def test_energy_does_not_trust_client_hex_totals(client):
    payload = selected_cell_request()
    ring = payload["aoi"]["coordinates"][0]
    lat = sum(p[1] for p in ring[:-1]) / len(ring[:-1])
    lon = sum(p[0] for p in ring[:-1]) / len(ring[:-1])
    index = h3.latlng_to_cell(lat, lon, 7)
    payload["selected_hex"] = {"h3_index": index, "mean_annual_fre": 987654321,
        "raw_pixel_count": 987654321, "trend_slope": 0, "is_industrial_site": True, "shannon_entropy": 1}
    result = client.post("/api/explain-spike", json=payload).json()
    assert "987654321" not in result["explanation_markdown"]
    assert result["physical_classification"] == "LOCAL_ENERGY_SUMMARY"
    assert result["map_context"]["h3_index"] == index


def test_missing_energy_columns_never_convert_raw_mw(client, monkeypatch):
    payload = selected_cell_request()
    monkeypatch.setattr(duckdb_engine, "missing_columns", lambda: ["obs_viirs_fre"])
    body = client.post("/api/explain-spike", json=payload).json()
    assert "energy columns are unavailable" in body["explanation_markdown"]
    assert "instantaneous MW cannot be converted" in body["explanation_markdown"]
    assert "[6]" not in body["explanation_markdown"]


def test_empty_cube_scope_is_missing_evidence_not_zero_energy(client):
    payload = selected_cell_request()
    payload["aoi"]["coordinates"] = [[[0, 0], [.05, 0], [.05, .05], [0, .05], [0, 0]]]
    body = client.post("/api/explain-spike", json=payload).json()
    assert "does not establish zero fire energy" in body["explanation_markdown"]


def test_context_override_discards_old_place_and_date_but_explicit_question_wins():
    coords = [[[-60.1,-3.9],[-59.9,-3.9],[-59.9,-3.7],[-60.1,-3.7],[-60.1,-3.9]]]
    req = ExplainSpikeRequest(aoi={"coordinates": coords}, region_name="New drawn area",
        period_start="2024-09-01", period_end="2024-09-30", prefer_map_context=True,
        user_question="How many detections?", conversation=[{"role":"user", "content":"Madrid July 2026"}])
    scope = copilot.resolve_scope(req)
    assert scope.coordinates == coords
    assert scope.start == "2024-09-01" and scope.end == "2024-09-30"
    req.user_question = "How many detections in Madrid on 24 July 2026?"
    scope = copilot.resolve_scope(req)
    assert scope.label.startswith("Madrid")
    assert scope.start == scope.end == "2026-07-24"


def test_unknown_explicit_location_never_returns_selected_region_metrics():
    req = ExplainSpikeRequest(region_name="Madrid", period_start="2026-01-01", period_end="2026-12-31",
        user_question="How many fires in Paris in 2026?")
    scope = copilot.resolve_scope(req)
    assert scope.coordinates is None
    assert copilot.retrieve_observations(scope)["status"] == "missing_scope"


def test_structured_previous_scope_survives_history_truncation_and_relative_dates():
    req = ExplainSpikeRequest(region_name="Chilecito", period_start="2022-01-01", period_end="2022-12-31",
        user_question="And on the next day?", previous_context={
            "label": "A previously queried custom area",
            "aoi": {"coordinates": [[[-4.3,40.3],[-4.1,40.3],[-4.1,40.5],[-4.3,40.3]]]},
            "period_start": "2026-07-24", "period_end": "2026-07-24"},
        conversation=[{"role": "user", "content": "And the observations?"}] * 10)
    scope = copilot.resolve_scope(req)
    assert scope.label == "A previously queried custom area"
    assert scope.coordinates == req.previous_context.aoi.coordinates
    assert scope.start == scope.end == "2026-07-25"
    req.prefer_map_context = True
    scope = copilot.resolve_scope(req)
    assert scope.label.startswith("Chilecito")
    assert scope.start == "2022-01-01"


@pytest.mark.parametrize("question,expected", [
    ("How many GJ in this area?", (True, True)),
    ("¿Cuánta energía en GJ hubo?", (True, True)),
    ("número de fuegos", (True, False)),
    ("And in GJ?", (True, True)),
    ("total FRP in MW", (True, False)),
    ("What is FRE?", (False, False)),
    ("Why did raw counts jump in January 2012?", (False, False)),
])
def test_quantitative_routing_preserves_method_questions(question, expected):
    assert copilot.quantitative_intent(question) == expected


def test_month_range_and_explicit_hex_scope():
    assert copilot.question_period("July to August 2026") == ("2026-07-01", "2026-08-31")
    index = h3.latlng_to_cell(40.4, -4.2, 7)
    scope = copilot.resolve_scope(ExplainSpikeRequest(user_question=f"How many detections in {index} in 2026?"))
    assert scope.h3_index == index
    assert copilot.queries.get_hierarchical_h3_filter(scope.coordinates)[1] == [int(index, 16)]


def test_chat_map_comparison_matches_independent_sparse_cell_sum(sparse_cube):
    from types import SimpleNamespace
    from backend.tests.test_api_accounting import square,CENTRE
    from backend.api.copilot_metrics import retrieve_energy
    client,expected=sparse_cube
    coordinates=square(*CENTRE,.05)
    scope=SimpleNamespace(coordinates=coordinates,start='2020-03-01',end='2020-03-03',label='Test area')
    req=ExplainSpikeRequest(enable_kalman_gap_filling=False)
    evidence=retrieve_energy(scope,req)
    total=sum(density*h3.cell_area(format(cell,'x'),unit='km^2')/1000 for density,cell in expected.values())
    assert evidence['mapped_energy_gj']==pytest.approx(total)
    assert evidence['mapped_biomass_tonnes']==pytest.approx(total*.368)
    assert evidence['available_through']=='2020-03-03'
    r=client.post('/api/map-period?start_date=2020-03-01&end_date=2020-03-03',json={
        'aoi':{'coordinates':coordinates},'start_year':2020,'end_year':2020})
    assert r.status_code==200
    mapped=sum(c['mean_annual_fre']*h3.cell_area(c['h3_index'],unit='km^2')/1000 for c in r.json()['map_hexagons'])
    assert evidence['mapped_energy_gj']==pytest.approx(mapped)

from backend.tests.test_api_accounting import sparse_cube
