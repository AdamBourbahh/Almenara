"""Exact temporal map filtering, independently of regional Kalman estimates."""

from contextlib import contextmanager
from datetime import date

import duckdb
import h3.api.basic_int as h3
import pyarrow as pa
import pytest
from fastapi.testclient import TestClient

from backend.api import routes
from backend.api.main import app
from backend.db import duckdb_engine, queries


@pytest.fixture
def period_cube(monkeypatch, tmp_path):
    a = h3.latlng_to_cell(-29.0, -67.5, 7)
    b = h3.grid_disk(a, 1)[1]
    parent = h3.cell_to_parent(a, 4)
    rows = []
    for cell, day, energy, count, industrial in [
        (a, "2020-02-28", 100.0, 1, 0.0),
        (a, "2020-02-29", 200.0, 2, 0.0),
        (b, "2020-02-29", 900.0, 9, 1.0),
        (a, "2020-03-01", 400.0, 4, 0.0),
    ]:
        row = {name: None for name in queries._SCAN_COLUMNS}
        row.update(h3_r4=h3.cell_to_parent(cell, 4), h3_r7=cell,
                   epoch_day=(date.fromisoformat(day) - date(1970, 1, 1)).days,
                   year=2020, raw_modis_cnt=count, raw_viirs_cnt=0, raw_frp_mw=energy,
                   obs_terra_fre=energy, industrial_prob=industrial)
        rows.append(row)
    conn = duckdb.connect()
    conn.register("seed", pa.Table.from_pylist(rows))
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
    monkeypatch.setattr(routes, "_filter_or_422", lambda coords: (
        sorted({parent, h3.cell_to_parent(b, 4)}), sorted([a, b]), 1.0))
    routes.ANALYZE_CACHE.clear()
    yield TestClient(app), h3.int_to_str(a), h3.int_to_str(b)
    conn.close()


def request(client, start, end, exclude=True):
    return client.post(f"/api/map-period?start_date={start}&end_date={end}", json={
        "aoi": {"type": "Polygon", "coordinates": [
            [[-68, -30], [-67, -30], [-67, -28], [-68, -28], [-68, -30]]]},
        "start_year": 2020, "end_year": 2020,
        "exclude_industrial_flaring": exclude})


def test_daily_monthly_empty_and_industrial_maps_use_only_requested_rows(period_cube):
    client, a, b = period_cube
    first = request(client, "2020-02-28", "2020-02-28")
    assert first.status_code == 200, first.text
    one = first.json()
    assert one["data_source"] == "synthetic"
    assert one["start_date"] == one["end_date"] == "2020-02-28"
    assert [(h["h3_index"], h["mean_annual_fre"], h["raw_pixel_count"])
            for h in one["map_hexagons"]] == [(a, 100.0, 1)]
    leap = request(client, "2020-02-29", "2020-02-29").json()
    assert leap["map_hexagons"][0]["mean_annual_fre"] == 200.0
    month = request(client, "2020-02-01", "2020-02-29").json()
    assert month["map_hexagons"][0]["mean_annual_fre"] == 300.0
    assert month["map_hexagons"][0]["raw_pixel_count"] == 3
    assert request(client, "2020-02-27", "2020-02-27").json()["map_hexagons"] == []
    all_cells = request(client, "2020-02-29", "2020-02-29", False).json()
    assert {h["h3_index"] for h in all_cells["map_hexagons"]} == {a, b}
    cached = request(client, "2020-02-28", "2020-02-28")
    assert cached.headers["x-cache"] == "HIT"
    assert cached.json()["map_hexagons"] == one["map_hexagons"]


@pytest.mark.parametrize("start,end", [
    ("2020-02-30", "2020-03-01"), ("2020-03-01", "2020-02-29"),
    ("2019-12-31", "2020-01-01"), ("2019-01-01", "2019-01-02"),
])
def test_invalid_period_is_rejected(period_cube, start, end):
    assert request(period_cube[0], start, end).status_code == 422
