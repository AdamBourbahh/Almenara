"""Explicit access to Adam's math core (backend/core). No conditional imports, no substitutes.

Every function the API needs is listed in CORE_FUNCTIONS with its agreed signature. If a module or
function is missing, CoreMissingError names exactly what is missing; routes turn it into HTTP 503.
"""

from __future__ import annotations

import importlib
import importlib.util
from typing import Callable

CORE_FUNCTIONS: dict[str, tuple[str, str, str]] = {
    "compute_cross_prior": (
        "backend.core.kalman_rts", "compute_cross_prior",
        "(doy: int[n], obs: float[n,3] NaN=missing) -> float[366]"),
    "kalman_rts_smooth": (
        "backend.core.kalman_rts", "kalman_rts_smooth",
        "(obs: float[n,3], u_spatial: float[n] NaN allowed, prior: float[n]) "
        "-> object with .x_smooth float[n] and .p_smooth float[n] >= 0"),
    "fit_von_mises_year": (
        "backend.core.von_mises", "fit_von_mises_year",
        "(doy: int[m], weights: float[m]) -> (mu_doy, kappa, width_days)"),
    "phenology_trend": (
        "backend.core.von_mises", "phenology_trend",
        "(years: int[k], peaks: float[k]) -> (slope_days_per_decade, mann_kendall_p)"),
    "chow_test": (
        "backend.core.auditor_stats", "chow_test",
        "(values: float[n], years: int[n], doy: int[n]) -> (F, p)"),
    "wasserstein_w1_normalized": (
        "backend.core.auditor_stats", "wasserstein_w1_normalized",
        "(values: float[n], years: int[n]) -> float"),
    "descriptive_r2": (
        "backend.core.auditor_stats", "descriptive_r2",
        "(x: float[n], y: float[n]) -> float | None"),
    "run_chaos_monkey_simulation": (
        "backend.core.chaos_monkey", "run_chaos_monkey_simulation",
        "(daily: dict[str, ndarray], target_year, drop_fraction, simulate_dual_blackout, random_seed) "
        "-> dict with ChaosMonkeyResponse fields except data_source"),
}


class CoreMissingError(RuntimeError):
    """A required backend.core function is not available."""


def _resolve(public_name: str) -> Callable:
    module_name, attr, signature = CORE_FUNCTIONS[public_name]
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise CoreMissingError(
            f"Missing module {module_name} (needed for {attr}{signature}). "
            "Owner: Adam (backend/core). See CAMBIOS.md.") from exc
    try:
        return getattr(module, attr)
    except AttributeError as exc:
        raise CoreMissingError(
            f"Missing {module_name}.{attr} — expected signature {signature}. "
            "Owner: Adam (backend/core). See CAMBIOS.md.") from exc


def require(public_name: str) -> Callable:
    """Return the core function or raise CoreMissingError (looked up at call time)."""
    return _resolve(public_name)


def core_status() -> dict[str, bool]:
    """Which core functions exist right now (no exception swallowing)."""
    status = {}
    for name, (module_name, attr, _) in CORE_FUNCTIONS.items():
        found = importlib.util.find_spec(module_name) is not None
        status[name] = found and callable(getattr(importlib.import_module(module_name), attr, None))
    return status
