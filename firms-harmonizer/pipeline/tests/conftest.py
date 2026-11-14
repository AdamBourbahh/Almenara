"""Builds the whole pipeline once on the FIRMS-format fixtures (tests/fixtures/), in a temporary folder."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline import config, cube, industrial, ingest, lookups, pairs, quality

FIXTURES = Path(__file__).parent / "fixtures"
GERMAN = sorted((FIXTURES / "german").glob("*.csv"))
GLOBAL = sorted((FIXTURES / "global").glob("*.csv"))


def build_all(root: Path, files: list[Path], region: str | None = "cerrado_brazil") -> SimpleNamespace:
    con = config.connect()
    det_file = root / "detections" / "product=fixture" / "year=0" / "part.parquet"
    stats = ingest.ingest_csvs(con, files, det_file)
    det = str(root / "detections" / "*" / "*" / "part.parquet")
    ns = SimpleNamespace(root=root, con=con, det=det, det_file=det_file, stats=stats,
                         industrial=root / "industrial_r10.parquet", counts=root / "global_daily_counts.parquet",
                         outages=root / "sensor_outages.parquet", ratios=root / "diurnal_ratios.parquet",
                         pairs=root / "pairs_aqua_snpp.parquet", lut=root / "eqm_gpd_lut.json",
                         cube=root / "fire_cube_real.parquet")
    industrial.build_industrial(con, det, ns.industrial)
    lookups.build_global_counts(con, det, ns.counts)
    lookups.build_outages(con, ns.counts, ns.outages)
    lookups.build_diurnal_ratios(con, det, ns.industrial, ns.ratios)
    pairs.build_pairs(con, det, ns.industrial, ns.pairs)
    pairs.train_lut(con, ns.pairs, ns.lut)
    cube.build_cube(con, det, region=region, output=ns.cube, industrial_path=ns.industrial, lut_path=ns.lut,
                    outages=ns.outages, ratios=ns.ratios, coverage={"fixture": ["2015-08-10", "2022-08-05"]})
    return ns


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    return build_all(tmp_path_factory.mktemp("pipeline"), GERMAN + GLOBAL)


@pytest.fixture(scope="session")
def built_global(tmp_path_factory):
    return build_all(tmp_path_factory.mktemp("pipeline_global"), GERMAN + GLOBAL, region=None)


@pytest.fixture()
def report(built, monkeypatch):
    for name, value in (("CUBE", built.cube), ("PAIRS", built.pairs), ("GLOBAL_COUNTS", built.counts),
                        ("REPORT_MD", built.root / "quality_report.md"),
                        ("REPORT_JSON", built.root / "quality_report.json"),
                        ("STAGED", built.root / "staged_none"), ("RAW", built.root / "raw_none")):
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(lookups, "OUTAGES", built.outages)
    monkeypatch.setattr(pairs, "LUT", built.lut)
    return quality.build_report(built.con, built.cube)
