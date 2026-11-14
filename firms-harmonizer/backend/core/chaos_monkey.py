"""Reproducible sensor sabotage and retrospective Kalman recovery diagnostics."""

from __future__ import annotations

import numpy as np

from backend.api.schemas import ChaosMonkeyResponse
from backend.core.kalman_rts import (
    _smooth_with_prior, build_cross_sensor_historical_prior,
    rts_kalman_smoother_with_cross_guard,
)


def run_chaos_monkey_simulation(
    dates: list[str], doy: np.ndarray, y_obs: np.ndarray, u_spatial: np.ndarray,
    cloud_cover: np.ndarray, drop_fraction: float = 0.25,
    simulate_dual_blackout: bool = True, random_seed: int = 42,
    full_doy_history: np.ndarray | None = None,
    full_y_obs_history: np.ndarray | None = None,
) -> ChaosMonkeyResponse:
    """Compare sabotaged estimates with the intact-input smoother baseline.

    This is an experiment, so data_source is synthetic: input provenance cannot
    be inferred from numerical arrays. The intact smoother is a reference, not
    independently observed physical truth. If supplied, full history fits a
    fixed prior/calibration for both runs without concatenating unrelated days
    or adding intact target-day measurements to the sabotaged filter. For a
    holdout experiment, callers must exclude target observations from history.

    Without external history each call learns its own retrospective prior.
    Naive FRE is the uncalibrated available-sensor mean, zero on total outages.
    Dropped days count only dates where an existing observation was removed.
    Recovery is 100*sum(reconstructed FRE)/sum(reference FRE); values above 100
    indicate over-recovery. RMSE is measured on those actually affected dates.
    """
    obs = np.asarray(y_obs, dtype=float)
    days = np.asarray(doy)
    build_cross_sensor_historical_prior(days, obs)
    n = len(days)
    if len(dates) != n or any(not isinstance(value, str) for value in dates):
        raise ValueError("Supply one ISO date string per observation day.")
    calendar = np.asarray(dates, dtype='datetime64[D]')
    if np.isnat(calendar).any() or [str(date) for date in calendar] != list(dates):
        raise ValueError("Dates must be canonical ISO YYYY-MM-DD strings.")
    if n and (np.any(np.diff(calendar).astype(int) != 1)
              or not np.array_equal((calendar - calendar.astype('datetime64[Y]')).astype(int) + 1, days)):
        raise ValueError("Dates must be consecutive and agree with the supplied Julian days.")
    if not np.isfinite(drop_fraction) or not 0 <= drop_fraction <= 1:
        raise ValueError("drop_fraction must be in [0, 1].")
    if not isinstance(random_seed, (int, np.integer)) or random_seed < 0:
        raise ValueError("random_seed must be a non-negative integer.")
    if (full_doy_history is None) != (full_y_obs_history is None):
        raise ValueError("Full historical days and observations must be supplied together.")
    fixed_prior = None
    if full_doy_history is not None:
        gains, _, lut = build_cross_sensor_historical_prior(full_doy_history, full_y_obs_history)
        if len(gains) == 0:
            raise ValueError("Supplied full history must contain at least one day.")
        fixed_prior = (np.broadcast_to(gains[0], obs.shape).copy(), lut[days.astype(int) - 1], lut)

    def estimate(observations):
        if fixed_prior is None:
            return rts_kalman_smoother_with_cross_guard(
                observations, u_spatial, days, cloud_cover, forecast_days=0,
            )
        return _smooth_with_prior(observations, u_spatial, days, cloud_cover, fixed_prior, forecast_days=0)

    intact = estimate(obs)
    truth = intact['x_smooth']
    sabotaged = obs.copy()
    rng = np.random.default_rng(random_seed)
    candidates = np.flatnonzero(np.isfinite(obs[:, 2]))
    number_to_drop = int(np.floor(drop_fraction * len(candidates)))
    chosen = rng.choice(candidates, size=number_to_drop, replace=False)
    sabotaged[chosen, 2] = np.nan
    if simulate_dual_blackout and n:
        length = min(10, n)
        peak = int(np.argmax(truth))
        start = max(0, min(peak - 5, n - length))
        sabotaged[start:start + length, :] = np.nan
    affected = np.any(np.isfinite(obs) & np.isnan(sabotaged), axis=1)
    available = np.isfinite(sabotaged)
    naive = np.sum(np.where(available, sabotaged, 0.0), axis=1) / np.maximum(available.sum(axis=1), 1)
    restored = estimate(sabotaged)
    reconstructed = restored['x_smooth']
    if affected.any():
        naive_rmse = float(np.sqrt(np.mean((naive[affected] - truth[affected])**2)))
        kalman_rmse = float(np.sqrt(np.mean((reconstructed[affected] - truth[affected])**2)))
    else:
        naive_rmse = kalman_rmse = 0.0
    reference_energy, restored_energy = float(truth.sum()), float(reconstructed.sum())
    recovery = (100.0 * (restored_energy / reference_energy) if reference_energy > 0
                else 100.0 if restored_energy == 0 else 0.0)
    return ChaosMonkeyResponse(
        data_source='synthetic', dropped_days_count=int(affected.sum()),
        dropped_dates=[dates[i] for i in np.flatnonzero(affected)], dates=list(dates),
        true_harmonized_fre=truth.tolist(), corrupted_naive_fre=naive.tolist(),
        historical_cross_guard_fre=restored['mu_cross'].tolist(),
        kalman_reconstructed_fre=reconstructed.tolist(),
        reconstructed_ci_lower=restored['ci_lower'].tolist(),
        reconstructed_ci_upper=restored['ci_upper'].tolist(),
        naive_rmse=naive_rmse, kalman_rmse=kalman_rmse,
        seasonal_energy_recovered_pct=float(recovery),
    )
