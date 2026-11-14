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
from backend.core import footprint_h3

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
    area = h3.cell_area(h3.latlng_to_cell(40.0, -4.0, 7), unit="km^2")
    assert len(rows) == 2
    first, second = rows
    assert first["obs_terra_fre"] == pytest.approx(30.0 * 3600 / area)
    assert first["obs_aqua_fre"] == pytest.approx(7.0 * 3600 / area)
    assert first["obs_viirs_fre"] == pytest.approx(12.0 * 3600 / area)
    assert first["raw_frp_mw"] == 61.0
    assert first["raw_modis_cnt"] == 3 and first["raw_viirs_cnt"] == 2
    assert first["sensor_obs_mask"] == 15
    assert second["obs_terra_fre"] == pytest.approx(5.0 * 3600 / area)
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
    base = 10.0 * 3600 / h3.cell_area(cell, unit="km^2")
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
    expected = 10.0 * 3600 / h3.cell_area(cell_a, unit="km^2")
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
            expected_energy.append(power * 3600 / h3.cell_area(cell, unit="km^2"))
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
    area = h3.cell_area(h3.latlng_to_cell(40.0, -4.0, 7), unit="km^2")
    assert len(rows) == 3
    for row in rows:
        assert row["raw_modis_cnt"] == 3 and row["raw_frp_mw"] == 105.0
        assert row["obs_terra_fre"] == pytest.approx(75.0 * 3600 / area)
        assert row["obs_aqua_fre"] == pytest.approx(75.0 * 3600 / area)
        assert row["neighbor_fre_lag1"] == 0.0

def run_outage_cli(staged, output, counts=None):
    command = [sys.executable, str(ROOT / "scripts/02_detect_outages_clouds.py"),
               "--staged", str(staged), "--output-dir", str(output)]
    if counts is not None:
        command.extend(["--global-counts", str(counts)])
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True)


def test_stage02_known_aqua_interval_is_exact_and_reproducible(tmp_path):
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
    expected = [dict(acq_date=date(2022, 7, 31) + timedelta(days=i),
                     satellite="Aqua", evidence="known_safe_mode") for i in range(17)]
    actual = pq.read_table(paths[0])
    assert [(field.name, field.type) for field in actual.schema] == [
        ("acq_date", pa.date32()), ("satellite", pa.string()), ("evidence", pa.string())]
    assert sorted(actual.to_pylist(), key=lambda row: row["acq_date"]) == expected
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
        "known_safe_mode"}


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
    pq.write_table(pa.Table.from_pylist(records), staged)
    return builder, staged, lookup, int(center, 16), int(neighbor, 16)


def test_stage04_aqua_outage_and_five_instrument_bits(stage04_inputs, tmp_path):
    builder, staged, lookup, center, neighbor = stage04_inputs
    path = builder.build_master_cube(staged, tmp_path / "cube.parquet", lookup_dir=lookup)
    table = pq.read_table(path)
    assert [(f.name, f.type) for f in table.schema] == EXPECTED
    assert table.num_rows == 38
    for row in table.to_pylist():
        day = date(1970, 1, 1) + timedelta(days=row["epoch_day"])
        outage = date(2022, 7, 31) <= day <= date(2022, 8, 16)
        assert row["sensor_obs_mask"] == (29 if outage else 31)
        assert row["gap_status_mask"] == (1 if outage else 0)
        assert (row["obs_aqua_fre"] is None) == outage
        assert row["obs_terra_fre"] > 0 and row["obs_viirs_fre"] > 0
        assert row["raw_modis_cnt"] == 2 and row["raw_viirs_cnt"] == 3


def test_stage04_viirs_outages_preserve_remaining_instrument(stage04_inputs, tmp_path):
    builder, staged, lookup, center, neighbor = stage04_inputs
    path = lookup / "sensor_outages.parquet"
    records = pq.read_table(path).to_pylist()
    for day, sensors in ((date(2022, 8, 1), ("Terra", "SNPP", "N20")),
                         (date(2022, 8, 2), ("Terra", "SNPP", "N20", "N21"))):
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
        dict(h3_r7=center, acq_date=date(2022, 7, 30), cloud_cover_pct=cloud,
             burned_area_ha_mcd64=0.0),
        dict(h3_r7=center, acq_date=date(2022, 7, 31), cloud_cover_pct=cloud,
             burned_area_ha_mcd64=0.0),
    ], schema=ancillary_schema), lookup / "cell_day_ancillary.parquet")
    path = builder.build_master_cube(staged, tmp_path / "cube.parquet", lookup_dir=lookup)
    rows = {(r["h3_r7"], r["epoch_day"]): r for r in pq.read_table(path).to_pylist()}
    epoch = (date(2022, 7, 30) - date(1970, 1, 1)).days
    for offset, outage_bit in ((0, 0), (1, 1)):
        row = rows[center, epoch + offset]
        assert row["gap_status_mask"] == mask | outage_bit
        assert row["sensor_obs_mask"] == (0 if missing else (29 if offset else 31))
        for field in ("obs_terra_fre", "obs_aqua_fre", "obs_viirs_fre"):
            assert (row[field] is None) == (missing or (offset == 1 and field == "obs_aqua_fre"))
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
    payload = orjson.loads((ROOT / "data/mock/mock_analyze_response.json").read_bytes())
    response = AnalyzeResponse.model_validate(payload)
    assert response.data_source == "synthetic"
    assert len(response.calendar_series) == 9496
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
        assert industrial_count == (6 if name == "niger_delta_flaring" else 2)


def test_generator_repeatability_performance_and_alternate_path(tmp_path,cube):
    start=perf_counter()
    path=bootstrap.generate_bootstrap_cube(tmp_path/"repeat.parquet")
    assert isinstance(path, str)
    assert perf_counter()-start<3.0
    assert pq.read_table(path).equals(cube)
    # Exercise the unchanged CLI default in an isolated project, never in production.
    isolated = tmp_path / "isolated_project"
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
