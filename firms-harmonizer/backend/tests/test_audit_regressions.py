"""Independent physical and adversarial checks for the all-nighter audit."""
from datetime import date
from importlib import import_module

import h3
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from backend.api.cache import CachedJSON, LRUCache
from backend.api.schemas import ExplainSpikeRequest, GeoJSONPolygon
from backend.core.emissions import factor, pm25_kg
from backend.core.energy_forecast import evaluate, project
from backend.db import queries
from backend.db.observation_coverage import apply_coverage


def sparse_columns():
    cells = np.array([int(h3.latlng_to_cell(lat, lon, 7), 16) for lat, lon in [(28.5, -81.3), (40., -4.)]], dtype=np.uint64)
    epoch = (date(2024, 1, 2) - date(1970, 1, 1)).days
    columns = {name: np.zeros(2) for name in queries.OBS_COLUMNS + ('neighbor_fre_lag1', 'cloud_cover_pct', 'burned_area_ha_mcd64')}
    columns.update(h3_r7=cells, epoch_day=np.array([epoch, epoch]), year=np.array([2024, 2024]),
                   raw_modis_cnt=np.array([1, 1]), raw_viirs_cnt=np.array([0, 0]), raw_frp_mw=np.array([1., 2.]),
                   sensor_obs_mask=np.array([1, 2]), gap_status_mask=np.array([0, 0]))
    columns['obs_terra_fre'] = np.array([10., np.nan])
    columns['obs_aqua_fre'] = np.array([np.nan, 30.])
    columns['obs_viirs_fre'][:] = np.nan
    return columns


def test_sparse_energy_fuses_inside_cells_and_preserves_unequal_areas():
    columns = sparse_columns()
    daily = queries._aggregate_daily(columns, np.ones(2, bool), 2024, 2024, set(), 1000.)
    expected = sum(value * h3.cell_area(format(int(cell), 'x'), unit='km^2')
                   for value, cell in zip([10., 30.], columns['h3_r7']))
    assert daily['observed_energy_mj'].sum() == pytest.approx(expected)
    assert daily['observed_energy_mj'][1] == pytest.approx(expected)
    assert daily['observation_known'].sum() == 1
    assert not daily['observed_zero'].any()
    assert np.isnan(daily['obs_terra_fre'][0])
    # Unknown days contribute no invented climatological energy.
    assert daily['observed_energy_mj'][0] == 0


def test_coverage_requires_every_cell_and_rejects_fire_pixels(tmp_path):
    import duckdb
    output = tmp_path / 'data/processed/observation_coverage'
    output.mkdir(parents=True)
    daily = {'epoch_day': np.array([10, 11, 12])}
    rows = [dict(h3_r7=cell, epoch_day=day, satellite='Terra', clear_area_km2=area,
                 fire_area_km2=fire, cell_area_km2=5., sampled_area_km2=5.)
            for day, values in [(10, [(1, 5., 0.), (2, 5., 0.)]),
                                (11, [(1, 5., 0.)]), (12, [(1, 5., 0.), (2, 5., 1.)])]
            for cell, area, fire in values]
    pq.write_table(pa.Table.from_pylist(rows), output / 'mask.parquet')
    with duckdb.connect() as cur:
        assert apply_coverage(cur, tmp_path, [1, 2], daily, 10.).tolist() == [True, False, False]


def test_geometry_area_is_winding_independent_and_subtracts_holes():
    exterior = [[-4, 39], [-3, 39], [-3, 40], [-4, 40], [-4, 39]]
    hole = [[-3.8, 39.2], [-3.2, 39.2], [-3.2, 39.8], [-3.8, 39.8], [-3.8, 39.2]]
    actual = queries.polygon_area_km2([exterior, hole])
    assert actual == pytest.approx(queries.polygon_area_km2([exterior]) - queries.polygon_area_km2([hole]))
    assert actual == pytest.approx(queries.polygon_area_km2([exterior[::-1], hole[::-1]]))


def test_large_polygons_are_rejected_before_polyfill(monkeypatch):
    monkeypatch.setattr(queries.h3i, 'polygon_to_cells', lambda *a: pytest.fail('Expensive polyfill ran'))
    with pytest.raises(ValueError, match='preflight'):
        queries.get_hierarchical_h3_filter([[[-30, -30], [30, -30], [30, 30], [-30, 30], [-30, -30]]])


def test_question_and_vertex_limits():
    with pytest.raises(ValueError):
        ExplainSpikeRequest(user_question='x' * 6001)
    with pytest.raises(ValueError):
        GeoJSONPolygon(coordinates=[[[0., 0.]] * 513])


def test_cache_byte_budget_and_oversized_replacements():
    cache = LRUCache(64, maxbytes=70)
    cache.put('a', CachedJSON(b'{"execution_time_ms":0,"data":"' + b'x' * 30 + b'"}'))
    cache.put('b', CachedJSON(b'{"execution_time_ms":0,"data":"' + b'y' * 30 + b'"}'))
    assert cache.get('a') is None and cache.get('b') is not None
    cache.put('b', CachedJSON(b'{"execution_time_ms":0,"data":"' + b'z' * 100 + b'"}'))
    assert len(cache) == 0


def test_forecast_calendar_and_nonnegative_intervals():
    dates = np.arange(np.datetime64('2020-01-01'), np.datetime64('2024-02-29'))
    values = 10 + np.sin(np.arange(len(dates)) / 30)
    result = project(dates, values, 14)
    assert str(result['dates'][0]) == '2024-02-29'
    assert str(result['dates'][-1]) == '2024-03-13'
    assert np.all(result['lower'] <= result['predicted'])
    assert np.all(result['predicted'] <= result['upper'])


def test_forecast_has_no_post_origin_training_leakage():
    dates = np.arange(np.datetime64('2020-01-01'), np.datetime64('2024-01-01'))
    values = np.sin(np.arange(len(dates)) / 30) + 5
    origin = 1000
    first = project(dates[:origin], values[:origin], 14)
    values[origin:] = 1e6
    second = project(dates[:origin], values[:origin], 14)
    np.testing.assert_array_equal(first['predicted'], second['predicted'])
    assert {m['horizon_days'] for m in evaluate(dates[:origin], values[:origin])} == {1, 7, 14}


def test_pm25_units_and_unsupported_fuels():
    assert float(pm25_kg(1000., 6.7)) == pytest.approx(2.4656)
    assert factor(10, 28.) == 6.7
    assert factor(2, -3.) == 8.3
    assert factor(17, 28.) is None


def test_missing_observation_credentials_have_actionable_error(monkeypatch):
    monkeypatch.syspath_prepend(str(queries.duckdb_engine.ROOT / 'scripts'))
    import earthaccess
    module = import_module('09_fetch_observation_coverage')
    def unavailable(**kwargs):
        raise ValueError('no credentials')
    monkeypatch.setattr(earthaccess, 'login', unavailable)
    with pytest.raises(RuntimeError, match='EARTHDATA_TOKEN'):
        module.acquire(['orlando_florida'], date(2024, 1, 1), date(2024, 1, 8))


def test_rate_and_body_limits_without_science(monkeypatch):
    from fastapi import FastAPI
    from backend.api.request_limits import RequestLimits
    monkeypatch.setenv('REQUEST_RATE_MULTIPLIER', '1')
    app = FastAPI()
    app.add_middleware(RequestLimits)
    @app.post('/api/explain-spike')
    def endpoint():
        return {'ok': True}
    @app.post('/api/map-period')
    def map_period():
        return {'ok': True}
    with TestClient(app) as client:
        for _ in range(10):
            assert client.post('/api/explain-spike', json={}).status_code == 200
        assert client.post('/api/explain-spike', json={}).status_code == 429
        # The oversized body counts as one regular request; the remaining budget
        # absorbs a full multi-year map range before the limiter engages.
        assert client.post('/api/analyze', content=b'x' * (256 * 1024 + 1)).status_code == 413
        for _ in range(119):
            assert client.post('/api/map-period', json={}).status_code == 200
        assert client.post('/api/map-period', json={}).status_code == 429


def test_packed_masks_preserve_gaps_fire_and_sensor_identity(tmp_path, monkeypatch):
    import json
    from backend.db.packed_coverage import read_selected
    monkeypatch.syspath_prepend(str(queries.duckdb_engine.ROOT / 'scripts'))
    module = import_module('09_fetch_observation_coverage')
    folder = tmp_path / 'data/processed/observation_coverage'
    folder.mkdir(parents=True)
    (tmp_path / 'data/regions.json').write_text(json.dumps({'orlando_florida': {'bounds': [-82,28,-80.7,29.3]}}))
    cells = [int(h3.latlng_to_cell(lat, -81.3, 7),16) for lat in [28.5,28.6]]
    rows = [dict(h3_r7=cell, epoch_day=day, clear_area_km2=5., sampled_area_km2=5.,
                 cell_area_km2=5., fire_area_km2=fire)
            for day, values in [(10, [(cells[0],0.), (cells[1],0.)]), (11,[(cells[0],0.)]),
                                (12, [(cells[0],0.), (cells[1],1.)])]
            for cell, fire in values]
    module.write_summary(rows, folder / 'orlando_florida_Terra_unit.parquet', {b'granule': b'unit'})
    zero, complete = read_selected(str(tmp_path), 1, tuple(sorted(cells)), 10, 12, False)
    assert zero.tolist() == [1,0,0]  # Only Terra; never fabricated Aqua/VIIRS zeros.
    assert complete.tolist() == [1,0,1]


def test_partial_composite_uses_explicit_dates(monkeypatch):
    monkeypatch.syspath_prepend(str(queries.duckdb_engine.ROOT / 'scripts'))
    module = import_module('09_fetch_observation_coverage')
    monkeypatch.setattr(module, 'pixel_groups', lambda *args: (np.array([0]), np.array([1],dtype=np.uint64), np.array([0]), np.array([1.])))
    mask = np.array([[[5]], [[5]]])
    result = module.reduce_mask(mask, 'MOD14A1.A2024001.h10v06.061.demo', [-82,28,-80.7,29.3],
        date(2024,1,1), date(2024,1,8), band_dates=[date(2024,1,1),date(2024,1,3)])
    origin = (date(2024,1,1)-date(1970,1,1)).days
    assert result['days'].tolist() == [origin, origin+2]
    with pytest.raises(ValueError, match='explicit'):
        module.reduce_mask(mask, 'MOD14A1.A2024001.h10v06.061.demo', [-82,28,-80.7,29.3], date(2024,1,1), date(2024,1,8))


def test_emission_uncertainty_keeps_common_fuel_factor_correlated(tmp_path):
    from backend.db.emission_inputs import estimate
    lookup = tmp_path / 'data/lookup'
    lookup.mkdir(parents=True)
    cell = int(h3.latlng_to_cell(28.5,-81.3,7),16)
    table = pa.Table.from_pylist([dict(h3_r7=cell, year=2024, igbp_biome=10)])
    pq.write_table(table.replace_schema_metadata({b'source': b'NASA MCD12Q1.061'}), lookup/'igbp_cells.parquet')
    mean, sd = estimate(tmp_path, np.array([cell,cell],dtype=np.uint64), np.array([2024,2024]),
                        np.array([1000.,1000.]), np.array([0,0]), 1)
    assert mean[0] == pytest.approx(2000*.368*6.7/1000)
    assert sd[0] == pytest.approx(np.hypot(2000*.368*3.3/1000, mean[0]*.015/.368))
    missing, _ = estimate(tmp_path, np.array([cell],dtype=np.uint64), np.array([2025]), np.array([1000.]),np.array([0]),1)
    assert np.isnan(missing[0])


def test_reload_does_not_close_inflight_cursor():
    engine = queries.duckdb_engine
    with engine.get_db_cursor() as cursor:
        expected = cursor.execute('SELECT count(*) FROM fire_cube').fetchone()[0]
        engine.reload_engine()
        assert cursor.execute('SELECT count(*) FROM fire_cube').fetchone()[0] == expected


def test_copilot_defaults_to_offline_without_provider_wait(monkeypatch):
    from backend.api import fire_copilot
    monkeypatch.delenv('COPILOT_OFFLINE', raising=False)
    monkeypatch.setattr(fire_copilot.httpx, 'Client', lambda **kw: pytest.fail('Offline default attempted HTTP'))
    assert fire_copilot.search_reports(None) == ([], '')
