"""Build and atomically publish the offline FIRMS master cube."""

import argparse
from datetime import date
from importlib import import_module
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
import h3
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

ingest = import_module("01_ingest_firms")
training = import_module("03_train_eqm_lut")
bootstrap = import_module("00_bootstrap_synthetic_cube")
ROOT = ingest.ROOT
EPOCH = date(1970, 1, 1)
SORT = [(key, "ascending") for key in ("h3_r4", "epoch_day", "h3_r7")]
OUT = ROOT / "data/processed/fire_cube.parquet"


def estimate(sensor, mw, biome, angle, lut):
    model = lut.get(f"{biome}:{angle}") or lut.get(f"{biome}:all") or lut.get("all:all")
    if model is None:
        return mw
    if sensor in ("Terra", "Aqua"):
        tail = model["gpd"]
        if tail and mw >= training.THRESHOLD:
            return mw + tail["mean_mw"] * tail["fraction"] / (1 - tail["fraction"])
        return mw
    if mw < training.THRESHOLD:
        return mw
    x, y = model["viirs_quantiles"], model["aqua_quantiles"]
    return float(np.interp(mw, x, y)) if x[0] <= mw <= x[-1] else mw * (y[0] / x[0] if mw < x[0] else y[-1] / x[-1])


def table_from_rows(rows):
    return pa.Table.from_pylist(list(rows), schema=bootstrap.CUBE_SCHEMA)


def real_rows(con, staged, lookup, regions):
    lut = json.loads((lookup / "eqm_gpd_lut.json").read_text())["models"]
    outages = set(con.execute("SELECT acq_date, satellite FROM read_parquet(?)",
                              [str(lookup / "sensor_outages.parquet")]).fetchall())
    ratios = {(block, month): ratio for block, month, ratio in con.execute(
        "SELECT h3_r4, month, ratio FROM read_parquet(?) WHERE matched_days >= 3",
        [str(lookup / "diurnal_ratios.parquet")]).fetchall()}
    rows = con.execute("""SELECT h3_r4, h3_r7, acq_date, satellite, sensor_bit,
        mode(igbp_biome) AS biome, mode(scan_bin) AS angle, sum(corrected_frp) AS power,
        count(*) FILTER (WHERE is_center) AS n,
        coalesce(sum(frp) FILTER (WHERE is_center), 0) AS raw_power,
        max(industrial_prob) AS industrial, mode(region) AS region
        FROM read_parquet(?) GROUP BY h3_r4, h3_r7, acq_date, satellite, sensor_bit
        ORDER BY h3_r7, acq_date, satellite""", [str(staged)]).fetchall()
    daily, viirs, areas = {}, {}, {}
    for h4, h7, day, sensor, bit, biome, angle, mw, n, raw, industrial, region in rows:
        ranges = regions[region].get("coverage", [])
        if not any(date.fromisoformat(start) <= day <= date.fromisoformat(end)
                   for start, end in ranges):
            raise ValueError(f"Declare coverage for {region} on {day} in data/regions.json")
        epoch = (day - EPOCH).days
        key = (h7, epoch)
        row = daily.setdefault(key, dict(h3_r4=h4, h3_r7=h7, epoch_day=epoch, year=day.year,
            doy=day.timetuple().tm_yday, igbp_biome=biome, sensor_obs_mask=0,
            gap_status_mask=int(any((day, item) in outages for item in ingest.SENSOR_BITS)),
            cloud_cover_pct=0.0, raw_modis_cnt=0, raw_viirs_cnt=0, raw_frp_mw=0.0,
            obs_terra_fre=None, obs_aqua_fre=None, obs_viirs_fre=None,
            neighbor_fre_lag1=0.0, industrial_prob=0.0, burned_area_ha_mcd64=0.0))
        modis = sensor in ("Terra", "Aqua")
        row["raw_modis_cnt" if modis else "raw_viirs_cnt"] += n
        row["raw_frp_mw"] += raw
        row["industrial_prob"] = max(row["industrial_prob"], industrial)
        if (day, sensor) in outages:
            continue
        if h7 not in areas:
            areas[h7] = h3.cell_area(format(h7, "x"), unit="km^2")
        # One-hour integration proxy. FIRMS does not measure fire duration.
        value = estimate(sensor, mw, biome, angle, lut) * 3600 / areas[h7]
        row["sensor_obs_mask"] |= bit
        if sensor == "Terra":
            row["obs_terra_fre"] = value * ratios.get((h4, day.month), 1.0)
        elif sensor == "Aqua":
            row["obs_aqua_fre"] = value
        else:
            viirs.setdefault(key, []).append(value)
    for key, values in viirs.items():
        daily[key]["obs_viirs_fre"] = float(np.mean(values))
    energy = {}
    neighbors = {}
    for key, row in daily.items():
        values = [row[name] for name in ("obs_terra_fre", "obs_aqua_fre", "obs_viirs_fre")
                  if row[name] is not None]
        if values:
            energy[key] = float(np.mean(values))
    for (cell, epoch), row in daily.items():
        if cell not in neighbors:
            neighbors[cell] = [int(x, 16) for x in h3.grid_disk(format(cell, "x"), 1)
                               if int(x, 16) != cell]
        lag = [energy[(neighbor, epoch - 1)] for neighbor in neighbors[cell]
               if (neighbor, epoch - 1) in energy]
        if lag:
            row["neighbor_fre_lag1"] = float(np.mean(lag))
    ancillary = lookup / "cell_day_ancillary.parquet"
    if ancillary.exists():
        seen = set()
        for cell, day, cloud, burned in con.execute(
            "SELECT h3_r7, acq_date::DATE, cloud_cover_pct, burned_area_ha_mcd64 "
            "FROM read_parquet(?)", [str(ancillary)]
        ).fetchall():
            key = (cell, (day - EPOCH).days)
            if key in seen:
                raise ValueError(f"Duplicate ancillary cell-day: {key}")
            seen.add(key)
            row = daily.get(key)
            if row is None:
                continue
            if cloud is not None and not 0 <= cloud <= 1:
                raise ValueError(f"Invalid cloud fraction for {key}: {cloud}")
            if burned is not None and (not np.isfinite(burned) or burned < 0):
                raise ValueError(f"Invalid burned area for {key}: {burned}")
            if burned is not None:
                row["burned_area_ha_mcd64"] = burned
            if cloud is not None:
                row["cloud_cover_pct"] = cloud
                if cloud > .8:
                    row["gap_status_mask"] |= 2
    return daily


def build_master_cube(staged_path=ingest.STAGED, output_path=OUT, force_bootstrap=False,
                      lookup_dir="data/lookup"):
    if force_bootstrap:
        fixture_path = bootstrap.SYNTHETIC_PATH if Path(output_path) == OUT else ROOT / output_path
        return Path(bootstrap.generate_bootstrap_cube(fixture_path))

    staged = ROOT / staged_path
    if not staged.is_file():
        raise FileNotFoundError(f"FIRMS staged detections not found at {staged}. Run script 01.")
    output = ROOT / output_path
    if output.resolve() == bootstrap.SYNTHETIC_PATH.resolve():
        raise ValueError("The synthetic cube path is reserved for generated fixture data.")
    output.parent.mkdir(parents=True, exist_ok=True)
    regions = ingest.load_regions()
    with TemporaryDirectory(dir=output.parent) as temp, duckdb.connect() as con:
        work = Path(temp)
        daily = real_rows(con, staged, ROOT / lookup_dir, regions)
        metadata = {
            b"source": b"REAL FIRMS detections",
            b"real_rows": str(len(daily)).encode(),
            b"synthetic_rows": b"0",
            b"epoch": EPOCH.isoformat().encode(),
            b"coverage": json.dumps(regions).encode(),
            b"real_cloud_and_burned_area": b"optional ancillary; zero sentinel for missing values",
            b"real_igbp": b"local IGBP lookup or nominal regional fallback",
            b"fre_method": b"one-hour FRP integration proxy",
        }
        table = table_from_rows(daily.values()).replace_schema_metadata(metadata)
        if not len(table):
            raise ValueError("Refusing to publish an empty cube.")
        physical = work / "cube.parquet"
        table = table.sort_by(SORT)
        pq.write_table(table, physical, compression="zstd", row_group_size=32768, write_statistics=True)
        physical.replace(output)
    print(f"Published {len(table):,} rows to {output}.")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", default=ingest.STAGED)
    parser.add_argument("--output", default=OUT)
    parser.add_argument("--lookup-dir", default="data/lookup")
    parser.add_argument("--bootstrap", action="store_true")
    args = parser.parse_args()
    build_master_cube(args.staged, args.output, args.bootstrap, args.lookup_dir)
