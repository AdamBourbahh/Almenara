"""Frozen HTTP contract tests: response shape, status codes and formats ONLY. DO NOT EDIT.

Scientific results (Chow, Wasserstein, recovered energy, latency) are NOT asserted here;
they are printed by `python -m backend.validation_report`.
"""

import ast
import inspect
import re
from pathlib import Path

import h3
import pytest
from fastapi.testclient import TestClient

from backend.api import cache as cache_mod
from backend.api import core_contract, routes
from backend.api.main import app
from backend.api.schemas import AnalyzeResponse, ChaosMonkeyResponse

ROOT = Path(__file__).resolve().parents[2]
HEX = re.compile(r"[0-9a-f]{15}")
CHILECITO = {'type': 'Polygon', 'coordinates': [[[-69.5, -31], [-65.5, -31], [-65.5, -27.5], [-69.5, -27.5], [-69.5, -31]]]}  # ASSUMPTION (SPECS.md §5.3 preset)
OCEAN = {"type": "Polygon", "coordinates": [[[-30.5, -30.5], [-29.5, -30.5], [-29.5, -29.5],
                                             [-30.5, -29.5], [-30.5, -30.5]]]}
BRAZIL_LAT, BRAZIL_LNG = (-34.0, 6.0), (-74.0, -34.0)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean_cache():
    cache_mod.ANALYZE_CACHE.clear()
    yield


def analyze(client, body, status=200):
    r = client.post("/api/analyze", json=body)
    assert r.status_code == status, r.text
    return r


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    b = r.json()
    assert b["status"] == "ok" and b["duckdb"] == "ok"
    assert isinstance(b["row_count"], int) and b["row_count"] > 0
    assert b["data_source"] == "synthetic" and isinstance(b["missing_columns"], list)
    assert set(b["core"]) == set(core_contract.CORE_FUNCTIONS)
    assert all(isinstance(v, bool) for v in b["core"].values())


def test_analyze_chilecito_matches_schema(client, fake_core):
    resp = AnalyzeResponse.model_validate(analyze(client, {"aoi": CHILECITO}).json())
    assert resp.data_source == "synthetic"
    assert resp.calendar_series and resp.map_hexagons and resp.phenology_by_year
    assert resp.forecast_series is None or (len(resp.forecast_series) == 14 and all(c.is_forecast for c in resp.forecast_series))
    assert all(c.pm25_emitted_kg is None and c.tooltip_narrative for c in resp.calendar_series)
    assert resp.audit_metrics is not None and resp.audit_metrics.total_pm25_emitted_tonnes is None
    assert resp.execution_time_ms > 0 and re.fullmatch(r"[0-9a-f]{64}", resp.query_hash)
    assert resp.total_h3_cells == len(resp.map_hexagons) and resp.aoi_area_km2 > 0


def test_h3_indices_are_15_char_hex_inside_brazil(client, fake_core):
    hexes = analyze(client, {"aoi": CHILECITO}).json()["map_hexagons"]
    assert hexes
    for h in hexes:
        idx = h["h3_index"]
        assert isinstance(idx, str) and HEX.fullmatch(idx) and h3.is_valid_cell(idx)
        lat, lng = h3.cell_to_latlng(idx)
        assert BRAZIL_LAT[0] < lat < BRAZIL_LAT[1] and BRAZIL_LNG[0] < lng < BRAZIL_LNG[1]


def test_repeated_request_is_served_from_cache(client, fake_core):
    r1, r2 = analyze(client, {"aoi": CHILECITO}), analyze(client, {"aoi": CHILECITO})
    assert r1.headers["x-cache"] == "MISS" and r2.headers["x-cache"] == "HIT"
    assert r1.json()["query_hash"] == r2.json()["query_hash"]
    assert r1.json()["calendar_series"] == r2.json()["calendar_series"]


def test_ocean_returns_empty_lists(client, fake_core):
    resp = AnalyzeResponse.model_validate(analyze(client, {"aoi": OCEAN}).json())
    assert resp.calendar_series == [] and resp.map_hexagons == [] and resp.phenology_by_year == []
    assert resp.audit_metrics is None and resp.total_h3_cells == 0 and resp.data_source == "synthetic"


@pytest.mark.parametrize("body", [
    {"aoi": {"type": "Polygon", "coordinates": [[[-49, -17], [-47, -17], [-47, -15], [-49, -15]]]}},
    {"aoi": {"type": "Polygon", "coordinates": [[[-49, -17], [-47, -17], [-49, -17]]]}},
    {"aoi": {"type": "Polygon", "coordinates": [[[-200, -17], [-47, -17], [-47, -15], [-200, -17]]]}},
    {"aoi": {"type": "Polygon", "coordinates": [[[-49, -17], [-47, -15], [-47, -17], [-49, -15], [-49, -17]]]}},
    {"aoi": CHILECITO, "start_year": 1990},
    {"aoi": CHILECITO, "end_year": 2030},
    {"aoi": CHILECITO, "start_year": 2020, "end_year": 2010},
])
def test_invalid_input_is_422(client, fake_core, body):
    assert client.post("/api/analyze", json=body).status_code == 422


def test_chaos_monkey_matches_schema(client, fake_core):
    r = client.post("/api/chaos-monkey", json={"aoi": CHILECITO})
    assert r.status_code == 200, r.text
    assert ChaosMonkeyResponse.model_validate(r.json()).data_source == "synthetic"


def test_chaos_monkey_without_data_is_404(client, fake_core):
    assert client.post("/api/chaos-monkey", json={"aoi": OCEAN}).status_code == 404


def test_core_missing_function_message_names_it(monkeypatch):
    mod, _, sig = core_contract.CORE_FUNCTIONS["kalman_rts_smooth"]
    monkeypatch.setitem(core_contract.CORE_FUNCTIONS, "kalman_rts_smooth", (mod, "function_that_does_not_exist", sig))
    with pytest.raises(core_contract.CoreMissingError, match="function_that_does_not_exist"):
        core_contract.require("kalman_rts_smooth")


def test_core_missing_returns_503(client, fake_core, monkeypatch):
    def resolve(name):
        if name == "kalman_rts_smooth":
            raise core_contract.CoreMissingError("Missing backend.core.kalman_rts.kalman_rts_smooth")
        return fake_core[name]
    monkeypatch.setattr(core_contract, "_resolve", resolve)
    r = client.post("/api/analyze", json={"aoi": CHILECITO})
    assert r.status_code == 503 and "kalman_rts_smooth" in r.text


def test_routes_are_sync_and_middleware_configured():
    for fn in (routes.analyze, routes.chaos_monkey, routes.health, routes.trigger_cube_sync, routes.get_cube_sync_status):
        assert inspect.isfunction(fn) and not inspect.iscoroutinefunction(fn)
    mws = {m.cls.__name__: m for m in app.user_middleware}
    assert {"CORSMiddleware", "GZipMiddleware"} <= set(mws)
    opts = lambda m: getattr(m, "kwargs", None) or getattr(m, "options", {})  # noqa: E731
    assert opts(mws["GZipMiddleware"]).get("minimum_size") == 1000
    assert opts(mws["CORSMiddleware"]).get("allow_origins") == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_gzip_is_applied(client, fake_core):
    assert analyze(client, {"aoi": CHILECITO}).headers.get("content-encoding") == "gzip"


def test_cube_sync_endpoints(client):
    r_status = client.get("/api/cube/sync-status")
    assert r_status.status_code == 200
    data = r_status.json()
    assert "status" in data
    assert "data_source" in data

    r_sync = client.post("/api/cube/sync", json={"days": 1, "regions": ["chilecito_la_rioja"]})
    assert r_sync.status_code == 200
    data_sync = r_sync.json()
    assert data_sync["status"] in ("success", "idle", "in_progress")



def test_no_silent_fallbacks_or_shortcuts_in_source():
    files = ["backend/api/routes.py", "backend/api/cache.py", "backend/api/main.py",
             "backend/api/core_contract.py", "backend/db/duckdb_engine.py", "backend/db/queries.py"]
    for f in files:
        src = (ROOT / f).read_text()
        assert src.strip(), f
        for banned in ("mock_analyze_response", "FAKE_CORE", "except ImportError", "TODO", "FIXME",
                       "async def analyze", "async def chaos_monkey", "pytest"):
            assert banned not in src, (f, banned)
        assert "INSTALL " not in src.upper(), f
    tree = ast.parse((ROOT / "backend/api/core_contract.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            assert any(isinstance(n, ast.Raise) for n in ast.walk(node)), node.lineno
