"""Vectorized temporal persistence and South Atlantic anomaly screening."""

from __future__ import annotations

import numpy as np
from scipy.special import expit


def compute_shannon_temporal_entropy(monthly_counts: np.ndarray) -> np.ndarray:
    """Return normalized entropy along the twelve-month axis (0 for empty cells)."""
    counts = np.asarray(monthly_counts, dtype=float)
    if counts.ndim not in (1, 2) or counts.shape[-1] != 12:
        raise ValueError("Monthly counts must have shape (12,) or (N, 12).")
    if not np.isfinite(counts).all() or np.any(counts < 0):
        raise ValueError("Monthly counts must be finite and non-negative.")
    totals = counts.sum(axis=-1, keepdims=True)
    if not np.isfinite(totals).all():
        raise ValueError("Monthly totals exceed floating point range.")
    fractions = counts / (totals + 1e-12)
    entropy = -np.sum(fractions * np.log(fractions + 1e-12), axis=-1) / np.log(12.0)
    return np.asarray(np.clip(entropy, 0.0, 1.0))


def compute_industrial_probability(
    monthly_counts: np.ndarray, delta_t4_t11: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Estimate persistence probability with an optional weak contrast modifier.

    Contrast can be one value per cell, or monthly values shaped like counts.
    For monthly contrast, steadiness is 1/(1 + standard deviation in kelvin).
    A single finite value cannot establish steadiness and gives no boost. Missing
    contrast gives no boost. The maximum boost is 5% of remaining probability,
    scaled by temporal entropy; zero-detection cells therefore receive none.
    """
    entropy = compute_shannon_temporal_entropy(monthly_counts)
    probability = expit(22.0 * (entropy - 0.72))
    if delta_t4_t11 is not None:
        contrast = np.asarray(delta_t4_t11, dtype=float)
        counts = np.asarray(monthly_counts)
        if contrast.shape == counts.shape:
            finite = np.isfinite(contrast)
            n = finite.sum(axis=-1)
            mean = np.sum(np.where(finite, contrast, 0.0), axis=-1) / np.maximum(n, 1)
            residual = np.where(finite, contrast - mean[..., None], 0.0)
            variance = np.sum(residual * residual, axis=-1) / np.maximum(n, 1)
            steadiness = np.where(n >= 2, 1.0 / (1.0 + np.sqrt(variance)), 0.0)
            probability += 0.05 * entropy * steadiness * (1.0 - probability)
        else:
            # Validate a per-cell optional covariate without pretending that a
            # single thermal sample establishes temporal stability.
            np.broadcast_to(contrast, entropy.shape)
    return entropy, np.asarray(np.clip(probability, 0.0, 1.0))


def filter_sama_anomalies(
    lat: np.ndarray, lon: np.ndarray, daynight: np.ndarray, is_low_conf: np.ndarray,
    delta_t11: np.ndarray, acq_year: np.ndarray | None = None,
    acq_month: np.ndarray | None = None,
) -> np.ndarray:
    """Return True for nighttime SAMA noise or pre-November 2000 records.

    Date filtering assumes the caller has selected Terra records: the supplied
    interface has no satellite argument and cannot distinguish instruments.
    """
    lat, lon, night, low, contrast = np.broadcast_arrays(
        np.asarray(lat, dtype=float), np.asarray(lon, dtype=float),
        np.asarray(daynight).astype(str), np.asarray(is_low_conf, dtype=bool),
        np.asarray(delta_t11, dtype=float),
    )
    spurious = ((lat >= -35.0) & (lat <= -15.0) & (lon >= -65.0) & (lon <= -30.0)
                & (night == "N") & low & (contrast < 1.5))
    if (acq_year is None) != (acq_month is None):
        raise ValueError("Acquisition year and month must be supplied together.")
    if acq_year is not None:
        years = np.broadcast_to(np.asarray(acq_year), spurious.shape)
        months = np.broadcast_to(np.asarray(acq_month), spurious.shape)
        if not np.isfinite(years).all() or not np.isfinite(months).all():
            raise ValueError("Acquisition dates must be finite.")
        if np.any((months < 1) | (months > 12) | (months != np.floor(months))):
            raise ValueError("Acquisition months must be integers from 1 to 12.")
        spurious |= (years == 2000) & (months < 11)
    return np.asarray(spurious, dtype=bool)
