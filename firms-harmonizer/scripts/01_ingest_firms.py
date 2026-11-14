"""Normalize local FIRMS detections and distribute corrected MODIS power."""

from __future__ import annotations

import argparse
from datetime import date
from functools import lru_cache
import json
from pathlib import Path
import sys

import duckdb
import h3
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.core import footprint_h3, industrial_filter

STAGED = ROOT / "data/processed/staged_firms.parquet"
SENSORS = {"T": "Terra", "A": "Aqua", "N": "SNPP", "NPP": "SNPP",
           "SUOMI-NPP": "SNPP", "NOAA20": "N20", "NOAA21": "N21",
           "NOAA-20": "N20", "NOAA-21": "N21", "J1": "N20", "J2": "N21"}
SENSOR_BITS = {"Terra": 1, "Aqua": 2, "SNPP": 4, "N20": 8, "N21": 16}


def load_regions():
    return json.loads((ROOT / "data/regions.json").read_text(encoding="utf-8"))


def region_at(lat, lon, regions):
    for name, region in regions.items():
        west, south, east, north = region["bounds"]
        if west <= lon <= east and south <= lat <= north:
            return name
    return None


def scan_bin(scan, sensor):
    # Approximate off-nadir angle from cross-track footprint expansion.
    nadir = 1.0 if sensor in ("Aqua", "Terra") else 0.375
    angle = np.degrees(np.arccos(np.sqrt(np.clip(nadir / scan, 0, 1))))
    return min(9, int(angle / 6.5))


def sama_artifact(row):
    predicate = getattr(industrial_filter, "filter_sama_anomalies", None)
    if callable(predicate):
        mir, tir = row["brightness_mir"], row["brightness_tir"]
        delta = (mir - tir) if (mir is not None and tir is not None) else np.nan
        day = row.get("acq_date")
        is_terra = (row.get("satellite") == "Terra")
        year = day.year if is_terra and hasattr(day, "year") else None
        month = day.month if is_terra and hasattr(day, "month") else None
        return bool(predicate(row["latitude"], row["longitude"], row["daynight"],
                              row["confidence_norm"] == "low", delta, year, month))
    mir, tir = row["brightness_mir"], row["brightness_tir"]
    return (
        -35 <= row["latitude"] <= -15 and -65 <= row["longitude"] <= -30
        and row["daynight"] == "N" and row["confidence_norm"] == "low"
        and mir is not None and tir is not None and mir - tir < 1.5
    )


@lru_cache(maxsize=32768)
def cell_center(cell):
    return h3.cell_to_latlng(cell)


def footprint(lat, lon, cell, scan, track, modis):
    if not modis or scan * track <= 3.5:
        return [(cell, 1.0)]
    psf_calc = getattr(footprint_h3, "compute_elliptical_psf_weights", None)
    if callable(psf_calc):
        return list(psf_calc(lat, lon, scan, track).items())
    disk = getattr(h3, "grid_disk", getattr(h3, "k_ring", None))
    cells = sorted(disk(cell, 1))
    coordinates = np.array([cell_center(item) for item in cells], dtype=float)
    delta_lon = (coordinates[:, 1] - lon + 180.0) % 360.0 - 180.0
    xy = 6371.0088 * np.deg2rad(np.column_stack([
        delta_lon * np.cos(np.deg2rad(lat)), coordinates[:, 0] - lat,
    ]))
    angle = np.deg2rad(98.2)
    rotation = np.array([[np.cos(angle), -np.sin(angle)],
                         [np.sin(angle), np.cos(angle)]])
    scaled = (xy @ rotation) / (np.array([scan, track]) / 2.355)
    log_weights = -0.5 * np.sum(scaled * scaled, axis=1)
    weights = np.exp(log_weights - np.max(log_weights))
    weights /= weights.sum()
    largest = int(np.argmax(weights))
    indices = [i for i in range(len(cells)) if i != largest]
    result = {cells[i]: float(weights[i]) for i in indices}
    result[cells[largest]] = 1.0 - sum(result.values())
    return list(result.items())


def ingest_raw_firms(raw_dir="data/raw", output_path=STAGED):
    files = sorted([p for p in (ROOT / raw_dir).glob("*.csv") if not p.name.startswith("sync_")])
    if not files:
        raise SystemExit("No FIRMS CSVs found. Use script 04 --bootstrap for the offline fixture.")
    regions = load_regions()
    land_cover_path = ROOT / "data/lookup/igbp_cells.parquet"
    land_cover = {}
    if land_cover_path.exists():
        cells = pq.read_table(land_cover_path, columns=["h3_r7", "igbp_biome"]).to_pylist()
        for record in cells:
            cell, biome = record["h3_r7"], record["igbp_biome"]
            if cell in land_cover or biome is None or not 1 <= biome <= 17:
                raise ValueError(f"Invalid or duplicate land-cover class for {cell}: {biome}")
            land_cover[cell] = biome
    rows, monthly, positions = [], {}, {}
    seen = set()
    with duckdb.connect() as con:
        for path in sorted(files, key=lambda p: ("nrt" in p.name.lower(), p.name)):
            cursor = con.execute("SELECT * FROM read_csv_auto(?, all_varchar=true)", [str(path)])
            columns = [item[0].lower() for item in cursor.description]
            required = {"latitude", "longitude", "acq_date", "acq_time", "satellite",
                        "frp", "scan", "track", "confidence", "daynight"}
            if not required.issubset(columns):
                raise ValueError(f"{path.name} is missing {sorted(required - set(columns))}")
            for values in cursor.fetchall():
                row = dict(zip(columns, values))
                from datetime import date
                day = date.fromisoformat(row["acq_date"])
                lat, lon, frp, scan, track = (float(row[key] or "nan") for key in
                                             ("latitude", "longitude", "frp", "scan", "track"))
                if not (np.isfinite([lat, lon, frp, scan, track]).all()
                        and abs(lat) <= 90 and abs(lon) <= 180 and frp >= 0 and min(scan, track) > 0
                        and date(2000, 11, 1) <= day <= date(2026, 12, 31)):
                    continue
                platform = row["satellite"].strip()
                sensor = SENSORS.get(platform.upper(), platform.upper() if platform.upper() in SENSOR_BITS else platform.title())
                if sensor not in SENSOR_BITS:
                    raise ValueError(f"Unknown FIRMS satellite {platform!r} in {path.name}")
                modis = sensor in ("Terra", "Aqua")
                acq_time = str(int(row["acq_time"])).zfill(4)
                if not (0 <= int(acq_time[:2]) <= 23 and 0 <= int(acq_time[2:]) <= 59):
                    raise ValueError(f"Invalid UTC acquisition time in {path.name}: {acq_time}")
                identity = (sensor, day, acq_time, round(lat, 5), round(lon, 5))
                if identity in seen:
                    continue
                seen.add(identity)
                confidence = (row["confidence"] or "").lower()
                if confidence.isdigit():
                    confidence = "low" if int(confidence) < 30 else "nominal" if int(confidence) < 80 else "high"
                confidence = {"l": "low", "n": "nominal", "h": "high"}.get(confidence, confidence)
                mir = row.get("bright_ti4") or row.get("brightness")
                tir = row.get("bright_ti5") or row.get("bright_t31")
                region = region_at(lat, lon, regions)
                if region is None:
                    raise ValueError(f"Detection outside configured regions in {path.name}: {lat}, {lon}")
                cell = h3.latlng_to_cell(lat, lon, 7)
                r10 = h3.latlng_to_cell(lat, lon, 10)
                row.update(latitude=lat, longitude=lon, acq_date=day, acq_time=acq_time,
                           satellite=sensor, instrument="MODIS" if modis else "VIIRS",
                           frp=frp, scan=scan, track=track, confidence_norm=confidence,
                           daynight=row["daynight"].upper(), brightness_mir=float(mir) if mir else None,
                           brightness_tir=float(tir) if tir else None)
                if sama_artifact(row):
                    continue
                monthly.setdefault(r10, np.zeros(12))[day.month - 1] += 1
                positions.setdefault(r10, []).append((lat, lon))
                rows.append((row, cell, r10, region, path.name, modis))

        if not rows:
            raise ValueError("The FIRMS inputs contain no usable detections.")
        scores = {}
        calc_ind = getattr(industrial_filter, "compute_industrial_probability", None)
        for cell, counts in monthly.items():
            if callable(calc_ind):
                ent, prob = calc_ind(counts)
                entropy, score = float(ent), float(prob)
            else:
                p = counts[counts > 0] / counts.sum()
                entropy = float(-np.sum(p * np.log(p)) / np.log(12))
                score = 1 / (1 + np.exp(-22 * (entropy - .72)))
            coords = np.asarray(positions[cell])
            metres = coords * [111195, 111195 * np.cos(np.radians(coords[:, 0].mean()))]
            scores[cell] = (entropy, score if metres.var(axis=0).sum() < 50 else 0.0)

        con.execute("""CREATE TABLE detections (
            latitude DOUBLE, longitude DOUBLE, acq_date DATE, acq_time VARCHAR,
            satellite VARCHAR, instrument VARCHAR, frp DOUBLE, scan DOUBLE, track DOUBLE,
            brightness_mir DOUBLE, brightness_tir DOUBLE, confidence_norm VARCHAR, daynight VARCHAR,
            h3_r4 UBIGINT, h3_r7 UBIGINT, h3_r10 UBIGINT, is_center BOOLEAN,
            bowtie_weight DOUBLE, footprint_weight DOUBLE, corrected_frp DOUBLE,
            h_temp DOUBLE, industrial_prob DOUBLE, region VARCHAR, igbp_biome UTINYINT,
            scan_bin UTINYINT, source_file VARCHAR, sensor_bit UTINYINT
        )""")
        import pyarrow as pa
        records = []
        fields = [item[0] for item in con.execute("DESCRIBE detections").fetchall()]
        for row, cell, r10, region, filename, modis in rows:
            bowtie_calc = getattr(footprint_h3, "compute_modis_bowtie_overlap_weight", None)
            weight = float(bowtie_calc(row["track"])) if callable(bowtie_calc) and modis else (1 / row["track"] if modis and row["track"] > 1.35 else 1.0)
            for target, fraction in footprint(row["latitude"], row["longitude"], cell,
                                              row["scan"], row["track"], modis):
                record = dict(row)
                record.update(h3_r4=int(h3.cell_to_parent(target, 4), 16), h3_r7=int(target, 16),
                              h3_r10=int(r10, 16), is_center=target == cell, bowtie_weight=weight,
                              footprint_weight=float(fraction), corrected_frp=row["frp"] * weight * fraction,
                              h_temp=scores[r10][0], industrial_prob=scores[r10][1], region=region,
                              igbp_biome=land_cover.get(int(target, 16), regions[region]["nominal_biome"]),
                              scan_bin=scan_bin(row["scan"], row["satellite"]),
                              source_file=filename, sensor_bit=SENSOR_BITS[row["satellite"]])
                records.append({field: record[field] for field in fields})
        # Arrow must infer unsigned H3 indices explicitly for a stable staging contract.
        schema = con.sql("SELECT * FROM detections").limit(0).arrow().schema
        table = pa.Table.from_pylist(records, schema=schema)
        out = ROOT / output_path
        out.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, out, compression="zstd")
    print(f"Staged {len(rows):,} detections and {len(records):,} footprint contributions.")
    return out


NRT_TARGET_FILES = {
    "chilecito_la_rioja": {
        "MODIS_NRT": "chilecito_modis_nrt_2026.csv",
        "VIIRS_NOAA20_NRT": "chilecito_viirs_noaa20_nrt_2026.csv",
        "VIIRS_NOAA21_NRT": "chilecito_viirs_noaa21_nrt_2026.csv",
        "VIIRS_SNPP_NRT": "chilecito_viirs_snpp_nrt_2026.csv",
    },
    "iberia_med": {
        "MODIS_NRT": "spain_fire_nrt_M-C61_847720.csv",
        "VIIRS_NOAA20_NRT": "spain_fire_nrt_J1V-C2_847721.csv",
        "VIIRS_NOAA21_NRT": "spain_fire_nrt_J2V-C2_847722.csv",
        "VIIRS_SNPP_NRT": "spain_fire_nrt_SV-C2_847723.csv",
    },
    "orlando_florida": {
        "MODIS_NRT": "orlando_fire_nrt_M-C61_848215.csv",
        "VIIRS_NOAA20_NRT": "orlando_fire_nrt_J1V-C2_848216.csv",
        "VIIRS_NOAA21_NRT": "orlando_fire_nrt_J2V-C2_848217.csv",
        "VIIRS_SNPP_NRT": "orlando_fire_nrt_SV-C2_848218.csv",
    },
    "amazonas_manaus": {
        "MODIS_NRT": "amazonas_fire_nrt_M-C61_848219.csv",
        "VIIRS_NOAA20_NRT": "amazonas_fire_nrt_J1V-C2_848220.csv",
        "VIIRS_NOAA21_NRT": "amazonas_fire_nrt_J2V-C2_848221.csv",
        "VIIRS_SNPP_NRT": "amazonas_fire_nrt_SV-C2_848222.csv",
    },
}


def fetch_firms_nrt(
    raw_dir: str | Path = "data/raw",
    start_date: str = "2026-11-01",
    end_date: str = "2026-11-14",
    regions_filter: list[str] | None = None,
    map_key: str | None = None,
) -> dict[str, int]:
    """Fetch live NRT detections from NASA FIRMS API and append new unique rows to raw NRT CSVs."""
    import csv
    import io
    import os
    from datetime import datetime, timedelta
    import httpx

    key = (map_key or os.environ.get("FIRMS_MAP_KEY", "")).strip()
    if not key:
        env_file = ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("FIRMS_MAP_KEY=") and not line.strip().startswith("#"):
                    key = line.strip().split("=", 1)[1].strip()
                    break
    if not key:
        raise ValueError("FIRMS_MAP_KEY is not set in environment or .env file.")

    regions = load_regions()
    raw_path = ROOT / raw_dir
    raw_path.mkdir(parents=True, exist_ok=True)

    counts_by_file: dict[str, int] = {}
    selected_regions = {
        name: targets for name, targets in NRT_TARGET_FILES.items()
        if regions_filter is None or name in regions_filter
    }

    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()

    chunk_starts = []
    curr = start_dt
    while curr <= end_dt:
        chunk_starts.append(curr.isoformat())
        curr += timedelta(days=5)

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for reg_name, sources in selected_regions.items():
            if reg_name not in regions:
                continue
            west, south, east, north = regions[reg_name]["bounds"]
            bbox = f"{west:.4f},{south:.4f},{east:.4f},{north:.4f}"

            for src_name, filename in sources.items():
                target_file = raw_path / filename
                if not target_file.exists():
                    continue

                seen_keys = set()
                with target_file.open("r", encoding="utf-8") as fp:
                    reader = csv.DictReader(fp)
                    for row in reader:
                        s = (row.get("satellite") or "").strip()
                        d = (row.get("acq_date") or "").strip()
                        t = (row.get("acq_time") or "").strip().zfill(4)
                        try:
                            lat = round(float(row.get("latitude", 0)), 5)
                            lon = round(float(row.get("longitude", 0)), 5)
                        except (ValueError, TypeError):
                            continue
                        seen_keys.add((s, d, t, lat, lon))

                new_rows = []
                urls = [
                    f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{src_name}/{bbox}/5/{chunk_d}"
                    for chunk_d in chunk_starts
                ] + [f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{src_name}/{bbox}/5"]

                for url in urls:
                    try:
                        resp = client.get(url)
                    except httpx.HTTPError:
                        continue
                    if resp.status_code != 200 or resp.text.lstrip().startswith("<"):
                        continue

                    reader = csv.DictReader(io.StringIO(resp.text))
                    for row in reader:
                        acq_date_val = (row.get("acq_date") or "").strip()
                        if not (start_date <= acq_date_val <= end_date):
                            continue
                        s = (row.get("satellite") or "").strip()
                        try:
                            t = str(int(row.get("acq_time", 0))).zfill(4)
                            lat = round(float(row.get("latitude", 0)), 5)
                            lon = round(float(row.get("longitude", 0)), 5)
                        except (ValueError, TypeError):
                            continue

                        ident = (s, acq_date_val, t, lat, lon)
                        if ident in seen_keys:
                            continue
                        seen_keys.add(ident)

                        mir = row.get("brightness") or row.get("bright_ti4") or ""
                        tir = row.get("bright_t31") or row.get("bright_ti5") or ""

                        std_row = {
                            "latitude": row.get("latitude", ""),
                            "longitude": row.get("longitude", ""),
                            "brightness": mir,
                            "scan": row.get("scan", ""),
                            "track": row.get("track", ""),
                            "acq_date": acq_date_val,
                            "acq_time": t,
                            "satellite": s,
                            "instrument": row.get("instrument", ""),
                            "confidence": row.get("confidence", ""),
                            "version": row.get("version", ""),
                            "bright_t31": tir,
                            "frp": row.get("frp", ""),
                            "daynight": (row.get("daynight") or "").upper(),
                        }
                        new_rows.append(std_row)

                if new_rows:
                    with target_file.open("a", newline="", encoding="utf-8") as fp:
                        writer = csv.DictWriter(
                            fp,
                            fieldnames=[
                                "latitude", "longitude", "brightness", "scan", "track",
                                "acq_date", "acq_time", "satellite", "instrument",
                                "confidence", "version", "bright_t31", "frp", "daynight",
                            ],
                            lineterminator="\n",
                        )
                        for r in new_rows:
                            writer.writerow(r)

                counts_by_file[filename] = len(new_rows)
                print(f"Fetched {len(new_rows):,} new rows for {filename} ({reg_name} {src_name}).")

    total_new = sum(counts_by_file.values())
    print(f"Total new FIRMS detections appended: {total_new:,}")
    return counts_by_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--output", default=STAGED)
    parser.add_argument("--fetch-nrt", action="store_true", help="Fetch live NRT detections from NASA FIRMS API")
    parser.add_argument("--start-date", default="2026-11-01", help="Start date for NRT fetch (YYYY-MM-DD)")
    parser.add_argument("--end-date", default="2026-11-14", help="End date for NRT fetch (YYYY-MM-DD)")
    parser.add_argument("--regions", nargs="*", default=None, help="Optional subset of region names to fetch")
    args = parser.parse_args()
    if args.fetch_nrt:
        fetch_firms_nrt(raw_dir=args.raw_dir, start_date=args.start_date, end_date=args.end_date, regions_filter=args.regions)
    ingest_raw_firms(args.raw_dir, args.output)
