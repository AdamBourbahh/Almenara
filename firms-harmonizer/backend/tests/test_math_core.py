"""Scientific regression tests for footprint, persistence and radiometry."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import h3
import numpy as np
import pytest
from scipy.stats import multivariate_normal

from backend.core import footprint_h3 as footprint
from backend.core.eqm_harmonizer import RadiometricHarmonizer
from backend.core.kalman_rts import (
    build_cross_sensor_historical_prior, rts_kalman_smoother_with_cross_guard,
)
from backend.core.industrial_filter import (
    compute_industrial_probability, compute_shannon_temporal_entropy, filter_sama_anomalies,
)


def test_bowtie_threshold_and_scalar_array():
    track = np.array([0.0, 1.0, 1.35, 1.35001, 2.0, 4.8])
    np.testing.assert_allclose(footprint.compute_modis_bowtie_overlap_weight(track),
                               [1.0, 1.0, 1.0, 1 / 1.35001, .5, 1 / 4.8])
    assert footprint.compute_modis_bowtie_overlap_weight(2.0) == .5
    assert isinstance(footprint.compute_modis_bowtie_overlap_weight(1.0), float)
    for invalid in [-1.0, np.nan, np.inf]:
        with pytest.raises(ValueError):
            footprint.compute_modis_bowtie_overlap_weight(invalid)


@pytest.mark.parametrize("scan,track", [(.375, .375), (1.0, 1.0), (3.5, 1.0)])
def test_small_footprints_stay_in_one_cell(scan, track):
    weights = footprint.compute_elliptical_psf_weights(-16.9, -56.2, scan, track)
    assert list(weights.values()) == [1.0]
    assert all(len(cell) == 15 and cell == cell.lower() for cell in weights)
    assert footprint.H3_R7_AREA_KM2 == 5.161


@pytest.mark.parametrize("lat,lon", [(-16.9, -56.2), (0.0, 179.999), (75.0, 25.0)])
def test_psf_matches_rotated_gaussian_and_conserves_energy(lat, lon):
    weights = footprint.compute_elliptical_psf_weights(lat, lon, 4.8, 2.0)
    assert len(weights) == 7 and sum(weights.values()) == 1.0
    assert all(0 <= weight <= 1 for weight in weights.values())
    centers = np.array([h3.cell_to_latlng(cell) for cell in weights])
    x = np.deg2rad((centers[:, 1] - lon + 180) % 360 - 180) * 6371.0088 * np.cos(np.deg2rad(lat))
    y = np.deg2rad(centers[:, 0] - lat) * 6371.0088
    angle = np.deg2rad(98.2)
    rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    covariance = rotation @ np.diag((np.array([4.8, 2.0]) / 2.355) ** 2) @ rotation.T
    expected = multivariate_normal(cov=covariance).pdf(np.column_stack([x, y]))
    np.testing.assert_allclose(list(weights.values()), expected / expected.sum(), atol=1e-14)
    turned = footprint.compute_elliptical_psf_weights(lat, lon, 4.8, 2.0, 8.2)
    assert any(abs(weights[cell] - turned[cell]) > .001 for cell in weights)


def test_h3_v3_adapter_matches_v4(monkeypatch):
    expected = footprint.compute_elliptical_psf_weights(39.1, -120.35, 4.8, 2.0)
    legacy = SimpleNamespace(geo_to_h3=h3.latlng_to_cell, h3_to_geo=h3.cell_to_latlng, k_ring=h3.grid_disk)
    monkeypatch.setattr(footprint, "h3", legacy)
    assert footprint.compute_elliptical_psf_weights(39.1, -120.35, 4.8, 2.0) == expected
    assert len(footprint.compute_elliptical_psf_weights(39.1, -120.35, .375, .375)) == 1


def test_invalid_footprint_rejected():
    for args in [(91, 0, 1, 1), (0, 181, 1, 1), (0, 0, 0, 1), (0, 0, np.nan, 2)]:
        with pytest.raises(ValueError):
            footprint.compute_elliptical_psf_weights(*args)


def test_shannon_empty_impulse_and_uniform():
    counts = np.array([np.zeros(12), np.eye(1, 12)[0] * 100, np.ones(12)])
    entropy = compute_shannon_temporal_entropy(counts)
    np.testing.assert_allclose(entropy, [0.0, 0.0, 1.0], atol=1e-10)
    assert compute_shannon_temporal_entropy(counts[0]).shape == ()
    assert compute_shannon_temporal_entropy(np.empty((0, 12))).shape == (0,)
    for bad in [np.zeros(11), np.zeros((2, 2, 12)), -np.ones(12), np.full(12, np.nan)]:
        with pytest.raises(ValueError):
            compute_shannon_temporal_entropy(bad)


def test_industry_sigmoid_and_steady_contrast_boost():
    counts = np.array([np.zeros(12), np.arange(12), np.ones(12)])
    entropy, base = compute_industrial_probability(counts)
    np.testing.assert_allclose(base, 1 / (1 + np.exp(-22 * (entropy - .72))))
    _, steady = compute_industrial_probability(counts, np.full((3, 12), 4.0))
    _, variable = compute_industrial_probability(counts, np.tile(np.arange(12), (3, 1)))
    assert np.all(steady >= variable) and np.all(variable >= base)
    assert steady[0] == base[0] and np.all(steady <= 1)
    _, missing = compute_industrial_probability(counts, np.full((3, 12), np.nan))
    np.testing.assert_equal(missing, base)


def test_sama_conditions_boundaries_and_terra_date_filter():
    lat = np.array([-35, -15, -25, -25, -25, -14, 0])
    lon = np.array([-65, -30, -50, -50, -50, -50, 0])
    night = np.array(['N', 'N', 'D', 'N', 'N', 'N', 'D'])
    low = np.array([True, True, True, False, True, True, False])
    contrast = np.array([1.49, 0, 0, 0, 1.5, 0, 10])
    args = lat, lon, night, low, contrast
    np.testing.assert_equal(filter_sama_anomalies(*args), [True, True, False, False, False, False, False])
    years = np.array([2001, 2001, 2000, 2000, 1999, 2001, 2000])
    months = np.array([1, 1, 10, 11, 10, 1, 1])
    np.testing.assert_equal(filter_sama_anomalies(*args, years, months), [True, True, True, False, False, False, True])
    with pytest.raises(ValueError):
        filter_sama_anomalies(*args, acq_year=years)


def test_eqm_exact_linear_mapping_and_nan_zero_preservation():
    harmonizer = RadiometricHarmonizer()
    training = np.linspace(10, 100, 501)
    lut = harmonizer.fit_biome_eqm_gpd(training * 2, training, biome_id=9)
    assert len(lut['viirs_quantiles']) == len(lut['modis_quantiles']) == 101
    assert lut['delta_e_sub'] == 0 and lut['gpd'] is None
    json.dumps(lut, allow_nan=False)
    values = np.array([[0, 25, 75], [np.nan, 10, 100]])
    np.testing.assert_allclose(harmonizer.harmonize_viirs_to_modis(values), values * 2, equal_nan=True)
    assert harmonizer.harmonize_viirs_to_modis(np.array(25.0)).shape == ()


def test_gpd_compensation_is_bounded_and_monotone():
    rng = np.random.default_rng(7)
    training = np.r_[rng.uniform(.5, 7.9, 300), rng.uniform(8, 100, 700)]
    model = RadiometricHarmonizer()
    lut = model.fit_biome_eqm_gpd(training * .8, training)
    assert lut['gpd']['fit_method'] == 'maximum_likelihood'
    assert .5 <= lut['gpd']['conditional_mean'] <= 8
    assert .15 <= lut['delta_e_sub'] <= 2.4
    json.dumps(lut, allow_nan=False)
    values = np.linspace(.5, 100, 1001)
    mapped = model.harmonize_viirs_to_modis(values)
    assert np.isfinite(mapped).all() and np.all(np.diff(mapped) >= 0)
    pure = dict(lut, delta_e_sub=0.0)
    np.testing.assert_allclose(mapped - model.harmonize_viirs_to_modis(values, pure), lut['delta_e_sub'])


@pytest.mark.parametrize("training", [np.array([.5]), np.array([2., 2., 2.]), np.array([20., 20.])])
def test_sparse_or_constant_training_is_finite(training):
    model = RadiometricHarmonizer()
    lut = model.fit_biome_eqm_gpd(training, training)
    json.dumps(lut, allow_nan=False)
    result = model.harmonize_viirs_to_modis(np.array([0., 1., 100., np.nan]))
    assert result[0] == 0 and np.isfinite(result[:3]).all() and np.isnan(result[-1])


def test_eqm_rejects_missing_models_invalid_training_and_nonmonotone_lut():
    model = RadiometricHarmonizer()
    with pytest.raises(ValueError):
        model.harmonize_viirs_to_modis(np.ones(3))
    for invalid in [np.array([]), np.array([np.nan]), np.array([-1]), np.array([np.inf])]:
        with pytest.raises(ValueError):
            model.fit_biome_eqm_gpd(invalid, np.ones(3))
    lut = model.fit_biome_eqm_gpd(np.array([1., 2.]), np.array([1., 2.]))
    with pytest.raises(ValueError):
        model.harmonize_viirs_to_modis(np.ones(3), dict(lut, viirs_quantiles=[2, 1], modis_quantiles=[1, 2]))


def test_core_has_only_allowed_imports():
    allowed = {'__future__', 'numpy', 'scipy', 'h3'}
    core = Path(__file__).resolve().parents[1] / 'core'
    for path in core.glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                assert all(alias.name.split('.')[0] in allowed for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.module.split('.')[0] in allowed


def test_cross_prior_calibrates_sensors_and_is_periodic():
    from scipy.ndimage import gaussian_filter1d

    days = np.arange(1, 367)
    truth = 50 + 20 * np.cos(2 * np.pi * (days - 1) / 366)
    obs = truth[:, None] * np.array([.7, 1., 1.8])
    gains, prior, lut = build_cross_sensor_historical_prior(days, obs)
    np.testing.assert_allclose(gains, np.tile([.7, 1., 1.8], (366, 1)))
    np.testing.assert_allclose(lut, gaussian_filter1d(truth, 5, mode='wrap', truncate=3))
    np.testing.assert_equal(prior, lut)
    _, sparse, sparse_lut = build_cross_sensor_historical_prior(np.array([366, 2]), np.full((2, 3), 12.))
    np.testing.assert_allclose(sparse_lut, 12.)
    np.testing.assert_allclose(sparse, 12.)


def test_cross_prior_clipping_single_sensor_and_empty_history():
    gains, prior, lut = build_cross_sensor_historical_prior(np.array([1, 1]), np.array([[.1, 2, 20], [.1, 2, 20]]))
    np.testing.assert_equal(gains[0], [.5, 1., 2.5])
    _, prior, lut = build_cross_sensor_historical_prior(np.array([1, 2]), np.array([[10, np.nan, np.nan], [np.nan, np.nan, np.nan]]))
    np.testing.assert_allclose(lut, 10)
    gains, prior, lut = build_cross_sensor_historical_prior(np.array([], dtype=int), np.empty((0, 3)))
    assert gains.shape == (0, 3) and prior.shape == (0,)
    np.testing.assert_equal(lut, np.zeros(366))


def test_rts_matches_batch_gaussian_posterior():
    obs = np.array([[30., 33., 29.], [31., 34., 32.], [32., 35., 31.], [33., 36., 34.]])
    days = np.arange(1, 5)
    spatial = np.full(4, 32.)
    out = rts_kalman_smoother_with_cross_guard(obs, spatial, days, np.zeros(4), forecast_days=0)
    phi, gamma, omega, Q = .68, .17, .15, 12.
    mean, covariance = np.zeros(4), np.zeros((4, 4))
    prior = out['mu_cross_series']
    for t in range(4):
        mean[t] = phi * (prior[0] if t == 0 else mean[t-1]) + gamma * spatial[t] + omega * prior[t]
        covariance[t, t] = phi**2 * (40 if t == 0 else covariance[t-1, t-1]) + Q
        if t:
            covariance[t, :t] = phi * covariance[t-1, :t]
            covariance[:t, t] = covariance[t, :t]
    H = np.zeros((12, 4))
    for t in range(4):
        H[3*t:3*t+3, t] = out['H_gain'][t]
    R = np.diag(np.tile([9., 6., 5.], 4))
    gain = np.linalg.solve(H @ covariance @ H.T + R, H @ covariance).T
    batch_mean = mean + gain @ (obs.ravel() - H @ mean)
    batch_covariance = covariance - gain @ H @ covariance
    np.testing.assert_allclose(out['x_smooth'], batch_mean, atol=1e-7)
    np.testing.assert_allclose(out['P_smooth'], np.diag(batch_covariance), atol=1e-7)


def test_blackout_guard_joseph_and_forecast_without_pseudo_updates():
    n = 100
    obs = np.full((n, 3), 100.)
    obs[30:80] = np.nan
    spatial, days = np.full(n, 100.), np.arange(1, n+1)
    out = rts_kalman_smoother_with_cross_guard(obs, spatial, days, np.zeros(n), forecast_days=14)
    assert np.min(out['x_smooth'][30:80]) > 99.9
    assert out['P_smooth'][55] > out['P_smooth'][15]
    assert out['guard_applied'].sum() == 50
    t = 30
    Pp = out['P_pred'][t]
    K = Pp / (Pp + 40 + 1e-8)
    np.testing.assert_allclose(out['P_filter'][t], (1-K)**2 * Pp + K**2 * 40)
    np.testing.assert_allclose(out['forecast_P'][0], .68**2 * out['P_filter'][-1] + 12 * 1.8)
    np.testing.assert_allclose(out['forecast_P'][1:], .68**2 * out['forecast_P'][:-1] + 12 * 1.8)
    for values in out.values():
        assert np.isfinite(values).all() and np.all(values >= 0)
    assert np.all(out['P_smooth'] >= 1e-4)
    assert np.all(out['ci_lower'] <= out['x_smooth']) and np.all(out['ci_upper'] >= out['x_smooth'])
    np.testing.assert_allclose(out['ci_upper'] - out['x_smooth'], 1.96 * np.sqrt(out['P_smooth']))


@pytest.mark.parametrize('n,horizon', [(0, 0), (1, 0), (1, 14), (366, 14)])
def test_kalman_missing_and_zero_data_remain_finite(n, horizon):
    days = np.arange(n) % 366 + 1
    for observations in [np.zeros((n, 3)), np.full((n, 3), np.nan)]:
        out = rts_kalman_smoother_with_cross_guard(observations, np.full(n, np.nan), days,
                                                 np.full(n, np.nan), forecast_days=horizon,
                                                 Q_var=0, R_var=(0, 0, 0), R_guard=0)
        assert out['x_smooth'].shape == (n,) and out['forecast_x'].shape == (horizon,)
        for array in out.values():
            assert np.isfinite(array).all() and np.all(array >= 0)
        assert np.all(out['P_smooth'] >= 1e-4) and np.all(out['forecast_P'] >= 1e-4)


def test_kalman_partial_missing_data_and_year_rollover():
    obs = np.full((5, 3), 1e100)
    obs[1:3, 1] = np.nan
    obs[3] = np.nan
    original = obs.copy()
    out = rts_kalman_smoother_with_cross_guard(obs, np.full(5, 1e100), np.array([362,363,364,365,366]), np.ones(5))
    np.testing.assert_equal(out['forecast_doy'][:2], [1, 2])
    np.testing.assert_equal(obs, original)
    for array in out.values():
        assert np.isfinite(array).all()
    assert out['guard_applied'].sum() == 1


def test_kalman_invalid_inputs_raise_instead_of_nonfinite_outputs():
    obs, days, spatial, clouds = np.ones((2, 3)), np.array([1, 2]), np.ones(2), np.zeros(2)
    for kwargs in [dict(phi=1.1), dict(Q_var=-1), dict(R_var=(1, 2)), dict(R_guard=np.inf),
                   dict(forecast_days=-1), dict(forecast_days=1.5)]:
        with pytest.raises(ValueError):
            rts_kalman_smoother_with_cross_guard(obs, spatial, days, clouds, **kwargs)
    for bad in [np.full((2,3), np.inf), -obs]:
        with pytest.raises(ValueError):
            build_cross_sensor_historical_prior(days, bad)
    for bad_days in [np.array([0,1]), np.array([1,367]), np.array([1,1.5])]:
        with pytest.raises(ValueError):
            build_cross_sensor_historical_prior(bad_days, obs)
    with pytest.raises(ValueError):
        rts_kalman_smoother_with_cross_guard(obs, spatial, days, np.full(2, 95))
