"""Offline tests for the FIRMS NRT poller (no network access)."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

import h3.api.basic_int as h3
import httpx
import pytest

from backend.db import nrt_poller
from backend.db.nrt_poller import (
    NrtPollerError,
    fetch_nrt,
    fetch_nrt_csv,
    parse_nrt_csv,
    write_nrt_csv,
)

SAMPLE = (
    "country_id,latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,"
    "instrument,confidence,version,bright_ti5,frp,daynight\n"
    "AR,29.413,-68.201,331.2,0.39,0.36,2026-11-13,1421,N20,VIIRS,n,2.0NRT,295.1,3.7,D\n"
    "AR,29.501,-68.115,340.8,0.42,0.40,2026-11-13,1421,N20,VIIRS,h,2.0NRT,300.4,12.1,D\n"
)


def _transport(payload: bytes = SAMPLE.encode(), status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=payload, request=request)

    return httpx.MockTransport(handler)


def test_parse_nrt_csv_coerces_numeric_fields() -> None:
    rows = parse_nrt_csv(SAMPLE.encode())
    assert len(rows) == 2
    assert rows[0]["latitude"] == pytest.approx(29.413)
    assert rows[0]["longitude"] == pytest.approx(-68.201)
    assert rows[0]["frp"] == pytest.approx(3.7)
    assert rows[0]["confidence"] == "n"
    assert rows[1]["acq_time"] == "1421"
    assert rows[1]["satellite"] == "N20"


def test_parse_nrt_csv_handles_empty_and_bom() -> None:
    assert parse_nrt_csv(b"") == []
    assert parse_nrt_csv(b"   \n") == []
    assert parse_nrt_csv(b"\xef\xbb\xbf" + SAMPLE.encode())[0]["country_id"] == "AR"


def test_fetch_builds_area_path_and_parses_rows() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=SAMPLE.encode(), request=request)

    rows = fetch_nrt(
        (-69.5, -31.0, -65.5, -27.5),
        source="VIIRS_SNPP_NRT",
        days=2,
        start_date="2026-11-13",
        map_key="test-key",
        transport=httpx.MockTransport(handler),
    )
    assert len(rows) == 2
    assert seen and "/test-key/VIIRS_SNPP_NRT/-69.5000,-31.0000,-65.5000,-27.5000/2/2026-11-13" in seen[0]


def test_missing_key_raises_before_any_request() -> None:
    with pytest.raises(NrtPollerError, match="FIRMS_MAP_KEY"):
        fetch_nrt_csv((0, 0, 1, 1), map_key="", transport=_transport())


@pytest.mark.parametrize("bbox", [(0, 0, 0, 1), (10, 0, 5, 1), (0, 20, 1, 10), (-200, 0, 1, 1)])
def test_invalid_bbox_is_rejected(bbox) -> None:
    with pytest.raises(NrtPollerError):
        fetch_nrt_csv(bbox, map_key="test-key", transport=_transport())


@pytest.mark.parametrize("days", [0, 6, -1])
def test_invalid_day_range_is_rejected(days: int) -> None:
    with pytest.raises(NrtPollerError, match="day range"):
        fetch_nrt_csv((0, 0, 1, 1), days=days, map_key="test-key", transport=_transport())


def test_invalid_source_and_date_are_rejected() -> None:
    with pytest.raises(NrtPollerError, match="source"):
        fetch_nrt_csv((0, 0, 1, 1), source="../etc/passwd", map_key="test-key", transport=_transport())
    with pytest.raises(NrtPollerError, match="date"):
        fetch_nrt_csv((0, 0, 1, 1), start_date="not-a-date", map_key="test-key", transport=_transport())


def test_http_error_does_not_leak_the_map_key() -> None:
    with pytest.raises(NrtPollerError) as caught:
        fetch_nrt_csv((0, 0, 1, 1), map_key="super-secret", transport=_transport(b"denied", 401))
    message = str(caught.value)
    assert "HTTP 401" in message
    assert "super-secret" not in message


def test_html_error_page_is_rejected() -> None:
    with pytest.raises(NrtPollerError, match="HTML"):
        fetch_nrt_csv((0, 0, 1, 1), map_key="test-key", transport=_transport(b"<html>oops</html>"))


def test_write_nrt_csv_accepts_a_directory_or_file(tmp_path) -> None:
    directory = write_nrt_csv(SAMPLE.encode(), tmp_path / "nrt")
    assert directory == tmp_path / "nrt" / "firms_nrt.csv"
    assert directory.read_bytes() == SAMPLE.encode()
    explicit = write_nrt_csv(SAMPLE.encode(), tmp_path / "out.csv")
    assert explicit.read_bytes() == SAMPLE.encode()


def test_default_transport_is_never_invoked_at_import() -> None:
    assert nrt_poller.MAX_DAY_RANGE == 5


SAMPLE_NRT_CSV = """latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,confidence,version,bright_ti5,frp,daynight
-31.42,-67.45,340.5,0.4,0.4,2026-07-15,1730,N,nominal,2.0NRT,295.2,14.8,D
-31.43,-67.46,335.2,0.4,0.4,2026-07-15,1730,N,nominal,2.0NRT,293.1,8.5,D
"""


def test_nrt_csv_ingestion_and_duckdb_table():
    nrt_poller.duckdb_engine.init_engine()
    count = nrt_poller.ingest_nrt_csv_text(SAMPLE_NRT_CSV)
    assert count == 2

    status = nrt_poller.get_nrt_status()
    assert status["status"] == "active"
    assert status["rows_ingested"] == 2
    assert status["last_success_utc"] is not None

    with nrt_poller.duckdb_engine.get_db_cursor() as cur:
        rows = cur.sql("SELECT h3_r4, h3_r7, epoch_day, raw_frp_mw, satellite FROM nrt_hotspots").fetchall()
        assert len(rows) == 2
        assert rows[0][2] == (date(2026, 7, 15) - date(1970, 1, 1)).days
        assert rows[0][3] > 0.0
        assert rows[0][4] == "N"
        assert all(row[0] == h3.cell_to_parent(row[1], 4) for row in rows)


def test_nrt_csv_empty_returns_zero():
    count = nrt_poller.ingest_nrt_csv_text("")
    assert count == 0


def test_nrt_poller_offline_resilience(monkeypatch):
    monkeypatch.setenv("OFFLINE_MODE", "1")

    def forbid_fetch(*args, **kwargs):
        pytest.fail("Offline polling contacted FIRMS")

    monkeypatch.setattr(nrt_poller, "fetch_nrt_csv", forbid_fetch)
    assert asyncio.run(nrt_poller.poll_firms_nrt_once(map_key="test-key")) == 0
    assert nrt_poller.get_nrt_status()["status"] == "offline_standby"


def test_nrt_poller_retains_a_safe_error(monkeypatch):
    monkeypatch.delenv("OFFLINE_MODE", raising=False)
    monkeypatch.delenv("AIRPLANE_MODE", raising=False)
    monkeypatch.setenv("USE_SYNTHETIC_CUBE", "0")

    def fail(*args, **kwargs):
        raise NrtPollerError("FIRMS NRT request failed: ConnectTimeout.")

    monkeypatch.setattr(nrt_poller, "fetch_nrt_csv", fail)
    assert asyncio.run(nrt_poller.poll_firms_nrt_once(map_key="test-key")) == 0
    assert nrt_poller.get_nrt_status()["last_error"] == "FIRMS NRT request failed: ConnectTimeout."


def test_sync_cube_offline_mode(monkeypatch):
    monkeypatch.setenv("USE_SYNTHETIC_CUBE", "0")
    monkeypatch.setenv("OFFLINE_MODE", "1")
    res = nrt_poller.sync_cube(sync_full_month=True)
    assert res["status"] == "error"
    assert "internet connection" in res["error"]


def _valid_sync_response(request):
    import csv, io
    parts = request.url.path.split('/')
    source, first = parts[-4], parts[-1]
    platform = {'MODIS_NRT':'Terra','VIIRS_SNPP_NRT':'N','VIIRS_NOAA20_NRT':'N20','VIIRS_NOAA21_NRT':'N21'}[source]
    reader = csv.DictReader(io.StringIO(SAMPLE))
    rows = list(reader)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=reader.fieldnames)
    writer.writeheader()
    for row in rows:
        row.update(latitude='-29.413', longitude='-68.201', acq_date=first, satellite=platform)
        writer.writerow(row)
    return httpx.Response(200, content=output.getvalue().encode(), request=request)


def test_sync_cube_with_mock_transport(tmp_path, monkeypatch):
    monkeypatch.delenv("OFFLINE_MODE", raising=False)
    monkeypatch.delenv("AIRPLANE_MODE", raising=False)
    monkeypatch.setenv("USE_SYNTHETIC_CUBE", "0")
    monkeypatch.setenv("FIRMS_MAP_KEY", "test_key_abc")
    monkeypatch.setattr(nrt_poller, "ROOT", tmp_path)
    monkeypatch.setattr(nrt_poller, "_rebuild_cube", lambda: None)
    monkeypatch.setattr(nrt_poller.duckdb_engine, "cube_path", lambda: tmp_path / "missing.parquet")
    monkeypatch.setattr(nrt_poller.duckdb_engine, "data_source", lambda: "real")

    transport = httpx.MockTransport(_valid_sync_response)
    res = nrt_poller.sync_cube(days=1, regions=["chilecito_la_rioja"], transport=transport)
    assert res["status"] == "success"
    assert res["new_detections_count"] >= 1
    assert "chilecito_la_rioja" in res["regions_updated"]
    status = nrt_poller.get_sync_status()
    assert status["status"] == "success"


def test_sync_status_reports_persisted_dates_and_default_sync_reaches_today(tmp_path, monkeypatch):
    import pyarrow as pa
    import pyarrow.parquet as pq

    today = date(2026, 12, 3)
    latest = today - timedelta(days=2)
    cube = tmp_path / "fire_cube.parquet"
    pq.write_table(pa.table({"epoch_day": [(latest - nrt_poller.EPOCH).days]}), cube)
    monkeypatch.setattr(nrt_poller.duckdb_engine, "cube_path", lambda: cube)
    monkeypatch.setattr(nrt_poller.duckdb_engine, "data_source", lambda: "real")
    monkeypatch.setattr(nrt_poller, "ROOT", tmp_path)
    monkeypatch.setattr(nrt_poller, "_rebuild_cube", lambda: None)
    monkeypatch.setattr(nrt_poller, "_CUBE_SYNC_STATUS", {"status": "idle"})
    monkeypatch.setenv("USE_SYNTHETIC_CUBE", "0")
    monkeypatch.setenv("FIRMS_MAP_KEY", "test_key")

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 12, 3, tzinfo=tz)

    monkeypatch.setattr(nrt_poller, "datetime", FrozenDateTime)
    requests = []

    def fetch(request):
        requests.append(request.url.path.split("/")[-2:])
        return httpx.Response(200, content=SAMPLE.splitlines()[0].encode(), request=request)

    assert nrt_poller.get_sync_status()["date_coverage_end"] == latest.isoformat()
    result = nrt_poller.sync_cube(regions=["chilecito_la_rioja"], transport=httpx.MockTransport(fetch))
    assert requests == [["4", (latest - timedelta(days=1)).isoformat()]] * len(nrt_poller.SYNC_SOURCES)
    assert result["status"] == "success"
    assert result["date_coverage_end"] == latest.isoformat()
    failed = nrt_poller.sync_cube(regions=["chilecito_la_rioja"], transport=_transport(status=503))
    assert failed["status"] == "error"
    assert failed["date_coverage_end"] == latest.isoformat()
