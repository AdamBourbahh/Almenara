"""NASA POWER CLOUD_AMT fetcher on a fixture shaped like the real response (no network)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pyarrow.parquet as pq
import pytest

from pipeline import cloud_power

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "power_cloud_amt.json").read_text())
START, END = date(2023, 1, 1), date(2023, 1, 5)


def fixture_client(calls: list, fail_first: int = 0):
    """httpx client whose transport answers with the fixture and records each request's query."""
    state = {"failures": fail_first}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        if state["failures"]:
            state["failures"] -= 1
            return httpx.Response(503, text="busy")
        body = json.loads(json.dumps(FIXTURE))
        lat, lon = float(request.url.params["latitude"]), float(request.url.params["longitude"])
        body["geometry"]["coordinates"] = [lon, lat, 1.0]
        # Shift the series by the cell so different cells give different values.
        series = body["properties"]["parameter"]["CLOUD_AMT"]
        for key, value in series.items():
            if value > 0:
                series[key] = round(value - abs(lat) * 0.01, 2)
        return httpx.Response(200, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler), headers=cloud_power.HEADERS)


def test_parse_response_converts_percent_to_fraction_and_fill_to_none():
    values = cloud_power.parse_response(FIXTURE)
    assert values == {date(2023, 1, 1): 0.9426, date(2023, 1, 2): 0.8392, date(2023, 1, 3): 0.8,
                      date(2023, 1, 4): None, date(2023, 1, 5): 0.0}
    assert values[date(2023, 1, 5)] == 0.0 and values[date(2023, 1, 4)] is None


def test_parse_response_rejects_out_of_range_percent_and_missing_parameter():
    bad = json.loads(json.dumps(FIXTURE))
    bad["properties"]["parameter"]["CLOUD_AMT"]["20230102"] = 100.5
    with pytest.raises(ValueError, match="outside 0-100"):
        cloud_power.parse_response(bad)
    with pytest.raises(ValueError, match="CLOUD_AMT"):
        cloud_power.parse_response({"properties": {"parameter": {}}})


@pytest.mark.parametrize("bounds,expected", [
    ((-62.0, -5.0, -58.0, -1.0), {(lat, lon) for lat in range(-5, 0) for lon in range(-62, -57)}),
    ((-9.5, 36, 4, 44), {(lat, lon) for lat in range(36, 45) for lon in range(-10, 5)}),
    ((-81.5, 28.2, -80.9, 28.8), {(28, -82), (28, -81)}),          # inside one latitude row
    ((-60.0, -3.0, -59.0, -2.0), {(-3, -60), (-3, -59), (-2, -60), (-2, -59)}),   # integer edges included
])
def test_cells_for_bounds_cover_every_intersecting_cell_including_edges(bounds, expected):
    assert set(cloud_power.cells_for_bounds(bounds)) == expected


def test_all_cells_is_the_sorted_union_over_regions():
    regions = {"a": {"bounds": [-60.5, -3.5, -59.5, -2.5]}, "b": {"bounds": [-59.5, -2.5, -58.5, -1.5]}}
    cells = cloud_power.all_cells(regions)
    assert cells == sorted(set(cells))
    assert (-3, -61) in cells and (-2, -59) in cells and (-2, -60) in cells and len(cells) == 4 + 4 - 1


def test_cell_for_point_uses_floor_on_both_axes():
    assert cloud_power.cell_for_point(-3.0, -60.0) == (-3, -60)
    assert cloud_power.cell_for_point(-3.0001, -60.0001) == (-4, -61)
    assert cloud_power.cell_for_point(-2.9, -59.4) == (-3, -60)


def test_fetch_queries_the_cell_centre_with_the_documented_parameters(tmp_path):
    calls = []
    with fixture_client(calls) as client:
        cloud_power.fetch_cell(client, (-4, -61), tmp_path, START, END, sleep=0)
    assert calls == [{"parameters": "CLOUD_AMT", "community": "AG", "longitude": "-60.5",
                      "latitude": "-3.5", "start": "20230101", "end": "20230105", "format": "JSON"}]
    cached = json.loads((tmp_path / "lat-04_lon-061.json").read_text())
    assert cached["lat_sw"] == -4 and cached["lon_sw"] == -61 and cached["start"] == "20230101"
    assert cached["values"]["20230104"] == -999.0 and cached["fetched_utc"].endswith("Z")


def test_fetch_is_resumable_and_retries_with_backoff(tmp_path):
    calls, waits = [], []
    cells = [(-4, -61), (-3, -60)]
    with fixture_client(calls, fail_first=2) as client:
        cloud_power.fetch_all(client, cells, tmp_path, START, END, sleep=0, backoff=waits.append)
    assert len(calls) == 4 and waits == [1, 2]
    with fixture_client(calls := []) as client:
        cloud_power.fetch_all(client, cells + [(-2, -59)], tmp_path, START, END, sleep=0)
    assert [c["latitude"] for c in calls] == ["-1.5"]          # only the missing cell is requested


def test_fetch_gives_up_after_the_retry_budget(tmp_path):
    with fixture_client([], fail_first=99) as client:
        with pytest.raises(RuntimeError, match="after 3 attempts"):
            cloud_power.fetch_cell(client, (-4, -61), tmp_path, START, END, sleep=0,
                                   retries=3, backoff=lambda seconds: None)
    assert not list(tmp_path.glob("*.json"))


def test_cache_with_another_date_range_is_refetched(tmp_path):
    with fixture_client([]) as client:
        cloud_power.fetch_cell(client, (-4, -61), tmp_path, START, END, sleep=0)
    with fixture_client(calls := []) as client:
        cloud_power.fetch_cell(client, (-4, -61), tmp_path, START, date(2023, 1, 6), sleep=0)
    assert len(calls) == 1


def build(tmp_path, cells, name="grid.parquet"):
    with fixture_client([]) as client:
        cloud_power.fetch_all(client, cells, tmp_path / "cache", START, END, sleep=0)
    return cloud_power.build_grid_table(cells, tmp_path / "cache", tmp_path / name, START, END)


def test_grid_table_schema_nulls_order_and_metadata(tmp_path):
    out = build(tmp_path, [(-3, -60), (-4, -61)])
    table = pq.read_table(out)
    assert table.column_names == ["grid_lat_sw", "grid_lon_sw", "acq_date", "cloud_fraction"]
    assert [str(f.type) for f in table.schema] == ["int16", "int16", "date32[day]", "double"]
    rows = table.to_pylist()
    assert len(rows) == 10
    assert [(r["grid_lat_sw"], r["grid_lon_sw"], r["acq_date"]) for r in rows] == sorted(
        (r["grid_lat_sw"], r["grid_lon_sw"], r["acq_date"]) for r in rows)
    first = rows[0]
    assert (first["grid_lat_sw"], first["grid_lon_sw"]) == (-4, -61)
    fills = [r for r in rows if r["acq_date"] == date(2023, 1, 4)]
    assert len(fills) == 2 and all(r["cloud_fraction"] is None for r in fills)
    zeros = [r for r in rows if r["acq_date"] == date(2023, 1, 5)]
    assert all(r["cloud_fraction"] == 0.0 for r in zeros)
    assert all(r["cloud_fraction"] is None or 0 <= r["cloud_fraction"] <= 1 for r in rows)
    assert pq.ParquetFile(out).metadata.row_group(0).column(0).compression == "ZSTD"
    meta = json.loads(pq.read_schema(out).metadata[b"cloud_power"])
    assert meta["parameter"] == "CLOUD_AMT" and meta["community"] == "AG"
    assert meta["url_template"].startswith("https://power.larc.nasa.gov/api/temporal/daily/point")
    assert meta["start"] == "2023-01-01" and meta["end"] == "2023-01-05"
    assert meta["grid"].startswith("1 degree") and meta["cells"] == 2 and meta["rows"] == 10
    assert "NULL" in meta["fill_handling"] and "-999" in meta["fill_handling"]
    cached = [json.loads(f.read_text())["fetched_utc"] for f in (tmp_path / "cache").glob("*.json")]
    assert meta["fetch_date_utc"] == max(cached)[:10]


def test_grid_table_is_byte_deterministic_and_order_independent(tmp_path):
    first = build(tmp_path, [(-3, -60), (-4, -61)], "a.parquet")
    second = cloud_power.build_grid_table([(-4, -61), (-3, -60)], tmp_path / "cache", tmp_path / "b.parquet",
                                          START, END)
    assert first.read_bytes() == second.read_bytes()


def test_grid_table_requires_every_cell_in_the_cache(tmp_path):
    build(tmp_path, [(-3, -60)])
    with pytest.raises(FileNotFoundError, match="lat-04_lon-061"):
        cloud_power.build_grid_table([(-3, -60), (-4, -61)], tmp_path / "cache", tmp_path / "x.parquet",
                                     START, END)
