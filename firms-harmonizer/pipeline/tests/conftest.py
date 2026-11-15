"""Builds the whole pipeline once on the FIRMS-format fixtures (tests/fixtures/), in a temporary folder."""

from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline import config, cube, german, ingest, lookups, pairs, quality

FIXTURES = Path(__file__).parent / "fixtures"
GERMAN = sorted((FIXTURES / "german").glob("*.csv"))
GLOBAL = sorted((FIXTURES / "global").glob("*.csv"))
REGION = "cerrado_brazil"
# data/regions.json declares no coverage for this preset yet; scripts/04 requires one for every detection day.
FIXTURE_COVERAGE = [["2015-08-10", "2022-08-05"]]


def fixture_regions() -> dict:
    regions = copy.deepcopy(config.load_regions())
    regions[REGION]["coverage"] = FIXTURE_COVERAGE
    return regions


@pytest.fixture(scope="session")
def regions_with_coverage():
    """scripts/01 and scripts/04 read regions through scripts/01.load_regions; give the preset a coverage."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(german.load("01_ingest_firms"), "load_regions", fixture_regions)
        yield


def build_all(root: Path, files: list[Path]) -> SimpleNamespace:
    con = config.connect()
    det_file = root / "detections" / "product=fixture" / "year=0" / "part.parquet"
    stats = ingest.ingest_csvs(con, files, det_file)
    det = str(root / "detections" / "*" / "*" / "part.parquet")
    counts = lookups.build_global_counts(con, det, root / "global_daily_counts.parquet")
    work = root / "regions" / REGION
    build = cube.build_region(con, det, REGION, global_counts=counts, work=work)
    pairs_path = pairs.build_pairs(con, build.staged, work / pairs.PAIRS_NAME)
    return SimpleNamespace(root=root, con=con, det=det, det_file=det_file, stats=stats, counts=counts, work=work,
                           staged=build.staged, lookup=build.lookup, outages=build.lookup / "sensor_outages.parquet",
                           ratios=build.lookup / "diurnal_ratios.parquet", lut=build.lookup / cube.LUT_NAME,
                           pairs=pairs_path, cube=build.cube)


@pytest.fixture(scope="session")
def built(tmp_path_factory, regions_with_coverage):
    return build_all(tmp_path_factory.mktemp("pipeline"), GERMAN + GLOBAL)


@pytest.fixture()
def report(built, monkeypatch):
    for name, value in (("REPORT_MD", built.root / "quality_report.md"),
                        ("REPORT_JSON", built.root / "quality_report.json"),
                        ("STAGED", built.root / "staged_none"), ("RAW", built.root / "raw_none")):
        monkeypatch.setattr(config, name, value)
    return quality.build_report(built.con, REGION, work=built.work, global_counts=built.counts)
