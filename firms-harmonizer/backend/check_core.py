"""Conformance runner for Adam's backend/core against the API contract (see CAMBIOS.md).

Usage:  python -m backend.check_core [--synthetic]
Runs every agreed core function on deterministic inputs built from the cube (Cerrado preset, 2001-2026,
n=9496 days), validates each output with backend.api.core_contract.call and prints PASS / FAIL / MISSING,
signature problems and the time per call.
Exit codes: 0 = all pass, 1 = at least one contract violation, crash or signature problem,
            2 = at least one function is missing.
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CERRADO = [[[-57.2, -17.8], [-55.2, -17.8], [-55.2, -16.0], [-57.2, -16.0], [-57.2, -17.8]]]  # SPECS.md §5.3 preset
TARGET_YEAR = 2022


def build_inputs() -> dict[str, tuple]:
    """Deterministic positional arguments for every core function (inputs only, never used as results)."""
    from backend.db import duckdb_engine, queries

    duckdb_engine.init_engine()
    r4, r7, _ = queries.get_hierarchical_h3_filter(CERRADO)
    daily = queries.fetch_aoi_aggregated_data(r4, r7, 2001, 2026, True).daily
    if len(daily["epoch_day"]) == 0:
        raise RuntimeError("The cube has no data for the Cerrado preset; cannot build conformance inputs.")
    obs = np.column_stack([daily[c] for c in queries.OBS_COLUMNS])
    count = np.isfinite(obs).sum(axis=1)
    naive = np.where(count > 0, np.nansum(obs, axis=1) / np.maximum(count, 1), 0.0)
    years, doy = daily["year"], daily["doy"]
    in_year = years == TARGET_YEAR
    burned = daily["burned_area_ha_mcd64"]
    ok = np.isfinite(burned)
    return {
        "compute_cross_prior": (doy, obs),
        "kalman_rts_smooth": (obs, daily["neighbor_fre_lag1"], naive),
        "fit_von_mises_year": (doy[in_year], naive[in_year]),
        "phenology_trend": (np.arange(2001, 2027), np.linspace(250.0, 268.75, 26)),
        "chow_test": (naive, years, doy),
        "wasserstein_w1_normalized": (naive, years),
        "descriptive_r2": (naive[ok], burned[ok]),
        "run_chaos_monkey_simulation": (daily, TARGET_YEAR, 0.25, True, 42),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--synthetic", action="store_true", help="set USE_SYNTHETIC_CUBE=1")
    args = parser.parse_args(argv)
    if args.synthetic:
        os.environ["USE_SYNTHETIC_CUBE"] = "1"

    from backend.api import core_contract

    inputs = build_inputs()
    signatures = core_contract.signature_issues()
    missing = failed = 0
    print(f"{'function':30s} {'status':8s} {'ms':>9s}  detail")
    for name, (_, _, expected) in core_contract.CORE_FUNCTIONS.items():
        if not core_contract._available(name):
            missing += 1
            print(f"{name:30s} {'MISSING':8s} {'':>9s}  {core_contract.qualified_name(name)} expected {expected}")
            continue
        if signatures.get(name):
            failed += 1
            print(f"{name:30s} {'FAIL':8s} {'':>9s}  signature: {signatures[name]}")
            continue
        try:
            _, ms = core_contract.call(name, *inputs[name])
        except core_contract.CoreContractViolation as exc:
            failed += 1
            print(f"{name:30s} {'FAIL':8s} {'':>9s}  {exc}")
            continue
        except Exception as exc:  # a crash inside the core is reported, never hidden
            failed += 1
            last = traceback.format_exception_only(type(exc), exc)[-1].strip()
            print(f"{name:30s} {'FAIL':8s} {'':>9s}  raised {last}")
            continue
        print(f"{name:30s} {'PASS':8s} {ms:9.2f}  n={len(inputs[name][0]) if name != 'run_chaos_monkey_simulation' else len(inputs[name][0]['epoch_day'])}")
    if missing:
        print(f"\n{missing} function(s) missing -> exit 2")
        return 2
    if failed:
        print(f"\n{failed} function(s) failing -> exit 1")
        return 1
    print("\nAll core functions conform to the API contract -> exit 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
