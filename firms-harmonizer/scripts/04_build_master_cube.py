"""Build and atomically publish the offline FIRMS master cube."""

import argparse
from datetime import date, datetime, timezone
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
bootstrap = import_module("00_bootstrap_synthetic_cube")
from backend.core.eqm_harmonizer import RadiometricHarmonizer  # noqa: E402  (path set by 01_ingest_firms)

ROOT = ingest.ROOT
HARMONIZER = RadiometricHarmonizer()
EPOCH = date(1970, 1, 1)
SORT = [(key, "ascending") for key in ("h3_r4", "epoch_day", "h3_r7")]
OUT = ROOT / "data/processed/fire_cube.parquet"
MIN_ORBITAL_WEIGHT = float(np.cos(np.deg2rad(80.0)))
ORBITAL_WEIGHTING = ("w_orb = clip(cos(centroid_lat_h3_r7), cos(80 deg), 1.0); "
                     "applied once to obs_terra_fre, obs_aqua_fre, obs_viirs_fre")
RADIOMETRIC_HARMONIZATION = ("core RadiometricHarmonizer on daily MW sums before FRE scaling: VIIRS = "
                             "EQM + delta_e_sub; Terra/Aqua = MW + delta_e_sub; stratum biome:angle > "
                             "biome:all > all:all; untrained strata stay raw")


def orbital_weight(h3_r7):
    """Horvitz-Thompson inverse revisit weight (SPECS.md §3.4(1)).

    Sun-synchronous revisit density grows as sec(latitude), so its inverse is cos(latitude),
    normalized to 1.0 at the equator and clamped at cos(80°) near the poles.
    """
    latitude, _ = h3.cell_to_latlng(format(h3_r7, "x"))
    return float(np.clip(np.cos(np.deg2rad(latitude)), MIN_ORBITAL_WEIGHT, 1.0))


def model_name(lut, biome, angle):
    """Most specific trained stratum: biome and angle, then biome, then pooled; None if untrained."""
    return next((name for name in (f"{biome}:{angle}", f"{biome}:all", "all:all") if name in lut), None)


def harmonize(modis, mw, model):
    """SPECS.md §3.3 via the core: EQM + delta E_sub for VIIRS, delta E_sub for MODIS (daily MW sums)."""
    if model is None:
        return np.asarray(mw, dtype=float)
    if modis:
        return HARMONIZER.compensate_modis_censoring(mw, model)
    return HARMONIZER.harmonize_viirs_to_modis(mw, model)


def table_from_rows(rows):
    return pa.Table.from_pylist(list(rows), schema=bootstrap.CUBE_SCHEMA)


def real_rows(con, staged, lookup, regions, ancillary_coverage=None, confidence_level='nominal'):
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
        FROM read_parquet(?) WHERE confidence_norm IN (SELECT unnest(?))
        GROUP BY h3_r4, h3_r7, acq_date, satellite, sensor_bit
        ORDER BY h3_r7, acq_date, satellite""", [str(staged),
            {'low': ['low', 'nominal', 'high'], 'nominal': ['nominal', 'high'], 'high': ['high']}[confidence_level]]).fetchall()
    daily, viirs, scales, pending = {}, {}, {}, []
    for h4, h7, day, sensor, bit, biome, angle, mw, n, raw, industrial, region in rows:
        if day > datetime.now(timezone.utc).date():
            raise ValueError(f"Future detection rejected for {region}: {day}")
        epoch = (day - EPOCH).days
        key = (h7, epoch)
        row = daily.setdefault(key, dict(h3_r4=h4, h3_r7=h7, epoch_day=epoch, year=day.year,
            doy=day.timetuple().tm_yday, igbp_biome=biome, sensor_obs_mask=0,
            gap_status_mask=int(any((day, item) in outages for item in ingest.SENSOR_BITS)),
            cloud_cover_pct=None, raw_modis_cnt=0, raw_viirs_cnt=0, raw_frp_mw=0.0,
            obs_terra_fre=None, obs_aqua_fre=None, obs_viirs_fre=None,
            neighbor_fre_lag1=0.0, industrial_prob=0.0, burned_area_ha_mcd64=None))
        modis = sensor in ("Terra", "Aqua")
        row["raw_modis_cnt" if modis else "raw_viirs_cnt"] += n
        row["raw_frp_mw"] += raw
        row["industrial_prob"] = max(row["industrial_prob"], industrial)
        if (day, sensor) in outages:
            continue
        if h7 not in scales:
            # One-hour integration proxy (FIRMS does not measure fire duration) per km²,
            # times the orbital revisit weight. This is the only place w_orb is applied.
            scales[h7] = 3600 / h3.cell_area(format(h7, "x"), unit="km^2") * orbital_weight(h7)
        factor = scales[h7] * (ratios.get((h4, day.month), 1.0) if sensor == "Terra" else 1.0)
        pending.append((key, sensor, model_name(lut, biome, angle), mw, factor))
        row["sensor_obs_mask"] |= bit
    # Harmonize daily MW sums in one vectorized core call per (stratum, instrument family).
    groups = {}
    for index, (_, sensor, name, _, _) in enumerate(pending):
        groups.setdefault((name, sensor in ("Terra", "Aqua")), []).append(index)
    harmonized = np.empty(len(pending))
    for (name, modis), indices in groups.items():
        harmonized[indices] = harmonize(modis, [pending[i][3] for i in indices], lut.get(name))
    for (key, sensor, _, _, factor), mw in zip(pending, harmonized):
        value = float(mw) * factor
        if sensor == "Terra":
            daily[key]["obs_terra_fre"] = value
        elif sensor == "Aqua":
            daily[key]["obs_aqua_fre"] = value
        else:
            viirs.setdefault(key, []).append(value)
    for key, values in viirs.items():
        daily[key]["obs_viirs_fre"] = float(np.mean(values))
    ancillary = lookup / "cell_day_ancillary.parquet"
    coverage = {
        "input_present": ancillary.exists(),
        "cloud_cover_pct": {"observed_rows": 0, "missing_rows": len(daily), "observed_zero_rows": 0},
        "burned_area_ha_mcd64": {"observed_rows": 0, "missing_rows": len(daily), "observed_zero_rows": 0},
    }
    if ancillary.exists():
        seen = set()
        # Compare in the stored numeric type so FLOAT 0.80 stays on the clean boundary.
        for cell, day, cloud, burned, occluded in con.execute(
            "SELECT h3_r7, acq_date::DATE, cloud_cover_pct, burned_area_ha_mcd64, "
            "cloud_cover_pct > 0.80 AS occluded "
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
                if occluded:
                    row["gap_status_mask"] |= 2
                    row["sensor_obs_mask"] = 0
                    for field in ("obs_terra_fre", "obs_aqua_fre", "obs_viirs_fre"):
                        row[field] = None
            for field, value in (("cloud_cover_pct", cloud), ("burned_area_ha_mcd64", burned)):
                if value is not None:
                    coverage[field]["observed_rows"] += 1
                    coverage[field]["missing_rows"] -= 1
                    coverage[field]["observed_zero_rows"] += int(value == 0)
    if ancillary_coverage is not None:
        ancillary_coverage.update(coverage)

    # Mask observations before deriving spatial energy; occluded values cannot seed a neighbor.
    energy = {}
    neighbors = {}
    for key, row in daily.items():
        values = [row[name] for name in ("obs_terra_fre", "obs_aqua_fre", "obs_viirs_fre")
                  if row[name] is not None]
        if values:
            energy[key] = float(np.mean(values))
        else:
            row["gap_status_mask"] |= 8
    for (cell, epoch), row in daily.items():
        if cell not in neighbors:
            neighbors[cell] = [int(x, 16) for x in h3.grid_disk(format(cell, "x"), 1)
                               if int(x, 16) != cell]
        # Only active burning neighbors contribute to the previous-day mean.
        lag = [energy[(neighbor, epoch - 1)] for neighbor in neighbors[cell]
               if (neighbor, epoch - 1) in energy and energy[(neighbor, epoch - 1)] > 0]
        if lag:
            row["neighbor_fre_lag1"] = float(np.mean(lag))
    return daily


def build_master_cube(staged_path=ingest.STAGED, output_path=OUT, force_bootstrap=False,
                      lookup_dir="data/lookup", confidence_level='nominal'):
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
        ancillary_coverage = {}
        daily = real_rows(con, staged, ROOT / lookup_dir, regions, ancillary_coverage, confidence_level)
        metadata = {
            b"source": b"REAL FIRMS detections",
            b"real_rows": str(len(daily)).encode(),
            b"synthetic_rows": b"0",
            b"epoch": EPOCH.isoformat().encode(),
            b"coverage": json.dumps(regions).encode(),
            b"confidence_level": confidence_level.encode(),
            b"industrial_method": b"Published EOG upstream site-year match <=1km plus persistence score; not a calibrated classifier",
            b"real_cloud_and_burned_area": b"optional ancillary; null for missing values",
            b"ancillary_coverage": json.dumps(ancillary_coverage, sort_keys=True).encode(),
            b"real_igbp": b"local IGBP lookup or nominal regional fallback",
            b"fre_method": b"one-hour FRP integration proxy",
            b"orbital_weighting": ORBITAL_WEIGHTING.encode(),
            b"radiometric_harmonization": RADIOMETRIC_HARMONIZATION.encode(),
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
