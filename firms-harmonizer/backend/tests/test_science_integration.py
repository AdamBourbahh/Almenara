"""HTTP integration with the real scientific implementation, without core substitutes."""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import core_contract
from backend.api.cache import ANALYZE_CACHE, GEOMETRY_CACHE
from backend.api.main import app
from backend.api.schemas import AnalyzeResponse, ChaosMonkeyResponse
from backend.core.kalman_rts import rts_kalman_smoother_with_cross_guard
from backend.db import queries

CHILECITO = {'type': 'Polygon', 'coordinates': [[[-69.5, -31], [-65.5, -31], [-65.5, -27.5], [-69.5, -27.5], [-69.5, -31]]]}


@pytest.fixture
def real_client():
    ANALYZE_CACHE.clear()
    GEOMETRY_CACHE.clear()
    with TestClient(app) as client:
        yield client
    ANALYZE_CACHE.clear()
    GEOMETRY_CACHE.clear()


@pytest.mark.parametrize('start,end', [(2001, 2026), (2022, 2022)])
def test_analysis_matches_real_smoother_and_keeps_cache_contract(real_client, start, end):
    body = {'aoi': CHILECITO, 'start_year': start, 'end_year': end}
    response = real_client.post('/api/analyze', json=body)
    assert response.status_code == 200, response.text
    result = AnalyzeResponse.model_validate(response.json())
    assert result.data_source == 'synthetic' and len(result.phenology_by_year) == end - start + 1
    r4, r7, _ = queries.get_hierarchical_h3_filter(CHILECITO['coordinates'])
    area = queries.polygon_area_km2(CHILECITO['coordinates'])
    daily = queries.fetch_aoi_aggregated_data(r4, r7, start, end, True, area).daily
    obs = np.column_stack([daily[name] for name in queries.OBS_COLUMNS])
    density = daily['observed_energy_mj'] / area
    obs = np.where(np.isfinite(obs), density[:, None], np.nan)
    expected = rts_kalman_smoother_with_cross_guard(
        obs, daily['neighbor_fre_lag1'], daily['doy'], daily['cloud_cover_pct'], forecast_days=0,
    )
    gap = (daily['gap_status_mask'] > 0) & ~np.isfinite(obs).any(axis=1)
    integrated = np.where(gap, expected['x_smooth'], density)
    np.testing.assert_allclose([day.harmonized_fre_mj_km2 for day in result.calendar_series], integrated)
    assert sum(d.biomass_burned_tonnes for d in result.calendar_series) == pytest.approx(.368 * integrated.sum() * area / 1000)
    np.testing.assert_allclose([day.ci_95_upper for day in result.calendar_series], integrated + 1.96 * np.sqrt(expected['P_smooth']))
    np.testing.assert_allclose([day.uncertainty_pct for day in result.calendar_series], np.clip(100 * 1.96 * np.sqrt(expected['P_smooth']) / (integrated + 1), 1, 99.9))
    assert (result.audit_metrics is None) == (start == end)
    if result.audit_metrics:
        assert result.audit_metrics.total_biomass_burned_kt > 0
    cached = real_client.post('/api/analyze', json=body)
    assert cached.status_code == 200 and cached.headers['x-cache'] == 'HIT'
    assert cached.json()['calendar_series'] == response.json()['calendar_series']


def test_chaos_runs_actual_recovery_and_preserves_cube_provenance(real_client):
    request = {'aoi': CHILECITO, 'target_year': 2022, 'drop_fraction': .25,
               'simulate_dual_blackout': True, 'random_seed': 42}
    response = real_client.post('/api/chaos-monkey', json=request)
    assert response.status_code == 200, response.text
    result = ChaosMonkeyResponse.model_validate(response.json())
    assert result.data_source == 'synthetic' and len(result.dates) == 365
    assert result.dropped_days_count > 0 and result.kalman_rmse < result.naive_rmse
    assert result.seasonal_energy_recovered_pct > 80
    assert result.model_dump() == real_client.post('/api/chaos-monkey', json=request).json()


def test_health_and_missing_dependency_use_actual_core(real_client, monkeypatch):
    from backend.core import kalman_rts

    health = real_client.get('/api/health').json()
    assert all(health['core'].values())
    assert all(issue is None for issue in health['core_signatures'].values())
    monkeypatch.delattr(kalman_rts, 'rts_kalman_smoother_with_cross_guard')
    assert not core_contract.core_status()['kalman_rts_smooth']
    response = real_client.post('/api/analyze', json={'aoi': CHILECITO})
    assert response.status_code == 503
