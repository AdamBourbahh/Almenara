"""Tests for the NASA FIRMS Near-Real-Time (NRT) Poller module."""

import asyncio
from datetime import date
from unittest.mock import AsyncMock, patch

import duckdb
import pytest

from backend.db import duckdb_engine, nrt_poller

SAMPLE_NRT_CSV = """latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,confidence,version,bright_ti5,frp,daynight
-31.42,-67.45,340.5,0.4,0.4,2026-07-15,1730,N,nominal,2.0NRT,295.2,14.8,D
-31.43,-67.46,335.2,0.4,0.4,2026-07-15,1730,N,nominal,2.0NRT,293.1,8.5,D
"""


def test_nrt_csv_ingestion_and_duckdb_table():
    duckdb_engine.init_engine()
    count = nrt_poller.ingest_nrt_csv_text(SAMPLE_NRT_CSV)
    assert count == 2

    status = nrt_poller.get_nrt_status()
    assert status["status"] == "active"
    assert status["rows_ingested"] == 2
    assert status["last_success_utc"] is not None

    with duckdb_engine.get_db_cursor() as cur:
        rows = cur.sql("SELECT h3_r4, h3_r7, epoch_day, raw_frp_mw, satellite FROM nrt_hotspots").fetchall()
        assert len(rows) == 2
        assert rows[0][2] == (date(2026, 7, 15) - date(1970, 1, 1)).days
        assert rows[0][3] > 0.0
        assert rows[0][4] == "N"


def test_nrt_csv_empty_returns_zero():
    count = nrt_poller.ingest_nrt_csv_text("")
    assert count == 0


@pytest.mark.anyio
async def test_nrt_poller_offline_resilience(monkeypatch):
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    monkeypatch.setenv("OFFLINE_MODE", "1")

    res = await nrt_poller.poll_firms_nrt_once()
    assert res == 0
    status = nrt_poller.get_nrt_status()
    assert status["status"] == "offline_standby"


@pytest.mark.anyio
async def test_nrt_poller_network_timeout(monkeypatch):
    monkeypatch.setenv("FIRMS_MAP_KEY", "dummy_test_key")
    monkeypatch.delenv("OFFLINE_MODE", raising=False)
    monkeypatch.delenv("AIRPLANE_MODE", raising=False)

    with patch("httpx.AsyncClient.get", side_effect=Exception("Connection refused")):
        res = await nrt_poller.poll_firms_nrt_once()
        assert res == 0
        status = nrt_poller.get_nrt_status()
        assert status["status"] == "error"
        assert "Connection refused" in status["last_error"]
