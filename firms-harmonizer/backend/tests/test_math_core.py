"""Scientific acceptance and regression tests for the complete math core."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import h3
import numpy as np
import pytest
from scipy.stats import multivariate_normal

from backend.core import footprint_h3 as footprint
from backend.core.risk_predictor import build_causal_features, predict_risk
from backend.core.eqm_harmonizer import RadiometricHarmonizer
from backend.api.schemas import ChaosMonkeyResponse, ScientificAuditMetrics, VonMisesPhenologyYear
from backend.core.von_mises import best_fisher_kappa, doy_to_date_label, compute_circular_phenology
from backend.core.auditor_stats import (
    compute_wooster_biomass_and_smoke, compute_chow_structural_break_test,
    compute_scientific_audit_metrics,
)
from backend.core.chaos_monkey import run_chaos_monkey_simulation
from backend.core.kalman_rts import (
    build_cross_sensor_historical_prior, rts_kalman_smoother_with_cross_guard,
)
from backend.core.industrial_filter import (
    compute_industrial_probability, compute_shannon_temporal_entropy, filter_sama_anomalies,
)


def test_footprint_h3_and_bowtie_weights():
    viirs = footprint.compute_elliptical_psf_weights(-16.9, -56.2, .375, .375)
    assert len(viirs) == 1
    cell, weight = next(iter(viirs.items()))
    assert len(cell) == 15 and all(char in '0123456789abcdef' for char in cell)
    assert h3.is_valid_cell(cell) and h3.get_resolution(cell) == 7
    assert weight == 1.0
    modis = footprint.compute_elliptical_psf_weights(-16.9, -56.2, 4.5, 2.0)
    assert len(modis) == 7
    assert all(h3.is_valid_cell(cell) and h3.get_resolution(cell) == 7 for cell in modis)
    assert sum(modis.values()) == pytest.approx(1.0, rel=1e-5)
    assert footprint.compute_modis_bowtie_overlap_weight(2.0) == pytest.approx(.5)

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


def test_shannon_entropy_and_sama_filter():
    flare = np.full(12, 50)
    wildfire = np.array([0, 0, 0, 0, 0, 0, 0, 120, 0, 0, 0, 0])
    entropy, probability = compute_industrial_probability(np.stack([flare, wildfire]))
    assert entropy[0] > .95 and probability[0] > .90
    assert entropy[1] < .05 and probability[1] < .05
    is_spurious = filter_sama_anomalies(
        lat=np.array([-22., -22.]), lon=np.array([-45., -45.]),
        daynight=np.array(['N', 'D']), is_low_conf=np.array([True, True]),
        delta_t11=np.array([.5, .5]),
    )
    np.testing.assert_equal(is_spurious, [True, False])

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


def test_eqm_harmonizer_monotone_mapping():
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
    assert np.isfinite(mapped).all() and np.all(mapped >= 0) and np.all(np.diff(mapped) >= 0)
    pure = dict(lut, delta_e_sub=0.0)
    np.testing.assert_allclose(mapped - model.harmonize_viirs_to_modis(values, pure), lut['delta_e_sub'])


def test_eqm_modis_censoring_compensation_shares_viirs_scale():
    rng = np.random.default_rng(11)
    viirs = np.r_[rng.uniform(.5, 7.9, 300), rng.uniform(8, 100, 700), np.zeros(5)]
    model = RadiometricHarmonizer()
    lut = model.fit_biome_eqm_gpd(viirs * .9, viirs, biome_id=8)
    below = np.count_nonzero((viirs >= .5) & (viirs < 8))
    # SPECS §3.3: delta E_sub = pi_sub * conditional GPD mean over [0.5, 8) MW.
    assert lut['delta_e_sub'] == pytest.approx(below / viirs.size * lut['gpd']['conditional_mean'])
    modis = np.array([[0., 8., 40.], [np.nan, 2., 400.]])
    compensated = model.compensate_modis_censoring(modis, lut)
    expected = np.where(modis > 0, modis + lut['delta_e_sub'], modis)
    np.testing.assert_allclose(compensated, expected, equal_nan=True)
    assert compensated[0, 0] == 0 and np.isnan(compensated[1, 0])
    assert model.compensate_modis_censoring(np.array(10.0)).shape == ()
    # The same additive term lands on both channels, so the paired offset cancels.
    pure = dict(lut, delta_e_sub=0.0)
    np.testing.assert_allclose(model.harmonize_viirs_to_modis(viirs[viirs > 0], lut)
                               - model.harmonize_viirs_to_modis(viirs[viirs > 0], pure), lut['delta_e_sub'])
    for invalid in [np.array([-1.0]), np.array([np.inf])]:
        with pytest.raises(ValueError):
            model.compensate_modis_censoring(invalid, lut)
    with pytest.raises(ValueError):
        model.compensate_modis_censoring(np.ones(2), dict(lut, delta_e_sub=-1.0))
    with pytest.raises(ValueError):
        RadiometricHarmonizer().compensate_modis_censoring(np.ones(2))


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
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Import):
                assert all(alias.name.split('.')[0] in allowed for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert (node.module.split('.')[0] in allowed
                        or node.module in {"backend.api.schemas", "backend.core.kalman_rts", "backend.core.energy_forecast"})


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
    gains, prior, _ = build_cross_sensor_historical_prior(days, obs)
    for t in range(4):
        mean[t] = phi * (prior[0] if t == 0 else mean[t-1]) + gamma * spatial[t] + omega * prior[t]
        covariance[t, t] = phi**2 * (40 if t == 0 else covariance[t-1, t-1]) + Q
        if t:
            covariance[t, :t] = phi * covariance[t-1, :t]
            covariance[:t, t] = covariance[t, :t]
    H = np.zeros((12, 4))
    for t in range(4):
        H[3*t:3*t+3, t] = gains[t]
    R = np.diag(np.tile([9., 6., 5.], 4))
    gain = np.linalg.solve(H @ covariance @ H.T + R, H @ covariance).T
    batch_mean = mean + gain @ (obs.ravel() - H @ mean)
    batch_covariance = covariance - gain @ H @ covariance
    np.testing.assert_allclose(out['x_smooth'], batch_mean, atol=1e-7)
    np.testing.assert_allclose(out['P_smooth'], np.diag(batch_covariance), atol=1e-7)


def test_kalman_rts_dual_blackout_guard_and_forecast():
    n = 1460
    calendar = np.datetime64('2001-01-01') + np.arange(n).astype('timedelta64[D]')
    days = (calendar - calendar.astype('datetime64[Y]')).astype(int) + 1
    truth = 10. + 300. * np.exp(-.5 * ((days - 235.) / 25.)**2)
    observations = truth[:, None] * np.array([[.75, 1., 1.4]])
    spatial = .9 * np.r_[truth[0], truth[:-1]]
    peak = 365 + int(np.argmax(truth[365:730]))
    peak_value = truth[peak]
    blackout = slice(peak - 5, peak + 5)
    observations[blackout] = np.nan
    clouds = np.zeros(n)
    clouds[blackout] = .95
    assert np.isnan(observations[blackout]).all() and len(observations[blackout]) == 10

    out = rts_kalman_smoother_with_cross_guard(observations, spatial, days, clouds, forecast_days=14)
    for key, values in out.items():
        assert np.isfinite(values).all(), f"Non-finite values in {key}"
        assert np.all(values >= 0), f"Negative values in {key}"
    assert out['x_smooth'].shape == (n,) and np.all(out['P_smooth'] >= 1e-4)
    assert np.min(out['x_smooth'][blackout]) > .35 * peak_value
    assert out['P_smooth'][peak] > out['P_smooth'][peak - 8]
    assert len(out['forecast_x']) == 14 and np.all(out['forecast_P'] >= 1e-4)
    assert np.all(out['forecast_ci_upper'] >= out['forecast_ci_lower'])
    assert np.all(out['forecast_ci_lower'] <= out['forecast_x'])
    assert np.all(out['forecast_x'] <= out['forecast_ci_upper'])
    np.testing.assert_allclose(out['forecast_P'][0], .68**2 * out['P_smooth'][-1] + 12 * 1.2)
    np.testing.assert_allclose(out['forecast_P'][1:], .68**2 * out['forecast_P'][:-1] + 12 * 1.2)
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
    np.testing.assert_equal(out['forecast_doy'][:2], [2, 3])
    np.testing.assert_equal(obs, original)
    for array in out.values():
        assert np.isfinite(array).all()


@pytest.mark.parametrize('observations', [
    [np.nan, np.nan, np.nan], [70., np.nan, np.nan],
    [np.nan, 100., np.nan], [np.nan, np.nan, 180.], [70., 100., 180.],
])
def test_single_day_joseph_update_with_missing_sensors(observations):
    obs, days = np.array([observations]), np.array([200])
    spatial = np.array([50.])
    gains, prior, _ = build_cross_sensor_historical_prior(days, obs)
    out = rts_kalman_smoother_with_cross_guard(obs, spatial, days, np.array([.4]), forecast_days=0)
    x = (.68 + .15) * prior[0] + .17 * spatial[0]
    variance = .68**2 * 40. + 12. * (1. + .8 * .4)
    readings = [(value, h, noise) for value, h, noise in zip(observations, gains[0], [9., 6., 5.])
                if not np.isnan(value)]
    if not readings:
        readings = [(.55 * prior[0] + .45 * spatial[0], 1., 40.)]
    for value, h, noise in readings:
        gain = variance * h / (h**2 * variance + noise + 1e-8)
        x = max(0., x + gain * (value - h * x))
        variance = (1. - gain * h)**2 * variance + gain**2 * noise
    np.testing.assert_allclose(out['x_smooth'], [x])
    np.testing.assert_allclose(out['P_smooth'], [max(variance, 1e-4)])


@pytest.mark.parametrize('last_day,expected', [(364, [365, 1]), (365, [1, 2]), (366, [2, 3])])
def test_forecast_contract_recurrence_and_calendar(last_day, expected):
    days = np.arange(1, last_day + 1)
    obs = (30. + days[:, None] * .1) * np.array([[.7, 1., 1.8]])
    spatial, clouds = np.full(last_day, 40.), np.zeros(last_day)
    _, prior, lut = build_cross_sensor_historical_prior(days, obs)
    out = rts_kalman_smoother_with_cross_guard(obs, spatial, days, clouds, forecast_days=14)
    historical_keys = {'x_smooth', 'P_smooth', 'ci_lower', 'ci_upper', 'uncertainty_pct', 'mu_cross'}
    forecast_keys = {'forecast_x', 'forecast_P', 'forecast_ci_lower', 'forecast_ci_upper',
                     'forecast_uncertainty_pct', 'forecast_mu_cross', 'forecast_doy'}
    assert set(out) == historical_keys | forecast_keys
    assert all(out[key].shape == (last_day,) for key in historical_keys)
    assert all(out[key].shape == (14,) for key in forecast_keys)
    np.testing.assert_equal(out['mu_cross'], prior)
    np.testing.assert_equal(out['forecast_doy'][:2], expected)
    np.testing.assert_equal(out['forecast_mu_cross'], lut[out['forecast_doy'] - 1])
    # Future steps have no measurements: their filtered and smoothed estimates
    # coincide, and follow the specified state-dependent spatial forcing.
    previous = np.r_[out['x_smooth'][-1], out['forecast_x'][:-1]]
    forcing = .82 * previous + .18 * out['forecast_mu_cross']
    expected_state = .68 * previous + .17 * forcing + .15 * out['forecast_mu_cross']
    np.testing.assert_allclose(out['forecast_x'], expected_state, atol=1e-12)
    previous_variance = np.r_[out['P_smooth'][-1], out['forecast_P'][:-1]]
    np.testing.assert_allclose(out['forecast_P'], .68**2 * previous_variance + 12. * 1.2)
    for prefix, state_key, variance_key in [('', 'x_smooth', 'P_smooth'), ('forecast_', 'forecast_x', 'forecast_P')]:
        margin = 1.96 * np.sqrt(out[variance_key])
        np.testing.assert_allclose(out[prefix + 'ci_lower'], np.maximum(0., out[state_key] - margin))
        np.testing.assert_allclose(out[prefix + 'ci_upper'], out[state_key] + margin)
        np.testing.assert_allclose(out[prefix + 'uncertainty_pct'],
                                   np.clip(margin / (out[state_key] + 1.) * 100., 1., 99.9))
    history_only = rts_kalman_smoother_with_cross_guard(obs, spatial, days, clouds, forecast_days=0)
    for key in historical_keys:
        np.testing.assert_allclose(out[key], history_only[key], atol=1e-12)
    assert all(history_only[key].shape == (0,) for key in forecast_keys)


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


def test_best_fisher_and_english_leap_calendar_labels():
    assert best_fisher_kappa(0) == 0 and best_fisher_kappa(1) == 10000
    assert best_fisher_kappa(.5) == pytest.approx(1 + .5**3 + 5 * .5**5 / 6)
    assert best_fisher_kappa(.53) == pytest.approx(-.4 + 1.39 * .53 + .43 / .47)
    assert best_fisher_kappa(.85) == pytest.approx(1 / (.85**3 - 4 * .85**2 + 3 * .85))
    assert doy_to_date_label(1) == '1 Jan'
    assert doy_to_date_label(232) == '19 Aug'
    assert doy_to_date_label(366) == '31 Dec'
    for value in [-.1, 1.1, np.nan]:
        with pytest.raises(ValueError):
            best_fisher_kappa(value)
    with pytest.raises(ValueError):
        doy_to_date_label(0)


def test_circular_von_mises_phenology_shift():
    years = np.repeat(np.arange(2001, 2016), 365)
    days = np.tile(np.arange(1, 366), 15)
    peak = 220. + 1.5 * (years - 2001)
    energy = 50. * np.exp(4 * (np.cos(2*np.pi*(days - peak)/365.25) - 1))
    models, slope, pvalue = compute_circular_phenology(years, days, energy, 5.161)
    assert len(models) == 15 and all(type(model) is VonMisesPhenologyYear for model in models)
    assert slope > 8.0
    assert slope == pytest.approx(15.0, abs=.2) and pvalue < 1e-6
    for model in models:
        assert 1 <= model.peak_doy_mu <= 365.25 and 0 < model.season_width_days <= 365
        assert model.total_annual_fre_gj == pytest.approx(energy[years == model.year].sum() * 5.161 / 1000)
        model.model_dump_json()


def test_circular_trend_unwraps_year_boundary_and_handles_empty_energy():
    years = np.arange(2001, 2008)
    peaks = np.array([350, 355, 360, 365, 5, 10, 15])
    models, shift, pvalue = compute_circular_phenology(years, peaks, np.ones(7), 1.)
    assert 50 <= shift < 51 and pvalue < .01
    assert all(model.concentration_kappa == 10000 for model in models)
    models, shift, pvalue = compute_circular_phenology(np.array([2001, 2002]), np.array([1, 1]), np.zeros(2), 1.)
    assert shift == 0 and pvalue == 1
    assert all(model.total_annual_fre_gj == 0 and model.concentration_kappa == 0 for model in models)
    assert compute_circular_phenology(np.array([]), np.array([]), np.array([]), 1.) == ([], 0., 1.)


def test_wooster_and_pm25_unit_conversion():
    biomass, smoke = compute_wooster_biomass_and_smoke(np.array([100., 0.]), 10.)
    np.testing.assert_allclose(biomass, [.368, 0.])
    np.testing.assert_allclose(smoke, [3.496, 0.])
    with pytest.raises(ValueError):
        compute_wooster_biomass_and_smoke(np.array([-1.]), 1.)


def test_chow_matches_nested_regression_f_test_and_degenerate_lines():
    from scipy.stats import f

    rng = np.random.default_rng(23)
    years = np.arange(2001, 2027)
    t = years - 2001
    post = (years >= 2012).astype(float)
    values = 20 + .2 * t + 7 * post + rng.normal(0, 1, len(t))
    pooled = np.column_stack([np.ones(len(t)), t])
    unrestricted = np.column_stack([pooled, post, t * post])
    restricted_rss = np.linalg.norm(values - pooled @ np.linalg.lstsq(pooled, values, rcond=None)[0])**2
    unrestricted_rss = np.linalg.norm(values - unrestricted @ np.linalg.lstsq(unrestricted, values, rcond=None)[0])**2
    expected_f = (restricted_rss - unrestricted_rss) / 2 / (unrestricted_rss / (len(t) - 4))
    actual_f, actual_p = compute_chow_structural_break_test(years, values)
    assert actual_f == pytest.approx(expected_f)
    assert actual_p == pytest.approx(f.sf(expected_f, 2, len(t) - 4))
    assert compute_chow_structural_break_test(years, np.zeros(26)) == (0., 1.)
    assert compute_chow_structural_break_test(years, 1. + .5 * t) == (0., 1.)
    stat, pval = compute_chow_structural_break_test(years, 1. + 4 * post)
    assert np.isfinite(stat) and stat > 100 and pval < 1e-10
    with pytest.raises(ValueError):
        compute_chow_structural_break_test(years[:4], values[:4])


def _audit_example(burned_missing=False):
    years = np.repeat(np.arange(2001, 2027), 60)
    day = np.tile(np.arange(60), 26)
    physical = (20 + 15 * np.sin(np.pi * day / 60)**2) * (1 + .02 * (years - 2001))
    raw = physical * np.where(years < 2012, 1., 4.5)
    burned = physical * .035
    if burned_missing:
        burned[:] = np.nan
    return years, raw, physical, burned


def test_scientific_audit_chow_test_and_wooster():
    arrays = _audit_example()
    out = compute_scientific_audit_metrics(*arrays, 10., 7.5, .001, 12)
    assert type(out) is ScientificAuditMetrics
    assert out.chow_test_p_val_raw < 1e-4 and out.chow_test_p_val_harm > .10
    assert out.total_biomass_burned_kt > 0 and out.total_pm25_emitted_tonnes > 0
    assert out.wasserstein_w1_harm < out.wasserstein_w1_raw
    assert out.burned_area_r2_harm == pytest.approx(1.)
    assert out.burned_area_r2_raw < out.burned_area_r2_harm
    assert out.total_biomass_burned_kt == pytest.approx(.368 * arrays[2].sum() * 10 / 1e6)
    assert out.total_pm25_emitted_tonnes == pytest.approx(.368 * arrays[2].sum() * 10 * 9.5 / 1e6)
    assert 'descriptive' in out.executive_verdict_en
    out.model_dump_json()
    missing = compute_scientific_audit_metrics(*_audit_example(True), 10., 0., 1., 0)
    assert missing.burned_area_r2_raw is None and missing.burned_area_r2_harm is None
    assert 'unavailable' in missing.executive_verdict_en


def _chaos_example(n=365, peak=230):
    calendar = np.arange(np.datetime64('2022-01-01'), np.datetime64('2022-01-01') + np.timedelta64(n, 'D'))
    days = (calendar - calendar.astype('datetime64[Y]')).astype(int) + 1
    energy = 10 + 180 * np.exp(-.5 * ((days - peak) / 30)**2)
    observations = energy[:, None] * np.array([[.75, 1., 1.4]])
    return [str(date) for date in calendar], days, observations, energy, np.zeros(n)


def test_chaos_monkey_recovery():
    arrays = _chaos_example()
    snapshot = arrays[2].copy()
    out = run_chaos_monkey_simulation(*arrays, drop_fraction=.25, simulate_dual_blackout=True, random_seed=42)
    assert type(out) is ChaosMonkeyResponse and out.data_source == 'synthetic'
    assert out.model_dump() == run_chaos_monkey_simulation(*arrays).model_dump()
    np.testing.assert_equal(arrays[2], snapshot)
    assert out.dropped_days_count == len(out.dropped_dates) >= int(.25 * 365)
    assert out.kalman_rmse < out.naive_rmse
    assert out.seasonal_energy_recovered_pct > 90
    assert np.count_nonzero(np.array(out.corrupted_naive_fre) == 0) == 10
    assert all(lo <= x <= hi for lo, x, hi in zip(out.reconstructed_ci_lower, out.kalman_reconstructed_fre, out.reconstructed_ci_upper))
    out.model_dump_json()


@pytest.mark.parametrize('peak,n', [(1, 365), (365, 365), (2, 5)])
def test_chaos_blackout_has_bounded_ten_day_window(peak, n):
    out = run_chaos_monkey_simulation(*_chaos_example(n, peak), drop_fraction=0)
    assert out.dropped_days_count == min(n, 10)
    assert sum(value == 0 for value in out.corrupted_naive_fre) == min(n, 10)


def test_chaos_drop_count_uses_available_viirs_and_reports_only_changes():
    arrays = _chaos_example()
    arrays[2][:100, 2] = np.nan
    out = run_chaos_monkey_simulation(*arrays, simulate_dual_blackout=False)
    assert out.dropped_days_count == int(.25 * (365 - 100))
    intact = run_chaos_monkey_simulation(*arrays, drop_fraction=0, simulate_dual_blackout=False)
    assert intact.dropped_days_count == 0 and intact.naive_rmse == intact.kalman_rmse == 0
    assert intact.seasonal_energy_recovered_pct == pytest.approx(100)


def test_chaos_full_history_drives_fixed_prior_and_empty_input_is_defined():
    arrays = _chaos_example(60, 30)
    history_doy = np.arange(1, 367)
    history_obs = np.full((366, 3), 20.) * np.array([[.75, 1., 1.4]])
    out = run_chaos_monkey_simulation(*arrays, full_doy_history=history_doy, full_y_obs_history=history_obs)
    np.testing.assert_allclose(out.historical_cross_guard_fre, 20.)
    np.testing.assert_equal(history_obs, np.full((366, 3), 20.) * np.array([[.75, 1., 1.4]]))
    empty = run_chaos_monkey_simulation([], np.array([], dtype=int), np.empty((0,3)), np.empty(0), np.empty(0))
    assert empty.dates == [] and empty.dropped_days_count == 0 and empty.seasonal_energy_recovered_pct == 100
    with pytest.raises(ValueError):
        run_chaos_monkey_simulation(*arrays, full_doy_history=history_doy)
    with pytest.raises(ValueError):
        run_chaos_monkey_simulation(*arrays, drop_fraction=1.1)


def _risk_fixture(n=1800):
    rng = np.random.default_rng(114)
    t = np.arange(n)
    seasonal = np.maximum(0, np.cos(2 * np.pi * t / 365.25))
    vegetation = 2 + 75 * seasonal + rng.uniform(0, 5, n)
    excursion = np.where(t % 53 < 4, 5.0, 0.0)
    return dict(
        epoch_day=18628 + t, vegetation_frp=vegetation, neighbor_frp=vegetation * 0.9,
        industrial_z=excursion, persistent_share=np.full(n, 0.1),
        cloud=np.full(n, np.nan), gap=np.zeros(n),
    )


def test_risk_predictor_probability_bounds_and_types():
    result = predict_risk(_risk_fixture())
    assert result is not None
    assert [h["days"] for h in result["horizons"]] == [1, 7, 14]
    for key in ("wildfire_prob_pct", "accident_prob_pct", "combined_risk_pct"):
        values = [h[key] for h in result["horizons"]]
        assert all(isinstance(p, float) and 0 <= p <= 100 for p in values)
        assert values == sorted(values)
    assert result["model_metrics"]["samples"] > 0
    assert 0 <= result["model_metrics"]["brier_score"] <= 1
    assert 0 <= result["model_metrics"]["roc_auc"] <= 1
    for horizon in result["horizons"]:
        assert horizon["combined_risk_pct"] >= max(horizon["wildfire_prob_pct"], horizon["accident_prob_pct"])


def test_risk_predictor_spatial_contagion_and_seasonal_sensitivity():
    history = _risk_fixture()
    active = {k: v.copy() for k, v in history.items()}
    quiet = {k: v.copy() for k, v in history.items()}
    for name in ("vegetation_frp", "neighbor_frp"):
        active[name][-14:] = 100.0
        quiet[name][-14:] = 2.0
    assert predict_risk(active)["wildfire_prob_24h_pct"] > 70
    assert predict_risk(quiet)["wildfire_prob_24h_pct"] < 15


def test_risk_predictor_industrial_accident_separation():
    daily = _risk_fixture()
    daily["industrial_z"][-5:] = 8.0
    daily["persistent_share"][-5:] = 0.98
    daily["vegetation_frp"][-14:] = 0.1
    result = predict_risk(daily)
    assert result["industrial_accident_prob_pct"] > result["wildfire_prob_24h_pct"]


def test_risk_predictor_no_temporal_leakage_and_nan_resilience():
    daily = _risk_fixture(9000)
    daily["vegetation_frp"][55:99] = np.nan
    daily["neighbor_frp"][8:19] = np.nan
    daily["gap"][56:99] = 1
    prefix = {k: v[:4500] for k, v in daily.items()}
    features = build_causal_features(daily)
    assert np.isfinite(features).all()
    np.testing.assert_array_equal(features[:4500], build_causal_features(prefix))
    original = predict_risk(daily)
    modified = {k: v.copy() for k, v in daily.items()}
    modified["vegetation_frp"][-30:] *= 10
    revised = predict_risk(modified)
    assert original["vegetation_event_threshold_mw"] == revised["vegetation_event_threshold_mw"]
    np.testing.assert_array_equal(original["daily_probability_series"][:-30],
                                  revised["daily_probability_series"][:-30])
    assert predict_risk(_risk_fixture(50))["horizons"][0]["prior_targets"] == ["wildfire", "accident", "combined"]


def test_risk_predictor_uses_prior_for_unlearnable_targets():
    daily = _risk_fixture()
    daily["industrial_z"][:] = 0
    result = predict_risk(daily)
    assert result["industrial_accident_prob_pct"] > 0
    assert result["combined_risk_pct"] >= result["wildfire_prob_24h_pct"]
    assert "accident" in result["horizons"][0]["prior_targets"]
    assert result["horizons"][0]["accident_validation"]["roc_auc"] is None
