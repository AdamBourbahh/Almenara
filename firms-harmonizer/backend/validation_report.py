"""Validation report: prints measured latencies and scientific diagnostics exactly as they come out.

This is NOT a test: nothing is asserted and no threshold changes the exit code except a missing core.
Usage:  python -m backend.validation_report [--synthetic]
Exit codes: 0 = report complete; otherwise the backend.check_core exit code (1 = contract violation,
2 = missing core functions). Latencies are always shown first.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PRESETS = {  # SPECS.md §5.3 bounds (west, south, east, north) = types.ts PRESET_REGIONS
    "cerrado_brazil": (-57.2, -17.8, -55.2, -16.0),
    "california_usa": (-121.2, 38.0, -119.5, 40.2),
    "iberia_med": (-6.5, 37.2, -3.2, 39.8),
    "niger_delta_flaring": (5.6, 4.6, 7.2, 5.8),
}
TARGET_QUERY_MS = 12.0
TARGET_ANALYZE_MS = 250.0


def rectangle(west: float, south: float, east: float, north: float) -> list:
    return [[[west, south], [east, south], [east, north], [west, north], [west, south]]]


def timed(fn, repeats: int = 9) -> tuple[float, float]:
    """(first call ms, median of the following `repeats` calls ms)."""
    t0 = perf_counter()
    fn()
    first = (perf_counter() - t0) * 1000
    rest = []
    for _ in range(repeats):
        t0 = perf_counter()
        fn()
        rest.append((perf_counter() - t0) * 1000)
    return first, statistics.median(rest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", action="store_true", help="set USE_SYNTHETIC_CUBE=1")
    args = parser.parse_args()
    if args.synthetic:
        os.environ["USE_SYNTHETIC_CUBE"] = "1"

    from fastapi.testclient import TestClient

    from backend import check_core
    from backend.api.cache import ANALYZE_CACHE, GEOMETRY_CACHE
    from backend.api.main import app
    from backend.db import duckdb_engine, queries

    duckdb_engine.init_engine()
    print(f"Cube: {duckdb_engine.cube_path()}  data_source={duckdb_engine.data_source()}  "
          f"rows={duckdb_engine.get_row_count()}  missing_columns={duckdb_engine.missing_columns()}")

    print("\n== Latency (first call | median of next 9) ==")
    print(f"   reference targets: query <{TARGET_QUERY_MS} ms, analyze <{TARGET_ANALYZE_MS} ms (not gates)")
    for name, bounds in PRESETS.items():
        coords = rectangle(*bounds)
        f_first, f_med = timed(lambda: queries.get_hierarchical_h3_filter(coords))
        r4, r7, _ = queries.get_hierarchical_h3_filter(coords)

        def daily_query():
            with duckdb_engine.get_db_cursor() as cur:
                queries.query_daily_rows(cur, r4, r7, 2001, 2026, True)

        q_first, q_med = timed(daily_query)
        a_first, a_med = timed(lambda: queries.fetch_aoi_aggregated_data(r4, r7, 2001, 2026, True))
        print(f"{name:22s} h3 filter {f_first:7.2f} | {f_med:7.2f}   query_daily_rows {q_first:7.2f} | "
              f"{q_med:7.2f}   fetch_aoi_aggregated_data {a_first:7.2f} | {a_med:7.2f}   "
              f"(R7={len(r7)}, R4={len(r4)})")

    print("\n== backend.core conformance (python -m backend.check_core) ==")
    conformance = check_core.main([])
    if conformance != 0:
        print("\nScientific diagnostics need a conforming backend/core (signatures and output contract in "
              "CAMBIOS.md).")
        return conformance

    print("\n== Scientific diagnostics (printed as measured; real core) ==")
    with TestClient(app) as client:
        for name, bounds in PRESETS.items():
            body = {"aoi": {"type": "Polygon", "coordinates": rectangle(*bounds)}}
            ANALYZE_CACHE.clear()
            GEOMETRY_CACHE.clear()
            t0 = perf_counter()
            r = client.post("/api/analyze", json=body)
            cold = (perf_counter() - t0) * 1000
            t0 = perf_counter()
            r_hit = client.post("/api/analyze", json=body)
            hit = (perf_counter() - t0) * 1000
            if r.status_code != 200:
                print(f"{name}: analyze HTTP {r.status_code} {r.text[:300]}")
                continue
            data = r.json()
            a = data["audit_metrics"]
            print(f"\n[{name}] data_source={data['data_source']} cells={data['total_h3_cells']} "
                  f"execution_time_ms={data['execution_time_ms']:.1f} wall cold={cold:.1f} ms, cache hit={hit:.1f} ms")
            print(f"   Server-Timing cold: {r.headers.get('server-timing')}")
            print(f"   Server-Timing hit:  {r_hit.headers.get('server-timing')}")
            if a is None:
                print("   no data in AOI (audit_metrics is null)")
                continue
            for k in ("chow_test_f_stat_raw", "chow_test_p_val_raw", "chow_test_f_stat_harm",
                      "chow_test_p_val_harm", "wasserstein_w1_raw", "wasserstein_w1_harm",
                      "burned_area_r2_raw", "burned_area_r2_harm", "phenology_shift_days_per_decade",
                      "mann_kendall_p_value", "industrial_false_positives_removed"):
                print(f"   {k:34s} {a[k]}")
            if a["wasserstein_w1_raw"]:
                print(f"   {'w1_reduction_pct':34s} {100 * (1 - a['wasserstein_w1_harm'] / a['wasserstein_w1_raw'])}")
            print(f"   verdict: {a['executive_verdict_en']}")
            c = client.post("/api/chaos-monkey", json=body)
            if c.status_code == 200:
                cm = c.json()
                print(f"   chaos: recovered={cm['seasonal_energy_recovered_pct']} naive_rmse={cm['naive_rmse']} "
                      f"kalman_rmse={cm['kalman_rmse']} dropped={cm['dropped_days_count']}")
            else:
                print(f"   chaos: HTTP {c.status_code} {c.text[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
