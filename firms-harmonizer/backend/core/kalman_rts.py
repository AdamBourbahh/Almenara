"""Scalar Joseph-stabilized RTS estimation with a cross-sensor blackout guard."""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter1d


def build_cross_sensor_historical_prior(
    doy: np.ndarray, y_obs: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build an Aqua-referenced, circular 366-day climatology.

    Observation gains follow y_s = h_s * x, so intercalibration divides by h_s.
    Median simultaneous positive-observation ratios estimate each sensor gain.
    Without overlap with Aqua a gain defaults to one (no invented calibration).
    Empty days are interpolated periodically before Gaussian smoothing. An
    entirely unobserved history has a zero climatology, not fabricated energy.
    NaNs denote missing observations; infinities, negatives and magnitudes above
    1e100 are rejected to keep floating point arithmetic safely representable.
    """
    days = np.asarray(doy)
    obs = np.asarray(y_obs, dtype=np.float64)
    if days.ndim != 1 or obs.shape != (len(days), 3):
        raise ValueError("Expected doy (T,) and y_obs (T, 3).")
    if not np.isfinite(days).all() or np.any((days < 1) | (days > 366) | (days != np.floor(days))):
        raise ValueError("Julian days must be integers from 1 to 366.")
    if np.isinf(obs).any() or np.any(obs < 0) or np.any(obs > 1e100):
        raise ValueError("Observations must be non-negative, at most 1e100, with NaN for missing data.")
    days = days.astype(np.int64)
    gains = np.ones(3, dtype=np.float64)
    for sensor in (0, 2):
        valid = np.isfinite(obs[:, sensor]) & np.isfinite(obs[:, 1]) & (obs[:, 1] > 1e-8) & (obs[:, sensor] > 0)
        if np.any(valid):
            gains[sensor] = np.clip(np.median(obs[valid, sensor] / obs[valid, 1]), 0.5, 2.5)
    H_gain = np.broadcast_to(gains, obs.shape).copy()
    present = np.isfinite(obs)
    counts = present.sum(axis=1)
    calibrated = np.where(present, obs / gains, 0.0)
    daily = calibrated.sum(axis=1) / np.maximum(counts, 1)
    observed = counts > 0
    totals = np.bincount(days[observed] - 1, weights=daily[observed], minlength=366)
    calendar_counts = np.bincount(days[observed] - 1, minlength=366)
    valid_days = np.flatnonzero(calendar_counts)
    lut = np.zeros(366, dtype=np.float64)
    if valid_days.size:
        means = totals[valid_days] / calendar_counts[valid_days]
        lut = np.interp(np.arange(366), valid_days, means, period=366)
        # A 3-sigma kernel fits entirely in the requested fifteen-day padding.
        padded = np.pad(lut, pad_width=15, mode="wrap")
        lut = gaussian_filter1d(padded, sigma=5.0, truncate=3.0)[15:-15]
    lut = np.maximum(lut, 0.0)
    return H_gain, lut[days - 1], lut


def rts_kalman_smoother_with_cross_guard(
    y_obs: np.ndarray,
    u_spatial: np.ndarray,
    doy: np.ndarray,
    cloud_cover: np.ndarray,
    forecast_days: int = 14,
    phi: float = 0.68,
    gamma: float = 0.17,
    omega_prior: float = 0.15,
    Q_var: float = 12.0,
    R_var: tuple[float, float, float] = (9.0, 6.0, 5.0),
    R_guard: float = 40.0,
) -> dict[str, np.ndarray]:
    """Filter history, smooth it with RTS, then project without pseudo-updates.

    Historical arrays have length T; forecast arrays have length forecast_days.
    Variances use uppercase P keys; all confidence bands are 95% marginal bands.
    H_gain, mu_cross_series and lut_366 expose the fitted observation model.
    guard_applied identifies historical pseudo-observations. Missing spatial
    energy falls back to the historical prior; missing cloud fractions become
    one, conservatively inflating process variance. Other invalid inputs raise
    ValueError, rather than emitting non-finite estimates.

    Forecast spatial forcing uses the future climatology and cloud fraction one.
    No forecast measurement is injected. Forecast days wrap on the 366-day
    Julian ring: exact civil-year/leap-year rollover requires dates, which this
    interface does not receive. Historical inputs must represent consecutive
    days; their prior uses the supplied DOYs, including ordinary-year rollovers.
    The prior is retrospective (all supplied years), not a causal backtest.
    """
    obs = np.asarray(y_obs, dtype=np.float64)
    H_gain, prior, lut = build_cross_sensor_historical_prior(doy, obs)
    n = len(prior)
    spatial = np.asarray(u_spatial, dtype=np.float64)
    clouds = np.asarray(cloud_cover, dtype=np.float64)
    if spatial.shape != (n,) or clouds.shape != (n,):
        raise ValueError("Spatial forcing and cloud fractions must each have shape (T,).")
    if np.isinf(spatial).any() or np.any(spatial < 0) or np.any(spatial > 1e100):
        raise ValueError("Spatial forcing must be in [0, 1e100], or NaN for missing data.")
    if np.isinf(clouds).any() or np.any((clouds < 0) | (clouds > 1)):
        raise ValueError("Cloud cover must be a fraction in [0, 1], or NaN.")
    if not isinstance(forecast_days, (int, np.integer)) or forecast_days < 0:
        raise ValueError("forecast_days must be a non-negative integer.")
    if n == 0 and forecast_days:
        raise ValueError("A forecast requires at least one historical day.")
    coefficients = np.asarray([phi, gamma, omega_prior], dtype=float)
    if not np.isfinite(coefficients).all() or np.any((coefficients < 0) | (coefficients > 1)):
        raise ValueError("Transition coefficients must be finite and in [0, 1].")
    noise = np.asarray(R_var, dtype=float)
    if noise.shape != (3,):
        raise ValueError("R_var must contain three sensor variances.")
    variances = np.r_[noise, Q_var, R_guard]
    if not np.isfinite(variances).all() or np.any(variances < 0) or np.any(variances > 1e100):
        raise ValueError("Noise variances must be finite and in [0, 1e100].")
    spatial = np.where(np.isnan(spatial), prior, spatial)
    clouds = np.where(np.isnan(clouds), 1.0, clouds)
    x_pred = np.empty(n)
    P_pred = np.empty(n)
    x_filter = np.empty(n)
    P_filter = np.empty(n)
    guard = np.all(np.isnan(obs), axis=1)
    x = float(prior[0]) if n else 0.0
    P = max(float(R_guard), 1e-4)
    for t in range(n):
        x_p = phi * x + gamma * spatial[t] + omega_prior * prior[t]
        P_p = max(phi ** 2 * P + Q_var * (1.0 + 0.8 * clouds[t]), 1e-4)
        x_pred[t], P_pred[t] = x_p, P_p
        for s in range(3):
            if np.isnan(obs[t, s]):
                continue
            h = H_gain[t, s]
            R_var_s = noise[s]
            S_innov = h ** 2 * P_p + R_var_s + 1e-8
            K = P_p * h / S_innov
            x_p = max(0.0, x_p + K * (obs[t, s] - h * x_p))
            P_p = ((1.0 - K * h) ** 2) * P_p + (K ** 2) * R_var_s
        if guard[t]:
            y_guard = 0.55 * prior[t] + 0.45 * spatial[t]
            h = 1.0
            K = P_p * h / (h ** 2 * P_p + R_guard + 1e-8)
            x_p = max(0.0, x_p + K * (y_guard - h * x_p))
            P_p = ((1.0 - K * h) ** 2) * P_p + (K ** 2) * R_guard
        x, P = x_p, max(P_p, 1e-4)
        x_filter[t], P_filter[t] = x, P

    x_smooth, P_smooth = x_filter.copy(), P_filter.copy()
    for t in range(n - 2, -1, -1):
        G_t = P_filter[t] * phi / (P_pred[t + 1] + 1e-8)
        x_smooth[t] = max(0.0, x_filter[t] + G_t * (x_smooth[t + 1] - x_pred[t + 1]))
        P_smooth[t] = max(1e-4, P_filter[t] + G_t ** 2 * (P_smooth[t + 1] - P_pred[t + 1]))

    forecast_doy = ((int(np.asarray(doy)[-1]) + np.arange(forecast_days)) % 366 + 1
                    if n else np.empty(0, dtype=int))
    forecast_x, forecast_P = np.empty(forecast_days), np.empty(forecast_days)
    for k, day in enumerate(forecast_doy):
        future_prior = lut[day - 1]
        x = max(0.0, phi * x + (gamma + omega_prior) * future_prior)
        P = max(1e-4, phi ** 2 * P + Q_var * 1.8)
        forecast_x[k], forecast_P[k] = x, P
    margin = 1.96 * np.sqrt(P_smooth)
    forecast_margin = 1.96 * np.sqrt(forecast_P)
    result = {
        "x_smooth": x_smooth, "P_smooth": P_smooth,
        "ci_lower": np.maximum(0.0, x_smooth - margin), "ci_upper": x_smooth + margin,
        "x_filter": x_filter, "P_filter": P_filter, "x_pred": x_pred, "P_pred": P_pred,
        "H_gain": H_gain, "mu_cross_series": prior, "lut_366": lut,
        "guard_applied": guard, "forecast_doy": forecast_doy,
        "forecast_x": forecast_x, "forecast_P": forecast_P,
        "forecast_ci_lower": np.maximum(0.0, forecast_x - forecast_margin),
        "forecast_ci_upper": forecast_x + forecast_margin,
    }
    if any(not np.isfinite(array).all() or np.any(array < 0) for array in result.values()):
        raise FloatingPointError("Kalman estimation exceeded the supported numerical range.")
    return result
