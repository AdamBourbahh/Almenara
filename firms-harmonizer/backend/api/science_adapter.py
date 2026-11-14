"""Explicit translations from the HTTP analysis interface to the scientific core."""

from dataclasses import dataclass
from types import SimpleNamespace
import importlib

import numpy as np
from scipy.stats import kendalltau, theilslopes, wasserstein_distance

DEPENDENCIES = {
    'compute_cross_prior': ('backend.core.kalman_rts', 'build_cross_sensor_historical_prior'),
    'kalman_rts_smooth': ('backend.core.kalman_rts', 'rts_kalman_smoother_with_cross_guard'),
    'fit_von_mises_year': ('backend.core.von_mises', 'compute_circular_phenology'),
    'phenology_trend': ('backend.core.von_mises', 'compute_circular_phenology'),
    'chow_test': ('backend.core.auditor_stats', 'compute_chow_structural_break_test'),
    'wasserstein_w1_normalized': ('backend.core.auditor_stats', 'compute_scientific_audit_metrics'),
    'descriptive_r2': ('backend.core.auditor_stats', '_annual_r2'),
    'run_chaos_monkey_simulation': ('backend.core.chaos_monkey', 'run_chaos_monkey_simulation'),
}


def dependency(name):
    module, attr = DEPENDENCIES[name]
    return getattr(importlib.import_module(module), attr)


@dataclass(frozen=True)
class KalmanInput:
    """Per-request calendar and measured cloud fractions, never global state."""
    doy: np.ndarray
    cloud_cover: np.ndarray


def compute_cross_prior(doy, obs):
    return dependency('compute_cross_prior')(doy, obs)[2]


def kalman_rts_smooth(obs, u_spatial, context):
    if not isinstance(context, KalmanInput):
        raise ValueError('KalmanInput with actual DOY and cloud fractions is required.')
    result = dependency('kalman_rts_smooth')(
        obs, u_spatial, context.doy, context.cloud_cover, forecast_days=0,
    )
    return SimpleNamespace(x_smooth=result['x_smooth'], p_smooth=result['P_smooth'])


def fit_von_mises_year(doy, weights):
    models, _, _ = dependency('fit_von_mises_year')(
        np.full(len(doy), 2000), doy, weights, 1.0,
    )
    if not models:
        raise ValueError('A phenology fit requires at least one day.')
    model = models[0]
    return model.peak_doy_mu, model.concentration_kappa, model.season_width_days


def phenology_trend(years, peaks):
    years, peaks = np.asarray(years), np.asarray(peaks)
    if len(years) < 2 or np.ptp(peaks) <= 1e-10:
        return 0.0, 1.0
    unwrapped = np.unwrap(peaks * (2 * np.pi / 365.25)) * 365.25 / (2 * np.pi)
    if np.ptp(unwrapped) <= 1e-10:
        return 0.0, 1.0
    return float(theilslopes(unwrapped, years).slope * 10), float(kendalltau(years, unwrapped).pvalue)


def chow_test(values, years, doy):
    years, inverse, counts = np.unique(years, return_inverse=True, return_counts=True)
    annual = np.bincount(inverse, weights=values) / counts
    return dependency('chow_test')(years, annual)


def wasserstein_w1_normalized(values, years):
    values, years = np.asarray(values, dtype=float), np.asarray(years)
    pre = years < 2012
    if not pre.any() or pre.all():
        raise ValueError('Wasserstein comparison needs observations on both sides of 2012.')
    scale = values.mean()
    return float(wasserstein_distance(values[pre] / scale, values[~pre] / scale)) if scale > 0 else 0.0


def descriptive_r2(x, y):
    return dependency('descriptive_r2')(np.asarray(x), np.asarray(y))


def run_chaos_monkey_simulation(daily, target_year, drop_fraction, simulate_dual_blackout, random_seed):
    selected = daily['year'] == target_year
    if not selected.any():
        raise ValueError('No observations in the requested target year.')
    obs = np.column_stack([daily[name] for name in ('obs_terra_fre', 'obs_aqua_fre', 'obs_viirs_fre')])
    dates = np.datetime64('1970-01-01') + daily['epoch_day'][selected].astype('timedelta64[D]')
    # Holdout: the prior and sensor calibration are learned only from the other years. Including the
    # target year would let the climatology see the very observations the experiment removes.
    history = ~selected
    if not np.isfinite(obs[history]).any():
        raise ValueError('The stress test needs observations outside the target year to learn its prior.')
    result = dependency('run_chaos_monkey_simulation')(
        [str(date) for date in dates], daily['doy'][selected], obs[selected],
        daily['neighbor_fre_lag1'][selected], daily['cloud_cover_pct'][selected],
        drop_fraction=drop_fraction, simulate_dual_blackout=simulate_dual_blackout,
        random_seed=random_seed, full_doy_history=daily['doy'][history], full_y_obs_history=obs[history],
    )
    # The HTTP boundary supplies the cube's actual provenance, not the core's
    # experiment label. No synthetic observations are introduced by this adapter.
    return result.model_dump(exclude={'data_source'})
