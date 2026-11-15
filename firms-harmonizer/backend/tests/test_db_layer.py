"""Frozen contract tests for backend/db and backend/api/cache.py. DO NOT EDIT."""

import ast
import hashlib
import inspect
import threading
from pathlib import Path

import h3
import numpy as np
import orjson
import pyarrow.parquet as pq
import pytest

from backend.api import cache as cache_mod
from backend.api.schemas import H3MapSummaryHex
from backend.db import duckdb_engine, queries

CHILECITO = [[[-69.5, -31], [-65.5, -31], [-65.5, -27.5], [-69.5, -27.5], [-69.5, -31]]]  # ASSUMPTION (SPECS.md §5.3 preset)
AMAZONAS = [[[-62, -5], [-58, -5], [-58, -1], [-62, -1], [-62, -5]]]
OCEAN = [[[-30.5, -30.5], [-29.5, -30.5], [-29.5, -29.5], [-30.5, -29.5], [-30.5, -30.5]]]
HEX = r"[0-9a-f]{15}"
SPEC_COLUMNS = {
    "h3_r4", "h3_r7", "epoch_day", "year", "doy", "igbp_biome", "sensor_obs_mask", "gap_status_mask",
    "cloud_cover_pct", "raw_modis_cnt", "raw_viirs_cnt", "raw_frp_mw", "obs_terra_fre", "obs_aqua_fre",
    "obs_viirs_fre", "neighbor_fre_lag1", "industrial_prob", "burned_area_ha_mcd64",
}
DAILY_KEYS = {
    "epoch_day", "year", "doy", "raw_modis_cnt", "raw_viirs_cnt", "raw_frp_mw", "obs_terra_fre",
    "obs_aqua_fre", "obs_viirs_fre", "neighbor_fre_lag1", "cloud_cover_pct", "gap_status_mask",
    "sensor_obs_mask", "burned_area_ha_mcd64", "observed_energy_mj", "observation_known", "observed_zero", "pm25_emitted_kg", "coverage_complete", "pm25_factor_sd_kg",
}


def latlng_poly(coords):
    return h3.LatLngPoly([(lat, lng) for lng, lat in coords[0][:-1]])


def direct_r7(coords):
    return sorted(h3.str_to_int(c) for c in h3.polygon_to_cells(latlng_poly(coords), 7))


def square(lng, lat, d):
    return [[[lng - d, lat - d], [lng + d, lat - d], [lng + d, lat + d], [lng - d, lat + d], [lng - d, lat - d]]]


@pytest.fixture(scope="module")
def engine():
    duckdb_engine.init_engine()
    return duckdb_engine


def fetch(coords, start=2001, end=2026, exclude=True):
    r4, r7, _ = queries.get_hierarchical_h3_filter(coords)
    return queries.fetch_aoi_aggregated_data(r4, r7, start, end, exclude)


# ---------------- hierarchical filter ----------------

def test_filter_equals_direct_r7_polyfill_and_unique_parents():
    r4, r7, area = queries.get_hierarchical_h3_filter(CHILECITO)
    assert r7 and r7 == direct_r7(CHILECITO)
    assert all(type(c) is int for c in r4 + r7)
    assert r4 == sorted({h3.str_to_int(h3.cell_to_parent(h3.int_to_str(c), 4)) for c in r7})
    assert area == pytest.approx(sum(h3.cell_area(h3.int_to_str(c), unit="km^2") for c in r7))


def test_filter_keeps_border_parents_that_r4_polyfill_misses():
    r4, _, _ = queries.get_hierarchical_h3_filter(CHILECITO)
    r4_direct = {h3.str_to_int(c) for c in h3.polygon_to_cells(latlng_poly(CHILECITO), 4)}
    assert set(r4) - r4_direct


def test_filter_respects_geojson_lon_lat_order():
    _, r7, _ = queries.get_hierarchical_h3_filter(CHILECITO)
    for c in r7:
        lat, lng = h3.cell_to_latlng(h3.int_to_str(c))
        assert -31.01 < lat < -27.49 and -69.51 < lng < -65.49


def test_tiny_polygon_has_no_centroid_fallback():
    tiny = square(-48.0, -16.0, 0.0005)
    r4, r7, area = queries.get_hierarchical_h3_filter(tiny)
    assert r7 == direct_r7(tiny)
    if not r7:
        assert r4 == [] and area == 0.0


def test_topology_validation_rejects_bowtie():
    bowtie = [[[-49.0, -17.0], [-47.0, -15.0], [-47.0, -17.0], [-49.0, -15.0], [-49.0, -17.0]]]
    with pytest.raises(ValueError):
        queries.validate_polygon_topology(bowtie)
    queries.validate_polygon_topology(CHILECITO)


# ---------------- queries ----------------

def test_query_returns_exactly_cube_cells_inside_polygon(engine):
    _, r7, _ = queries.get_hierarchical_h3_filter(CHILECITO)
    cube_cells = set(pq.read_table(engine.cube_path(), columns=["h3_r7"])["h3_r7"].to_pylist())
    expected = sorted(h3.int_to_str(c) for c in set(r7) & cube_cells)
    assert expected
    assert [h.h3_index for h in fetch(CHILECITO, exclude=False).hexagons] == expected


def test_query_filters_r7_after_r4(engine):
    center = h3.latlng_to_cell(-29.25, -67.5, 7)  # synthetic Chilecito centre
    lat, lng = h3.cell_to_latlng(center)
    small = square(lng, lat, 0.003)
    _, r7, _ = queries.get_hierarchical_h3_filter(small)
    assert r7 == [h3.str_to_int(center)]
    assert [h.h3_index for h in fetch(small).hexagons] == [center]


def test_ocean_has_no_data(engine):
    agg = fetch(OCEAN)
    assert agg.hexagons == [] and agg.n_cells_used == 0 and agg.industrial_false_positives_removed == 0
    assert set(agg.daily) == DAILY_KEYS and all(len(v) == 0 for v in agg.daily.values())


def test_daily_contract(engine):
    agg = fetch(CHILECITO, 2015, 2016)
    d = agg.daily
    assert set(d) == DAILY_KEYS
    assert all(isinstance(v, np.ndarray) and len(v) == 731 for v in d.values())
    assert d["epoch_day"][0] == int((np.datetime64("2015-01-01") - np.datetime64("1970-01-01")).astype(int))
    assert np.all(np.diff(d["epoch_day"]) == 1)
    assert set(d["year"].tolist()) == {2015, 2016}
    assert d["raw_modis_cnt"].dtype.kind in "iu" and d["obs_terra_fre"].dtype == np.float64


def test_industrial_exclusion_contract(engine):
    keep, drop = fetch(AMAZONAS, exclude=False), fetch(AMAZONAS, exclude=True)
    total = int(keep.daily["raw_modis_cnt"].sum() + keep.daily["raw_viirs_cnt"].sum())
    assert keep.industrial_false_positives_removed == 0 and total > 0
    kept = int(drop.daily["raw_modis_cnt"].sum() + drop.daily["raw_viirs_cnt"].sum())
    assert drop.industrial_false_positives_removed > 0
    assert drop.industrial_false_positives_removed + kept == total  # every hotspot is kept or counted as removed
    assert drop.n_cells_used <= keep.n_cells_used
    assert drop.hexagons and any(h.is_industrial_site for h in drop.hexagons)


def test_hexagon_format(engine):
    hexes = fetch(CHILECITO).hexagons
    assert hexes and all(isinstance(h, H3MapSummaryHex) for h in hexes)
    import re
    for h in hexes:
        assert re.fullmatch(HEX, h.h3_index) and h3.is_valid_cell(h.h3_index)
        assert 0.0 <= h.shannon_entropy <= 1.0 and h.raw_pixel_count >= 0
    assert [h.h3_index for h in hexes] == sorted(h.h3_index for h in hexes)


def test_sql_is_never_built_from_formatted_strings():
    for f in (queries.__file__, duckdb_engine.__file__):
        tree = ast.parse(Path(f).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                text = "".join(v.value for v in node.values
                               if isinstance(v, ast.Constant) and isinstance(v.value, str)).upper()
                assert not any(k in text for k in ("SELECT ", " WHERE ", "READ_PARQUET", " IN (")), (f, node.lineno)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr != "format", (f, node.lineno)
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) \
                    and isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
                assert "SELECT" not in node.left.value.upper(), (f, node.lineno)
    src = Path(queries.__file__).read_text()
    assert "printf('%x', h3_r7)" in src and ".register(" in src


# ---------------- engine ----------------

def test_cursor_is_isolated_and_closed(engine):
    with engine.get_db_cursor() as cur:
        assert cur is not engine._MASTER_CONN
        assert cur.execute("SELECT COUNT(*) FROM fire_cube").fetchone()[0] > 0
    with pytest.raises(Exception):
        cur.execute("SELECT 1")
    assert inspect.isgeneratorfunction(inspect.unwrap(engine.get_db_cursor))


def test_cursor_closed_even_on_error(engine):
    with pytest.raises(RuntimeError):
        with engine.get_db_cursor() as cur:
            raise RuntimeError("boom")
    with pytest.raises(Exception):
        cur.execute("SELECT 1")


def test_parallel_cursors(engine):
    results, errors = [], []

    def work():
        try:
            with engine.get_db_cursor() as cur:
                results.append(cur.execute("SELECT COUNT(*) FROM fire_cube").fetchone()[0])
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and len(set(results)) == 1 and len(results) == 8


def test_cube_resolution_rules(tmp_path):
    real, synth = tmp_path / "real.parquet", tmp_path / "synth.parquet"
    with pytest.raises(duckdb_engine.CubeNotAvailableError, match="USE_SYNTHETIC_CUBE"):
        duckdb_engine.resolve_cube(real, synth, use_synthetic=False)
    path, source = duckdb_engine.resolve_cube(real, synth, use_synthetic=True)
    assert Path(path) == synth and synth.is_file() and source == "synthetic"
    real.write_bytes(synth.read_bytes())
    with pytest.raises(duckdb_engine.CubeNotAvailableError, match="SYNTHETIC"):
        duckdb_engine.resolve_cube(real, synth, use_synthetic=False)


def test_engine_reports_synthetic_source(engine):
    assert engine.data_source() == "synthetic"
    assert engine.missing_columns() == []


def test_missing_columns_detection():
    assert set(duckdb_engine.REQUIRED_COLUMNS) | set(duckdb_engine.OPTIONAL_COLUMNS) == SPEC_COLUMNS
    allc = sorted(SPEC_COLUMNS)
    assert duckdb_engine.missing_optional_columns(allc) == []
    partial = [c for c in allc if c not in ("cloud_cover_pct", "burned_area_ha_mcd64")]
    assert duckdb_engine.missing_optional_columns(partial) == ["burned_area_ha_mcd64", "cloud_cover_pct"]
    with pytest.raises(duckdb_engine.CubeNotAvailableError, match="h3_r7"):
        duckdb_engine.missing_optional_columns([c for c in allc if c != "h3_r7"])


# ---------------- cache ----------------

def test_cache_key_normalization_and_mtime():
    key = cache_mod.make_cache_key([30, 10, 20, 10], {"b": 2, "a": [1, 2]}, 123)
    expected = hashlib.blake2b(
        np.asarray([10, 20, 30], dtype="<u8").tobytes() + b"|"
        + orjson.dumps({"a": [1, 2], "b": 2}, option=orjson.OPT_SORT_KEYS) + b"|" + b"123",
        digest_size=32).hexdigest()
    assert key == expected
    assert key != cache_mod.make_cache_key([10, 20, 30], {"a": [1, 2], "b": 3}, 123)
    assert key != cache_mod.make_cache_key([10, 20, 31], {"a": [1, 2], "b": 2}, 123)
    assert key != cache_mod.make_cache_key([10, 20, 30], {"a": [1, 2], "b": 2}, 124)


def test_lru_eviction_and_bounds():
    c = cache_mod.LRUCache(maxsize=2)
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("a") == 1
    c.put("c", 3)
    assert c.get("b") is None and c.get("a") == 1 and c.get("c") == 3 and len(c) == 2
    c.clear()
    assert len(c) == 0
    with pytest.raises(ValueError):
        cache_mod.LRUCache(maxsize=0)
    assert isinstance(cache_mod.ANALYZE_CACHE, cache_mod.LRUCache)


def test_lru_thread_safety():
    c = cache_mod.LRUCache(maxsize=16)

    def work(k):
        for i in range(500):
            c.put(f"{k}-{i}", i)
            c.get(f"{k}-{i - 1}")

    threads = [threading.Thread(target=work, args=(k,)) for k in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(c) == 16
