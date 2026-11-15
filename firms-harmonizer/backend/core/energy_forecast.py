"""Causal seasonal/AR energy forecasts and rolling-origin diagnostics.

Unknown dates are NaN, never training zeros. Every backtest fits on preceding
observations only. The estimates describe the sampled FRE proxy, not ignitions.
"""
import numpy as np


def project(dates, values, horizon):
    dates = np.asarray(dates, dtype='datetime64[D]')
    values = np.asarray(values, dtype=float)
    if len(dates) < 730 or np.isfinite(values).sum() < 365:
        return None
    finite = np.isfinite(values)
    if not finite[-1]:
        return None
    doy = (dates - dates.astype('datetime64[Y]')).astype(int) + 1
    future = dates[-1] + np.arange(1, horizon + 1).astype('timedelta64[D]')
    future_doy = (future - future.astype('datetime64[Y]')).astype(int) + 1
    seasonal = np.zeros(366)
    overall = float(np.nanmean(values))
    for day in range(1, 367):
        distance = np.abs(doy - day)
        chosen = finite & (np.minimum(distance, 366 - distance) <= 15)
        seasonal[day - 1] = np.mean(values[chosen]) if chosen.any() else overall
    residual = values - seasonal[doy - 1]
    paired = finite[:-1] & finite[1:]
    a, b = residual[:-1][paired], residual[1:][paired]
    phi = float(np.clip(np.dot(a, b) / (np.dot(a, a) + 1e-8), 0, .95))
    error = b - phi * a
    sigma = float(np.sqrt(np.mean(error**2))) if len(error) else 0.0
    steps = np.arange(1, horizon + 1)
    predicted = np.maximum(0, seasonal[future_doy - 1] + phi**steps * residual[-1])
    margin = 1.96 * sigma * np.sqrt(np.cumsum(phi**(2 * np.arange(horizon))))
    return dict(dates=future, predicted=predicted, lower=np.maximum(0, predicted - margin),
                upper=predicted + margin, seasonal=seasonal[future_doy - 1])


def evaluate(dates, values):
    dates, values = np.asarray(dates, dtype='datetime64[D]'), np.asarray(values, dtype=float)
    errors = {h: [] for h in (1, 7, 14)}
    # Monthly rolling origins in the final two years. Each fit excludes all future labels.
    origins = np.arange(max(730, len(values) - 730), len(values) - 14, 30)
    for origin in origins:
        result = project(dates[:origin + 1], values[:origin + 1], 14)
        if result is None:
            continue
        for horizon in errors:
            actual = values[origin + horizon]
            if not np.isfinite(actual):
                continue
            k = horizon - 1
            errors[horizon].append((abs(actual - result['predicted'][k]),
                abs(actual - values[origin]), abs(actual - result['seasonal'][k]),
                result['lower'][k] <= actual <= result['upper'][k]))
    metrics = []
    for horizon, rows in errors.items():
        if not rows:
            continue
        means = np.asarray(rows, dtype=float).mean(axis=0)
        metrics.append(dict(horizon_days=horizon, samples=len(rows), mae=float(means[0]),
            persistence_mae=float(means[1]), climatology_mae=float(means[2]),
            interval_coverage_pct=float(100 * means[3])))
    return metrics
