"""Validated access to the scientific core through explicit HTTP-boundary adapters.

Every API operation is listed in CORE_FUNCTIONS; adapters declare their underlying scientific dependency.
* Missing module/function  -> CoreMissingError (routes answer HTTP 503 naming it).
* Output breaks the contract -> CoreContractViolation (routes answer HTTP 500 naming it).
`call()` is the only way routes invoke the core: it resolves, times and validates every result.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
from time import perf_counter
from types import SimpleNamespace
from typing import Any, Callable

import numpy as np

from backend.api import science_adapter

CORE_FUNCTIONS: dict[str, tuple[str, str, str]] = {
    "compute_cross_prior": (
        "backend.api.science_adapter", "compute_cross_prior",
        "(doy: int[n], obs: float[n,3] NaN=missing) -> float[366]"),
    "kalman_rts_smooth": (
        "backend.api.science_adapter", "kalman_rts_smooth",
        "(obs: float[n,3], u_spatial: float[n] NaN allowed, context: KalmanInput) "
        "-> object with .x_smooth float[n] and .p_smooth float[n] >= 0"),
    "fit_von_mises_year": (
        "backend.api.science_adapter", "fit_von_mises_year",
        "(doy: int[m], weights: float[m]) -> (mu_doy, kappa, width_days)"),
    "phenology_trend": (
        "backend.api.science_adapter", "phenology_trend",
        "(years: int[k], peaks: float[k]) -> (slope_days_per_decade, mann_kendall_p)"),
    "chow_test": (
        "backend.api.science_adapter", "chow_test",
        "(values: float[n], years: int[n], doy: int[n]) -> (F, p)"),
    "wasserstein_w1_normalized": (
        "backend.api.science_adapter", "wasserstein_w1_normalized",
        "(values: float[n], years: int[n]) -> float"),
    "descriptive_r2": (
        "backend.api.science_adapter", "descriptive_r2",
        "(x: float[n], y: float[n]) -> float | None"),
    "run_chaos_monkey_simulation": (
        "backend.api.science_adapter", "run_chaos_monkey_simulation",
        "(daily: dict[str, ndarray], target_year, drop_fraction, simulate_dual_blackout, random_seed) "
        "-> dict with ChaosMonkeyResponse fields except data_source"),
}
# Positional arity of each agreed signature above.
EXPECTED_ARITY = {"compute_cross_prior": 2, "kalman_rts_smooth": 3, "fit_von_mises_year": 2, "phenology_trend": 2,
                  "chow_test": 3, "wasserstein_w1_normalized": 2, "descriptive_r2": 2,
                  "run_chaos_monkey_simulation": 5}
CHAOS_KEYS = frozenset({"dropped_days_count", "dropped_dates", "dates", "true_harmonized_fre", "corrupted_naive_fre",
                        "historical_cross_guard_fre", "kalman_reconstructed_fre", "reconstructed_ci_lower",
                        "reconstructed_ci_upper", "naive_rmse", "kalman_rmse", "seasonal_energy_recovered_pct"})
CHAOS_DAILY_LISTS = ("true_harmonized_fre", "corrupted_naive_fre", "historical_cross_guard_fre",
                     "kalman_reconstructed_fre", "reconstructed_ci_lower", "reconstructed_ci_upper")


class CoreMissingError(RuntimeError):
    """A required backend.core function is not available."""


class CoreContractViolation(RuntimeError):
    """A backend.core function returned something that breaks the agreed output contract."""


def qualified_name(public_name: str) -> str:
    module_name, attr, _ = CORE_FUNCTIONS[public_name]
    return f"{module_name}.{attr}"


# ---------------------------------------------------------------- resolution

def _resolve(public_name: str) -> Callable:
    module_name, attr, signature = CORE_FUNCTIONS[public_name]
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise CoreMissingError(
            f"Missing module {module_name} (needed for {attr}{signature}). "
            "Owner: Adam (backend/core). See CAMBIOS.md.") from exc
    try:
        fn = getattr(module, attr)
        if module_name == "backend.api.science_adapter":
            science_adapter.dependency(public_name)
        return fn
    except AttributeError as exc:
        raise CoreMissingError(
            f"Missing {module_name}.{attr} — expected signature {signature}. "
            "Owner: Adam (backend/core). See CAMBIOS.md.") from exc


def _available(public_name: str) -> bool:
    """True when the core function exists and is callable (no exception swallowing)."""
    module_name, attr, _ = CORE_FUNCTIONS[public_name]
    if importlib.util.find_spec(module_name) is None:
        return False
    available = callable(getattr(importlib.import_module(module_name), attr, None))
    if available and module_name == "backend.api.science_adapter":
        dep_module, dep_attr = science_adapter.DEPENDENCIES[public_name]
        return callable(getattr(importlib.import_module(dep_module), dep_attr, None))
    return available


def require(public_name: str) -> Callable:
    """Return the core function or raise CoreMissingError (looked up at call time)."""
    return _resolve(public_name)


def core_status() -> dict[str, bool]:
    return {name: _available(name) for name in CORE_FUNCTIONS}


def signature_issues() -> dict[str, str | None]:
    """None when the positional arity matches the agreed signature, otherwise a description."""
    issues: dict[str, str | None] = {}
    for name, expected in EXPECTED_ARITY.items():
        if not _available(name):
            issues[name] = f"{qualified_name(name)} is missing"
            continue
        fn = _resolve(name)
        if inspect.isbuiltin(fn):
            issues[name] = f"{qualified_name(name)} signature cannot be introspected"
            continue
        params = list(inspect.signature(fn).parameters.values())
        positional = [p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        required = [p for p in positional if p.default is p.empty]
        varargs = any(p.kind == p.VAR_POSITIONAL for p in params)
        required_kwonly = [p.name for p in params if p.kind == p.KEYWORD_ONLY and p.default is p.empty]
        if len(required) > expected or (len(positional) < expected and not varargs) or required_kwonly:
            issues[name] = (f"{qualified_name(name)} accepts {len(required)}..{len(positional)} positional "
                            f"arguments{' (+*args)' if varargs else ''}"
                            f"{', requires keyword-only ' + str(required_kwonly) if required_kwonly else ''}; "
                            f"expected {expected}: {CORE_FUNCTIONS[name][2]}")
        else:
            issues[name] = None
    return issues


# ---------------------------------------------------------------- output validation

def _violation(name: str, what: str) -> CoreContractViolation:
    return CoreContractViolation(f"{qualified_name(name)} violated the API contract: {what}")


def _float(name: str, value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise _violation(name, f"{label} is not a number ({value!r})") from exc
    if not np.isfinite(result):
        raise _violation(name, f"{label} is not finite ({result})")
    return result


def _array(name: str, value: Any, shape: tuple[int, ...], label: str) -> np.ndarray:
    try:
        arr = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise _violation(name, f"{label} is not a numeric array") from exc
    if arr.shape != shape:
        raise _violation(name, f"{label} has shape {arr.shape}, expected {shape}")
    if not np.all(np.isfinite(arr)):
        raise _violation(name, f"{label} contains NaN or Inf")
    return arr


def _tuple(name: str, value: Any, size: int) -> tuple:
    try:
        items = tuple(value)
    except TypeError as exc:
        raise _violation(name, f"expected a tuple of {size} values, got {type(value).__name__}") from exc
    if len(items) != size:
        raise _violation(name, f"expected a tuple of {size} values, got {len(items)}")
    return items


def _check_prior(name, out, args):
    return _array(name, out, (366,), "prior")


def _check_kalman(name, out, args):
    n = len(args[0])
    if not (hasattr(out, "x_smooth") and hasattr(out, "p_smooth")):
        raise _violation(name, "result lacks .x_smooth and/or .p_smooth")
    x = _array(name, out.x_smooth, (n,), "x_smooth")
    p = _array(name, out.p_smooth, (n,), "p_smooth")
    if np.any(p < 0):
        raise _violation(name, "p_smooth contains negative variances")
    return SimpleNamespace(x_smooth=x, p_smooth=p)


def _check_von_mises(name, out, args):
    mu, kappa, width = (_float(name, v, label) for v, label in zip(_tuple(name, out, 3), ("mu", "kappa", "width")))
    if kappa < 0:
        raise _violation(name, f"kappa must be >= 0 (got {kappa})")
    if width <= 0:
        raise _violation(name, f"width must be > 0 (got {width})")
    return mu, kappa, width


def _check_probability_pair(first_label, first_min):
    def check(name, out, args):
        first, p = (_float(name, v, label) for v, label in zip(_tuple(name, out, 2), (first_label, "p")))
        if first_min is not None and first < first_min:
            raise _violation(name, f"{first_label} must be >= {first_min} (got {first})")
        if not 0.0 <= p <= 1.0:
            raise _violation(name, f"p must be within [0, 1] (got {p})")
        return first, p
    return check


def _check_w1(name, out, args):
    value = _float(name, out, "W1")
    if value < 0:
        raise _violation(name, f"W1 must be >= 0 (got {value})")
    return value


def _check_r2(name, out, args):
    if out is None:
        return None
    value = _float(name, out, "R²")
    if not 0.0 <= value <= 1.0:
        raise _violation(name, f"R² must be within [0, 1] or None (got {value})")
    return value


def _check_chaos(name, out, args):
    if not isinstance(out, dict):
        raise _violation(name, f"expected a dict, got {type(out).__name__}")
    keys = set(out)
    if keys != CHAOS_KEYS:
        raise _violation(name, f"keys differ from the contract: missing {sorted(CHAOS_KEYS - keys)}, "
                               f"unexpected {sorted(keys - CHAOS_KEYS)}")
    n = len(out["dates"])
    ragged = [k for k in CHAOS_DAILY_LISTS if len(out[k]) != n]
    if ragged:
        raise _violation(name, f"lists {ragged} do not have the same length as dates ({n})")
    return out


_VALIDATORS = {
    "compute_cross_prior": _check_prior,
    "kalman_rts_smooth": _check_kalman,
    "fit_von_mises_year": _check_von_mises,
    "phenology_trend": _check_probability_pair("slope", None),
    "chow_test": _check_probability_pair("F", 0.0),
    "wasserstein_w1_normalized": _check_w1,
    "descriptive_r2": _check_r2,
    "run_chaos_monkey_simulation": _check_chaos,
}


def call(public_name: str, *args) -> tuple[Any, float]:
    """Resolve, run and validate a core function. Returns (normalized output, elapsed ms)."""
    fn = require(public_name)
    t0 = perf_counter()
    out = fn(*args)
    elapsed_ms = (perf_counter() - t0) * 1000
    return _VALIDATORS[public_name](public_name, out, args), elapsed_ms
