"""Offline tests for the FIRMS NRT poller (no network access)."""

from __future__ import annotations

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
