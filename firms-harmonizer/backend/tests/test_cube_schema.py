"""Offline synthetic cube schema, storage and physical scenario regression gates."""

import importlib.util
from importlib import import_module
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
sys.path.insert(0,str(ROOT))
from backend.api.schemas import AnalyzeRequest, AnalyzeResponse, ChaosMonkeyRequest, GeoJSONPolygon

spec = importlib.util.spec_from_file_location("bootstrap",ROOT/"scripts/00_bootstrap_synthetic_cube.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)

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
    # A foreign working directory must not alter the default output location.
    result=subprocess.run([sys.executable,str(ROOT/"scripts/00_bootstrap_synthetic_cube.py")],cwd=tmp_path,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert "Synthetic cube:" in result.stdout


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
