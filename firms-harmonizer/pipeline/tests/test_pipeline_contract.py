"""Frozen contract tests for pipeline/ (shape, keys, provenance, sentinels). No scientific assertions.
DO NOT EDIT — see FROZEN_TESTS.sha256."""

from __future__ import annotations

import ast
import json
from datetime import date
import os
import subprocess
import sys
from pathlib import Path

import h3
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest

from pipeline import config, cube, german, ingest, pairs
from pipeline.tests.conftest import FIXTURES, GERMAN, REGION

PKG = Path(__file__).resolve().parents[1]
CUBE_FIELDS = [(f.name, f.type, f.nullable) for f in german.load("00_bootstrap_synthetic_cube").CUBE_SCHEMA]
SNPP_OUTAGE = german.load("02_detect_outages_clouds").KNOWN_OUTAGES


def table(path) -> pa.Table:
    return pq.read_table(path)


# ---------------- ingest ----------------

def test_staged_detection_columns_and_types(built):
    t = table(built.det_file)
    assert t.column_names == list(ingest.DETECTION_COLUMNS)
    for name in ("h3_r4", "h3_r7", "h3_r10", "det_id"):
        assert t.schema.field(name).type == pa.uint64()
    assert t.schema.field("acq_date").type == pa.date32()
    assert len(set(t["det_id"].to_pylist())) == len(t)


def test_h3_keys_are_consistent(built):
    t = table(built.det_file).to_pylist()
    for r in t:
        assert r["h3_r7"] == h3.str_to_int(h3.latlng_to_cell(r["latitude"], r["longitude"], 7))
        assert r["h3_r10"] == h3.str_to_int(h3.latlng_to_cell(r["latitude"], r["longitude"], 10))
        assert r["h3_r4"] == h3.str_to_int(h3.cell_to_parent(h3.int_to_str(r["h3_r7"]), 4))


def test_exact_duplicates_collapse_and_standard_beats_nrt(built):
    t = table(built.det_file).to_pylist()
    keys = [(r["satellite"], r["acq_date"], r["acq_time"], round(r["latitude"], 5), round(r["longitude"], 5)) for r in t]
    assert len(keys) == len(set(keys))
    dup = [r for r in t if r["satellite"] == "Aqua" and r["acq_time"] == "1340" and r["latitude"] == -16.9012]
    assert len(dup) == 1 and dup[0]["tier"] == "SP"
    assert any(r["tier"] == "NRT" for r in t)


def test_sama_rule_removes_rows_and_is_counted(built):
    t = table(built.det_file).to_pylist()
    assert not [r for r in t if r["satellite"] == "Terra" and r["acq_time"] == "0150"]
    assert built.stats["sensors"]["Terra"]["sama_removed"] >= 1
    for s in built.stats["sensors"].values():
        assert s["rows_read"] >= s["valid"] >= s["after_dedup"] >= s["kept"] >= 0
        assert s["after_dedup"] - s["sama_removed"] == s["kept"]


def test_detection_outside_regions_is_kept_without_region(built):
    t = table(built.det_file).to_pylist()
    out = [r for r in t if r["longitude"] == 20.5]
    assert len(out) == 1 and out[0]["region"] is None
    regions = config.load_regions()
    for r in t:
        if r["region"] is not None:
            west, south, east, north = regions[r["region"]]["bounds"]
            assert west <= r["longitude"] <= east and south <= r["latitude"] <= north


def test_unknown_satellite_and_missing_columns_raise(tmp_path):
    con = config.connect()
    bad = tmp_path / "bad.csv"
    bad.write_text((FIXTURES / "german" / "viirs_snpp_fixture_archive.csv").read_text().replace(",N,VIIRS", ",ZZ,VIIRS"))
    with pytest.raises(ValueError, match="satellite"):
        ingest.ingest_csvs(con, [bad], tmp_path / "o" / "part.parquet")
    short = tmp_path / "short.csv"
    short.write_text("latitude,longitude\n1,2\n")
    with pytest.raises(ValueError, match="missing required columns"):
        ingest.ingest_csvs(con, [short], tmp_path / "o2" / "part.parquet")


# ---------------- canonical staging (scripts/01) ----------------

def _rows(t: pa.Table) -> list[dict]:
    key = ("satellite", "acq_date", "acq_time", "latitude", "longitude", "h3_r7")
    return sorted(t.to_pylist(), key=lambda r: tuple(r[k] for k in key))


def test_regional_staging_is_scripts01_output_on_the_raw_csvs(built, tmp_path):
    """Parity: global ingest -> FIRMS CSV export -> scripts/01 == scripts/01 on the original region CSVs."""
    raw = tmp_path / "raw"
    raw.mkdir()
    for path in GERMAN:  # every fixture row outside the global-only file lies inside a configured region
        (raw / path.name).write_bytes(path.read_bytes())
    stage01 = german.load("01_ingest_firms")
    reference = pq.read_table(stage01.ingest_raw_firms(raw, tmp_path / "staged.parquet"))
    reference = reference.filter(pc.equal(reference["region"], REGION))
    staged = table(built.staged)
    assert staged.schema == reference.schema
    assert set(staged["region"].to_pylist()) == {REGION}
    ours, theirs = _rows(staged), _rows(reference)
    assert len(ours) == len(theirs) > 0
    for a, b in zip(ours, theirs):
        assert a.keys() == b.keys()
        for name in a:
            if isinstance(a[name], float):
                assert a[name] == pytest.approx(b[name], rel=1e-12, abs=1e-15), name
            else:
                assert a[name] == b[name], name


def test_regional_staging_keeps_footprints_and_drops_sama(built):
    rows = table(built.staged).to_pylist()
    by_detection = {}
    for r in rows:
        by_detection.setdefault((r["satellite"], r["acq_date"], r["acq_time"], r["latitude"], r["longitude"]),
                                []).append(r)
    assert any(len(parts) > 1 for parts in by_detection.values())  # deformed MODIS pixels spread
    for parts in by_detection.values():
        assert sum(r["footprint_weight"] for r in parts) == pytest.approx(1.0, abs=1e-12)
        assert sum(r["is_center"] for r in parts) == 1
    assert not [r for r in rows if r["satellite"] == "Terra" and r["acq_time"] == "0150"]
    assert {r["source_file"] for r in rows} <= {p.name for p in GERMAN}


def test_unknown_region_and_empty_region_raise(built, tmp_path):
    with pytest.raises(ValueError, match="Unknown region"):
        cube.stage_region(built.con, built.det, "atlantis", tmp_path)
    with pytest.raises(ValueError, match="No ingested detections"):
        cube.stage_region(built.con, built.det, "orlando_florida", tmp_path)


# ---------------- lookups ----------------

def test_global_counts_have_every_day_including_zeros(built):
    t = table(built.counts)
    assert t.column_names == ["satellite", "acq_date", "detection_count"]
    for sat in set(t["satellite"].to_pylist()):
        days = sorted(d for s, d in zip(t["satellite"].to_pylist(), t["acq_date"].to_pylist()) if s == sat)
        assert (days[-1] - days[0]).days + 1 == len(days) == len(set(days))
    assert 0 in t["detection_count"].to_pylist()


def test_outages_are_scripts02_with_the_known_snpp_outage(built):
    t = table(built.outages)
    assert t.column_names == ["acq_date", "satellite", "evidence"]
    rows = t.to_pylist()
    assert len({(r["acq_date"], r["satellite"], r["evidence"]) for r in rows}) == len(rows)
    assert {r["evidence"] for r in rows} <= {"known_outage", "global_count_drop", "zero_global_count"}
    for satellite, first, last in SNPP_OUTAGE:
        known = {r["acq_date"] for r in rows if r["satellite"] == satellite and r["evidence"] == "known_outage"}
        assert known == {r["acq_date"] for r in rows if r["evidence"] == "known_outage"}
        assert len(known) == (date.fromisoformat(last) - date.fromisoformat(first)).days + 1
    assert not [r for r in rows if r["satellite"] == "Aqua" and r["evidence"] == "known_outage"]
    # Interior zero-count days of the fixture's global counts are zero_global_count evidence.
    counts = table(built.counts).to_pylist()
    zero = {(r["acq_date"], r["satellite"]) for r in rows if r["evidence"] == "zero_global_count"}
    for satellite in {r["satellite"] for r in counts}:
        positive = [r["acq_date"] for r in counts if r["satellite"] == satellite and r["detection_count"] > 0]
        expected = {(r["acq_date"], satellite) for r in counts if r["satellite"] == satellite
                    and r["detection_count"] == 0 and min(positive) < r["acq_date"] < max(positive)}
        assert {z for z in zero if z[1] == satellite} == expected


def test_diurnal_ratios_table_shape(built):
    t = table(built.ratios)
    assert t.column_names == ["h3_r4", "month", "ratio", "matched_days"]
    assert len(t) > 0


# ---------------- pairs ----------------

def test_pairs_contract(built):
    t = table(built.pairs)
    assert t.column_names == list(pairs.PAIR_COLUMNS)
    rows = t.to_pylist()
    assert rows
    assert len({(r["h3_r7"], r["epoch_day"], r["daynight"]) for r in rows}) == len(rows)
    staged = table(built.staged).to_pylist()
    for r in rows:
        assert r["snpp_count"] > 0 and r["aqua_frp_corrected_mw"] > 0 and r["acq_date"] >= config.PAIRS_START
        raw = [d["frp"] for d in staged if d["satellite"] == "SNPP" and d["h3_r7"] == r["h3_r7"]
               and d["acq_date"] == r["acq_date"] and d["daynight"] == r["daynight"]]
        assert r["snpp_frp_sum_mw"] == pytest.approx(sum(raw)) and r["snpp_count"] == len(raw)


def test_lut_is_written_by_scripts03(built):
    lut = json.loads(built.lut.read_text())
    assert {"reference", "method", "threshold_mw", "biomes", "angle_edges_degrees", "models"} <= set(lut)
    assert lut["method"] == german.load("03_train_eqm_lut").METHOD


# ---------------- cube ----------------

def test_cube_schema_matches_contract(built):
    f = pq.ParquetFile(built.cube)
    assert [(x.name, x.type, x.nullable) for x in f.schema_arrow] == CUBE_FIELDS
    assert f.metadata.row_group(0).column(0).compression == "ZSTD"


def test_cube_sorted_unique_and_dates(built):
    t = table(built.cube)
    a, b, c = (t[k].to_numpy().astype(object) for k in ("h3_r4", "epoch_day", "h3_r7"))
    keys = list(zip(a, b, c))
    assert keys == sorted(keys) and len({(z, y) for _, y, z in keys}) == len(t)
    for e, y, d in zip(t["epoch_day"].to_pylist(), t["year"].to_pylist(), t["doy"].to_pylist()):
        day = config.EPOCH.fromordinal(config.EPOCH.toordinal() + e)
        assert day.year == y and day.timetuple().tm_yday == d


def test_cube_metadata_is_the_canonical_scripts04_provenance(built):
    meta = pq.ParquetFile(built.cube).schema_arrow.metadata
    builder = german.load("04_build_master_cube")
    assert b"SYNTHETIC" not in meta[b"source"] and b"REAL" in meta[b"source"]
    assert int(meta[b"real_rows"]) == pq.ParquetFile(built.cube).metadata.num_rows
    assert meta[b"synthetic_rows"] == b"0"
    assert meta[b"orbital_weighting"] == builder.ORBITAL_WEIGHTING.encode()
    assert meta[b"radiometric_harmonization"] == builder.RADIOMETRIC_HARMONIZATION.encode()
    ancillary = json.loads(meta[b"ancillary_coverage"])
    assert ancillary["input_present"] is False


def test_cube_without_ancillary_keeps_zero_sentinels_and_masks(built):
    t = table(built.cube).to_pylist()
    for r in t:
        assert r["cloud_cover_pct"] == 0.0 and r["burned_area_ha_mcd64"] == 0.0
        assert r["sensor_obs_mask"] & ~0b11111 == 0 and r["gap_status_mask"] & 0b0110 == 0
        assert 0.0 <= r["industrial_prob"] <= 1.0 and r["neighbor_fre_lag1"] >= 0.0


def test_snpp_outage_day_keeps_aqua_and_drops_snpp(built):
    day = (date(2022, 8, 5) - config.EPOCH).days  # inside the known SNPP outage 2022-07-27..08-10
    rows = [r for r in table(built.cube).to_pylist() if r["epoch_day"] == day]
    assert rows
    for r in rows:
        assert r["gap_status_mask"] & 1 and not r["sensor_obs_mask"] & 4
    # Aqua was nominal (the former "Aqua safe mode" was wrong): its observations survive.
    assert any(r["obs_aqua_fre"] is not None and r["sensor_obs_mask"] & 2 for r in rows)


def test_region_cube_only_has_region_detections(built):
    t = table(built.cube)
    staged = table(built.staged)
    assert set(t["h3_r7"].to_pylist()) == set(staged["h3_r7"].to_pylist())
    nominal = config.load_regions()[REGION]["nominal_biome"]
    assert set(t["igbp_biome"].to_pylist()) == {nominal}
    outside = [h3.str_to_int(h3.latlng_to_cell(r["latitude"], r["longitude"], 7))
               for r in table(built.det_file).to_pylist() if r["region"] != REGION]
    assert outside and not set(outside) & set(t["h3_r7"].to_pylist())


def test_reserved_synthetic_path_is_refused(built):
    with pytest.raises(ValueError, match="synthetic"):
        cube.publish_cube(built.staged, config.ROOT / "data/processed/fire_cube_synthetic.parquet", built.lookup)


def test_pipeline_has_no_parallel_stage_implementation():
    names = {p.stem for p in PKG.glob("*.py")}
    assert "industrial" not in names
    for name in ("AQUA_SAFE_MODE", "OUTAGE_DROP_FACTOR", "EQM_THRESHOLD_MW", "FRP_INTEGRATION_S"):
        assert not hasattr(config, name)
    assert not hasattr(cube, "estimate_vec") and not hasattr(pairs, "train_lut")


# ---------------- quality report ----------------

def test_quality_report_contract(report, built):
    assert {"coverage", "detections_by_year_satellite", "kept_by_year_satellite_region_tier",
            "global_daily_counts", "cube", "pairs_aqua_snpp"} <= set(report)
    columns = report["cube"]["columns"]
    assert [c["column"] for c in columns] == [n for n, _, _ in CUBE_FIELDS]
    assert {c["status"] for c in columns} <= {"computed", "partial", "sentinel", "not_available"}
    assert report["cube"]["schema_matches_contract"] is True
    assert report["cube"]["duplicate_keys"] == 0 and report["cube"]["unsorted_rows"] == 0
    md = (built.root / "quality_report.md").read_text()
    for heading in ("Coverage", "Detections per year and satellite", "Cube columns", "Aqua–Suomi-NPP pairs"):
        assert heading in md


# ---------------- API integration ----------------

def test_api_serves_the_real_cube(built):
    code = ("import json; from fastapi.testclient import TestClient; from backend.api.main import app\n"
            "with TestClient(app) as c: print(json.dumps(c.get('/api/health').json()))")
    env = {**os.environ, "FIRE_CUBE_PATH": str(built.cube)}
    env.pop("USE_SYNTHETIC_CUBE", None)
    out = subprocess.run([sys.executable, "-c", code], cwd=config.ROOT, env=env, capture_output=True, text=True,
                         timeout=120)
    assert out.returncode == 0, out.stderr
    health = json.loads(out.stdout.strip().splitlines()[-1])
    assert health["data_source"] == "real"


# ---------------- code rules ----------------

def test_no_fstring_sql_in_pipeline():
    for path in PKG.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("execute", "sql"):
                assert not (node.args and isinstance(node.args[0], ast.JoinedStr)), f"{path.name}:{node.lineno}"

