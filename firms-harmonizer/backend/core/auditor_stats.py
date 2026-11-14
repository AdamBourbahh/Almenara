"""Unit-consistent biomass conversion and descriptive fire-record diagnostics."""

from __future__ import annotations

import numpy as np
from scipy.stats import f as f_distribution, wasserstein_distance

from backend.api.schemas import ScientificAuditMetrics


def compute_wooster_biomass_and_smoke(
    fre_mj_km2: np.ndarray, aoi_area_km2: float, ef_pm25_g_per_kg: float = 9.5,
) -> tuple[np.ndarray, np.ndarray]:
    """Convert daily FRE density to dry tonnes and emitted PM2.5 kilograms."""
    fre = np.asarray(fre_mj_km2, dtype=float)
    if not np.isfinite(fre).all() or np.any(fre < 0) or np.any(fre > 1e100):
        raise ValueError("FRE must be finite, non-negative and at most 1e100.")
    if not np.isfinite(aoi_area_km2) or not 0 < aoi_area_km2 <= 1e100:
        raise ValueError("AOI area must be finite, positive and at most 1e100.")
    if not np.isfinite(ef_pm25_g_per_kg) or not 0 <= ef_pm25_g_per_kg <= 1e100:
        raise ValueError("The emission factor must be finite and non-negative, at most 1e100.")
    biomass = .368 * fre * aoi_area_km2 * 1e-3
    return np.asarray(biomass), np.asarray(biomass * ef_pm25_g_per_kg)


def compute_chow_structural_break_test(
    years: np.ndarray, annual_series: np.ndarray, break_year: int = 2012,
) -> tuple[float, float]:
    """Test equality of pre/post linear regressions on distinct annual values.

    Each segment needs two distinct years and total residual degrees of freedom
    must be positive. Insufficient or missing annual data raises ValueError.
    Regression scaling avoids year-offset conditioning and magnitude overflow.
    Numerically exact common lines return (0, 1); perfect piecewise lines use a
    roundoff floor in residual variance to keep F finite and JSON serializable.
    """
    years, values = np.asarray(years, dtype=float), np.asarray(annual_series, dtype=float)
    if years.ndim != 1 or values.shape != years.shape or not np.isfinite(years).all() or not np.isfinite(values).all():
        raise ValueError("Annual years and series must be equal-length finite 1D arrays.")
    if np.any(years != np.floor(years)) or np.unique(years).size != years.size:
        raise ValueError("Provide one observation per distinct integer year.")
    if not isinstance(break_year, (int, np.integer)):
        raise ValueError("The break year must be an integer.")
    pre = years < break_year
    if min(np.count_nonzero(pre), np.count_nonzero(~pre)) < 2 or len(years) <= 4:
        raise ValueError("Chow testing needs two years per segment and more than four years in total.")
    t = years - years.mean()
    t /= max(float(np.max(np.abs(t))), 1.0)
    design = np.column_stack([np.ones(len(t)), t])
    scaled = values / max(float(np.max(np.abs(values))), 1.0)
    def rss(mask):
        x, y = design[mask], scaled[mask]
        residual = y - x @ np.linalg.lstsq(x, y, rcond=None)[0]
        return float(residual @ residual)
    pooled = rss(np.ones(len(years), dtype=bool))
    separate = rss(pre) + rss(~pre)
    tolerance = 64.0 * len(years) * np.finfo(float).eps**2
    if pooled <= tolerance:
        return 0.0, 1.0
    df2 = max(1, len(years) - 4)
    statistic = max(0.0, (pooled - separate) / 2.0) / max(separate / df2, tolerance)
    return float(statistic), float(f_distribution.sf(statistic, 2, df2))


def _annual_r2(metric: np.ndarray, burned: np.ndarray) -> float | None:
    """Descriptive OLS-with-intercept R2; unavailable for constant/missing data."""
    valid = np.isfinite(burned) & np.isfinite(metric)
    if valid.sum() < 3:
        return None
    x, y = metric[valid], burned[valid]
    x, y = x / max(float(np.max(x)), 1.0), y / max(float(np.max(y)), 1.0)
    x, y = x - x.mean(), y - y.mean()
    if np.dot(x, x) <= 1e-24 or np.dot(y, y) <= 1e-24:
        return None
    correlation = np.dot(x, y) / np.sqrt(np.dot(x, x) * np.dot(y, y))
    return float(np.clip(correlation**2, 0.0, 1.0))


def compute_scientific_audit_metrics(
    years: np.ndarray, raw_counts: np.ndarray, harm_fre: np.ndarray,
    burned_area_ha: np.ndarray, aoi_area_km2: float,
    phenology_shift_days_per_decade: float, mann_kendall_p_value: float,
    industrial_false_positives_removed: int,
) -> ScientificAuditMetrics:
    """Compare annual means, normalized daily W1, and annual burned-area totals.

    Chow uses annual means to avoid day-count/leap-year exposure effects. W1
    divides each entire daily series by its own full-record mean (not separate
    pre/post means, which would erase the break). R2 is squared annual Pearson
    correlation, equivalent to fitted OLS R2 with intercept, not out-of-sample
    validation. A year with any missing burned-area input is omitted from R2.
    At least five distinct years with two on either side of 2012 are required.
    """
    years = np.asarray(years)
    raw, harm, burned = (np.asarray(a, dtype=float) for a in (raw_counts, harm_fre, burned_area_ha))
    if years.ndim != 1 or any(a.shape != years.shape for a in (raw, harm, burned)):
        raise ValueError("All daily inputs must be equal-length 1D arrays.")
    if not np.isfinite(years).all() or np.any(years != np.floor(years)):
        raise ValueError("Years must be finite integers.")
    for values in (raw, harm):
        if not np.isfinite(values).all() or np.any((values < 0) | (values > 1e100)):
            raise ValueError("Daily raw counts and harmonized FRE must be finite and in [0, 1e100].")
    if np.isinf(burned).any() or np.any((burned < 0) | (burned > 1e100)):
        raise ValueError("Burned area must be non-negative and at most 1e100, with NaN if unavailable.")
    if not np.isfinite(phenology_shift_days_per_decade) or not np.isfinite(mann_kendall_p_value) or not 0 <= mann_kendall_p_value <= 1:
        raise ValueError("Trend must be finite and its p-value must be in [0, 1].")
    if not isinstance(industrial_false_positives_removed, (int, np.integer)) or industrial_false_positives_removed < 0:
        raise ValueError("Removed industrial detections must be a non-negative integer.")
    unique, inverse, counts = np.unique(years, return_inverse=True, return_counts=True)
    raw_total = np.bincount(inverse, weights=raw, minlength=len(unique))
    harm_total = np.bincount(inverse, weights=harm, minlength=len(unique))
    burned_total = np.bincount(inverse, weights=burned, minlength=len(unique))
    raw_f, raw_p = compute_chow_structural_break_test(unique, raw_total / counts)
    harm_f, harm_p = compute_chow_structural_break_test(unique, harm_total / counts)
    pre = years < 2012
    def normalized_w1(values):
        scale = float(values.mean())
        if scale == 0:
            return 0.0
        return float(wasserstein_distance(values[pre] / scale, values[~pre] / scale))
    raw_w1, harm_w1 = normalized_w1(raw), normalized_w1(harm)
    raw_r2, harm_r2 = _annual_r2(raw_total, burned_total), _annual_r2(harm_total, burned_total)
    biomass, smoke = compute_wooster_biomass_and_smoke(harm, aoi_area_km2)
    break_verdict = 'no significant 2012 break detected' if harm_p > .10 else 'a 2012 break remains detectable'
    area_verdict = ('Burned-area R2 is unavailable (missing or constant annual data).' if harm_r2 is None
                    else f'Annual descriptive burned-area R2: raw {raw_r2:.3f}, harmonized {harm_r2:.3f}.'
                    if raw_r2 is not None else f'Annual descriptive harmonized burned-area R2: {harm_r2:.3f}; raw unavailable.')
    verdict = (f'Harmonized annual Chow test: {break_verdict} (p={harm_p:.3g}); raw p={raw_p:.3g}. '
               f'Normalized daily W1: raw {raw_w1:.3f}, harmonized {harm_w1:.3f}. {area_verdict} '
               f'Peak shift {phenology_shift_days_per_decade:+.2f} days/decade '
               f'(Kendall p={mann_kendall_p_value:.3g}). These are descriptive diagnostics; '
               'statistical non-rejection does not establish sensor equivalence or independent validation.')
    return ScientificAuditMetrics(
        chow_test_f_stat_raw=raw_f, chow_test_p_val_raw=raw_p,
        chow_test_f_stat_harm=harm_f, chow_test_p_val_harm=harm_p,
        wasserstein_w1_raw=raw_w1, wasserstein_w1_harm=harm_w1,
        burned_area_r2_raw=raw_r2, burned_area_r2_harm=harm_r2,
        phenology_shift_days_per_decade=float(phenology_shift_days_per_decade),
        mann_kendall_p_value=float(mann_kendall_p_value),
        industrial_false_positives_removed=int(industrial_false_positives_removed),
        total_biomass_burned_kt=float(biomass.sum() / 1000.0),
        total_pm25_emitted_tonnes=float(smoke.sum() / 1000.0), executive_verdict_en=verdict,
    )
