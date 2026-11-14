"""Streaming archive pass on tiny fixture zips built here (no network, no real archive)."""

from __future__ import annotations

import csv
import json
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from pipeline import archive_pass, config, download, german, ingest, lookups, run

HEADER = ["latitude", "longitude", "brightness", "scan", "track", "acq_date", "acq_time", "satellite",
          "instrument", "confidence", "version", "bright_t31", "frp", "daynight"]
CERRADO = (-57.2, -17.8, -55.2, -16.0)        # west, south, east, north of data/regions.json
CERRADO_POINT = dict(latitude="-16.9", longitude="-56.2")
ONE = ["cerrado_brazil"]


def row(**kw) -> dict:
    base = dict(latitude="10.0", longitude="20.0", brightness="330.5", scan="1.0", track="1.0",
                acq_date="2005-01-01", acq_time="1030", satellite="Terra", instrument="MODIS",
                confidence="80", version="6.1NRT", bright_t31="300.1", frp="12.50", daynight="D")
    return base | kw


def make_zip(path: Path, members: dict[str, list[dict]], header=HEADER) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, rows in members.items():
            lines = [",".join(header)] + [",".join(str(r.get(h, "")) for h in header) for r in rows]
            zf.writestr(name, "\n".join(lines) + "\n")
    return path


@pytest.fixture()
def env(tmp_path, monkeypatch):
    real = tmp_path / "real"
    for name, value in (("REAL", real), ("RAW", real / "raw"), ("TMP", real / ".tmp"),
                        ("REGIONS", real / "regions"), ("ARCHIVE_PASS", real / "archive_pass"),
                        ("ARCHIVE_COUNTS", tmp_path / "lookup/global_daily_counts_archive.csv")):
        monkeypatch.setattr(config, name, value)
    return tmp_path


@pytest.fixture()
def con(env):
    return config.connect()


def process(con, zip_path, product="modis", year=2005, regions=("cerrado_brazil",)):
    return archive_pass.process_archive(con, zip_path, product, year, list(regions))


def merged_rows(path: Path) -> list[tuple]:
    with path.open(encoding="utf-8") as fh:
        reader = csv.reader(fh)
        assert next(reader) == ["satellite", "acq_date", "detection_count"]
        return [(s, d, int(n)) for s, d, n in reader]


def test_counts_with_explicit_zero_days_and_canonical_names(env, con):
    rows = [
        row(satellite="T", latitude="10.0", acq_date="2005-01-01"), row(satellite="T", latitude="10.1"),
        row(satellite="T", latitude="10.2"),
        row(satellite="T", latitude="10.0", acq_date="2005-01-04"), row(satellite="T", latitude="10.1",
                                                                          acq_date="2005-01-04"),
        row(satellite="Aqua", acq_date="2005-01-02", acq_time="1330"),
    ]
    stats = process(con, make_zip(env / "z.zip", {"modis_2005_Brazil.csv": rows}))
    assert stats["satellites"]["Terra"]["detections"] == 5 and stats["satellites"]["Aqua"]["detections"] == 1
    out = env / "merged.csv"
    result = archive_pass.merge_counts(out, partial=True)
    assert merged_rows(out) == [
        ("Aqua", "2005-01-02", 1),
        ("Terra", "2005-01-01", 3), ("Terra", "2005-01-02", 0), ("Terra", "2005-01-03", 0),
        ("Terra", "2005-01-04", 2)]
    assert result["satellites"]["Terra"]["zero_days"] == 2 and result["satellites"]["Terra"]["days"] == 4


def test_exact_duplicates_collapse_across_members_and_match_the_global_ingest(env, con):
    sama = row(satellite="Aqua", latitude="-20.0", longitude="-50.0", daynight="N", confidence="10",
               bright_t31="329.5", acq_time="0200")
    members = {"modis_2005_A.csv": [row(), row(latitude="10.5"), sama,
                                     row(acq_date="2000-10-31"), row(satellite="Terra", frp="-1")],
               "modis_2005_B.csv": [row(), row(acq_date="2005-01-03", satellite="Aqua")]}
    archive = make_zip(env / "z.zip", members)
    process(con, archive)
    out = env / "merged.csv"
    archive_pass.merge_counts(out, partial=True)
    got = merged_rows(out)
    assert ("Terra", "2005-01-01", 2) in got                      # the repeated row counts once
    assert not any(d < "2005-01-01" for _, d, _ in got)           # validity window, negative FRP dropped
    assert not any(s == "Aqua" and d == "2005-01-01" for s, d, _ in got)   # SAMA artifact excluded
    # Parity: same counts as the pipeline's global ingest over the same CSVs.
    files = ingest.extract_csvs(archive, env / "parity")
    ingest.ingest_csvs(con, files, env / "det/part.parquet")
    parity = lookups.build_global_counts(con, str(env / "det/part.parquet"), env / "parity.parquet")
    expected = con.execute("SELECT satellite, acq_date::VARCHAR, detection_count FROM read_parquet(?) "
                           "ORDER BY 1, 2", [str(parity)]).fetchall()
    assert got == [(s, d, n) for s, d, n in expected]


def test_clipping_is_inclusive_at_the_bbox_edges_and_keeps_original_text(env, con):
    west, south, east, north = CERRADO
    inside = [row(latitude=str(south), longitude=str(west), frp="1.10"),
              row(latitude=str(north), longitude=str(east), frp="2.20", acq_time="0005"),
              row(latitude="-16.9", longitude="-56.2", frp="3.30", acq_time="1200")]
    outside = [row(latitude="-17.8001", longitude="-56.0"), row(latitude="-16.5", longitude="-57.2001"),
               row(latitude="-15.9999", longitude="-56.0"), row(latitude="-16.5", longitude="-55.1999")]
    stats = process(con, make_zip(env / "z.zip", {"modis_2005_Brazil.csv": inside + outside}),
                    regions=("cerrado_brazil", "niger_delta_flaring"))
    assert stats["regions"] == {"cerrado_brazil": 3, "niger_delta_flaring": 0}
    target = archive_pass.clip_path("cerrado_brazil", "modis", 2005)
    assert target.name == "cerrado_brazil_modis_archive_2005.csv" and "nrt" not in target.name.lower()
    with target.open(newline="", encoding="utf-8") as fh:
        records = list(csv.DictReader(fh))
    assert list(records[0]) == HEADER
    assert [r["frp"] for r in records] == ["2.20", "1.10", "3.30"]       # acq_time order, text untouched
    assert records[0]["version"] == "6.1NRT"
    assert not archive_pass.clip_path("niger_delta_flaring", "modis", 2005).exists()   # no empty files
    assert stats["rows_read"] == 7


def test_clipped_files_are_ingestible_by_script_01_together_with_a_raw_directory(env, con, tmp_path):
    process(con, make_zip(env / "z.zip", {"m.csv": [row(**CERRADO_POINT, frp="3.30")]}))
    raw = tmp_path / "raw_dir"
    raw.mkdir()
    with (raw / "other_archive.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADER)
        writer.writeheader()
        writer.writerow(row(latitude="-3.1", longitude="-60.0", satellite="Aqua", frp="9.0"))
    script = german.load("01_ingest_firms")
    staged = script.ingest_raw_firms(raw, tmp_path / "staged.parquet",
                                     [archive_pass.clip_path("cerrado_brazil", "modis", 2005).parent])
    import pyarrow.parquet as pq
    table = pq.read_table(staged).to_pylist()
    assert {(r["region"], r["satellite"], r["source_file"]) for r in table} == {
        ("cerrado_brazil", "Terra", "cerrado_brazil_modis_archive_2005.csv"),
        ("amazonas_manaus", "Aqua", "other_archive.csv")}


def test_unknown_satellite_raises_and_leaves_no_success_marker(env, con):
    archive = make_zip(env / "z.zip", {"m.csv": [row(), row(satellite="Z9")]})
    with pytest.raises(ValueError, match="Unknown FIRMS satellite codes"):
        process(con, archive)
    folder = archive_pass.chunk_dir("modis", 2005)
    assert not (folder / "_SUCCESS").exists() and not (folder / "counts.csv").exists()
    assert not (config.TMP / "archive_modis_2005").exists()           # extraction folder cleaned up


def test_members_with_different_headers_are_refused(env, con):
    archive = env / "z.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("a.csv", ",".join(HEADER) + "\n" + ",".join(row()[h] for h in HEADER) + "\n")
        zf.writestr("b.csv", ",".join(HEADER[:-1]) + "\n" + ",".join(row()[h] for h in HEADER[:-1]) + "\n")
    with pytest.raises(ValueError, match="different headers"):
        process(con, archive)


@pytest.fixture()
def fake_download(env, monkeypatch):
    calls = []

    def fake(client, product, year):
        calls.append((product, year))
        return make_zip(download.archive_path(product, year),
                        {f"{product}_{year}.csv": [row(**CERRADO_POINT, acq_date=f"{year}-03-01")]})
    monkeypatch.setattr(download, "download_one", fake)
    return calls


def test_run_pass_is_resumable_and_deletes_the_zip(env, con, fake_download, capsys):
    archive_pass.run_pass(["modis"], [2005, 2006], regions=ONE, con=con)
    assert fake_download == [("modis", 2005), ("modis", 2006)]
    for year in (2005, 2006):
        assert (archive_pass.chunk_dir("modis", year) / "_SUCCESS").is_file()
        assert not download.archive_path("modis", year).exists()      # zip deleted after success
        assert archive_pass.clip_path("cerrado_brazil", "modis", year).is_file()
    archive_pass.run_pass(["modis"], [2005, 2006], regions=ONE, con=con)
    assert len(fake_download) == 2 and "skipped" in capsys.readouterr().out
    archive_pass.run_pass(["modis"], [2005], regions=ONE, force=True, con=con)
    assert fake_download[-1] == ("modis", 2005) and len(fake_download) == 3
    # A newly requested region invalidates the chunk even without --force.
    archive_pass.run_pass(["modis"], [2005], regions=["cerrado_brazil", "california_usa"], con=con)
    assert len(fake_download) == 4
    stats = json.loads((archive_pass.chunk_dir("modis", 2005) / "stats.json").read_text())
    assert set(stats["regions"]) == {"cerrado_brazil", "california_usa"}


def test_keep_zips_and_failure_keep_the_zip(env, con, fake_download):
    archive_pass.run_pass(["modis"], [2005], keep_zips=True, con=con)
    assert download.archive_path("modis", 2005).is_file()
    bad = make_zip(download.archive_path("modis", 2006), {"m.csv": [row(satellite="Z9")]})
    with pytest.raises(ValueError):
        archive_pass.process_archive(con, bad, "modis", 2006, ["cerrado_brazil"])
    assert bad.is_file()


def test_run_pass_rejects_unknown_region_and_empty_selection(env, con):
    with pytest.raises(ValueError, match="Unknown regions"):
        archive_pass.run_pass(["modis"], [2005], regions=["atlantis"], con=con)
    with pytest.raises(ValueError, match="No \\(product, year\\)"):
        archive_pass.run_pass(["modis"], [1999], con=con)


def test_merge_refuses_missing_chunks(env, con):
    process(con, make_zip(env / "a.zip", {"m.csv": [row(acq_date="2005-01-01")]}), year=2005)
    with pytest.raises(archive_pass.ArchiveIncomplete, match="Missing archive-pass chunks") as full:
        archive_pass.merge_counts(env / "out.csv")
    assert "modis 2000" in str(full.value) and "viirs-snpp 2012" in str(full.value)
    assert not (env / "out.csv").exists()
    process(con, make_zip(env / "b.zip", {"m.csv": [row(acq_date="2007-01-01")]}), year=2007)
    with pytest.raises(archive_pass.ArchiveIncomplete, match="modis 2006"):
        archive_pass.merge_counts(env / "out.csv", partial=True)    # a hole inside the span is never allowed
    process(con, make_zip(env / "c.zip", {"m.csv": [row(acq_date="2006-01-01")]}), year=2006)
    result = archive_pass.merge_counts(env / "out.csv", partial=True)
    assert result["chunks"] == 3
    days = {d for s, d, _ in merged_rows(env / "out.csv") if s == "Terra"}
    assert len(days) == (date(2007, 1, 1) - date(2005, 1, 1)).days + 1


def test_merge_requires_a_finished_chunk_and_unique_days(env, con):
    with pytest.raises(archive_pass.ArchiveIncomplete, match="No finished chunk"):
        archive_pass.merge_counts(env / "out.csv")
    process(con, make_zip(env / "a.zip", {"m.csv": [row(acq_date="2005-01-01")]}), year=2005)
    process(con, make_zip(env / "b.zip", {"m.csv": [row(acq_date="2005-01-01")]}), year=2006)
    with pytest.raises(archive_pass.ArchiveIncomplete, match="more than one chunk"):
        archive_pass.merge_counts(env / "out.csv", partial=True)


def test_merge_is_deterministic_and_sorted(env, con):
    process(con, make_zip(env / "a.zip", {"m.csv": [row(satellite="Terra", acq_date="2005-01-02"),
                                                     row(satellite="Aqua", acq_date="2005-01-01")]}))
    archive_pass.merge_counts(env / "one.csv", partial=True)
    archive_pass.merge_counts(env / "two.csv", partial=True)
    assert (env / "one.csv").read_bytes() == (env / "two.csv").read_bytes()
    rows = merged_rows(env / "one.csv")
    assert rows == sorted(rows)


def test_run_cli_forwards_archive_pass_and_merge(env, con, fake_download, monkeypatch):
    monkeypatch.setattr(config, "connect", lambda *a, **k: con)
    assert run.main(["--archive-pass", "--products", "modis", "--years", "2005", "--regions",
                     "cerrado_brazil", "--keep-zips"]) == 0
    assert download.archive_path("modis", 2005).is_file()
    assert run.main(["--merge-counts", "--partial"]) == 0
    assert merged_rows(config.ARCHIVE_COUNTS) == [("Terra", "2005-03-01", 1)]
    with pytest.raises(SystemExit):
        run.main(["--archive-pass", "--merge-counts"])
