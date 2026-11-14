"""Replay satellite blackouts against the recorded outcomes in the local FIRMS cube."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from backend.core.risk_predictor import INDUSTRIAL_EXCURSION, predict_risk, with_observation_gap
from backend.db import duckdb_engine, queries

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ("wildfire_prob_pct", "accident_prob_pct", "combined_risk_pct")
GAPS = (1, 3, 7)
HIDDEN_WINDOWS = (1, 7, 14)


def score(rows):
    forecast, baseline, observed = np.asarray(rows).T
    return {
        "windows": len(rows),
        "events": int(observed.sum()),
        "brier": float(np.mean((forecast - observed) ** 2)),
        "baseline_brier": float(np.mean((baseline - observed) ** 2)),
    }


def compare_window(scores, label, daily, forecast, fit_end, start, days):
    threshold = forecast["vegetation_event_threshold_mw"]
    fire = daily["vegetation_frp"] >= threshold
    anomaly = daily["industrial_z"] >= INDUSTRIAL_EXCURSION
    valid = (daily["gap"] == 0) & np.isfinite(daily["vegetation_frp"])
    window = slice(start, start + days)
    if not valid[window].all():
        return
    horizon = next(item for item in forecast["horizons"] if item["days"] == days)
    known = np.lib.stride_tricks.sliding_window_view(valid[:fit_end], days).all(axis=1)
    for target, event in zip(TARGETS, (fire, anomaly, fire | anomaly)):
        history = np.lib.stride_tricks.sliding_window_view(event[:fit_end], days)
        baseline = (history[known].any(axis=1).sum() + .5) / (known.sum() + 1)
        scores.setdefault(f"{label}_{target}", []).append((
            horizon[target] / 100, baseline, int(event[window].any()),
        ))


def replay(daily, start_year, end_year):
    epoch = daily["epoch_day"]
    dates = queries.EPOCH + epoch.astype("timedelta64[D]")
    months = dates.astype("datetime64[M]")
    years = dates.astype("datetime64[Y]").astype(int) + 1970
    if not len(epoch):
        return {}
    # Select one origin per month without looking at thermal outcomes.
    origins = np.flatnonzero(np.r_[False, months[1:] != months[:-1]]) + 14
    origins = origins[(origins + 14 < len(epoch)) & (origins >= 365)]
    origins = origins[(years[origins] >= start_year) & (years[origins] <= end_year)]
    scores = {}
    for origin in origins:
        visible = {key: values[:origin + 1] for key, values in daily.items()}
        forecast = predict_risk(visible)
        # Withhold the entire forecast window and compare with its observations.
        for days in HIDDEN_WINDOWS:
            compare_window(scores, f"hidden_window_{days}d", daily, forecast, origin + 1, origin + 1, days)
        for gap in GAPS:
            fit_end = origin + 1 - gap
            visible = {key: values[:fit_end] for key, values in daily.items()}
            forecast = predict_risk(with_observation_gap(visible, int(epoch[origin])))
            for days in HIDDEN_WINDOWS:
                compare_window(scores, f"gap_{gap}d_horizon_{days}d", daily, forecast, fit_end, origin + 1, days)
    return {key: score(rows) for key, rows in sorted(scores.items())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=2024)
    parser.add_argument("--end-year", type=int, default=2025)
    args = parser.parse_args()
    if not 2002 <= args.start_year <= args.end_year <= 2026:
        parser.error("Validation years must be ordered and lie in 2002–2026.")
    regions = json.loads((ROOT / "data/regions.json").read_text(encoding="utf-8"))
    out = {"data_source": duckdb_engine.data_source(), "years": [args.start_year, args.end_year]}
    cutoff = int((np.datetime64(f"{args.end_year + 1}-01-15") - queries.EPOCH).astype(int))
    for region in ("chilecito_la_rioja", "iberia_med"):
        w, s, e, n = regions[region]["bounds"]
        r4, r7, _ = queries.get_hierarchical_h3_filter([[[w,s],[e,s],[e,n],[w,n],[w,s]]])
        daily = queries.fetch_risk_daily(r4, r7, 2001, min(2026, args.end_year + 1), cutoff)
        if not daily:
            raise RuntimeError(f"No observations available for {region}")
        out[region] = replay(daily, args.start_year, args.end_year)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
