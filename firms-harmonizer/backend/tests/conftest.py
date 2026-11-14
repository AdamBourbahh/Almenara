"""Shared test setup. DO NOT EDIT.

* Opts in to the SYNTHETIC cube (USE_SYNTHETIC_CUBE=1) before the app is imported.
* `fake_core`: a FAKE, shape-only stand-in for Adam's backend/core, used ONLY by contract
  tests. Production code never imports it; its numbers mean nothing scientifically.
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ["USE_SYNTHETIC_CUBE"] = "1"


def _naive(obs):
    obs = np.asarray(obs, dtype=float)
    cnt = np.isfinite(obs).sum(axis=1)
    return np.where(cnt > 0, np.nansum(obs, axis=1) / np.maximum(cnt, 1), 0.0)


def _fake_chaos(daily, target_year, drop_fraction, simulate_dual_blackout, random_seed):
    sel = daily["year"] == target_year
    dates = [str(np.datetime64("2000-01-01") + int(d)) for d in daily["epoch_day"][sel]]
    zeros = [0.0] * len(dates)
    return dict(dropped_days_count=0, dropped_dates=[], dates=dates, true_harmonized_fre=zeros,
                corrupted_naive_fre=zeros, historical_cross_guard_fre=zeros,
                kalman_reconstructed_fre=zeros, reconstructed_ci_lower=zeros,
                reconstructed_ci_upper=zeros, naive_rmse=0.0, kalman_rmse=0.0,
                seasonal_energy_recovered_pct=0.0)


FAKE_CORE = {
    "compute_cross_prior": lambda doy, obs: np.zeros(366),
    "kalman_rts_smooth": lambda obs, u, prior: SimpleNamespace(x_smooth=_naive(obs), p_smooth=np.ones(len(obs))),
    "fit_von_mises_year": lambda doy, w: (1.0, 0.0, 365.25),
    "phenology_trend": lambda years, peaks: (0.0, 1.0),
    "chow_test": lambda values, years, doy: (0.0, 1.0),
    "wasserstein_w1_normalized": lambda values, years: 0.0,
    "descriptive_r2": lambda x, y: 0.0,
    "run_chaos_monkey_simulation": _fake_chaos,
}


@pytest.fixture
def fake_core(monkeypatch):
    from backend.api import core_contract
    assert set(FAKE_CORE) == set(core_contract.CORE_FUNCTIONS)
    monkeypatch.setattr(core_contract, "_resolve", lambda public_name: FAKE_CORE[public_name])
    yield FAKE_CORE
