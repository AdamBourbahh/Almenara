"""Benchmark regional Parquet queries and report project audit targets."""

import argparse
from importlib import import_module
import json
from pathlib import Path
from time import perf_counter

import duckdb
import h3
import numpy as np
import pyarrow.parquet as pq
from scipy.stats import wasserstein_distance

bootstrap = import_module("00_bootstrap_synthetic_cube")
ingest = import_module("01_ingest_firms")
from backend.core.auditor_stats import compute_chow_structural_break_test  # noqa: E402  (path set by 01)
from backend.core.chaos_monkey import run_chaos_monkey_simulation  # noqa: E402

ROOT = ingest.ROOT
EPOCH = np.datetime64("1970-01-01")
CHANNELS = ("obs_terra_fre", "obs_aqua_fre", "obs_viirs_fre")
ENERGY = """coalesce((coalesce(obs_terra_fre, 0) + coalesce(obs_aqua_fre, 0) + coalesce(obs_viirs_fre, 0))
    / nullif((obs_terra_fre IS NOT NULL)::INT + (obs_aqua_fre IS NOT NULL)::INT
    + (obs_viirs_fre IS NOT NULL)::INT, 0), 0)"""
MODIS_SEEN = "(obs_terra_fre IS NOT NULL OR obs_aqua_fre IS NOT NULL)"
INDUSTRIAL_THRESHOLD = 0.75  # same exclusion as the API (backend/db/queries.py)
P95_GATE_MS = 150.0  # release gate; the original <15 ms target is descoped (Implementation_backend_plan.md)


def reference_daily(con, path, parents):
    """Synchronized daily record on MODIS (Terra/Aqua): (epoch_day, fire cell-days, harmonized FRE, spreading).

    MODIS is the only instrument family observing every year 2000-2026; VIIRS joined in 2012 and its
    constellation grew in 2018 (NOAA-20) and 2023 (NOAA-21), each step revealing more small fires. Counting
    only MODIS-detected cell-days keeps the fire count on one detection capability in every year, without
    estimation; VIIRS still contributes its EQM-harmonized value to the mean on co-observed cell-days.
    A cell-day is spreading when an H3 R7 neighbour was MODIS-detected on the previous day (VIIRS-only
    neighbours are ignored so the spread signal is synchronized too).
    """
    rows = con.execute(f"""SELECT h3_r7, epoch_day, {ENERGY}
        FROM read_parquet(?) SEMI JOIN region_cells USING (h3_r7)
        WHERE h3_r4 IN ({parents}) AND {MODIS_SEEN} AND industrial_prob < {INDUSTRIAL_THRESHOLD}""",
        [str(path)]).fetchall()
    seen = {(cell, day) for cell, day, _ in rows}
    neighbours, daily = {}, {}
    for cell, day, energy in rows:
        if cell not in neighbours:
            neighbours[cell] = [int(n, 16) for n in h3.grid_disk(format(cell, "x"), 1) if int(n, 16) != cell]
        count, total, spreading = daily.get(day, (0, 0.0, 0))
        spreads = any((neighbour, day - 1) in seen for neighbour in neighbours[cell])
        daily[day] = (count + 1, total + energy, spreading + spreads)
    return [(day, *daily[day]) for day in sorted(daily)]


def annual_predictors(fire_count, energy, spreading, years, year):
    """Burned area ~ fire extent (cell-days) + fuel consumed (harmonized FRE) + spreading fire cell-days."""
    selected = years == year
    return [fire_count[selected].sum(), energy[selected].sum(), spreading[selected].sum()]


def _design(predictors):
    predictors = np.asarray(predictors, dtype=float)
    return np.column_stack((np.ones(len(predictors)), predictors.reshape(len(predictors), -1)))


def cross_validated_r2(predictors, area):
    """Leave-one-year-out R2 of the linear model area ~ predictors (one column or several)."""
    area = np.asarray(area, dtype=float)
    if len(area) < 6 or np.ptp(area) == 0:
        return None
    design = _design(predictors)
    predicted = np.empty_like(area)
    for index in range(len(area)):
        train = np.arange(len(area)) != index
        predicted[index] = design[index] @ np.linalg.lstsq(design[train], area[train], rcond=None)[0]
    return float(1 - np.sum((area - predicted)**2) / np.sum((area - area.mean())**2))


def in_sample_r2(predictors, area):
    """SPECS §3.7(3) coefficient of determination of the fitted linear model (diagnostic beside the CV gate)."""
    area = np.asarray(area, dtype=float)
    design = _design(predictors)
    if len(area) < 6 or np.ptp(area) == 0 or np.all(np.ptp(design[:, 1:], axis=0) == 0):
        return None
    residual = area - design @ np.linalg.lstsq(design, area, rcond=None)[0]
    return float(1 - np.sum(residual**2) / np.sum((area - area.mean())**2))


def complete_years(coverage):
    """Calendar years lying entirely inside the declared coverage intervals."""
    years = set()
    for start, end in coverage:
        first = int(start[:4]) + (start[5:] != "01-01")
        last = int(end[:4]) - (end[5:] != "12-31")
        years.update(range(first, last + 1))
    return sorted(years)


def chow_p(values, years, break_year=2012):
    """SPECS §3.7(1) via the core: Chow test on annual means of the daily series; None if unsupported."""
    unique = np.unique(years)
    if np.count_nonzero(unique < break_year) < 2 or np.count_nonzero(unique >= break_year) < 2 or len(unique) <= 4:
        return None
    annual = np.array([values[years == year].mean() for year in unique])
    return float(compute_chow_structural_break_test(unique, annual, break_year)[1])


def dense_daily(rows):
    """API-equivalent dense daily inputs from (epoch_day, terra, aqua, viirs, lag, cloud) per-day AOI means."""
    data = np.array([[np.nan if v is None else v for v in row] for row in rows], dtype=float)
    first = (EPOCH + np.timedelta64(int(data[:, 0].min()), "D")).astype("datetime64[Y]").astype("datetime64[D]")
    last = ((EPOCH + np.timedelta64(int(data[:, 0].max()), "D")).astype("datetime64[Y]")
            + np.timedelta64(1, "Y")).astype("datetime64[D]") - np.timedelta64(1, "D")
    epoch_day = np.arange((first - EPOCH).astype(int), (last - EPOCH).astype(int) + 1)
    dates = EPOCH + epoch_day.astype("timedelta64[D]")
    daily = {"epoch_day": epoch_day, "year": dates.astype("datetime64[Y]").astype(int) + 1970,
             "doy": (dates - dates.astype("datetime64[Y]")).astype(int) + 1}
    index = data[:, 0].astype(int) - epoch_day[0]
    for column, name in enumerate(CHANNELS + ("neighbor_fre_lag1", "cloud_cover_pct"), start=1):
        daily[name] = np.full(len(epoch_day), np.nan)
        daily[name][index] = data[:, column]
    return daily


def chaos_recovery(daily, target_year=2022):
    """SPECS §3.4(6) via the core Chaos Monkey (25% VIIRS drop, 10-day dual blackout, seed 42)."""
    selected = daily["year"] == target_year
    obs = np.column_stack([daily[name] for name in CHANNELS])
    if not np.isfinite(obs[selected]).any():
        return None
    dates = EPOCH + daily["epoch_day"][selected].astype("timedelta64[D]")
    result = run_chaos_monkey_simulation(
        [str(date) for date in dates], daily["doy"][selected], obs[selected],
        daily["neighbor_fre_lag1"][selected], daily["cloud_cover_pct"][selected],
        drop_fraction=0.25, simulate_dual_blackout=True, random_seed=42,
        full_doy_history=daily["doy"][~selected], full_y_obs_history=obs[~selected])
    return float(result.seasonal_energy_recovered_pct)


def run_benchmark(cube_path="data/processed/fire_cube.parquet"):
    """Use exactly the API's series, coverage policy and scientific verdicts."""
    import os
    path = (ROOT / cube_path).resolve()
    if not path.is_file():
        print(f"Cube unavailable at {path}. Run scripts/run_pipeline.py etl.")
        return False
    os.environ['FIRE_CUBE_PATH'] = str(path)
    report = import_module('12_audit_report').generate()
    for region in report['regions']:
        print(region['region'], region['audit']['executive_verdict_en'])
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cube", default="data/processed/fire_cube.parquet")
    args = parser.parse_args()
    raise SystemExit(0 if run_benchmark(args.cube) else 1)
