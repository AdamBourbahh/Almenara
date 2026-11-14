"""Energy-weighted circular phenology and robust interannual peak trends."""

from __future__ import annotations

import numpy as np
from scipy.stats import kendalltau, theilslopes

from backend.api.schemas import VonMisesPhenologyYear


_PERIOD = 365.25
_MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


def best_fisher_kappa(r_bar: float) -> float:
    """Approximate inverse mean resultant length using Best and Fisher."""
    r = float(r_bar)
    if not np.isfinite(r) or not 0.0 <= r <= 1.0:
        raise ValueError("Mean resultant length must be finite and in [0, 1].")
    if r < .53:
        return 2.0 * r + r**3 + 5.0 * r**5 / 6.0
    if r < .85:
        return -.4 + 1.39 * r + .43 / (1.0 - r)
    return 1.0 / max(1e-4, r**3 - 4.0 * r**2 + 3.0 * r)


def doy_to_date_label(doy_float: float) -> str:
    """Label nearest Julian day using leap-year 2000 and fixed English months.

    This year-independent label supports DOY 366; it is not an acquisition date.
    """
    day = float(doy_float)
    if not np.isfinite(day) or not 1.0 <= day <= 366.0:
        raise ValueError("Julian day must be finite and in [1, 366].")
    date = str(np.datetime64('2000-01-01') + np.timedelta64(int(np.floor(day + .5)) - 1, 'D'))
    return f"{int(date[8:10])} {_MONTHS[int(date[5:7]) - 1]}"


def compute_circular_phenology(
    years: np.ndarray, doy: np.ndarray, fre_series: np.ndarray, aoi_area_km2: float,
) -> tuple[list[VonMisesPhenologyYear], float, float]:
    """Fit annual circular moments and an unwrapped Theil-Sen trend.

    Input FRE is daily MJ/km2 on a common AOI. Annual GJ is sum(FRE)*area/1000.
    Zero-energy or directionless years use peak 1, kappa 0 and width 365 as
    deterministic display conventions and are excluded from the trend. With
    fewer than two directional years (or constant peaks), return slope 0, p=1.
    Kendall's two-sided rank p-value is the requested Mann-Kendall proxy and
    does not correct for serial correlation or incomplete calendar coverage.
    """
    years, days, energy = np.asarray(years), np.asarray(doy), np.asarray(fre_series, dtype=float)
    if years.ndim != 1 or days.shape != years.shape or energy.shape != years.shape:
        raise ValueError("Years, DOY and FRE must be equal-length 1D arrays.")
    if (not np.isfinite(years).all() or np.any(years != np.floor(years))
            or np.any((years < 1) | (years > 9999))):
        raise ValueError("Years must be integers in [1, 9999].")
    if not np.isfinite(days).all() or np.any((days < 1) | (days > 366) | (days != np.floor(days))):
        raise ValueError("Julian days must be integers in [1, 366].")
    if not np.isfinite(energy).all() or np.any(energy < 0) or np.any(energy > 1e100):
        raise ValueError("FRE must be finite, non-negative and at most 1e100.")
    if not np.isfinite(aoi_area_km2) or not 0 < aoi_area_km2 <= 1e100:
        raise ValueError("AOI area must be finite, positive and at most 1e100.")
    results, directional_years, angles = [], [], []
    for year in np.unique(years):
        selected = years == year
        weights = energy[selected]
        total = float(weights.sum())
        peak, kappa = 1.0, 0.0
        if total > 0:
            theta = 2.0 * np.pi * days[selected] / _PERIOD
            moment = np.sum((weights / total) * np.exp(1j * theta))
            resultant = float(np.clip(abs(moment), 0.0, 1.0))
            if resultant > 1e-12:
                angle = float(np.angle(moment))
                peak = float(np.clip((angle % (2.0 * np.pi)) * _PERIOD / (2.0 * np.pi), 1.0, _PERIOD))
                kappa = best_fisher_kappa(resultant)
                directional_years.append(float(year))
                angles.append(angle)
        results.append(VonMisesPhenologyYear(
            year=int(year), peak_doy_mu=peak, peak_date_label=doy_to_date_label(peak),
            concentration_kappa=kappa, season_width_days=min(365.0, _PERIOD / np.sqrt(max(.15, kappa))),
            total_annual_fre_gj=total * aoi_area_km2 / 1000.0,
        ))
    if len(angles) < 2:
        return results, 0.0, 1.0
    unwrapped_days = np.unwrap(angles) * _PERIOD / (2.0 * np.pi)
    if np.ptp(unwrapped_days) <= 1e-10:
        return results, 0.0, 1.0
    shift = float(theilslopes(unwrapped_days, directional_years).slope * 10.0)
    p_value = float(kendalltau(directional_years, unwrapped_days).pvalue)
    return results, shift, p_value
