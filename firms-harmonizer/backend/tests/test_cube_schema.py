"""Offline ETL evidence, cube schema, storage and physical scenario regression gates."""

import csv
import importlib.util
from datetime import date, timedelta
from importlib import import_module
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

import duckdb
import h3
import numpy as np
import orjson
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from backend.api.schemas import AnalyzeRequest, AnalyzeResponse, ChaosMonkeyRequest, GeoJSONPolygon
from backend.core import footprint_h3, industrial_filter

spec = importlib.util.spec_from_file_location("bootstrap",ROOT/"scripts/00_bootstrap_synthetic_cube.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


@pytest.fixture
def phase2_etl(tmp_path, monkeypatch):
    """Keep input configuration, auxiliary lookups and published artifacts temporary."""
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    ingest = import_module("01_ingest_firms")
    outages = import_module("02_detect_outages_clouds")
    builder = import_module("04_build_master_cube")
    for module in (ingest, outages, builder):
        monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / "data/raw").mkdir(parents=True)
    regions = {"fixture": {"bounds": [-5, 39, -3, 41], "nominal_biome": 8,
                            "coverage": [["2024-01-01", "2024-12-31"]]}}
    (tmp_path / "data/regions.json").write_text(json.dumps(regions), encoding="utf-8")
    lookup = tmp_path / "data/lookup"
    outages.build_outages_table(tmp_path / "absent.parquet", lookup)
    (lookup / "eqm_gpd_lut.json").write_text('{"models": {}}', encoding="utf-8")
    return ingest, outages, builder


def w_orb(cell):
    """Independent SPECS.md §3.4(1) Horvitz-Thompson weight for an H3 R7 cell (hex or int)."""
    latitude = h3.cell_to_latlng(cell if isinstance(cell, str) else format(cell, "x"))[0]
    return float(np.clip(np.cos(np.radians(latitude)), np.cos(np.radians(80.0)), 1.0))


def write_phase2_csv(path, records):
    """Write nadir FIRMS records; test inputs override the shared valid defaults."""
    defaults = dict(latitude=40.0, longitude=-4.0, acq_date="2024-01-10", acq_time="1030",
                    satellite="Terra", frp=10.0, scan=1.0, track=1.0,
                    confidence=100, daynight="D", brightness=330.0, bright_t31=300.0)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(defaults))
        writer.writeheader()
        writer.writerows(defaults | record for record in records)


@pytest.mark.parametrize("region,latitude,longitude,biome", [
    ("chilecito_la_rioja", -29.16, -67.5, 16),
    ("iberia_med", 40.0, -4.0, 8),
    ("orlando_florida", 28.54, -81.38, 8),
    ("amazonas_manaus", -3.1, -60.02, 2),
])
def test_registered_real_regions_ingest_and_publish(phase2_etl, tmp_path,
                                                  region, latitude, longitude, biome):
    ingest, _, builder = phase2_etl
    regions = json.loads((ROOT / "data/regions.json").read_text(encoding="utf-8"))
    assert region in regions
    (tmp_path / "data/regions.json").write_text(json.dumps(regions), encoding="utf-8")
    write_phase2_csv(tmp_path / "data/raw/archive.csv", [
        dict(latitude=latitude, longitude=longitude, satellite="Terra", frp=10.0),
        dict(latitude=latitude, longitude=longitude, satellite="Aqua", frp=20.0),
    ])
    staged = ingest.ingest_raw_firms(output_path=tmp_path / "staged.parquet")
    assert pq.read_table(staged)["region"].to_pylist() == [region, region]
    cube = builder.build_master_cube(staged, tmp_path / "cube.parquet")
    table = pq.read_table(cube)
    assert table.num_rows == 1 and table.schema.metadata[b"synthetic_rows"] == b"0"
    row = table.to_pylist()[0]
    assert row["h3_r7"] == int(h3.latlng_to_cell(latitude, longitude, 7), 16)
    assert row["igbp_biome"] == biome and row["sensor_obs_mask"] == 3
    assert row["raw_modis_cnt"] == 2 and row["raw_frp_mw"] == 30.0
    assert row["obs_terra_fre"] > 0 and row["obs_aqua_fre"] > 0


def test_stage01_deduplication_exact_records(phase2_etl, tmp_path):
    ingest, _, _ = phase2_etl
    raw = tmp_path / "data/raw"
    # NRT sorts first lexically; archive priority must still win after normalization.
    write_phase2_csv(raw / "a_nrt.csv", [dict(satellite="T", acq_time="930", frp=99.0,
                                             latitude=40.000002, longitude=-4.000002)])
    write_phase2_csv(raw / "z_archive.csv", [
        dict(acq_time="0930", latitude=40.000001, longitude=-4.000001),
        dict(satellite="T", acq_time="930", latitude=40.000002, longitude=-4.000002),
        dict(acq_time="1130", frp=20.0),
        dict(satellite="A", acq_time="0930", frp=30.0),
        dict(acq_time="0930", acq_date="2024-01-11", frp=40.0),
        dict(acq_time="0930", latitude=40.00002, frp=50.0),
    ])
    path = ingest.ingest_raw_firms(output_path=tmp_path / "staged.parquet")
    rows = pq.read_table(path).to_pylist()
    assert len(rows) == 5
    assert all(row["source_file"] == "z_archive.csv" and row["is_center"] for row in rows)
    assert sorted(row["frp"] for row in rows) == [10, 20, 30, 40, 50]
    first = next(row for row in rows if row["frp"] == 10)
    assert first["satellite"] == "Terra" and first["acq_time"] == "0930"
    assert first["latitude"] == 40.000001
    assert sum(row["satellite"] == "Terra" for row in rows) == 4
    assert sum(row["acq_date"] == date(2024, 1, 10) for row in rows) == 4


def test_stage04_eulerian_fre_conversion_and_units(phase2_etl, tmp_path):
    ingest, _, builder = phase2_etl
    write_phase2_csv(tmp_path / "data/raw/archive.csv", [
        dict(frp=10.0, acq_time="1030"), dict(frp=20.0, acq_time="1230"),
        dict(satellite="Aqua", frp=7.0, acq_time="1330"),
        dict(satellite="SNPP", frp=6.0), dict(satellite="N20", frp=18.0),
        dict(frp=5.0, acq_time="0000", acq_date="2024-01-11"),
    ])
    staged = ingest.ingest_raw_firms(output_path=tmp_path / "staged.parquet")
    path = builder.build_master_cube(staged, tmp_path / "cube.parquet")
    rows = pq.read_table(path).to_pylist()
    cell = h3.latlng_to_cell(40.0, -4.0, 7)
    scale = 3600 / h3.cell_area(cell, unit="km^2") * w_orb(cell)
    assert len(rows) == 2
    first, second = rows
    assert first["obs_terra_fre"] == pytest.approx(30.0 * scale)
    assert first["obs_aqua_fre"] == pytest.approx(7.0 * scale)
    assert first["obs_viirs_fre"] == pytest.approx(12.0 * scale)
    assert first["raw_frp_mw"] == 61.0
    assert first["raw_modis_cnt"] == 3 and first["raw_viirs_cnt"] == 2
    assert first["sensor_obs_mask"] == 15
    assert second["obs_terra_fre"] == pytest.approx(5.0 * scale)
    assert second["raw_modis_cnt"] == 1 and second["raw_frp_mw"] == 5.0
    assert second["epoch_day"] == first["epoch_day"] + 1
    assert second["neighbor_fre_lag1"] == 0.0  # Self is not a neighbor.


def test_stage02_diurnal_ratio_uses_positive_coincident_daytime_sums(phase2_etl, tmp_path):
    ingest, outages, _ = phase2_etl
    write_phase2_csv(tmp_path / "data/raw/archive.csv", [
        dict(frp=4.0), dict(frp=6.0, acq_time="1130"), dict(satellite="Aqua", frp=20.0),
        dict(acq_date="2024-01-11", frp=20.0),
        dict(acq_date="2024-01-11", satellite="Aqua", frp=50.0),
        dict(acq_date="2024-01-12", frp=30.0),
        dict(acq_date="2024-01-12", satellite="Aqua", frp=80.0),
        dict(daynight="N", satellite="Aqua", acq_time="0130", frp=900.0),
        dict(acq_date="2024-01-13", frp=700.0),
        dict(acq_date="2024-01-14", satellite="Aqua", frp=800.0),
        dict(acq_date="2024-01-15", frp=0.0),
        dict(acq_date="2024-01-15", satellite="Aqua", frp=60.0),
        dict(acq_date="2024-01-16", frp=60.0),
        dict(acq_date="2024-01-16", satellite="Aqua", frp=0.0),
        dict(acq_date="2024-02-01", frp=2.0),
        dict(acq_date="2024-02-01", satellite="Aqua", frp=8.0),
    ])
    staged = ingest.ingest_raw_firms(output_path=tmp_path / "staged.parquet")
    outages.build_outages_table(staged)
    ratios = pq.read_table(tmp_path / "data/lookup/diurnal_ratios.parquet").to_pylist()
    assert len(ratios) == 2
    assert [(row["month"], row["matched_days"], row["ratio"]) for row in ratios] == [
        (1, 3, 2.5), (2, 1, 4.0)]


@pytest.mark.parametrize("matched_days", [3, 5])
def test_stage04_diurnal_scaling_terra_to_aqua(phase2_etl, tmp_path, matched_days):
    ingest, _, builder = phase2_etl
    write_phase2_csv(tmp_path / "data/raw/archive.csv", [
        dict(acq_date=f"2024-{month:02d}-10", satellite=sensor)
        for month in (1, 2, 3) for sensor in ("Terra", "Aqua")
    ])
    staged = ingest.ingest_raw_firms(output_path=tmp_path / "staged.parquet")
    cell = h3.latlng_to_cell(40.0, -4.0, 7)
    parent = int(h3.cell_to_parent(cell, 4), 16)
    pq.write_table(pa.Table.from_pylist([
        dict(h3_r4=parent, month=1, ratio=2.5, matched_days=matched_days),
        dict(h3_r4=parent, month=2, ratio=2.5, matched_days=2),
    ]), tmp_path / "data/lookup/diurnal_ratios.parquet")
    path = builder.build_master_cube(staged, tmp_path / "cube.parquet")
    base = 10.0 * 3600 / h3.cell_area(cell, unit="km^2") * w_orb(cell)
    rows = pq.read_table(path).to_pylist()
    assert len(rows) == 3
    for row, factor in zip(rows, (2.5, 1.0, 1.0)):
        assert row["obs_terra_fre"] == pytest.approx(base * factor)
        assert row["obs_aqua_fre"] == pytest.approx(base)


def test_stage04_neighbor_lag1_alignment(phase2_etl, tmp_path):
    ingest, _, builder = phase2_etl
    cell_a = h3.latlng_to_cell(40.0, -4.0, 7)
    cell_b = sorted(set(h3.grid_disk(cell_a, 1)) - {cell_a})[0]
    lat_b, lon_b = h3.cell_to_latlng(cell_b)
    # Use a valid 2024 UTC epoch rather than day 100 after 1970 (outside FIRMS coverage).
    write_phase2_csv(tmp_path / "data/raw/archive.csv", [
        dict(acq_time="2359", frp=10.0),
    ] + [
        dict(latitude=lat_b, longitude=lon_b, acq_date=day, acq_time="0000", frp=20.0)
        for day in ("2024-01-10", "2024-01-11", "2024-01-12")
    ])
    staged = ingest.ingest_raw_firms(output_path=tmp_path / "staged.parquet")
    path = builder.build_master_cube(staged, tmp_path / "cube.parquet")
    rows = sorted((row for row in pq.read_table(path).to_pylist() if row["h3_r7"] == int(cell_b, 16)),
                  key=lambda row: row["epoch_day"])
    assert len(rows) == 3
    expected = 10.0 * 3600 / h3.cell_area(cell_a, unit="km^2") * w_orb(cell_a)
    assert [row["neighbor_fre_lag1"] for row in rows] == pytest.approx([0.0, expected, 0.0])
    assert [row["epoch_day"] for row in rows] == [19732, 19733, 19734]


@pytest.mark.parametrize("powers", [(10.0, 0.0), (10.0, 30.0), (0.0, 0.0)])
def test_stage04_neighbor_lag_averages_only_active_burning_cells(phase2_etl, tmp_path, powers):
    ingest, _, builder = phase2_etl
    target = h3.latlng_to_cell(40.0, -4.0, 7)
    neighbors = sorted(set(h3.grid_disk(target, 1)) - {target})[:2]
    records = [dict(acq_date="2024-01-11")]
    expected_energy = []
    for cell, power in zip(neighbors, powers):
        lat, lon = h3.cell_to_latlng(cell)
        records.append(dict(latitude=lat, longitude=lon, frp=power))
        if power > 0:
            expected_energy.append(power * 3600 / h3.cell_area(cell, unit="km^2") * w_orb(cell))
    write_phase2_csv(tmp_path / "data/raw/archive.csv", records)
    staged = ingest.ingest_raw_firms(output_path=tmp_path / "staged.parquet")
    path = builder.build_master_cube(staged, tmp_path / "cube.parquet")
    rows = pq.read_table(path).to_pylist()
    row = next(row for row in rows if row["h3_r7"] == int(target, 16))
    expected = sum(expected_energy) / len(expected_energy) if expected_energy else 0.0
    assert row["neighbor_fre_lag1"] == pytest.approx(expected)
    for source in (row for row in rows if row["h3_r7"] != int(target, 16)):
        assert source["gap_status_mask"] == 0  # Measured zero is not a blackout.


def test_phase2_csv_to_cube_preserves_energy_and_empirical_scaling(phase2_etl, tmp_path):
    ingest, outages, builder = phase2_etl
    raw = tmp_path / "data/raw"
    records = [dict(acq_date=day, acq_time=time, satellite=sensor, frp=power)
               for day in ("2024-01-10", "2024-01-11", "2024-01-12")
               for time, sensor, power in (("1030", "Terra", 10.0), ("1130", "Terra", 20.0),
                                           ("1330", "Aqua", 75.0))]
    write_phase2_csv(raw / "z_archive.csv", records + [records[0]])
    write_phase2_csv(raw / "a_nrt.csv", [records[0] | {"frp": 999.0}])
    staged = ingest.ingest_raw_firms(output_path=tmp_path / "staged.parquet")
    assert pq.read_table(staged).num_rows == 9
    outages.build_outages_table(staged)
    ratio = pq.read_table(tmp_path / "data/lookup/diurnal_ratios.parquet").to_pylist()
    assert len(ratio) == 1 and ratio[0]["matched_days"] == 3 and ratio[0]["ratio"] == 2.5
    path = builder.build_master_cube(staged, tmp_path / "cube.parquet")
    rows = pq.read_table(path).to_pylist()
    cell = h3.latlng_to_cell(40.0, -4.0, 7)
    expected = 75.0 * 3600 / h3.cell_area(cell, unit="km^2") * w_orb(cell)
    assert len(rows) == 3
    for row in rows:
        assert row["raw_modis_cnt"] == 3 and row["raw_frp_mw"] == 105.0
        assert row["obs_terra_fre"] == pytest.approx(expected)
        assert row["obs_aqua_fre"] == pytest.approx(expected)
        assert row["neighbor_fre_lag1"] == 0.0


def write_orbital_regions(tmp_path):
    """Register an equatorial and a 60° N fixture region (bounds: west, south, east, north)."""
    regions = {name: {"bounds": bounds, "nominal_biome": 8, "coverage": [["2024-01-01", "2024-12-31"]]}
               for name, bounds in (("equator", [-61, -1, -59, 1]), ("subarctic", [9, 59, 11, 61]))}
    (tmp_path / "data/regions.json").write_text(json.dumps(regions), encoding="utf-8")


@pytest.mark.parametrize("latitude,expected", [
    (0.0, 1.0), (60.0, 0.5), (-60.0, 0.5),
    (85.0, float(np.cos(np.radians(80.0)))), (-89.0, float(np.cos(np.radians(80.0)))),
])
def test_stage04_orbital_weight_normalization_and_polar_clamp(phase2_etl, latitude, expected):
    _, _, builder = phase2_etl
    cell = h3.latlng_to_cell(latitude, 10.0, 7)
    weight = builder.orbital_weight(int(cell, 16))
    assert weight == pytest.approx(w_orb(cell), abs=1e-12)
    assert weight == pytest.approx(expected, abs=2e-3)  # Centroid is within ~1.3 km of the input point.
    assert np.cos(np.radians(80.0)) <= weight <= 1.0


def test_stage04_orbital_revisit_weighting_equator_vs_high_latitude(phase2_etl, tmp_path):
    ingest, _, builder = phase2_etl
    write_orbital_regions(tmp_path)
    points = {"equator": (0.0, -60.0), "subarctic": (60.0, 10.0)}
    write_phase2_csv(tmp_path / "data/raw/archive.csv", [
        dict(latitude=lat, longitude=lon, satellite=sensor, frp=40.0)
        for lat, lon in points.values() for sensor in ("Terra", "Aqua", "SNPP")
    ])
    staged = ingest.ingest_raw_firms(output_path=tmp_path / "staged.parquet")
    path = builder.build_master_cube(staged, tmp_path / "cube.parquet")
    table = pq.read_table(path)
    rows = {row["h3_r7"]: row for row in table.to_pylist()}
    assert len(rows) == 2
    ratios = {}
    for name, (lat, lon) in points.items():
        cell = h3.latlng_to_cell(lat, lon, 7)
        row = rows[int(cell, 16)]
        unweighted = 40.0 * 3600 / h3.cell_area(cell, unit="km^2")
        centroid_lat = h3.cell_to_latlng(cell)[0]
        for field in ("obs_terra_fre", "obs_aqua_fre", "obs_viirs_fre"):
            assert row[field] == pytest.approx(unweighted * np.cos(np.radians(centroid_lat)), rel=1e-6)
        assert row["raw_frp_mw"] == 120.0  # Raw provenance remains unweighted.
        ratios[name] = row["obs_aqua_fre"] / unweighted
    # Applied exactly once: cos(φ), never cos²(φ) and never sec(φ).
    assert ratios["equator"] == pytest.approx(1.0, abs=1e-4)
    assert ratios["subarctic"] == pytest.approx(0.5, abs=2e-3)
    assert ratios["subarctic"] != pytest.approx(0.25, abs=0.05)
    assert b"cos(centroid_lat_h3_r7)" in table.schema.metadata[b"orbital_weighting"]


def test_stage04_orbital_weight_and_terra_diurnal_orthogonality(phase2_etl, tmp_path):
    ingest, _, builder = phase2_etl
    write_orbital_regions(tmp_path)
    cell = h3.latlng_to_cell(60.0, 10.0, 7)
    neighbor = sorted(set(h3.grid_disk(cell, 1)) - {cell})[0]
    lat_n, lon_n = h3.cell_to_latlng(neighbor)
    write_phase2_csv(tmp_path / "data/raw/archive.csv", [
        dict(latitude=60.0, longitude=10.0, satellite=sensor, frp=frp)
        for sensor, frp in (("Terra", 10.0), ("Aqua", 20.0), ("SNPP", 30.0), ("N20", 50.0))
    ] + [dict(latitude=lat_n, longitude=lon_n, acq_date="2024-01-11", satellite="Aqua", frp=1.0)])
    staged = ingest.ingest_raw_firms(output_path=tmp_path / "staged.parquet")
    pq.write_table(pa.Table.from_pylist([
        dict(h3_r4=int(h3.cell_to_parent(cell, 4), 16), month=1, ratio=2.0, matched_days=3),
    ]), tmp_path / "data/lookup/diurnal_ratios.parquet")
    path = builder.build_master_cube(staged, tmp_path / "cube.parquet")
    rows = {row["h3_r7"]: row for row in pq.read_table(path).to_pylist()}
    row = rows[int(cell, 16)]
    weight = float(np.cos(np.radians(h3.cell_to_latlng(cell)[0])))
    assert weight == pytest.approx(0.5, abs=2e-3)
    scale = 3600 / h3.cell_area(cell, unit="km^2")
    terra = 10.0 * scale * 2.0 * weight
    aqua = 20.0 * scale * weight
    viirs = (30.0 + 50.0) / 2 * scale * weight
    assert row["obs_terra_fre"] == pytest.approx(terra, rel=1e-6)
    assert row["obs_aqua_fre"] == pytest.approx(aqua, rel=1e-6)
    assert row["obs_viirs_fre"] == pytest.approx(viirs, rel=1e-6)
    # Lag energy inherits the channel weights and is not weighted again.
    lag = rows[int(neighbor, 16)]["neighbor_fre_lag1"]
    assert lag == pytest.approx((terra + aqua + viirs) / 3, rel=1e-6)

def run_outage_cli(staged, output, counts=None):
    command = [sys.executable, str(ROOT / "scripts/02_detect_outages_clouds.py"),
               "--staged", str(staged), "--output-dir", str(output)]
    if counts is not None:
        command.extend(["--global-counts", str(counts)])
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True)


SNPP_OUTAGE = [date(2022, 7, 27) + timedelta(days=i) for i in range(15)]  # 2022-07-27..2022-08-10


def test_stage02_tracked_global_counts_validate_the_known_snpp_outage(tmp_path):
    """Real FIRMS world counts: the detector must find exactly the documented SNPP interval."""
    counts = ROOT / "data/lookup/global_daily_counts.csv"
    with counts.open(encoding="utf-8") as stream:
        records = list(csv.DictReader(stream))
    keys = {(r["satellite"], r["acq_date"]) for r in records}
    assert len(keys) == len(records) == 4 * 50
    assert {r["satellite"] for r in records} == {"Terra", "Aqua", "SNPP", "N20"}
    zero = sorted(date.fromisoformat(r["acq_date"]) for r in records if int(r["detection_count"]) == 0)
    assert zero == SNPP_OUTAGE and all(r["satellite"] == "SNPP" for r in records
                                       if int(r["detection_count"]) == 0)
    result = run_outage_cli(tmp_path / "missing.parquet", tmp_path, counts)
    assert result.returncode == 0, result.stderr
    rows = pq.read_table(tmp_path / "sensor_outages.parquet").to_pylist()
    dynamic = [(r["acq_date"], r["satellite"]) for r in rows if r["evidence"] == "global_count_drop"]
    known = [(r["acq_date"], r["satellite"]) for r in rows if r["evidence"] == "known_outage"]
    assert dynamic == known == [(day, "SNPP") for day in SNPP_OUTAGE]


def test_stage02_known_snpp_interval_is_exact_and_reproducible(tmp_path):
    staged = tmp_path / "staged.parquet"
    # A local detection drop must never be treated as a global outage.
    pq.write_table(pa.Table.from_pylist([
        dict(h3_r4=1, acq_date=date(2022, 1, 1) + timedelta(days=i),
             satellite=sensor, daynight="D", corrected_frp=power)
        for i in range(16) for sensor, power in (("Terra", 10.0), ("Aqua", 20.0))
        if i < 15 or sensor == "Aqua"
    ]), staged)
    output = tmp_path / "lookup"
    result = run_outage_cli(staged, output)
    assert result.returncode == 0, result.stderr
    paths = [output / name for name in ("sensor_outages.parquet", "diurnal_ratios.parquet")]
    first = [path.read_bytes() for path in paths]
    # No --global-counts: the tracked lookup is used, so both evidence kinds cover the same days.
    expected = [dict(acq_date=day, satellite="SNPP", evidence=evidence)
                for day in SNPP_OUTAGE for evidence in ("global_count_drop", "known_outage")]
    actual = pq.read_table(paths[0])
    assert [(field.name, field.type) for field in actual.schema] == [
        ("acq_date", pa.date32()), ("satellite", pa.string()), ("evidence", pa.string())]
    assert actual.to_pylist() == expected
    assert pq.read_table(paths[1]).to_pylist() == [
        dict(h3_r4=1, month=1, ratio=2.0, matched_days=15)]
    for _ in range(2):
        result = run_outage_cli(staged, output)
        assert result.returncode == 0, result.stderr
        assert [path.read_bytes() for path in paths] == first


@pytest.mark.parametrize("history,current,expected", [
    ([100.0] * 15, 24.0, True),
    ([100.0] * 15, 25.0, False),
    ([100.0] * 15, 0.0, True),
    ([100.0] * 14 + [0.0], 24.0, False),
    ([100.0] * 14 + [0.0], 23.0, True),
    ([0.0] * 15, 0.0, False),
    ([100.0] * 14, 0.0, False),
    ([100.0] * 7 + [None] + [100.0] * 7, 0.0, False),
    ([100.0] * 15, None, False),
])
def test_stage02_global_counts_complete_window(tmp_path, history, current, expected):
    target = date(2022, 2, 1)
    records = [dict(satellite="Terra", acq_date=target - timedelta(days=len(history) - i),
                    detection_count=count) for i, count in enumerate(history)]
    records.append(dict(satellite="Terra", acq_date=target, detection_count=current))
    # A second instrument cannot contribute days to Terra's baseline.
    records.extend(dict(satellite="SNPP", acq_date=target - timedelta(days=i),
                        detection_count=1000.0) for i in range(16))
    counts = tmp_path / "global.parquet"
    pq.write_table(pa.Table.from_pylist(records), counts)
    result = run_outage_cli(tmp_path / "missing.parquet", tmp_path, counts)
    assert result.returncode == 0, result.stderr
    dynamic = [row for row in pq.read_table(tmp_path / "sensor_outages.parquet").to_pylist()
               if row["evidence"] == "global_count_drop"]
    assert dynamic == ([dict(acq_date=target, satellite="Terra", evidence="global_count_drop")]
                       if expected else [])
    assert pq.read_table(tmp_path / "diurnal_ratios.parquet").num_rows == 0


def test_stage02_missing_calendar_day_does_not_trigger(tmp_path):
    target = date(2022, 2, 1)
    records = [dict(satellite="Terra", acq_date=target - timedelta(days=i), detection_count=100)
               for i in range(1, 17) if i != 7]
    records.append(dict(satellite="Terra", acq_date=target, detection_count=0))
    counts = tmp_path / "global.parquet"
    pq.write_table(pa.Table.from_pylist(records), counts)
    result = run_outage_cli(tmp_path / "missing.parquet", tmp_path, counts)
    assert result.returncode == 0, result.stderr
    assert set(pq.read_table(tmp_path / "sensor_outages.parquet")["evidence"].to_pylist()) == {
        "known_outage"}


def test_stage02_duplicate_days_cannot_fake_a_complete_window(tmp_path):
    target = date(2022, 2, 1)
    records = [dict(satellite="Terra", acq_date=target - timedelta(days=i), detection_count=100)
               for i in range(1, 15)]
    records.extend([records[0], dict(satellite="Terra", acq_date=target, detection_count=0)])
    counts = tmp_path / "global.parquet"
    pq.write_table(pa.Table.from_pylist(records), counts)
    existing = tmp_path / "sensor_outages.parquet"
    existing.write_bytes(b"previous lookup")
    result = run_outage_cli(tmp_path / "missing.parquet", tmp_path, counts)
    assert result.returncode != 0
    assert "Duplicate global count" in result.stderr
    assert existing.read_bytes() == b"previous lookup"


def write_global_counts(path, records):
    if path.suffix == ".csv":
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["satellite", "acq_date", "detection_count"])
            writer.writeheader()
            writer.writerows(records)
    else:
        pq.write_table(pa.Table.from_pylist(records), path)


def n20_drop_records(target):
    records = [dict(satellite="N20", acq_date=target - timedelta(days=i), detection_count=100)
               for i in range(15, 0, -1)]
    return records + [dict(satellite="N20", acq_date=target, detection_count=3)]


@pytest.mark.parametrize("suffix", [".csv", ".parquet"])
def test_stage02_global_counts_accept_csv_and_parquet(tmp_path, suffix):
    target = date(2022, 2, 1)
    counts = tmp_path / f"global{suffix}"
    write_global_counts(counts, n20_drop_records(target))
    result = run_outage_cli(tmp_path / "missing.parquet", tmp_path, counts)
    assert result.returncode == 0, result.stderr
    dynamic = [row for row in pq.read_table(tmp_path / "sensor_outages.parquet").to_pylist()
               if row["evidence"] == "global_count_drop"]
    assert dynamic == [dict(acq_date=target, satellite="N20", evidence="global_count_drop")]


def test_stage02_defaults_to_tracked_global_counts(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    outages = import_module("02_detect_outages_clouds")
    monkeypatch.setattr(outages, "ROOT", tmp_path)
    target = date(2022, 2, 1)
    (tmp_path / "data/lookup").mkdir(parents=True)
    write_global_counts(tmp_path / outages.GLOBAL_COUNTS, n20_drop_records(target))
    outages.build_outages_table(tmp_path / "absent.parquet", "out")
    rows = pq.read_table(tmp_path / "out/sensor_outages.parquet").to_pylist()
    assert dict(acq_date=target, satellite="N20", evidence="global_count_drop") in rows


@pytest.fixture
def stage04_inputs(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    builder = import_module("04_build_master_cube")
    outages = import_module("02_detect_outages_clouds")
    lookup = tmp_path / "lookup"
    outages.build_outages_table(tmp_path / "absent.parquet", lookup)
    (lookup / "eqm_gpd_lut.json").write_text('{"models": {}}', encoding="utf-8")
    center = h3.latlng_to_cell(40.0, -4.0, 7)
    neighbor = next(cell for cell in h3.grid_disk(center, 1) if cell != center)
    days = [date(2022, 7, 30) + timedelta(days=i) for i in range(19)]
    records = [dict(h3_r4=int(h3.cell_to_parent(cell, 4), 16), h3_r7=int(cell, 16),
                    acq_date=day, satellite=sensor, sensor_bit=bit, igbp_biome=8, scan_bin=0,
                    corrected_frp=10.0, is_center=True, frp=10.0, industrial_prob=0.0,
                    region="iberia_med", daynight="D")
               for cell in (center, neighbor) for day in days
               for sensor, bit in (("Terra", 1), ("Aqua", 2), ("SNPP", 4), ("N20", 8), ("N21", 16))]
    staged = tmp_path / "staged.parquet"
    pq.write_table(pa.Table.from_pylist([dict(record, confidence_norm="high", source_file="fixture.csv") for record in records]), staged)
    return builder, staged, lookup, int(center, 16), int(neighbor, 16)


def test_stage04_snpp_outage_and_five_instrument_bits(stage04_inputs, tmp_path):
    builder, staged, lookup, center, neighbor = stage04_inputs
    path = builder.build_master_cube(staged, tmp_path / "cube.parquet", lookup_dir=lookup)
    table = pq.read_table(path)
    assert [(f.name, f.type) for f in table.schema] == EXPECTED
    assert table.num_rows == 38
    outage_rows = 0
    for row in table.to_pylist():
        day = date(1970, 1, 1) + timedelta(days=row["epoch_day"])
        outage = day in SNPP_OUTAGE
        outage_rows += outage
        assert row["sensor_obs_mask"] == (27 if outage else 31)
        assert row["gap_status_mask"] == (1 if outage else 0)
        # Aqua is never removed; NOAA-20/21 keep the VIIRS channel alive during the SNPP outage.
        assert row["obs_terra_fre"] > 0 and row["obs_aqua_fre"] > 0 and row["obs_viirs_fre"] > 0
        assert row["raw_modis_cnt"] == 2 and row["raw_viirs_cnt"] == 3
    assert outage_rows == 2 * 12  # fixture days 2022-07-30..08-10 inside the outage, two cells


def test_stage04_viirs_outages_preserve_remaining_instrument(stage04_inputs, tmp_path):
    builder, staged, lookup, center, neighbor = stage04_inputs
    path = lookup / "sensor_outages.parquet"
    records = pq.read_table(path).to_pylist()
    # SNPP is already out on both days (known outage); remove the other instruments around N21.
    for day, sensors in ((date(2022, 8, 1), ("Terra", "Aqua", "N20")),
                         (date(2022, 8, 2), ("Terra", "Aqua", "N20", "N21"))):
        records.extend(dict(acq_date=day, satellite=sensor, evidence="global_count_drop")
                       for sensor in sensors)
    pq.write_table(pa.Table.from_pylist(records), path)
    cube = builder.build_master_cube(staged, tmp_path / "cube.parquet", lookup_dir=lookup)
    rows = {r["epoch_day"]: r for r in pq.read_table(cube).to_pylist() if r["h3_r7"] == center}
    first = rows[(date(2022, 8, 1) - date(1970, 1, 1)).days]
    assert first["sensor_obs_mask"] == 16 and first["gap_status_mask"] == 1
    assert first["obs_terra_fre"] is None and first["obs_aqua_fre"] is None
    assert first["obs_viirs_fre"] > 0
    second = rows[(date(2022, 8, 2) - date(1970, 1, 1)).days]
    assert second["sensor_obs_mask"] == 0 and second["gap_status_mask"] == 9
    assert all(second[field] is None for field in ("obs_terra_fre", "obs_aqua_fre", "obs_viirs_fre"))


@pytest.mark.parametrize("cloud,mask,missing", [(0.0, 0, False), (0.8, 0, False),
                                               (0.8001, 10, True), (1.0, 10, True)])
@pytest.mark.parametrize("cloud_type", [pa.float32(), pa.float64()])
def test_stage04_cloud_masks_observations_before_neighbor_lag(stage04_inputs, tmp_path,
                                                           cloud, mask, missing, cloud_type):
    builder, staged, lookup, center, neighbor = stage04_inputs
    ancillary_schema = pa.schema([
        ("h3_r7", pa.uint64()), ("acq_date", pa.date32()),
        ("cloud_cover_pct", cloud_type), ("burned_area_ha_mcd64", pa.float32()),
    ])
    pq.write_table(pa.Table.from_pylist([
        dict(h3_r7=center, acq_date=date(2022, 8, 10), cloud_cover_pct=cloud,
             burned_area_ha_mcd64=0.0),
        dict(h3_r7=center, acq_date=date(2022, 8, 11), cloud_cover_pct=cloud,
             burned_area_ha_mcd64=0.0),
    ], schema=ancillary_schema), lookup / "cell_day_ancillary.parquet")
    path = builder.build_master_cube(staged, tmp_path / "cube.parquet", lookup_dir=lookup)
    rows = {(r["h3_r7"], r["epoch_day"]): r for r in pq.read_table(path).to_pylist()}
    epoch = (date(2022, 8, 10) - date(1970, 1, 1)).days  # last SNPP outage day, then recovery
    for offset, outage_bit in ((0, 1), (1, 0)):
        row = rows[center, epoch + offset]
        assert row["gap_status_mask"] == mask | outage_bit
        assert row["sensor_obs_mask"] == (0 if missing else (27 if outage_bit else 31))
        for field in ("obs_terra_fre", "obs_aqua_fre", "obs_viirs_fre"):
            assert (row[field] is None) == missing
        assert row["raw_modis_cnt"] == 2 and row["raw_viirs_cnt"] == 3
    lag = rows[neighbor, epoch + 1]["neighbor_fre_lag1"]
    assert (lag == 0.0) if missing else (lag > 0.0)


def test_stage04_ancillary_metadata_distinguishes_missing_and_observed_zero(stage04_inputs, tmp_path):
    builder, staged, lookup, center, neighbor = stage04_inputs
    path = builder.build_master_cube(staged, tmp_path / "cube.parquet", lookup_dir=lookup)
    absent = json.loads(pq.read_schema(path).metadata[b"ancillary_coverage"])
    assert absent["input_present"] is False
    assert absent["cloud_cover_pct"] == {"observed_rows": 0, "missing_rows": 38, "observed_zero_rows": 0}
    pq.write_table(pa.Table.from_pylist([
        dict(h3_r7=center, acq_date=date(2022, 7, 30), cloud_cover_pct=0.0, burned_area_ha_mcd64=0.0),
        dict(h3_r7=neighbor, acq_date=date(2022, 7, 30), cloud_cover_pct=None, burned_area_ha_mcd64=2.0),
    ]), lookup / "cell_day_ancillary.parquet")
    builder.build_master_cube(staged, path, lookup_dir=lookup)
    present = json.loads(pq.read_schema(path).metadata[b"ancillary_coverage"])
    assert present["input_present"] is True
    assert present["cloud_cover_pct"] == {"observed_rows": 1, "missing_rows": 37, "observed_zero_rows": 1}
    assert present["burned_area_ha_mcd64"] == {"observed_rows": 2, "missing_rows": 36, "observed_zero_rows": 1}

def test_missing_staging_preserves_existing_master(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    builder = import_module("04_build_master_cube")
    master = tmp_path / "fire_cube.parquet"
    master.write_bytes(b"existing master")
    with pytest.raises(FileNotFoundError, match="staged"):
        builder.build_master_cube(tmp_path / "missing.parquet", master)
    assert master.read_bytes() == b"existing master"


def test_mock_and_request_contract():
    from backend.api.routes import analyze
    response = AnalyzeResponse.model_validate_json(analyze(AnalyzeRequest(aoi=GeoJSONPolygon(
        coordinates=[[[-69.5,-31],[-65.5,-31],[-65.5,-27.5],[-69.5,-27.5],[-69.5,-31]]]), forecast_days=0)).body)
    assert response.data_source == "synthetic"
    assert response.calendar_series and all(not c.is_forecast for c in response.calendar_series)
    aoi = GeoJSONPolygon(coordinates=[[[-6, 38], [-4, 38], [-4, 40], [-6, 38]]])
    assert AnalyzeRequest(aoi=aoi).forecast_days == 14
    assert ChaosMonkeyRequest(aoi=aoi).drop_fraction == .25
    with pytest.raises(ValidationError):
        AnalyzeRequest(aoi=aoi, forecast_days=15)
    with pytest.raises(ValidationError):
        AnalyzeRequest(aoi=aoi, start_year=2025, end_year=2020)

EXPECTED = [
    ("h3_r4",pa.uint64()),("h3_r7",pa.uint64()),("epoch_day",pa.uint16()),
    ("year",pa.uint16()),("doy",pa.uint16()),("igbp_biome",pa.uint8()),
    ("sensor_obs_mask",pa.uint8()),("gap_status_mask",pa.uint8()),
    ("cloud_cover_pct",pa.float32()),("raw_modis_cnt",pa.uint16()),
    ("raw_viirs_cnt",pa.uint16()),("raw_frp_mw",pa.float32()),
    ("obs_terra_fre",pa.float32()),("obs_aqua_fre",pa.float32()),
    ("obs_viirs_fre",pa.float32()),("neighbor_fre_lag1",pa.float32()),
    ("industrial_prob",pa.float32()),("burned_area_ha_mcd64",pa.float32()),
]


@pytest.fixture(scope="module")
def cube_path(tmp_path_factory):
    return bootstrap.generate_bootstrap_cube(
        tmp_path_factory.mktemp("cube_schema") / "fire_cube_synthetic.parquet"
    )


@pytest.fixture(scope="module")
def cube(cube_path):
    return pq.read_table(cube_path)


def test_exact_schema_and_compression(cube, cube_path):
    assert [(f.name,f.type) for f in cube.schema] == EXPECTED
    with duckdb.connect() as con:
        columns = con.execute("DESCRIBE SELECT * FROM read_parquet(?)",
                              [str(cube_path)]).fetchall()
    sql_types = ["UBIGINT", "UBIGINT", "USMALLINT", "USMALLINT", "USMALLINT",
                 "UTINYINT", "UTINYINT", "UTINYINT", "FLOAT", "USMALLINT", "USMALLINT"] + ["FLOAT"] * 7
    assert [(row[0], row[1]) for row in columns] == [(name, typ) for (name, _), typ in zip(EXPECTED, sql_types)]
    assert [f.name for f in cube.schema if f.nullable] == ["obs_terra_fre","obs_aqua_fre","obs_viirs_fre"]
    parquet = pq.ParquetFile(cube_path)
    for i in range(parquet.metadata.num_row_groups):
        for j in range(18):
            assert parquet.metadata.row_group(i).column(j).compression == "ZSTD"
    assert b"SYNTHETIC" in cube.schema.metadata[b"source"]


def test_sorted_and_unique(cube):
    r4,day,r7 = [cube[n].to_numpy() for n in ["h3_r4","epoch_day","h3_r7"]]
    order = np.lexsort((r7,day,r4))
    assert np.array_equal(order,np.arange(len(day)))
    assert len(set(zip(r7.tolist(),day.tolist()))) == len(day)


def test_four_regions_and_daily_coverage(cube):
    cells = cube["h3_r7"].to_numpy()
    expected = set()
    days = np.arange(np.datetime64("2001-01-01"), np.datetime64("2027-01-01"))
    for name, (lat, lon, _, _) in bootstrap.REGIONS.items():
        regional = bootstrap.region_cells(lat, lon)
        assert len(regional) == len(set(regional)) == 10
        west, south, east, north = bootstrap.REGION_BOUNDS[name]
        for cell in regional:
            h = int(cell, 16)
            expected.add(h)
            center_lat, center_lon = (h3.cell_to_latlng(cell) if hasattr(h3, "cell_to_latlng")
                                      else h3.h3_to_geo(cell))
            assert south <= center_lat <= north and west <= center_lon <= east
            selected = cube.filter(pc.equal(cube["h3_r7"], h))
            assert len(selected) == 9496
            assert np.all(selected["h3_r4"].to_numpy() == bootstrap._h3_to_parent_int(h, 4))
            assert np.array_equal(selected["epoch_day"].to_numpy(), days.astype(int))
    assert set(cells.tolist()) == expected
    assert len(cube) == 40 * 9496 == len(days) * len(expected)


def test_calendar_keys_and_value_ranges(cube):
    dates = np.datetime64("1970-01-01") + cube["epoch_day"].to_numpy().astype("timedelta64[D]")
    assert np.array_equal(dates.astype("datetime64[Y]").astype(int) + 1970, cube["year"].to_numpy())
    assert np.array_equal((dates - dates.astype("datetime64[Y]")).astype(int) + 1, cube["doy"].to_numpy())
    assert np.all((cube["igbp_biome"].to_numpy() >= 1) & (cube["igbp_biome"].to_numpy() <= 17))
    for field in cube.schema:
        values = cube[field.name].to_numpy()
        if not field.nullable:
            assert cube[field.name].null_count == 0
            assert np.isfinite(values).all()
        if pa.types.is_floating(field.type):
            assert np.all(values[np.isfinite(values)] >= 0)
    for name in ["cloud_cover_pct", "industrial_prob"]:
        assert np.all(cube[name].to_numpy() <= 1.0)


def test_outages_and_sensor_masks(cube):
    days = cube["epoch_day"].to_numpy()
    def between(start, end):
        return (days >= np.datetime64(start).astype(int)) & (days <= np.datetime64(end).astype(int))
    aqua = between("2022-07-31", "2022-08-16")
    black = between("2022-08-22", "2022-08-26")
    flags = cube["gap_status_mask"].to_numpy()
    obs = np.column_stack([cube[n].to_numpy() for n in ["obs_terra_fre", "obs_aqua_fre", "obs_viirs_fre"]])
    assert aqua.sum() == 17 * 40 and black.sum() == 5 * 40
    assert np.isnan(obs[aqua, 1]).all() and np.isfinite(obs[aqua][:, [0, 2]]).all()
    assert np.all(flags[aqua] == 1) and np.all(flags[black] == 8)
    assert np.isnan(obs[black]).all()
    assert np.all(cube["cloud_cover_pct"].to_numpy()[black] == np.float32(.95))
    assert np.array_equal(np.sum(np.isfinite(obs) * [1, 2, 4], axis=1), cube["sensor_obs_mask"].to_numpy())
    assert np.all(flags[~(aqua | black)] == 0)


@pytest.mark.parametrize("date,sensors", [
    ("2022-08-10", ["obs_aqua_fre"]),
    ("2022-08-24", ["obs_terra_fre", "obs_aqua_fre", "obs_viirs_fre"]),
])
def test_required_outage_dates_in_duckdb(cube_path, date, sensors):
    day = int(np.datetime64(date).astype(int))
    condition = " AND ".join(f"({s} IS NULL OR isnan({s}))" for s in sensors)
    with duckdb.connect() as con:
        total, missing = con.execute(
            f"SELECT count(*), count(*) FILTER (WHERE {condition}) "
            "FROM read_parquet(?) WHERE epoch_day = ?",
            [str(cube_path), day],
        ).fetchone()
    assert total == missing == 40


def test_instrumental_jump_and_physical_stability(cube):
    dates = cube["epoch_day"].to_numpy()
    years = cube["year"].to_numpy()
    modis = cube["raw_modis_cnt"].to_numpy().astype(np.float64)
    viirs = cube["raw_viirs_cnt"].to_numpy().astype(np.float64)
    before = dates < np.datetime64("2012-01-20").astype(int)
    assert np.all(viirs[before] == 0)
    assert np.isnan(cube["obs_viirs_fre"].to_numpy()[before]).all()
    assert np.isfinite(cube["obs_viirs_fre"].to_numpy()[dates == np.datetime64("2012-01-20").astype(int)]).all()
    assert np.mean(viirs[~before]) > 0
    # Full years compare equal seasonal exposure, while the exact-date checks
    # above catch accidental January 1 activation.
    pre, post = years < 2012, years >= 2012
    raw_ratio = np.mean((modis + viirs)[post]) / np.mean((modis + viirs)[pre])
    assert 4.2 < raw_ratio < 4.8
    terra = cube["obs_terra_fre"].to_numpy()
    for sensor in ["obs_terra_fre", "obs_aqua_fre"]:
        values = cube[sensor].to_numpy()
        assert .95 < np.nanmean(values[post]) / np.nanmean(values[pre]) < 1.05
    for sensor in ["obs_aqua_fre", "obs_viirs_fre"]:
        values = cube[sensor].to_numpy()
        available = np.isfinite(values) & np.isfinite(terra)
        assert .98 < np.mean(values[available]) / np.mean(terra[available]) < 1.02
    # Compare the same calendar window across the launch boundary.
    for lo, hi in [("2011-01-20", "2011-02-19"), ("2012-01-20", "2012-02-19")]:
        selected = (dates >= np.datetime64(lo).astype(int)) & (dates <= np.datetime64(hi).astype(int))
        if lo.startswith("2011"):
            raw_pre = np.mean((modis + viirs)[selected])
            harm_pre = np.mean(terra[selected])
        else:
            assert np.mean((modis + viirs)[selected]) / raw_pre > 3.0
            assert .9 < np.mean(terra[selected]) / harm_pre < 1.1


def test_industrial_and_climate_scenarios(cube):
    for name, (lat, lon, _, _) in bootstrap.REGIONS.items():
        industrial_count = 0
        for cell in bootstrap.region_cells(lat, lon):
            one = cube.filter(pc.equal(cube["h3_r7"], int(cell, 16)))
            energy = one["obs_terra_fre"].to_numpy()
            probability = one["industrial_prob"].to_numpy()
            if np.allclose(probability, .92):
                industrial_count += 1
                assert np.nanstd(energy) / np.nanmean(energy) < .04
                assert np.all(one["burned_area_ha_mcd64"].to_numpy() == 0)
                continue
            assert np.allclose(probability, .04)
            valid = np.isfinite(energy)
            assert np.corrcoef(energy[valid], one["burned_area_ha_mcd64"].to_numpy()[valid])[0, 1] ** 2 > .88
            years, days = one["year"].to_numpy(), one["doy"].to_numpy()
            peaks, widths = [], []
            for year in range(2001, 2027):
                mask = (years == year) & valid
                # Remove the year-round background to measure fire-season width.
                weights = np.maximum(energy[mask] - np.nanmin(energy[mask]), 0)
                z = np.sum(weights * np.exp(2j * np.pi * (days[mask] - 1) / 365.25)) / weights.sum()
                peaks.append(1 + (np.angle(z) % (2 * np.pi)) * 365.25 / (2 * np.pi))
                widths.append(np.sqrt(-2 * np.log(abs(z))) * 365.25 / (2 * np.pi))
            assert .70 < np.polyfit(np.arange(26), peaks, 1)[0] < .80
            assert 1.25 < widths[-1] / widths[0] < 1.35
        assert industrial_count == (6 if name == "amazonas_manaus" else 2)


def test_generator_repeatability_performance_and_alternate_path(tmp_path,cube):
    start=perf_counter()
    path=bootstrap.generate_bootstrap_cube(tmp_path/"repeat.parquet")
    assert isinstance(path, str)
    assert perf_counter()-start<3.0
    assert pq.read_table(path).equals(cube)
    # Exercise the unchanged CLI default in an isolated project, never in production.
    isolated = tmp_path / "isolated_project"
    (isolated / "data").mkdir(parents=True)
    (isolated / "data/regions.json").write_bytes((ROOT / "data/regions.json").read_bytes())
    script = isolated / "scripts/00_bootstrap_synthetic_cube.py"
    script.parent.mkdir(parents=True)
    script.write_bytes((ROOT / "scripts/00_bootstrap_synthetic_cube.py").read_bytes())
    result=subprocess.run([sys.executable,str(script)],cwd=tmp_path,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert "Synthetic cube:" in result.stdout
    generated = isolated / "data/processed/fire_cube_synthetic.parquet"
    assert str(generated) in result.stdout
    assert pq.read_table(generated).equals(cube)


@pytest.mark.parametrize("version", [3, 4])
def test_h3_compatibility_adapters(monkeypatch, version):
    from types import SimpleNamespace

    expected = bootstrap._latlng_to_h3_int(-16.9, -56.2, 7)
    expected_parent = bootstrap._h3_to_parent_int(expected, 4)
    def to_cell(lat, lon, res):
        assert (lat, lon, res) == (-16.9, -56.2, 7)
        return format(expected, "x")
    def to_parent(cell, res):
        assert cell == format(expected, "x") and res == 4
        return format(expected_parent, "x")
    adapter = ({"latlng_to_cell": to_cell, "cell_to_parent": to_parent} if version == 4
               else {"geo_to_h3": to_cell, "h3_to_parent": to_parent})
    monkeypatch.setattr(bootstrap, "h3", SimpleNamespace(**adapter))
    actual = bootstrap._latlng_to_h3_int(-16.9, -56.2, 7)
    parent = bootstrap._h3_to_parent_int(actual, 4)
    assert type(actual) is int and type(parent) is int
    assert actual == expected and parent == expected_parent
    assert 2**53 < actual < 2**64 and 0 <= parent < 2**64


# =====================================================================
# Phase 1: Numerical parity between ETL footprint / bow-tie and core
# =====================================================================

@pytest.mark.parametrize("label,latitude,longitude,scan,track,modis", [
    ("viirs_nadir_chilecito", -29.16, -67.5, 0.375, 0.375, False),
    ("viirs_nadir_iberia", 40.0, -4.0, 0.375, 0.375, False),
    ("viirs_nadir_orlando", 28.54, -81.38, 0.375, 0.375, False),
    ("viirs_nadir_amazonas", -3.10, -60.02, 0.375, 0.375, False),
    ("modis_nadir", 40.0, -4.0, 1.0, 1.0, True),
    ("modis_threshold_boundary", -29.16, -67.5, 3.5, 1.0, True),
    ("modis_deformed_chilecito", -29.16, -67.5, 3.6, 1.8, True),
    ("modis_deformed_iberia", 40.0, -4.0, 4.8, 2.0, True),
    ("modis_deformed_orlando", 28.54, -81.38, 3.8, 1.9, True),
    ("modis_deformed_amazonas", -3.10, -60.02, 4.8, 2.0, True),
    ("modis_deformed_antimeridian", 0.0, 179.999, 4.2, 1.9, True),
    ("modis_deformed_high_lat", 75.0, 25.0, 4.8, 2.0, True),
    ("modis_deformed_pantanal", -16.9, -56.2, 4.5, 2.0, True),
])
def test_phase1_footprint_and_bowtie_parity_etl_vs_core(label, latitude, longitude,
                                                         scan, track, modis):
    """Verify bit-level / numerical parity between scripts/01_ingest_firms.py and backend/core/footprint_h3.py."""
    ingest = import_module("01_ingest_firms")
    cell = h3.latlng_to_cell(latitude, longitude, 7)

    # 1. Direct ETL footprint vs Core footprint
    etl_weights = dict(ingest.footprint(latitude, longitude, cell, scan, track, modis))
    if not modis or scan * track <= 3.5:
        expected_weights = {format(int(cell, 16), "015x"): 1.0}
    else:
        expected_weights = footprint_h3.compute_elliptical_psf_weights(latitude, longitude, scan, track)

    assert set(etl_weights.keys()) == set(expected_weights.keys()), f"Cell mismatch for {label}"
    for k in etl_weights:
        assert etl_weights[k] == pytest.approx(expected_weights[k], abs=1e-12), f"Weight mismatch at {k} for {label}"
    assert sum(etl_weights.values()) == pytest.approx(1.0, abs=1e-12), f"Energy conservation violated for {label}"

    # 2. Bow-tie weight parity
    expected_bw = float(footprint_h3.compute_modis_bowtie_overlap_weight(track)) if modis else 1.0
    etl_bw = (1.0 / track if modis and track > 1.35 else 1.0)
    assert etl_bw == pytest.approx(expected_bw, abs=1e-12), f"Bow-tie weight mismatch for {label}"

    # 3. Fallback calculation parity (verify ETL fallback produces identical result without footprint_h3)
    if modis and scan * track > 3.5:
        orig = ingest.footprint_h3
        try:
            ingest.footprint_h3 = None
            fallback_weights = dict(ingest.footprint(latitude, longitude, cell, scan, track, modis))
        finally:
            ingest.footprint_h3 = orig
        assert set(fallback_weights.keys()) == set(expected_weights.keys())
        for k in fallback_weights:
            assert fallback_weights[k] == pytest.approx(expected_weights[k], abs=1e-12)
        assert sum(fallback_weights.values()) == pytest.approx(1.0, abs=1e-12)


def test_phase1_staged_parquet_preserves_footprint_and_bowtie_weights(phase2_etl, tmp_path):
    """Verify that staged Parquet written by ingest_raw_firms adheres to footprint_h3 contracts."""
    ingest, _, _ = phase2_etl
    raw = tmp_path / "data/raw"

    # Ensure real regions are present
    (tmp_path / "data/regions.json").write_text((ROOT / "data/regions.json").read_text(encoding="utf-8"), encoding="utf-8")

    # Write test CSV with deformed MODIS and small VIIRS detections across multiple regions
    records = [
        # Chilecito deformed MODIS (scan*track > 3.5, track > 1.35)
        dict(latitude=-29.16, longitude=-67.5, acq_date="2024-06-15", acq_time="1430",
             satellite="Terra", frp=100.0, scan=3.6, track=1.8, confidence=100, daynight="D"),
        # Iberia nadir MODIS (scan*track <= 3.5, track <= 1.35)
        dict(latitude=40.0, longitude=-4.0, acq_date="2024-06-15", acq_time="1030",
             satellite="Terra", frp=50.0, scan=1.0, track=1.0, confidence=100, daynight="D"),
        # Amazonas deformed MODIS (scan*track > 3.5, track > 1.35)
        dict(latitude=-3.10, longitude=-60.02, acq_date="2024-06-15", acq_time="1330",
             satellite="Aqua", frp=200.0, scan=4.8, track=2.0, confidence=100, daynight="D"),
        # Orlando nadir VIIRS
        dict(latitude=28.54, longitude=-81.38, acq_date="2024-06-15", acq_time="0730",
             satellite="NOAA-20", frp=30.0, scan=0.375, track=0.375, confidence="nominal", daynight="D"),
    ]
    write_phase2_csv(raw / "test_phase1_detections.csv", records)

    staged_path = ingest.ingest_raw_firms(output_path=tmp_path / "staged_phase1.parquet")
    table = pq.read_table(staged_path)
    rows = table.to_pylist()

    # Deformed Terra in Chilecito: 7 rows
    chilecito_rows = [r for r in rows if r["region"] == "chilecito_la_rioja" and r["satellite"] == "Terra"]
    assert len(chilecito_rows) == 7
    expected_c_weights = footprint_h3.compute_elliptical_psf_weights(-29.16, -67.5, 3.6, 1.8)
    expected_c_bw = float(footprint_h3.compute_modis_bowtie_overlap_weight(1.8))
    assert sum(r["footprint_weight"] for r in chilecito_rows) == pytest.approx(1.0, abs=1e-12)
    center_count = 0
    for r in chilecito_rows:
        hex_id = format(r["h3_r7"], "015x")
        assert hex_id in expected_c_weights
        assert r["footprint_weight"] == pytest.approx(expected_c_weights[hex_id], abs=1e-12)
        assert r["bowtie_weight"] == pytest.approx(expected_c_bw, abs=1e-12)
        assert r["corrected_frp"] == pytest.approx(100.0 * expected_c_bw * expected_c_weights[hex_id], abs=1e-12)
        if r["is_center"]:
            center_count += 1
            assert hex_id == format(int(h3.latlng_to_cell(-29.16, -67.5, 7), 16), "015x")
    assert center_count == 1

    # Iberia nadir MODIS: 1 row
    iberia_rows = [r for r in rows if r["region"] == "iberia_med"]
    assert len(iberia_rows) == 1
    assert iberia_rows[0]["footprint_weight"] == 1.0
    assert iberia_rows[0]["bowtie_weight"] == 1.0
    assert iberia_rows[0]["corrected_frp"] == 50.0
    assert iberia_rows[0]["is_center"] is True

    # Amazonas deformed MODIS: 7 rows
    amazonas_rows = [r for r in rows if r["region"] == "amazonas_manaus"]
    assert len(amazonas_rows) == 7
    expected_a_weights = footprint_h3.compute_elliptical_psf_weights(-3.10, -60.02, 4.8, 2.0)
    expected_a_bw = float(footprint_h3.compute_modis_bowtie_overlap_weight(2.0))
    assert sum(r["footprint_weight"] for r in amazonas_rows) == pytest.approx(1.0, abs=1e-12)
    for r in amazonas_rows:
        hex_id = format(r["h3_r7"], "015x")
        assert hex_id in expected_a_weights
        assert r["footprint_weight"] == pytest.approx(expected_a_weights[hex_id], abs=1e-12)
        assert r["bowtie_weight"] == pytest.approx(expected_a_bw, abs=1e-12)
        assert r["corrected_frp"] == pytest.approx(200.0 * expected_a_bw * expected_a_weights[hex_id], abs=1e-12)

    # Orlando nadir VIIRS: 1 row
    orlando_rows = [r for r in rows if r["region"] == "orlando_florida"]
    assert len(orlando_rows) == 1
    assert orlando_rows[0]["footprint_weight"] == 1.0
    assert orlando_rows[0]["bowtie_weight"] == 1.0
    assert orlando_rows[0]["corrected_frp"] == 30.0
    assert orlando_rows[0]["is_center"] is True


# =====================================================================
# Phase 3: SAMA anomaly rejection and Shannon industrial entropy
# =====================================================================

@pytest.mark.parametrize("label,lat,lon,daynight,conf,mir,tir,acq_date,satellite,expected_drop", [
    # Inside SAMA box (-35 to -15 lat, -65 to -30 lon), night, low conf, contrast < 1.5K -> DROP
    ("sama_noise_outside_presets", -16.9, -56.2, "N", "low", 300.0, 299.5, "2024-06-15", "Aqua", True),
    ("sama_noise_south_atlantic", -25.0, -45.0, "N", "low", 300.0, 299.5, "2024-06-15", "Aqua", True),
    ("sama_noise_digit_conf", -22.0, -45.0, "N", "20", 305.0, 304.5, "2024-06-15", "Terra", True),
    # Inside SAMA box but daytime -> KEEP
    ("sama_daytime_valid", -16.9, -56.2, "D", "low", 300.0, 299.5, "2024-06-15", "Aqua", False),
    # Inside SAMA box but nominal/high conf -> KEEP
    ("sama_nominal_conf_valid", -16.9, -56.2, "N", "nominal", 300.0, 299.5, "2024-06-15", "Aqua", False),
    ("sama_high_conf_valid", -16.9, -56.2, "N", "100", 300.0, 299.5, "2024-06-15", "Terra", False),
    # Inside SAMA box but thermal contrast >= 1.5K -> KEEP
    ("sama_high_contrast_valid", -16.9, -56.2, "N", "low", 305.0, 300.0, "2024-06-15", "Aqua", False),
    # Outside SAMA box (Iberia 40.0, -4.0) with low conf & night -> KEEP
    ("iberia_outside_sama", 40.0, -4.0, "N", "low", 300.0, 299.5, "2024-06-15", "Terra", False),
    # Outside SAMA box (Orlando 28.54, -81.38) with low conf & night -> KEEP
    ("orlando_outside_sama", 28.54, -81.38, "N", "low", 300.0, 299.5, "2024-06-15", "NOAA-20", False),
    # Outside SAMA box (Amazonas -3.10, -60.02 is north of -15) with low conf & night -> KEEP
    ("amazonas_north_of_sama", -3.10, -60.02, "N", "low", 300.0, 299.5, "2024-06-15", "Aqua", False),
    # Outside SAMA box (Chilecito -29.16, -67.5 is west of -65) with low conf & night -> KEEP
    ("chilecito_west_of_sama", -29.16, -67.5, "N", "low", 300.0, 299.5, "2024-06-15", "Terra", False),
    # Terra pre-Nov 2000 records -> DROP
    ("terra_pre_nov_2000", 40.0, -4.0, "D", "high", 350.0, 300.0, "2000-10-15", "Terra", True),
    # Non-Terra pre-Nov 2000 records -> KEEP
    ("non_terra_pre_nov_2000", 40.0, -4.0, "D", "high", 350.0, 300.0, "2000-10-15", "Aqua", False),
])
def test_phase3_sama_artifact_filter_parity_etl_vs_core(label, lat, lon, daynight, conf,
                                                        mir, tir, acq_date, satellite, expected_drop):
    """Verify that ingest.sama_artifact delegates to industrial_filter.filter_sama_anomalies with identical verdicts."""
    ingest = import_module("01_ingest_firms")
    d = date.fromisoformat(acq_date)
    conf_norm = "low" if conf.isdigit() and int(conf) < 30 else ("nominal" if conf.isdigit() and int(conf) < 80 else conf)
    row = dict(
        latitude=lat, longitude=lon, daynight=daynight.upper(),
        confidence_norm=conf_norm, brightness_mir=mir, brightness_tir=tir,
        acq_date=d, satellite=satellite,
    )
    # Direct ETL call
    is_dropped = ingest.sama_artifact(row)
    assert is_dropped == expected_drop, f"ETL verdict mismatch for {label}: got {is_dropped}, expected {expected_drop}"

    # Core call parity
    delta = (mir - tir) if (mir is not None and tir is not None) else np.nan
    is_terra = (satellite == "Terra")
    core_verdict = bool(industrial_filter.filter_sama_anomalies(
        lat, lon, daynight.upper(), conf_norm == "low", delta,
        d.year if is_terra else None, d.month if is_terra else None,
    ))
    assert is_dropped == core_verdict, f"Parity mismatch with core for {label}"


def test_phase3_staged_entropy_and_industrial_score(phase2_etl, tmp_path):
    """Verify that staged FIRMS detections filter SAMA noise and preserve exact Shannon entropy and industrial probability."""
    ingest, _, _ = phase2_etl
    raw = tmp_path / "data/raw"
    (tmp_path / "data/regions.json").write_text((ROOT / "data/regions.json").read_text(encoding="utf-8"), encoding="utf-8")

    # In Chilecito: 12 monthly detections at fixed position (flare/industrial site)
    flare_records = [
        dict(latitude=-29.16000, longitude=-67.50000, acq_date=f"2024-{m:02d}-15", acq_time="1200",
             satellite="Terra", frp=50.0, scan=1.0, track=1.0, confidence=100, daynight="D",
             brightness=340.0, bright_t31=300.0)
        for m in range(1, 13)
    ]
    # In Iberia: a single seasonal wildfire detection in August
    wildfire_records = [
        dict(latitude=40.00000, longitude=-4.00000, acq_date="2024-08-15", acq_time="1200",
             satellite="Terra", frp=80.0, scan=1.0, track=1.0, confidence=100, daynight="D",
             brightness=360.0, bright_t31=300.0)
    ]
    # SAMA noise candidate outside the configured study regions that must be filtered out
    sama_records = [
        dict(latitude=-16.90000, longitude=-56.20000, acq_date="2024-07-15", acq_time="0330",
             satellite="Aqua", frp=15.0, scan=1.0, track=1.0, confidence=20, daynight="N",
             brightness=300.0, bright_t31=299.5)
    ]
    (tmp_path / "data/lookup/flare_reference.csv").write_text(
        "year,latitude,longitude,site_id,region\n2024,-29.16,-67.5,fixture,chilecito_la_rioja\n", encoding="utf-8")
    write_phase2_csv(raw / "phase3_test_detections.csv", flare_records + wildfire_records + sama_records)

    staged_path = ingest.ingest_raw_firms(output_path=tmp_path / "staged_phase3.parquet")
    table = pq.read_table(staged_path)
    rows = table.to_pylist()

    # The SAMA record must have been dropped (0 rows in staged)
    assert not any(r["daynight"] == "N" and r["confidence_norm"] == "low" for r in rows)

    # Flare cell in Chilecito: 12 detections staged
    flare_rows = [r for r in rows if r["region"] == "chilecito_la_rioja"]
    assert len(flare_rows) == 12
    expected_ent, expected_prob = industrial_filter.compute_industrial_probability(np.ones(12))
    for r in flare_rows:
        assert r["h_temp"] == pytest.approx(float(expected_ent), abs=1e-6)
        assert r["industrial_prob"] == pytest.approx(float(expected_prob), abs=1e-6)
        assert r["h_temp"] > 0.95
        assert r["industrial_prob"] > 0.90

    # Wildfire in Iberia: 1 detection staged
    wildfire_rows = [r for r in rows if r["region"] == "iberia_med"]
    assert len(wildfire_rows) == 1
    w_counts = np.zeros(12)
    w_counts[7] = 1.0  # August
    w_ent, w_prob = industrial_filter.compute_industrial_probability(w_counts)
    w = wildfire_rows[0]
    assert w["h_temp"] == pytest.approx(float(w_ent), abs=1e-6)
    assert w["industrial_prob"] == 0.0  # No documented industrial reference.
    assert w["h_temp"] < 0.05
    assert w["industrial_prob"] < 0.05


def phase6_training_staged(path):
    """Matched daytime Aqua/SNPP cell-days: 40 in biome 8, a sparse 5-day biome 16, plus excluded rows."""
    rng = np.random.default_rng(6)
    iberia = int(h3.latlng_to_cell(40.0, -4.0, 7), 16)
    andes = int(h3.latlng_to_cell(-29.16, -67.5, 7), 16)
    rows = []
    for k in range(40):
        day = date(2020, 1, 1) + timedelta(days=k)
        viirs = float(rng.uniform(.6, 7.5) if k % 3 == 0 else rng.uniform(9, 120))
        rows += [(iberia, day, "D", "Aqua", float(rng.uniform(8, 150)), 8, 3),
                 (iberia, day, "D", "SNPP", viirs, 8, 3)]
    for k in range(5):
        day = date(2021, 3, 1) + timedelta(days=k)
        rows += [(andes, day, "D", "Aqua", 30.0 + k, 16, 1), (andes, day, "D", "SNPP", 25.0 + k, 16, 1)]
    rows += [(iberia, date(2020, 6, 1), "N", "Aqua", 500.0, 8, 3), (iberia, date(2020, 6, 1), "N", "SNPP", 1.0, 8, 3),
             (iberia, date(2011, 6, 1), "D", "Aqua", 900.0, 8, 3), (iberia, date(2011, 6, 1), "D", "SNPP", 2.0, 8, 3)]
    names = ["h3_r7", "acq_date", "daynight", "satellite", "corrected_frp", "igbp_biome", "scan_bin"]
    types = [pa.uint64(), pa.date32(), pa.string(), pa.string(), pa.float64(), pa.int64(), pa.int64()]
    columns = list(zip(*rows))
    pq.write_table(pa.table({n: pa.array(c, t) for n, c, t in zip(names, columns, types)}), path)
    included = [r for r in rows if r[2] == "D" and r[1].year >= 2012]
    pick = lambda sat, biome=None: np.array([r[4] for r in included if r[3] == sat and biome in (None, r[5])])
    return pick


def test_stage03_lut_is_trained_by_the_core_harmonizer(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    training = import_module("03_train_eqm_lut")
    from backend.core.eqm_harmonizer import RadiometricHarmonizer
    pick = phase6_training_staged(tmp_path / "staged.parquet")
    path = training.generate_eqm_gpd_lut(tmp_path / "lut.json", tmp_path / "staged.parquet")
    lut = json.loads(path.read_text(encoding="utf-8"))
    assert lut["method"] == training.METHOD and lut["threshold_mw"] == 8.0
    models = lut["models"]
    assert set(models) == {"all:all", "8:all", "8:3"}  # 5 biome-16 days < MIN_SAMPLES
    for name, biome in (("all:all", None), ("8:all", 8), ("8:3", 8)):
        expected = RadiometricHarmonizer().fit_biome_eqm_gpd(pick("Aqua", biome), pick("SNPP", biome),
                                                             biome_id=biome or 1)
        model = models[name]
        assert model["biome_id"] == biome and model["matched_days"] == (45 if biome is None else 40)
        assert len(model["viirs_quantiles"]) == len(model["modis_quantiles"]) == 101
        np.testing.assert_allclose(model["viirs_quantiles"], expected["viirs_quantiles"], atol=1e-6)
        np.testing.assert_allclose(model["modis_quantiles"], expected["modis_quantiles"], atol=1e-6)
        assert model["delta_e_sub"] == pytest.approx(expected["delta_e_sub"], abs=1e-6)
        assert model["delta_e_sub"] > 0 and model["gpd"]["fit_method"] == "maximum_likelihood"
    assert path.stat().st_size < 150_000


@pytest.mark.parametrize("stratum", ["all:all", "8:all"])
def test_stage04_eqm_gpd_parity_with_core_on_every_channel(phase2_etl, tmp_path, stratum):
    ingest, _, builder = phase2_etl
    from backend.core.eqm_harmonizer import RadiometricHarmonizer
    core = RadiometricHarmonizer()
    rng = np.random.default_rng(3)
    viirs = np.r_[rng.uniform(.5, 7.9, 200), rng.uniform(8, 90, 300)]
    chosen = core.fit_biome_eqm_gpd(viirs * 1.3, viirs, biome_id=8)
    decoy = core.fit_biome_eqm_gpd(viirs * 5.0, viirs, biome_id=8)
    models = {stratum: chosen} if stratum == "all:all" else {"8:all": chosen, "all:all": decoy}
    (tmp_path / "data/lookup/eqm_gpd_lut.json").write_text(json.dumps({"models": models}), encoding="utf-8")
    write_phase2_csv(tmp_path / "data/raw/archive.csv", [
        dict(satellite="Terra", frp=10.0, acq_time="1030"), dict(satellite="Aqua", frp=20.0, acq_time="1330"),
        dict(satellite="SNPP", frp=40.0, acq_time="1330"),
        dict(satellite="SNPP", frp=3.0, acq_date="2024-01-11"),
    ])
    staged = ingest.ingest_raw_firms(output_path=tmp_path / "staged.parquet")
    first, second = pq.read_table(builder.build_master_cube(staged, tmp_path / "cube.parquet")).to_pylist()
    cell = h3.latlng_to_cell(40.0, -4.0, 7)
    scale = 3600 / h3.cell_area(cell, unit="km^2") * w_orb(cell)
    delta = chosen["delta_e_sub"]
    assert delta > 0
    assert first["obs_terra_fre"] == pytest.approx((10.0 + delta) * scale)
    assert first["obs_aqua_fre"] == pytest.approx((20.0 + delta) * scale)
    assert first["obs_viirs_fre"] == pytest.approx(float(core.harmonize_viirs_to_modis(40.0, chosen)) * scale)
    # Sub-threshold VIIRS energy is mapped by the same full-distribution EQM, not left raw.
    assert second["obs_viirs_fre"] == pytest.approx(float(core.harmonize_viirs_to_modis(3.0, chosen)) * scale)
    assert second["obs_viirs_fre"] != pytest.approx(3.0 * scale)
    assert first["raw_frp_mw"] == 70.0 and second["raw_frp_mw"] == 3.0


def test_real_cube_november_2026_coverage_and_schema():
    """Verify that the published master cube spans through November 14, 2026 with valid schema and H3."""
    regions = json.loads((ROOT / "data/regions.json").read_text(encoding="utf-8"))
    for reg in ("chilecito_la_rioja", "iberia_med", "orlando_florida", "amazonas_manaus"):
        assert reg in regions
        ranges = regions[reg].get("coverage", [])
        assert any(end >= "2026-11-14" for _, end in ranges)

    cube_file = ROOT / "data/processed/fire_cube.parquet"
    assert cube_file.is_file(), "Master fire_cube.parquet must be published"
    table = pq.read_table(cube_file)
    assert [(f.name, f.type) for f in table.schema] == EXPECTED

    # Check date coverage spanning through 2026-11-14 (epoch_day 20771)
    with duckdb.connect() as con:
        min_day, max_day, total_rows = con.execute(
            "SELECT min(epoch_day), max(epoch_day), count(*) FROM read_parquet(?)",
            [str(cube_file)]
        ).fetchone()
        assert min_day == (date(2000, 11, 1) - date(1970, 1, 1)).days
        assert max_day >= (date(2026, 11, 14) - date(1970, 1, 1)).days
        staged = ROOT / "data/processed/staged_firms.parquet"
        expected_rows = con.execute("SELECT count(*) FROM (SELECT DISTINCT h3_r7, acq_date FROM read_parquet(?) WHERE confidence_norm IN ('nominal','high'))", [str(staged)]).fetchone()[0]
        assert total_rows == expected_rows and total_rows > 0

        # Verify November 2026 records
        nov_records = con.execute("""
            SELECT count(*), count(DISTINCT h3_r4), count(DISTINCT h3_r7),
                   sum(raw_frp_mw), min(igbp_biome), max(igbp_biome)
            FROM read_parquet(?)
            WHERE epoch_day >= 20758
        """, [str(cube_file)]).fetchone()
        nov_count, distinct_r4, distinct_r7, sum_frp, min_biome, max_biome = nov_records
        assert nov_count >= 1900
        assert distinct_r4 >= 200
        assert distinct_r7 >= 1000
        assert sum_frp > 10_000
        assert 1 <= min_biome <= 17 and 1 <= max_biome <= 17


@pytest.fixture
def stage07(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return import_module("07_fetch_mcd64a1_ancillary")


def test_stage07_burn_dates_follow_the_composite_year(stage07):
    dates = stage07.burn_dates(2020, np.array([1, 60, 366]))
    assert [str(d) for d in dates] == ["2020-01-01", "2020-02-29", "2020-12-31"]
    for year, doy in ((2021, 366), (2021, 0), (2021, -1)):
        with pytest.raises(ValueError):
            stage07.burn_dates(year, np.array([doy]))


def test_stage07_aggregates_burned_pixels_into_r7_cell_days(stage07):
    assert stage07.PIXEL_HA == pytest.approx(463.3127165279167 ** 2 / 1e4)
    a, b = (40.0, -4.0), (40.3, -4.3)
    lat = np.array([a[0], a[0] + 1e-4, a[0] - 1e-4, a[0], b[0], a[0]])
    lon = np.array([a[1], a[1] + 1e-4, a[1] - 1e-4, a[1], b[1], a[1]])
    dates = np.array(["2022-08-01"] * 3 + ["2022-08-02", "2022-08-01", "2022-08-01"], dtype="datetime64[D]")
    # The last pixel repeats the first (overlapping region boxes) and must not be double counted.
    table = stage07.aggregate_burned_pixels(lat, lon, dates)
    assert table.schema == stage07.SCHEMA
    rows = table.to_pylist()
    cell_a, cell_b = (int(h3.latlng_to_cell(*p, 7), 16) for p in (a, b))
    expected = sorted([(cell_a, date(2022, 8, 1), 3), (cell_a, date(2022, 8, 2), 1), (cell_b, date(2022, 8, 1), 1)])
    assert [(r["h3_r7"], r["acq_date"]) for r in rows] == [(c, d) for c, d, _ in expected]
    for row, (_, _, pixels) in zip(rows, expected):
        assert row["burned_area_ha_mcd64"] == pytest.approx(pixels * stage07.PIXEL_HA, rel=1e-6)
        assert row["cloud_cover_pct"] is None
    empty = stage07.aggregate_burned_pixels(np.array([]), np.array([]), np.array([], dtype="datetime64[D]"))
    assert empty.num_rows == 0 and empty.schema == stage07.SCHEMA


def test_stage07_extracts_pixel_centres_inside_the_region(stage07):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin
    from rasterio.warp import transform as warp
    crs = rasterio.crs.CRS.from_proj4("+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +R=6371007.181 +units=m +no_defs")
    size = stage07.PIXEL_METRES
    (x0,), (y0,) = warp("EPSG:4326", crs, [-4.0], [40.0])
    data = np.zeros((40, 40), dtype=np.int16)
    data[20, 20], data[11, 28], data[30, 2] = 214, 215, -1  # two burns (~4 km apart) and a fill value
    data[0, 0] = 216  # outside the 0.1-degree region box below
    profile = dict(driver="GTiff", width=40, height=40, count=1, dtype="int16", crs=crs, nodata=-1,
                   transform=from_origin(x0 - 20 * size, y0 + 20 * size, size, size))
    with MemoryFile() as memory, memory.open(**profile) as dataset:
        dataset.write(data, 1)
        lat, lon, dates = stage07.extract_burned_pixels(dataset, (-4.06, 39.94, -3.94, 40.06), 2022)
    assert sorted(str(d) for d in dates) == ["2022-08-02", "2022-08-03"]
    centre = int(np.argmin(np.abs(lat - 40.0) + np.abs(lon + 4.0)))
    assert lat[centre] == pytest.approx(40.0 - 0.5 * size / 6371007.181 * 180 / np.pi, abs=1e-6)
    assert np.all((lat >= 39.94) & (lat <= 40.06) & (lon >= -4.06) & (lon <= -3.94))


def test_stage07_complete_years_require_every_tile_month(stage07):
    months = ["001", "032", "060", "091", "121", "152", "182", "213", "244", "274", "305", "335"]
    ids = [f"MCD64A1.A2021{m}.{t}.061.2022001000000" for m in months for t in ("h17v04", "h18v04")]
    ids += [f"MCD64A1.A2022{m}.h17v04.061.2023001000000" for m in months]  # h18v04 missing all of 2022
    ids += [f"MCD64A1.A2023{m}.{t}.061.2024001000000" for m in months[:-1] for t in ("h17v04", "h18v04")]
    ids += ["MCD64A1.A2021001.h17v04.061.2025001000000"]  # reprocessed duplicate does not double count
    assert stage07.complete_years(ids) == [2021]
    assert stage07.complete_years([]) == []


def test_stage04_and_stage05_turn_mcd64_ancillary_into_cross_validated_r2(phase2_etl, tmp_path, monkeypatch,
                                                                          stage07, capsys):
    ingest, _, builder = phase2_etl
    benchmark = import_module("05_cli_benchmark")
    monkeypatch.setattr(benchmark, "ROOT", tmp_path)
    # A registered region without declared coverage has no real data: it is skipped, not failed.
    regions = {"fixture": {"bounds": [-5, 39, -3, 41], "nominal_biome": 8,
                            "coverage": [["2004-01-01", "2019-12-31"]]},
               "uncovered": {"bounds": [5.6, 4.6, 7.2, 5.8], "nominal_biome": 12}}
    (tmp_path / "data/regions.json").write_text(json.dumps(regions), encoding="utf-8")
    records, burned = [], {}
    for year in range(2004, 2020):
        power = 10.0 + 7.0 * ((year * 37) % 11)
        for day in ("06-10", "07-15", "08-20"):
            records.append(dict(acq_date=f"{year}-{day}", frp=power, satellite="Aqua", acq_time="1330"))
        burned[year] = power * 3
    write_phase2_csv(tmp_path / "data/raw/archive.csv", records)
    pixels = [(40.0, -4.0, np.datetime64(f"{year}-07-15"), round(area)) for year, area in burned.items()]
    lat = np.repeat([p[0] for p in pixels], [p[3] for p in pixels])
    lon = np.repeat([p[1] for p in pixels], [p[3] for p in pixels])
    dates = np.repeat(np.array([p[2] for p in pixels], dtype="datetime64[D]"), [p[3] for p in pixels])
    # Distinct pixel centres (sub-metre offsets) inside one R7 cell; exact duplicates would be merged.
    # 2019 is flagged incomplete (missing MCD64A1 months) and its corrupted total must be excluded from R2.
    in_2019 = dates.astype("datetime64[Y]").astype(int) + 1970 == 2019
    keep = ~in_2019 | (np.cumsum(in_2019) <= 3)  # only 3 pixels survive in the incomplete year
    ancillary = stage07.aggregate_burned_pixels(lat[keep] + np.arange(keep.sum()) * 1e-9, lon[keep], dates[keep])
    complete = {"fixture": list(range(2004, 2019))}
    ancillary = ancillary.replace_schema_metadata({b"complete_years": json.dumps(complete).encode()})
    pq.write_table(ancillary, tmp_path / "data/lookup/cell_day_ancillary.parquet")
    staged = ingest.ingest_raw_firms(output_path=tmp_path / "staged.parquet")
    cube = builder.build_master_cube(staged, tmp_path / "data/processed/fire_cube.parquet")
    coverage = json.loads(pq.read_schema(cube).metadata[b"ancillary_coverage"])
    assert coverage["input_present"] is True and coverage["burned_area_ha_mcd64"]["observed_rows"] == 16
    # Independently test the ancillary regression without changing the process-wide API cube.
    predictors = [[burned[year]] for year in range(2004, 2019)]
    totals = [burned[year] for year in range(2004, 2019)]
    assert benchmark.cross_validated_r2(predictors, totals) > .99
    from backend.db.burned_area import annual_totals
    import duckdb
    coords = [[[-5,39],[-3,39],[-3,41],[-5,41],[-5,39]]]
    with duckdb.connect() as cur:
        cell = int(h3.latlng_to_cell(40., -4., 7), 16)
        measured = annual_totals(tmp_path, cur, coords, [cell], np.arange(2004,2020))
    assert np.isfinite(measured[:-1]).all() and np.isnan(measured[-1])



@pytest.fixture
def stage05(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return import_module("05_cli_benchmark")


def test_stage05_chow_is_the_core_annual_test(stage05):
    from backend.core.auditor_stats import compute_chow_structural_break_test
    years = np.repeat(np.arange(2003, 2023), 30)
    doy = np.tile(np.arange(1, 31), 20)
    continuous = 100 + (years - 2003) * 2.0 + np.sin(doy)
    jump = continuous * np.where(years >= 2012, 4.5, 1.0)
    for series in (continuous, jump):
        unique = np.unique(years)
        annual = np.array([series[years == y].mean() for y in unique])
        assert stage05.chow_p(series, years) == pytest.approx(compute_chow_structural_break_test(unique, annual)[1])
    assert stage05.chow_p(continuous, years) > 0.10 > 1e-4 > stage05.chow_p(jump, years)
    assert stage05.chow_p(continuous[years < 2012], years[years < 2012]) is None


def test_stage05_recovery_is_the_core_chaos_monkey_on_api_daily_inputs(stage05):
    from backend.core.chaos_monkey import run_chaos_monkey_simulation
    rng = np.random.default_rng(5)
    days = np.arange(np.datetime64("2019-01-01"), np.datetime64("2023-01-01"))
    keep = rng.random(len(days)) < 0.6
    season = 50 + 40 * np.sin(2 * np.pi * np.arange(len(days)) / 365.25)
    epoch = (days - np.datetime64("1970-01-01")).astype(int)
    rows = [(int(e), float(s), float(s * 1.1), float(s * .9), float(s / 2), 0.0)
            for e, s, k in zip(epoch, season, keep) if k]
    daily = stage05.dense_daily(rows)
    assert len(daily["epoch_day"]) == len(days) and np.isnan(daily["obs_terra_fre"][~keep]).all()
    assert daily["doy"][0] == 1 and daily["year"][-1] == 2022
    result = stage05.chaos_recovery(daily, 2022)
    selected = daily["year"] == 2022
    obs = np.column_stack([daily[k] for k in ("obs_terra_fre", "obs_aqua_fre", "obs_viirs_fre")])
    expected = run_chaos_monkey_simulation(
        [str(d) for d in days[selected]], daily["doy"][selected], obs[selected],
        daily["neighbor_fre_lag1"][selected], daily["cloud_cover_pct"][selected],
        full_doy_history=daily["doy"][~selected], full_y_obs_history=obs[~selected])
    assert result == pytest.approx(expected.seasonal_energy_recovered_pct)
    assert stage05.chaos_recovery(daily, 2030) is None


def test_stage05_reports_in_sample_r2_beside_the_cross_validated_gate(stage05):
    energy = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 50.0])
    area = 3.0 * energy + np.array([0.1, -0.1, 0.2, -0.2, 0.1, -0.1, 0.0])
    assert stage05.in_sample_r2(energy, area) == pytest.approx(np.corrcoef(energy, area)[0, 1] ** 2)
    assert stage05.in_sample_r2(energy[:5], area[:5]) is None  # fewer than six years
    assert stage05.in_sample_r2(energy, np.ones(7)) is None  # constant burned area


def test_stage05_reference_series_counts_only_modis_detected_cell_days(stage05, tmp_path):
    """Synchronized record on MODIS Terra + Aqua (every year 2000-2026): count, energy and MODIS-only spread."""
    schema = pa.schema([(f.name, f.type) for f in bootstrap.CUBE_SCHEMA])
    a = h3.latlng_to_cell(40.0, -4.0, 7)
    a_nb = next(c for c in h3.grid_disk(a, 1) if c != a)
    b = h3.latlng_to_cell(40.5, -4.5, 7)
    b_nb = next(c for c in h3.grid_disk(b, 1) if c != b)
    far = h3.latlng_to_cell(41.0, -5.0, 7)
    def row(cell, day, terra=None, aqua=None, viirs=None):
        d = date(1970, 1, 1) + timedelta(days=day)
        return dict(h3_r4=int(h3.cell_to_parent(cell, 4), 16), h3_r7=int(cell, 16), epoch_day=day, year=d.year,
                    doy=d.timetuple().tm_yday, igbp_biome=8, sensor_obs_mask=0, gap_status_mask=0,
                    cloud_cover_pct=0.0, raw_modis_cnt=0, raw_viirs_cnt=0, raw_frp_mw=0.0, obs_terra_fre=terra,
                    obs_aqua_fre=aqua, obs_viirs_fre=viirs, neighbor_fre_lag1=0.0, industrial_prob=0.0,
                    burned_area_ha_mcd64=0.0)
    day = (date(2019, 8, 2) - date(1970, 1, 1)).days
    rows = [row(a_nb, day - 1, aqua=3.0),       # MODIS-detected neighbour of a on the previous day
            row(b_nb, day - 1, viirs=9.0),      # VIIRS-only neighbour of b: does not make b a spreading fire
            row(a, day, terra=10.0, viirs=4.0), # counted, harmonized mean (10 + 4) / 2, spreading
            row(b, day, aqua=6.0),              # counted, not spreading
            row(far, day, viirs=50.0),          # VIIRS only: excluded from the synchronized record
            row(a, day + 1, viirs=8.0)]         # VIIRS-only day: absent
    cube = tmp_path / "cube.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), cube)
    parents = ",".join(str(int(h3.cell_to_parent(c, 4), 16)) for c in {a, a_nb, b, b_nb, far})
    with duckdb.connect() as con:
        con.execute("CREATE TEMP TABLE region_cells AS SELECT unnest(?::UBIGINT[]) AS h3_r7",
                    [[int(c, 16) for c in (a, a_nb, b, b_nb, far)]])
        series = stage05.reference_daily(con, cube, parents)
    assert series == [(day - 1, 1, pytest.approx(3.0), 0), (day, 2, pytest.approx(7.0 + 6.0), 1)]


def test_stage05_cross_validated_r2_accepts_count_and_energy_predictors(stage05):
    rng = np.random.default_rng(9)
    count, energy, spread = rng.uniform(10, 100, 22), rng.uniform(1e3, 1e5, 22), rng.uniform(0, 40, 22)
    predictors = np.column_stack([count, energy, spread])
    area = 40.0 * count + 0.002 * energy + 15.0 * spread
    assert stage05.cross_validated_r2(predictors, area) == pytest.approx(1.0)
    assert stage05.in_sample_r2(predictors, area) == pytest.approx(1.0)
    noisy = area + rng.normal(0, area.std(), 22)
    assert stage05.cross_validated_r2(predictors, noisy) < stage05.in_sample_r2(predictors, noisy)


def test_stage05_chow_uses_only_complete_covered_years(stage05):
    years = np.repeat(np.arange(2000, 2027), 10).astype(int)
    values = np.full(len(years), 50.0) + (years - 2000) * 0.1
    padded = values.copy()
    padded[years == 2000] = 0.0  # zero-padded partial first year (coverage starts in November)
    coverage = [["2000-11-01", "2026-11-01"]]
    assert stage05.complete_years(coverage) == list(range(2001, 2026))
    complete = np.isin(years, stage05.complete_years(coverage))
    assert stage05.chow_p(padded[complete], years[complete]) == pytest.approx(
        stage05.chow_p(values[complete], years[complete]))
    assert stage05.chow_p(padded, years) < stage05.chow_p(padded[complete], years[complete])
