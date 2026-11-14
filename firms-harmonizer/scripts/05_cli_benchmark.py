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
        full_doy_history=daily["doy"], full_y_obs_history=obs)
    return float(result.seasonal_energy_recovered_pct)


def run_benchmark(cube_path="data/processed/fire_cube.parquet"):
    path = ROOT / cube_path
    if not path.is_file():
        print(f"Cube unavailable at {path}. Run script 04.")
        return False
    parquet = pq.ParquetFile(path)
    synthetic = b"SYNTHETIC" in (parquet.schema_arrow.metadata or {}).get(b"source", b"")
    metadata = parquet.metadata
    compressed = all(metadata.row_group(i).column(j).compression == "ZSTD"
                     for i in range(metadata.num_row_groups) for j in range(metadata.num_columns))
    success = compressed and parquet.schema_arrow.equals(bootstrap.CUBE_SCHEMA, check_metadata=False)
    regions = ingest.load_regions()
    print(f"Project audit targets   P95 < {P95_GATE_MS:.0f} ms   Chow p > .10   R2 > .90   Recovery > 90%")
    print("Chow, W1 and R2 use the synchronized MODIS-reference record. R2: leave-one-year-out, burned area "
          "~ fire cell-days + harmonized FRE + spreading cell-days vs MCD64A1. Recovery: core Chaos Monkey (2022). Fixture metrics are synthetic.")
    print(f"{'Region':23} {'P95 ms':>8} {'Chow p':>8} {'BA Chow':>8} {'W1':>10} {'CV R2':>8} {'Fit R2':>8} "
          f"{'Recov %':>8}")
    with duckdb.connect(config={"threads": 4}) as con:
        all_cells = con.execute("SELECT DISTINCT h3_r4,h3_r7 FROM read_parquet(?)",
                                [str(path)]).fetchall()
        for name, region in regions.items():
            if not synthetic and "coverage" not in region:
                # No declared real coverage means no real data was acquired: not a benchmark subject.
                print(f"{name:23} no coverage declared (skipped)")
                continue
            fixture = bootstrap.REGIONS.get(name) if synthetic else None
            fixture_cells = {int(c, 16) for c in bootstrap.region_cells(*fixture[:2])} if fixture else set()
            cells = [(r4, r7) for r4, r7 in all_cells if r7 in fixture_cells
                     or ingest.region_at(*h3.cell_to_latlng(format(r7, "x")), {name: region}) == name]
            if not cells:
                print(f"{name:23} {'no rows':>8}")
                success = False
                continue
            parents = ",".join(str(item) for item in sorted({r4 for r4, _ in cells}))
            con.execute("CREATE OR REPLACE TEMP TABLE region_cells AS SELECT unnest(?::UBIGINT[]) AS h3_r7",
                        [[r7 for _, r7 in cells]])
            sql = f"""SELECT year, doy,
                sum(coalesce((coalesce(obs_terra_fre, 0) + coalesce(obs_aqua_fre, 0)
                    + coalesce(obs_viirs_fre, 0)) / nullif(
                    (obs_terra_fre IS NOT NULL)::INT + (obs_aqua_fre IS NOT NULL)::INT
                    + (obs_viirs_fre IS NOT NULL)::INT, 0), 0)) AS energy,
                sum(obs_viirs_fre) AS viirs, sum(burned_area_ha_mcd64) AS area
                FROM read_parquet(?) SEMI JOIN region_cells USING (h3_r7) WHERE h3_r4 IN ({parents})
                    AND industrial_prob < {INDUSTRIAL_THRESHOLD}
                GROUP BY year, doy ORDER BY year, doy"""
            rows = con.execute(sql, [str(path)]).fetchall()
            latency = []
            for _ in range(12):
                started = perf_counter()
                con.execute(sql, [str(path)]).fetchall()
                latency.append((perf_counter() - started) * 1000)
            p95 = float(np.percentile(latency, 95))
            years, doy, energy, viirs, area = np.asarray(rows, dtype=float).T
            years, doy = years.astype(int), doy.astype(int)
            # Scientific metrics use the synchronized MODIS-reference record (same instruments every year).
            reference = np.asarray(reference_daily(con, path, parents), dtype=float).reshape(-1, 4)
            energy_years = (EPOCH + reference[:, 0].astype("int64").astype("timedelta64[D]")).astype(
                "datetime64[Y]").astype(int) + 1970
            fire_count, energy, spreading = reference[:, 1], reference[:, 2], reference[:, 3]
            before = energy_years < 2012
            w1 = None
            if min(before.sum(), (~before).sum()) >= 10:
                # Same estimator as the API audit: W1 between eras normalized by the overall mean.
                scale = float(energy.mean())
                w1 = wasserstein_distance(energy[before] / scale, energy[~before] / scale) if scale > 0 else 0.0
            inputs = con.execute(f"""SELECT epoch_day, avg(obs_terra_fre), avg(obs_aqua_fre), avg(obs_viirs_fre),
                avg(neighbor_fre_lag1), avg(cloud_cover_pct)
                FROM read_parquet(?) SEMI JOIN region_cells USING (h3_r7) WHERE h3_r4 IN ({parents})
                    AND industrial_prob < {INDUSTRIAL_THRESHOLD}
                GROUP BY epoch_day ORDER BY epoch_day""", [str(path)]).fetchall()
            daily = dense_daily(inputs)
            # Days without detections carry zero regional energy in the annual means.
            dense_energy = np.zeros(len(daily["epoch_day"]))
            dense_energy[reference[:, 0].astype(int) - int(daily["epoch_day"][0])] = energy
            # Partial first/last years would be padded with zero-fire days; test complete years only.
            covered = complete_years(region["coverage"]) if not synthetic else sorted(set(daily["year"].tolist()))
            in_years = np.isin(daily["year"], covered)
            chow = chow_p(dense_energy[in_years], daily["year"][in_years])
            burned_chow = None
            unique = np.unique(years)
            # Real-region validation requires independent burned-area input.
            # Fixture remnants outside declared coverage cannot supply that input.
            r2 = fit_r2 = None
            if synthetic:
                r2 = cross_validated_r2(
                    np.array([annual_predictors(fire_count, energy, spreading, energy_years, year)
                              for year in unique]),
                    np.array([area[years == year].sum() for year in unique]),
                )
            elif (ROOT / "data/lookup/cell_day_ancillary.parquet").is_file():
                # Only years in which MCD64A1 has every tile-month for this region are comparable.
                metadata = pq.read_schema(ROOT / "data/lookup/cell_day_ancillary.parquet").metadata or {}
                burned_years = set(json.loads(metadata.get(b"complete_years", b"{}")).get(name, []))
                annual = con.execute("""WITH reference AS (
                    SELECT year(acq_date::DATE) AS year, sum(burned_area_ha_mcd64) AS area
                    FROM read_parquet(?) SEMI JOIN region_cells USING (h3_r7)
                    WHERE burned_area_ha_mcd64 IS NOT NULL GROUP BY 1
                ) SELECT year, area FROM reference ORDER BY year""",
                    [str(ROOT / "data/lookup/cell_day_ancillary.parquet")]).fetchall()
                # Compare complete calendar years of declared FIRMS coverage only.
                complete = [(year, observed) for year, observed in annual
                            if year in unique and year in burned_years and year in covered]
                if complete:
                    annual = np.array([annual_predictors(fire_count, energy, spreading, energy_years, year)
                                       for year, _ in complete])
                    annual_area = np.array([observed for _, observed in complete], dtype=float)
                    r2 = cross_validated_r2(annual, annual_area)
                    fit_r2 = in_sample_r2(annual, annual_area)
                    # Control: an independent burned-area break means the fire regime itself changed.
                    burned_chow = float(compute_chow_structural_break_test(
                        np.array([year for year, _ in complete]), annual_area)[1])
            recovery = chaos_recovery(daily)
            values = [f"{v:.3f}" if v is not None else "N/A"
                      for v in (p95, chow, burned_chow, w1, r2, fit_r2, recovery)]
            print(f"{name:23} {values[0]:>8} {values[1]:>8} {values[2]:>8} {values[3]:>10} {values[4]:>8} "
                  f"{values[5]:>8} {values[6]:>8}")
            success &= (p95 < P95_GATE_MS and chow is not None and chow > .1
                        and r2 is not None and r2 > .9 and recovery is not None and recovery > 90)
    return success


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cube", default="data/processed/fire_cube.parquet")
    args = parser.parse_args()
    raise SystemExit(0 if run_benchmark(args.cube) else 1)
