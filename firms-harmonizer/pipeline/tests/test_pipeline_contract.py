"""Frozen contract tests for pipeline/ (shape, keys, provenance, sentinels). No scientific assertions.
DO NOT EDIT — see FROZEN_TESTS.sha256."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import h3
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pipeline import config, cube, industrial, ingest, pairs
from pipeline.tests.conftest import FIXTURES, GERMAN

PKG = Path(__file__).resolve().parents[1]
CUBE_FIELDS = [(f.name, f.type, f.nullable) for f in cube.cube_schema()]


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


def test_detection_outside_regions_is_kept_with_fill_biome(built):
    t = table(built.det_file).to_pylist()
    out = [r for r in t if r["longitude"] == 20.5]
    assert len(out) == 1 and out[0]["region"] is None and out[0]["igbp_biome"] == config.IGBP_FILL
    regions = config.load_regions()
    for r in t:
        if r["region"] is not None:
            assert r["igbp_biome"] == regions[r["region"]]["nominal_biome"]


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


# ---------------- footprint / industrial ----------------

def test_footprint_weights_sum_to_one_and_only_deformed_modis_spreads(built):
    f = industrial.footprint_relation(built.con, built.det, built.industrial).arrow().read_all().to_pylist()
    by_det = {}
    for r in f:
        by_det.setdefault(r["det_id"], []).append(r)
    for rows in by_det.values():
        assert sum(r["footprint_weight"] for r in rows) == pytest.approx(1.0, abs=1e-12)
        assert sum(r["is_center"] for r in rows) == 1
        spreads = rows[0]["instrument"] == "MODIS" and rows[0]["scan"] * rows[0]["track"] > config.FOOTPRINT_MIN_AREA_KM2
        assert len(rows) == (7 if spreads else 1)
        for r in rows:
            assert r["corrected_frp"] == pytest.approx(r["frp"] * r["bowtie_weight"] * r["footprint_weight"])


def test_industrial_table_shape(built):
    t = table(built.industrial)
    assert t.column_names == ["h3_r10", "h_temp", "industrial_prob"]
    assert len(set(t["h3_r10"].to_pylist())) == len(t)
    p = t["industrial_prob"].to_numpy()
    assert np.all((p >= 0) & (p <= 1))


# ---------------- lookups ----------------

def test_global_counts_have_every_day_including_zeros(built):
    t = table(built.counts)
    assert t.column_names == ["satellite", "acq_date", "detection_count"]
    for sat in set(t["satellite"].to_pylist()):
        days = sorted(d for s, d in zip(t["satellite"].to_pylist(), t["acq_date"].to_pylist()) if s == sat)
        assert (days[-1] - days[0]).days + 1 == len(days) == len(set(days))
    assert 0 in t["detection_count"].to_pylist()


def test_outages_contain_known_aqua_safe_mode(built):
    t = table(built.outages).to_pylist()
    assert {"acq_date", "satellite", "evidence"} == set(t[0])
    start, end = config.AQUA_SAFE_MODE
    aqua = {r["acq_date"] for r in t if r["satellite"] == "Aqua" and r["evidence"] == "known_safe_mode"}
    assert len(aqua) == (end - start).days + 1
    assert len({(r["acq_date"], r["satellite"]) for r in t}) == len(t)


# ---------------- pairs ----------------

def test_pairs_contract(built):
    t = table(built.pairs)
    assert t.column_names == list(pairs.PAIR_COLUMNS)
    rows = t.to_pylist()
    assert rows
    assert len({(r["h3_r7"], r["epoch_day"], r["daynight"]) for r in rows}) == len(rows)
    staged = table(built.det_file).to_pylist()
    for r in rows:
        assert r["snpp_count"] > 0 and r["aqua_frp_corrected_mw"] > 0 and r["acq_date"] >= config.PAIRS_START
        raw = [d["frp"] for d in staged if d["satellite"] == "SNPP" and d["h3_r7"] == r["h3_r7"]
               and d["acq_date"] == r["acq_date"] and d["daynight"] == r["daynight"]]
        assert r["snpp_frp_sum_mw"] == pytest.approx(sum(raw)) and r["snpp_count"] == len(raw)


def test_lut_json_format(built):
    lut = json.loads(built.lut.read_text())
    assert {"reference", "threshold_mw", "biomes", "angle_edges_degrees", "models"} <= set(lut)


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


def test_cube_metadata_is_real_with_declared_sentinels(built):
    meta = pq.ParquetFile(built.cube).schema_arrow.metadata
    assert b"SYNTHETIC" not in meta[b"source"] and b"REAL" in meta[b"source"]
    sentinels = json.loads(meta[b"ancillary_sentinels"])
    assert {"cloud_cover_pct", "burned_area_ha_mcd64", "igbp_biome"} <= set(sentinels)
    assert int(meta[b"real_rows"]) == pq.ParquetFile(built.cube).metadata.num_rows
    assert meta[b"synthetic_rows"] == b"0"


def test_cube_sentinels_and_masks(built):
    t = table(built.cube).to_pylist()
    for r in t:
        assert r["cloud_cover_pct"] == config.CLOUD_SENTINEL and r["burned_area_ha_mcd64"] == config.BURNED_SENTINEL
        assert r["sensor_obs_mask"] & ~0b11111 == 0 and r["gap_status_mask"] & 0b0110 == 0
        assert 0.0 <= r["industrial_prob"] <= 1.0 and r["neighbor_fre_lag1"] >= 0.0


def test_outage_day_has_no_aqua_observation(built):
    start = config.AQUA_SAFE_MODE[0]
    day = (config.EPOCH.fromordinal(start.toordinal()) - config.EPOCH).days + 5  # 2022-08-05
    rows = [r for r in table(built.cube).to_pylist() if r["epoch_day"] == day]
    assert rows
    for r in rows:
        assert r["obs_aqua_fre"] is None and r["gap_status_mask"] & 1 and not r["sensor_obs_mask"] & 2


def test_region_cube_only_has_region_detections(built, built_global):
    region = table(built.cube)
    every = table(built_global.cube)
    assert 0 < len(region) < len(every)
    assert config.IGBP_FILL in every["igbp_biome"].to_pylist()
    assert config.IGBP_FILL not in region["igbp_biome"].to_pylist()


def test_reserved_synthetic_path_is_refused(built):
    with pytest.raises(ValueError, match="synthetic"):
        cube.build_cube(built.con, built.det, output=config.ROOT / "data/processed/fire_cube_synthetic.parquet",
                        industrial_path=built.industrial, lut_path=built.lut, outages=built.outages,
                        ratios=built.ratios)


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

