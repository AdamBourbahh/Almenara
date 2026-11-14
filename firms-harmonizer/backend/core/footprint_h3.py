"""Local Gaussian footprint allocation and MODIS bow-tie suppression."""

from __future__ import annotations

import h3
import numpy as np

H3_R7_AREA_KM2: float = 5.161
_EARTH_RADIUS_KM = 6371.0088


def compute_modis_bowtie_overlap_weight(track_km: np.ndarray | float) -> np.ndarray | float:
    """Discount along-track overlap only beyond the 1.35 km threshold."""
    track = np.asarray(track_km, dtype=float)
    if not np.isfinite(track).all() or np.any(track < 0):
        raise ValueError("Along-track dimensions must be finite and non-negative.")
    result = np.where(track > 1.35, 1.0 / np.maximum(1.0, track), 1.0)
    return float(result) if result.ndim == 0 else result


def compute_elliptical_psf_weights(
    lat: float, lon: float, scan_km: float, track_km: float, azimuth_deg: float = 98.2,
) -> dict[str, float]:
    """Allocate unit energy to R7 centers using the normalized Gaussian PDF.

    The rotation follows R(alpha) in an east/north tangent plane, with alpha
    measured counterclockwise from east. Wrapped longitude differences handle
    the antimeridian. Log weights avoid Gaussian underflow for narrow ellipses.
    H3 pentagons naturally have five rather than six first-ring neighbors.
    """
    if not np.isfinite([lat, lon, scan_km, track_km, azimuth_deg]).all():
        raise ValueError("Coordinates, footprint dimensions and azimuth must be finite.")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Latitude/longitude are outside geographic bounds.")
    if scan_km <= 0 or track_km <= 0:
        raise ValueError("Footprint dimensions must be strictly positive.")
    to_cell = h3.latlng_to_cell if hasattr(h3, "latlng_to_cell") else h3.geo_to_h3
    to_center = h3.cell_to_latlng if hasattr(h3, "cell_to_latlng") else h3.h3_to_geo
    disk = h3.grid_disk if hasattr(h3, "grid_disk") else h3.k_ring
    center = to_cell(lat, lon, 7)
    center = format(int(center, 16) if isinstance(center, str) else int(center), "015x")
    if scan_km * track_km <= 3.5:
        return {center: 1.0}
    cells = sorted(disk(center, 1))
    coordinates = np.array([to_center(cell) for cell in cells], dtype=float)
    delta_lon = (coordinates[:, 1] - lon + 180.0) % 360.0 - 180.0
    xy = _EARTH_RADIUS_KM * np.deg2rad(np.column_stack([
        delta_lon * np.cos(np.deg2rad(lat)), coordinates[:, 0] - lat,
    ]))
    angle = np.deg2rad(azimuth_deg % 360.0)
    rotation = np.array([[np.cos(angle), -np.sin(angle)],
                         [np.sin(angle), np.cos(angle)]])
    # Project onto the covariance eigenvectors: equivalent to evaluating
    # xy @ inv(R diag(sigma**2) R.T) @ xy.T without forming an inverse.
    scaled = (xy @ rotation) / (np.array([scan_km, track_km]) / 2.355)
    log_weights = -0.5 * np.sum(scaled * scaled, axis=1)
    weights = np.exp(log_weights - np.max(log_weights))
    weights /= weights.sum()
    # Put the largest weight last and take the residual, so Python sum of the
    # returned values is exactly 1.0 despite floating point rounding.
    largest = int(np.argmax(weights))
    indices = [i for i in range(len(cells)) if i != largest]
    result = {cells[i]: float(weights[i]) for i in indices}
    result[cells[largest]] = 1.0 - sum(result.values())
    return result
