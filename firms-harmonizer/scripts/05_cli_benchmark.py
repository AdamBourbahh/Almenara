"""Benchmark regional Parquet queries and report project audit targets."""

import argparse
from importlib import import_module
from pathlib import Path
from time import perf_counter

import duckdb
import h3
import numpy as np
import pyarrow.parquet as pq
from scipy.stats import wasserstein_distance

bootstrap = import_module("00_bootstrap_synthetic_cube")
ingest = import_module("01_ingest_firms")
ROOT = ingest.ROOT


def cross_validated_r2(energy, area):
    if len(area) < 6 or np.ptp(area) == 0:
        return None
    design = np.column_stack((np.ones(len(energy)), energy))
    predicted = np.empty_like(area)
    for index in range(len(area)):
        train = np.arange(len(area)) != index
        predicted[index] = design[index] @ np.linalg.lstsq(design[train], area[train], rcond=None)[0]
    return float(1 - np.sum((area - predicted)**2) / np.sum((area - area.mean())**2))


def seasonal_recovery(energy, viirs, years, doy):
    target = years == 2022
    history = ~target
    if target.sum() < 10 or not np.any(history) or not np.any(np.isfinite(viirs[target])):
        return None
    totals = np.bincount(doy[history], weights=energy[history], minlength=367)
    counts = np.bincount(doy[history], minlength=367)
    prior = np.divide(totals, counts, out=np.full(367, energy[history].mean()), where=counts > 0)
    series = energy[target]
    drop = np.random.default_rng(42).random(len(series)) < .25
    peak = int(np.argmax(series))
    start = min(max(peak - 5, 0), len(series) - 10)
    blackout = slice(start, start + 10)
    recovered = series.copy()
    missing = drop & np.isfinite(viirs[target])
    recovered[missing] = prior[doy[target][missing]]
    recovered[blackout] = prior[doy[target][blackout]]
    total = series.sum()
    return float(100 * max(0, 1 - abs(np.maximum(recovered, 0).sum() - total) / total)) if total > 0 else None


def run_benchmark(cube_path="data/processed/fire_cube.parquet"):
    path = ROOT / cube_path
    if not path.is_file():
        print(f"Cube unavailable at {path}. Run script 04.")
        return False
    parquet = pq.ParquetFile(path)
    metadata = parquet.metadata
    compressed = all(metadata.row_group(i).column(j).compression == "ZSTD"
                     for i in range(metadata.num_row_groups) for j in range(metadata.num_columns))
    success = compressed and parquet.schema_arrow.equals(bootstrap.CUBE_SCHEMA, check_metadata=False)
    regions = ingest.load_regions()
    print("Project audit targets   P95 < 15 ms   Chow p > .10   R2 > .90   Recovery > 90%")
    print("Recovery uses a seasonal prior stress test. Fixture metrics are synthetic.")
    print(f"{'Region':23} {'P95 ms':>8} {'Chow p':>8} {'W1':>10} {'CV R2':>8} {'Recov %':>8}")
    with duckdb.connect(config={"threads": 4}) as con:
        all_cells = con.execute("SELECT DISTINCT h3_r4,h3_r7 FROM read_parquet(?)",
                                [str(path)]).fetchall()
        for name, region in regions.items():
            fixture = bootstrap.REGIONS.get(name)
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
            before = years < 2012
            chow = w1 = None
            if min(before.sum(), (~before).sum()) >= 10:
                _, chow = bootstrap._chow(energy, years, doy)
                w1 = wasserstein_distance(energy[before], energy[~before])
            unique = np.unique(years)
            # Real-region validation requires independent burned-area input.
            # Fixture remnants outside declared coverage cannot supply that input.
            r2 = None
            if not region.get("coverage"):
                r2 = cross_validated_r2(
                    np.array([energy[years == year].sum() for year in unique]),
                    np.array([area[years == year].sum() for year in unique]),
                )
            elif (ROOT / "data/lookup/cell_day_ancillary.parquet").is_file():
                annual = con.execute("""WITH reference AS (
                    SELECT year(acq_date::DATE) AS year, sum(burned_area_ha_mcd64) AS area
                    FROM read_parquet(?) SEMI JOIN region_cells USING (h3_r7)
                    WHERE burned_area_ha_mcd64 IS NOT NULL GROUP BY 1
                ) SELECT year, area FROM reference ORDER BY year""",
                    [str(ROOT / "data/lookup/cell_day_ancillary.parquet")]).fetchall()
                # Compare complete calendar years of declared FIRMS coverage only.
                complete = [(year, observed) for year, observed in annual
                            if year in unique and any(
                                start <= f"{year}-01-01" and end >= f"{year}-12-31"
                                for start, end in region["coverage"])]
                if complete:
                    r2 = cross_validated_r2(
                        np.array([energy[years == year].sum() for year, _ in complete]),
                        np.array([observed for _, observed in complete], dtype=float),
                    )
            recovery = seasonal_recovery(energy, viirs, years, doy) if np.isfinite(viirs).any() else None
            values = [f"{v:.3f}" if v is not None else "N/A" for v in (p95, chow, w1, r2, recovery)]
            print(f"{name:23} {values[0]:>8} {values[1]:>8} {values[2]:>10} {values[3]:>8} {values[4]:>8}")
            success &= (p95 < 15 and chow is not None and chow > .1
                        and r2 is not None and r2 > .9 and recovery is not None and recovery > 90)
    return success


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cube", default="data/processed/fire_cube.parquet")
    args = parser.parse_args()
    raise SystemExit(0 if run_benchmark(args.cube) else 1)
