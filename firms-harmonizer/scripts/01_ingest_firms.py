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
    predicate = getattr(industrial_filter, "is_sama_artifact", None)
    if callable(predicate):
        return predicate(row["latitude"], row["longitude"], row["daynight"],
                         row["confidence_norm"], row["brightness_mir"], row["brightness_tir"])
    # Local implementation of spec section 3.2 while the core module is empty.
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
    files = sorted((ROOT / raw_dir).glob("*.csv"))
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
        for cell, counts in monthly.items():
            p = counts[counts > 0] / counts.sum()
            entropy = float(-np.sum(p * np.log(p)) / np.log(12))
            coords = np.asarray(positions[cell])
            metres = coords * [111195, 111195 * np.cos(np.radians(coords[:, 0].mean()))]
            score = 1 / (1 + np.exp(-20 * (entropy - .72)))
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--output", default=STAGED)
    args = parser.parse_args()
    ingest_raw_firms(args.raw_dir, args.output)
