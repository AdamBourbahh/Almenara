"""Regression tests for energy accounting, calendar bounds, sensor labels, input limits and caches.

The frozen fixture cube is dense (one row per cell and day). The real cube is sparse (a row only when
a cell has detections), so these tests build a small sparse cube to exercise the real data shape.
"""

from contextlib import contextmanager
from datetime import date
from time import perf_counter
from types import SimpleNamespace

import duckdb
import h3.api.basic_int as h3
import numpy as np
import pyarrow as pa
import pytest
from fastapi.testclient import TestClient
from scipy.stats import theilslopes

from backend.api import cache as cache_mod
from backend.api import routes, science_adapter
from backend.api.main import app
from backend.db import duckdb_engine, queries

EPOCH = date(1970, 1, 1)
CENTRE = (-29.0, -67.5)
CUBE_SCHEMA = pa.schema([
    ("h3_r4", pa.uint64()), ("h3_r7", pa.uint64()), ("epoch_day", pa.uint16()), ("year", pa.uint16()),
    ("doy", pa.uint16()), ("raw_modis_cnt", pa.uint16()), ("raw_viirs_cnt", pa.uint16()),
    ("raw_frp_mw", pa.float32()), ("obs_terra_fre", pa.float32()), ("obs_aqua_fre", pa.float32()),
    ("obs_viirs_fre", pa.float32()), ("neighbor_fre_lag1", pa.float32()), ("cloud_cover_pct", pa.float32()),
    ("gap_status_mask", pa.uint8()), ("sensor_obs_mask", pa.uint8()), ("burned_area_ha_mcd64", pa.float32()),
    ("industrial_prob", pa.float32()),
])


def epoch(day: str) -> int:
    return (date.fromisoformat(day) - EPOCH).days


def square(lat: float, lng: float, d: float) -> list:
    return [[[lng - d, lat - d], [lng + d, lat - d], [lng + d, lat + d], [lng - d, lat + d], [lng - d, lat - d]]]


@pytest.fixture
def sparse_cube(monkeypatch, tmp_path):
    """Two neighbouring cells, three detection days in 2020, nothing else (real-cube shape)."""
    a = h3.latlng_to_cell(*CENTRE, 7)
    b = next(c for c in h3.grid_disk(a, 1) if c != a)
    # day, cell, terra, aqua, viirs, sensor_obs_mask (bits as written by the ETL)
    days = [("2020-03-01", a, 100.0, None, None, 1),
            ("2020-03-02", b, None, None, 60.0, 8 | 16),   # NOAA-20 + NOAA-21 only
            ("2020-03-03", a, 30.0, 50.0, None, 1 | 2)]
    rows = [dict(h3_r4=h3.cell_to_parent(cell, 4), h3_r7=cell, epoch_day=epoch(day), year=2020,
                 doy=date.fromisoformat(day).timetuple().tm_yday, raw_modis_cnt=1 if terra or aqua else 0,
                 raw_viirs_cnt=1 if viirs else 0, raw_frp_mw=10.0, obs_terra_fre=terra, obs_aqua_fre=aqua,
                 obs_viirs_fre=viirs, neighbor_fre_lag1=None, cloud_cover_pct=None, gap_status_mask=0,
                 sensor_obs_mask=mask, burned_area_ha_mcd64=None, industrial_prob=0.0)
            for day, cell, terra, aqua, viirs, mask in days]
    conn = duckdb.connect()
    conn.register("seed", pa.Table.from_pylist(rows, schema=CUBE_SCHEMA))
    conn.execute("CREATE TABLE fire_cube AS SELECT * FROM seed")

    @contextmanager
    def cursor():
        cur = conn.cursor()
        try:
            yield cur
        finally:
            cur.close()

    stamp = tmp_path / "cube.parquet"
    stamp.touch()
    monkeypatch.setattr(duckdb_engine, "get_db_cursor", cursor)
    monkeypatch.setattr(duckdb_engine, "missing_columns", lambda: [])
    monkeypatch.setattr(duckdb_engine, "cube_path", lambda: stamp)
    monkeypatch.setattr(duckdb_engine, "data_source", lambda: "synthetic")
    monkeypatch.setattr(duckdb_engine, "last_epoch_day", lambda: epoch("2020-03-03"))
    cache_mod.ANALYZE_CACHE.clear()
    cache_mod.GEOMETRY_CACHE.clear()
    expected = {"2020-03-01": (100.0, a), "2020-03-02": (60.0, b), "2020-03-03": (40.0, a)}
    yield TestClient(app), expected
    cache_mod.ANALYZE_CACHE.clear()
    cache_mod.GEOMETRY_CACHE.clear()
    conn.close()


def analyze_sparse(client, **extra):
    aoi = {"type": "Polygon", "coordinates": square(*CENTRE, 0.05)}
    body = {"aoi": aoi, "start_year": 2020, "end_year": 2020, "enable_kalman_gap_filling": False, **extra}
    response = client.post("/api/analyze", json=body)
    assert response.status_code == 200, response.text
    return aoi, response.json()


def test_biomass_integrates_density_over_the_cells_present_each_day(sparse_cube):
    client, expected = sparse_cube
    aoi, data = analyze_sparse(client)
    _, r7, _ = queries.get_hierarchical_h3_filter(aoi["coordinates"])
    assert {cell for _, cell in expected.values()} <= set(r7)
    by_date = {cell["date"]: cell for cell in data["calendar_series"]}
    for day, (density, cell) in expected.items():
        energy_mj = density * h3.cell_area(cell, unit="km^2")
        assert by_date[day]["harmonized_fre_mj_km2"] == pytest.approx(density)
        assert by_date[day]["biomass_burned_tonnes"] == pytest.approx(routes.WOOSTER_KG_PER_MJ * energy_mj / 1000)
    assert all(cell["biomass_burned_tonnes"] == 0 for d, cell in by_date.items() if d not in expected)
    total_mj = sum(density * h3.cell_area(cell, unit="km^2") for density, cell in expected.values())
    assert data["phenology_by_year"][0]["total_annual_fre_gj"] == pytest.approx(total_mj / 1000)


def test_aoi_area_is_the_polygon_area_not_the_burning_cells(sparse_cube):
    client, _ = sparse_cube
    aoi, data = analyze_sparse(client)
    _, r7, area = queries.get_hierarchical_h3_filter(aoi["coordinates"])
    assert len(r7) > 2 and data["aoi_area_km2"] == pytest.approx(area)


def test_calendar_ends_on_the_last_cube_day(sparse_cube):
    client, _ = sparse_cube
    _, data = analyze_sparse(client, enable_kalman_gap_filling=True)
    dates = [cell["date"] for cell in data["calendar_series"]]
    assert dates[0] == "2020-01-01" and dates[-1] == "2020-03-03" and len(dates) == 63


def test_noaa20_and_noaa21_bits_are_labelled(sparse_cube):
    client, _ = sparse_cube
    _, data = analyze_sparse(client)
    sensors = {cell["date"]: cell["active_sensors"] for cell in data["calendar_series"]}
    assert sensors["2020-03-01"] == ["Terra"]
    assert sensors["2020-03-02"] == ["VIIRS NOAA-20", "VIIRS NOAA-21"]
    assert sensors["2020-03-03"] == ["Terra", "Aqua"]
    assert sensors["2020-01-01"] == []


def test_polygon_vertex_limit():
    angles = np.linspace(0, 2 * np.pi, queries.MAX_POLYGON_VERTICES, endpoint=False)
    ring = [[-67.5 + 0.3 * float(np.cos(t)), -29.0 + 0.3 * float(np.sin(t))] for t in angles]
    with pytest.raises(ValueError, match="positions"):
        queries.validate_polygon_topology([ring + [ring[0]]])
    queries.validate_polygon_topology([ring[:-1] + [ring[0]]])  # exactly at the limit


def test_huge_polygons_are_rejected_before_the_r7_polyfill():
    started = perf_counter()
    with pytest.raises(ValueError, match="AOI too large"):
        queries.get_hierarchical_h3_filter(square(30.0, 0.0, 30.0))
    assert perf_counter() - started < 1.0


def test_polygons_at_the_limit_are_still_counted_exactly():
    # An 11.85° square from (-5°, 38°) holds just under 250,000 R7 cells: it must not be rejected early.
    side = 11.85
    _, r7, _ = queries.get_hierarchical_h3_filter(
        [[[-5, 38], [-5 + side, 38], [-5 + side, 38 + side], [-5, 38 + side], [-5, 38]]])
    assert 0.95 * queries.MAX_R7_CELLS < len(r7) <= queries.MAX_R7_CELLS


def test_copilot_text_limits():
    with TestClient(app) as client:
        too_long = client.post("/api/explain-spike", json={"user_question": "x" * (routes.MAX_QUESTION_CHARS + 1)})
        assert too_long.status_code == 422
        name = client.post("/api/explain-spike", json={"region_name": "x" * (routes.MAX_REGION_NAME_CHARS + 1)})
        assert name.status_code == 422


def test_cache_is_bounded_by_bytes():
    sized = lambda n: SimpleNamespace(nbytes=n)  # noqa: E731
    lru = cache_mod.LRUCache(maxsize=10, max_bytes=100)
    for key in "abc":
        lru.put(key, sized(40))
    assert lru.get("a") is None and lru.get("b") is not None and lru.nbytes == 80
    lru.put("huge", sized(101))
    assert lru.get("huge") is None and lru.nbytes == 80
    lru.put("b", sized(10))
    assert lru.nbytes == 50
    assert cache_mod.CachedJSON(b'{"execution_time_ms":1.0}').nbytes > 0
    assert cache_mod.CachedGeometry(([1], [2, 3], 1.0)).nbytes == 3 * cache_mod.CachedGeometry.BYTES_PER_CELL


def test_theil_sen_rows_match_scipy():
    rng = np.random.default_rng(3)
    values = rng.exponential(5, (300, 26)) * (rng.random((300, 26)) < 0.3)
    values[:5] = 4.0
    years = np.arange(2001, 2027, dtype=float)
    slopes = queries._theil_sen_rows(values, years)
    assert np.all(slopes[:5] == 0)
    for row in range(5, 300):
        expected = theilslopes(values[row], years).slope if np.ptp(values[row]) > 0 else 0.0
        assert slopes[row] == pytest.approx(expected)


def test_chaos_prior_excludes_the_target_year(monkeypatch):
    days = np.arange(epoch("2021-01-01"), epoch("2022-12-31") + 1)
    dates = np.datetime64("1970-01-01") + days.astype("timedelta64[D]")
    years = dates.astype("datetime64[Y]").astype(int) + 1970
    daily = {"epoch_day": days, "year": years,
             "doy": (dates - dates.astype("datetime64[Y]")).astype(int) + 1,
             "obs_terra_fre": np.where(years == 2022, 999.0, 1.0), "obs_aqua_fre": np.full(len(days), np.nan),
             "obs_viirs_fre": np.full(len(days), np.nan), "neighbor_fre_lag1": np.full(len(days), np.nan),
             "cloud_cover_pct": np.full(len(days), np.nan)}
    seen = {}

    def fake(*args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(model_dump=lambda exclude: {})

    monkeypatch.setattr(science_adapter, "dependency", lambda name: fake)
    science_adapter.run_chaos_monkey_simulation(daily, 2022, 0.25, True, 42)
    assert len(seen["full_doy_history"]) == 365 and np.all(seen["full_y_obs_history"][:, 0] == 1.0)
    with pytest.raises(ValueError, match="outside the target year"):
        science_adapter.run_chaos_monkey_simulation({**daily, "obs_terra_fre": np.where(years == 2022, 5.0, np.nan)},
                                                    2022, 0.25, True, 42)
