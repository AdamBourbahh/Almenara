"""Frozen contract tests: validation of Adam's core outputs, signatures, conformance tool, timing headers.
DO NOT EDIT. No latency thresholds are asserted here."""

from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend import check_core
from backend.api import cache as cache_mod
from backend.api import core_contract
from backend.api.main import app

CHILECITO = {'type': 'Polygon', 'coordinates': [[[-69.5, -31], [-65.5, -31], [-65.5, -27.5], [-69.5, -27.5], [-69.5, -31]]]}  # ASSUMPTION (SPECS.md §5.3 preset)
STAGES = {"h3", "db", "core", "build", "validate", "serialize"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean_cache():
    cache_mod.ANALYZE_CACHE.clear()
    cache_mod.GEOMETRY_CACHE.clear()
    yield


def use_core(monkeypatch, impl):
    monkeypatch.setattr(core_contract, "_resolve", lambda name: impl[name])
    monkeypatch.setattr(core_contract, "_available", lambda name: name in impl)


def sample_args(n=40):
    doy = np.arange(1, n + 1)
    obs = np.full((n, 3), 5.0)
    years = np.r_[np.full(n // 2, 2010), np.full(n - n // 2, 2014)]
    daily = {"year": np.full(n, 2022), "epoch_day": np.arange(8036, 8036 + n)}
    return {
        "compute_cross_prior": (doy, obs),
        "kalman_rts_smooth": (obs, np.full(n, 5.0), np.full(n, 5.0)),
        "fit_von_mises_year": (doy, np.ones(n)),
        "phenology_trend": (np.arange(2001, 2011), np.full(10, 200.0)),
        "chow_test": (np.ones(n), years, doy),
        "wasserstein_w1_normalized": (np.ones(n), years),
        "descriptive_r2": (np.arange(n, dtype=float), np.arange(n, dtype=float)),
        "run_chaos_monkey_simulation": (daily, 2022, 0.25, True, 42),
    }


def test_fake_core_outputs_pass_validation(fake_core):
    for name, args in sample_args().items():
        value, ms = core_contract.call(name, *args)
        assert ms >= 0.0, name
        assert value is not None or name == "descriptive_r2"


def _chaos_ok(*_):
    return dict(dropped_days_count=0, dropped_dates=[], dates=["2022-01-01"], true_harmonized_fre=[1.0],
                corrupted_naive_fre=[1.0], historical_cross_guard_fre=[1.0], kalman_reconstructed_fre=[1.0],
                reconstructed_ci_lower=[1.0], reconstructed_ci_upper=[1.0], naive_rmse=0.0, kalman_rmse=0.0,
                seasonal_energy_recovered_pct=100.0)


def _chaos_missing_key(*a):
    out = _chaos_ok(*a)
    del out["kalman_rmse"]
    return out


def _chaos_ragged(*a):
    out = _chaos_ok(*a)
    out["kalman_reconstructed_fre"] = [1.0, 2.0]
    return out


BROKEN = [
    ("compute_cross_prior", lambda doy, obs: np.zeros(365)),
    ("kalman_rts_smooth", lambda obs, u, p: SimpleNamespace(x_smooth=np.full(len(obs), np.nan), p_smooth=np.ones(len(obs)))),
    ("kalman_rts_smooth", lambda obs, u, p: SimpleNamespace(x_smooth=np.ones(len(obs)), p_smooth=-np.ones(len(obs)))),
    ("kalman_rts_smooth", lambda obs, u, p: SimpleNamespace(x_smooth=np.ones(len(obs) - 1), p_smooth=np.ones(len(obs) - 1))),
    ("fit_von_mises_year", lambda doy, w: (1.0, 0.0)),
    ("chow_test", lambda v, y, d: (1.0, 1.5)),
    ("wasserstein_w1_normalized", lambda v, y: -0.1),
    ("descriptive_r2", lambda x, y: 2.0),
    ("phenology_trend", lambda y, p: (float("nan"), 0.5)),
    ("run_chaos_monkey_simulation", _chaos_missing_key),
    ("run_chaos_monkey_simulation", _chaos_ragged),
]


@pytest.mark.parametrize("name,impl", BROKEN)
def test_broken_outputs_raise_contract_violation(fake_core, monkeypatch, name, impl):
    use_core(monkeypatch, {**fake_core, name: impl})
    module, attr, _ = core_contract.CORE_FUNCTIONS[name]
    with pytest.raises(core_contract.CoreContractViolation, match=f"{module}.{attr}"):
        core_contract.call(name, *sample_args()[name])


def test_api_returns_500_naming_the_violating_function(client, fake_core, monkeypatch):
    bad = lambda obs, u, p: SimpleNamespace(x_smooth=np.ones(len(obs)), p_smooth=-np.ones(len(obs)))  # noqa: E731
    use_core(monkeypatch, {**fake_core, "kalman_rts_smooth": bad})
    r = client.post("/api/analyze", json={"aoi": CHILECITO})
    assert r.status_code == 500 and "kalman_rts_smooth" in r.text


def test_signature_issues_detect_wrong_arity(fake_core, monkeypatch):
    use_core(monkeypatch, {**fake_core, "chow_test": lambda values, years: (0.0, 1.0)})
    issues = core_contract.signature_issues()
    assert set(issues) == set(core_contract.CORE_FUNCTIONS)
    assert issues["chow_test"] and "chow_test" in issues["chow_test"]
    assert all(v is None for k, v in issues.items() if k != "chow_test")


def test_health_reports_core_signatures(client):
    body = client.get("/api/health").json()
    assert set(body["core_signatures"]) == set(core_contract.CORE_FUNCTIONS)


def _stages(header):
    return {part.split(";")[0].strip() for part in header.split(",") if part.strip()}


def test_server_timing_header_and_cached_json(client, fake_core):
    cold = client.post("/api/analyze", json={"aoi": CHILECITO})
    hit = client.post("/api/analyze", json={"aoi": CHILECITO})
    assert cold.status_code == hit.status_code == 200
    assert STAGES <= _stages(cold.headers["server-timing"])
    assert "cache" in _stages(hit.headers["server-timing"])
    a, b = cold.json(), hit.json()
    assert isinstance(b["execution_time_ms"], float) and b["execution_time_ms"] > 0
    a.pop("execution_time_ms")
    b.pop("execution_time_ms")
    assert a == b


def test_gzip_level_one():
    gz = next(m for m in app.user_middleware if m.cls.__name__ == "GZipMiddleware")
    opts = getattr(gz, "kwargs", None) or getattr(gz, "options", {})
    assert opts.get("compresslevel") == 1 and opts.get("minimum_size") == 1000


def test_check_core_exit_codes(fake_core, monkeypatch):
    use_core(monkeypatch, dict(fake_core))
    assert check_core.main([]) == 0
    missing = {k: v for k, v in fake_core.items() if k != "chow_test"}
    use_core(monkeypatch, missing)
    assert check_core.main([]) == 2
    use_core(monkeypatch, {**fake_core, "wasserstein_w1_normalized": lambda v, y: -1.0})
    assert check_core.main([]) == 1
