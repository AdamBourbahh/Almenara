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
