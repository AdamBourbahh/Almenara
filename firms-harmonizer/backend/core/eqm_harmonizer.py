"""Empirical VIIRS-to-MODIS mapping with a bounded GPD energy correction."""

from __future__ import annotations

import numpy as np
from scipy.integrate import quad
from scipy.stats import genpareto


class RadiometricHarmonizer:
    """Fit reusable, JSON-serializable biome LUTs without I/O dependencies.

    Inputs must already share FRE density units and temporal/spatial support.
    The requested numerical censoring bounds 0.5 and 8.0 are applied in those
    input units; this class does not convert instantaneous MW into daily FRE.
    A fitted LUT is remembered as the default; pass one explicitly to select a
    different biome. Endpoint extrapolation is clamped, as in numpy.interp.
    """

    def __init__(self) -> None:
        self.lut: dict | None = None

    def fit_biome_eqm_gpd(
        self, modis_fre: np.ndarray, viirs_fre: np.ndarray, biome_id: int = 1,
    ) -> dict:
        """Fit 101 quantile knots and a sub-threshold expected-energy correction.

        Finite, non-negative training samples are required; NaNs are omitted
        independently because empirical CDF matching uses marginal samples.
        The GPD models excesses above 0.5, truncated at 8.0. Its conditional
        mean times the observed tail fraction estimates delta E_sub. Sparse
        or constant tails use the exponential GPD limit (shape zero).
        """
        if not isinstance(biome_id, (int, np.integer)) or not 1 <= biome_id <= 17:
            raise ValueError("Biome ID must be an integer from 1 to 17.")
        samples = []
        for values in (modis_fre, viirs_fre):
            data = np.asarray(values, dtype=float)
            if data.ndim != 1 or np.isinf(data).any() or np.any(data < 0):
                raise ValueError("Training data must be 1D non-negative FRE, with optional NaNs.")
            data = data[np.isfinite(data)]
            if not data.size:
                raise ValueError("Each instrument needs at least one finite training sample.")
            samples.append(data)
        modis, viirs = samples
        quantiles = np.linspace(0.0, 1.0, 101)
        x, y = np.quantile(viirs, quantiles), np.quantile(modis, quantiles)
        below = viirs[(viirs >= 0.5) & (viirs < 8.0)]
        correction, tail = 0.0, None
        if below.size:
            excess = below - 0.5
            shape, scale = 0.0, max(float(excess.mean()), 1e-8)
            method = "exponential_sparse_tail"
            if below.size >= 3 and np.ptp(excess) > 1e-8:
                shape, _, scale = genpareto.fit(excess, floc=0.0)
                method = "maximum_likelihood"
            if not np.isfinite([shape, scale]).all() or scale <= 0:
                raise ValueError("GPD fit did not yield finite, positive-scale parameters.")
            distribution = genpareto(shape, loc=0.0, scale=scale)
            span = 7.5
            mass = float(distribution.cdf(span))
            # Survival integration is stable even for finite-support GPDs whose
            # density diverges at the upper endpoint (negative shape < -1).
            survival_integral = quad(distribution.sf, 0.0, span, epsabs=1e-9)[0]
            mean = 0.5 + (survival_integral - span * distribution.sf(span)) / mass
            mean = float(np.clip(mean, 0.5, 8.0))
            fraction = float(below.size / viirs.size)
            correction = fraction * mean
            tail = {"shape": float(shape), "scale": float(scale), "lower": 0.5,
                    "upper": 8.0, "fraction": fraction, "conditional_mean": mean,
                    "fit_method": method}
        lut = {"biome_id": int(biome_id), "quantiles": quantiles.tolist(),
               "viirs_quantiles": x.tolist(), "modis_quantiles": y.tolist(),
               "gpd": tail, "delta_e_sub": float(correction)}
        self.lut = lut
        return lut

    def harmonize_viirs_to_modis(self, viirs_fre: np.ndarray, lut: dict | None = None) -> np.ndarray:
        """Map FRE monotonically and add the fitted tail expectation to detections.

        NaNs remain missing and zeros remain zero. Duplicate source quantiles
        are pooled by averaging target knots, so constant/quantized samples
        define a deterministic monotone interpolation.
        """
        model = self.lut if lut is None else lut
        if model is None:
            raise ValueError("Fit a LUT first or supply one explicitly.")
        x = np.asarray(model["viirs_quantiles"], dtype=float)
        y = np.asarray(model["modis_quantiles"], dtype=float)
        correction = float(model.get("delta_e_sub", 0.0))
        if (x.ndim != 1 or x.size == 0 or x.shape != y.shape
                or not np.isfinite(x).all() or not np.isfinite(y).all()
                or np.any(x < 0) or np.any(y < 0)
                or np.any(np.diff(x) < 0) or np.any(np.diff(y) < 0)
                or not np.isfinite(correction) or correction < 0):
            raise ValueError("LUT knots and correction must be finite, non-negative and monotone.")
        unique, indices, counts = np.unique(x, return_index=True, return_counts=True)
        targets = np.add.reduceat(y, indices) / counts
        data = np.asarray(viirs_fre, dtype=float)
        if np.isinf(data).any() or np.any(data < 0):
            raise ValueError("FRE must be non-negative and finite, with optional NaNs.")
        mapped = np.interp(data, unique, targets) + correction
        return np.asarray(np.where(np.isnan(data), np.nan, np.where(data == 0, 0.0, mapped)))
