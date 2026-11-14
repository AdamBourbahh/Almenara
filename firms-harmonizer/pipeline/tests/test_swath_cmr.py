"""MODIS swath-gap evidence from CMR granule footprints, on fixtures shaped like the real response (no network)."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import h3
import httpx
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pipeline import swath_cmr

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "cmr_mod03_granules.json").read_text())
D1, D2, D3 = date(2022, 8, 1), date(2022, 8, 2), date(2022, 8, 3)
REGIONS = {"eq": {"bounds": [10.0, 0.0, 11.0, 0.6]}, "far": {"bounds": [40.0, 0.0, 40.2, 0.2]}}
EAST_EDGE = 10.4                      # west-part ring: lon 9..10.2, meridian edge (an exact great circle)


def ring_string(corners):
    """CMR ring text: lat-first pairs, closed (first point repeated)."""
    points = list(corners) + [corners[0]]
    return " ".join(f"{lat:g} {lon:g}" for lat, lon in points)


def entry(time_start, corners=None, day_night="DAY", minutes=5, concept="C1379767668-LAADS"):
    """A granule entry with the keys of a real CMR JSON response (``polygons`` omitted when corners is None)."""
    end = datetime.fromisoformat(time_start.replace("Z", "+00:00")) + timedelta(minutes=minutes)
    item = {"time_start": time_start, "time_end": end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "day_night_flag": day_night, "coordinate_system": "GEODETIC", "collection_concept_id": concept,
            "dataset_id": "MODIS/Terra Geolocation Fields 5-Min L1A Swath 1km", "links": [{"href": "x"}]}
    if corners is not None:
        item["polygons"] = [[ring_string(corners)]]
    return item


def box(west, south, east, north):
    return [(south, west), (south, east), (north, east), (north, west)]


WHOLE_EQ = box(9.0, -1.0, 12.0, 1.5)
WEST_EQ = box(9.0, -1.0, EAST_EDGE, 1.5)
WHOLE_FAR = box(39.0, -1.0, 41.5, 1.5)


def paging_client(entries_by_short_name: dict, calls: list, fail_first: int = 0, hits_offset: int = 0):
    """httpx client answering like CMR: sorted pages, ``CMR-Hits`` and ``CMR-Search-After`` headers."""
    state = {"failures": fail_first}

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        calls.append({"params": params, "search_after": request.headers.get("CMR-Search-After"),
                      "user_agent": request.headers.get("User-Agent")})
        if state["failures"]:
            state["failures"] -= 1
            return httpx.Response(503, text="busy")
        west, south, east, north = map(float, params["bounding_box"].split(","))
        t0, t1 = params["temporal"].split(",")
        selected = []
        for item in entries_by_short_name.get(params["short_name"], []):
            if not (item["time_start"] < t1 and item["time_end"] > t0):
                continue
            rings = swath_cmr.parse_rings(item.get("polygons", []))
            lats = [lat for ring in rings for lat, _ in ring]
            lons = [lon for ring in rings for _, lon in ring]
            touches = not rings or (min(lons) <= east and max(lons) >= west
                                    and min(lats) <= north and max(lats) >= south)
            if touches:
                selected.append(item)
        selected.sort(key=lambda item: item["time_start"])
        size = int(params["page_size"])
        offset = json.loads(request.headers["CMR-Search-After"])[0] if "CMR-Search-After" in request.headers else 0
        page = selected[offset:offset + size]
        headers = {"CMR-Hits": str(len(selected) + hits_offset),
                   "CMR-Search-After": json.dumps([offset + len(page), 1])}
        return httpx.Response(200, json={"feed": {"entry": page}}, headers=headers)

    return httpx.Client(transport=httpx.MockTransport(handler), headers=swath_cmr.HEADERS)


def write_outages(path, rows):
    schema = pa.schema([("acq_date", pa.date32()), ("satellite", pa.string()), ("evidence", pa.string())])
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)
    return path


def fetch_and_build(tmp_path, entries, outages=(), start=D1, end=D3, page_size=2):
    cache = tmp_path / "cache"
    calls = []
    with paging_client(entries, calls) as client:
        requests = swath_cmr.fetch_all(client, REGIONS, cache, start, end, sleep=0, page_size=page_size)
    outage_path = write_outages(tmp_path / "sensor_outages.parquet", list(outages))
    out = swath_cmr.build_gap_table(REGIONS, cache, tmp_path / "gaps.parquet", outage_path, start, end)
    return out, calls, requests


def cell_points_lonlat(cell):
    return [h3.cell_to_latlng(cell)] + list(h3.cell_to_boundary(cell))


def eq_cells():
    return [format(c, "x") for c in swath_cmr.region_r4_cells(REGIONS["eq"]["bounds"])]


def test_parse_rings_reads_lat_first_and_drops_the_closing_point():
    rings = swath_cmr.parse_rings(FIXTURE["feed"]["entry"][0]["polygons"])
    assert rings == [[(2.513893, -50.288328), (-0.400538, -71.173636), (-18.41056, -67.910458),
                      (-15.320336, -46.12695)]]
    assert swath_cmr.parse_rings([]) == []
    with pytest.raises(ValueError, match="latitude"):
        swath_cmr.parse_rings([["120.0 10.0 121.0 10.0 121.0 11.0 120.0 10.0"]])   # lon-first text is rejected
    with pytest.raises(ValueError, match="pairs"):
        swath_cmr.parse_rings([["1 2 3"]])


def test_compact_entry_keeps_only_satellite_time_flag_and_rings():
    item = swath_cmr.compact_entry(FIXTURE["feed"]["entry"][2])
    assert item == ["2022-08-01T14:40:00.000Z", "2022-08-01T14:45:00.000Z", "DAY",
                    [[-11.782264, -79.537249, -14.923188, -58.201269, 3.071843, -54.679941, 6.100486, -75.528104]]]


def test_duplicate_versions_are_merged_by_time_start():
    compact = [swath_cmr.compact_entry(item) for item in FIXTURE["feed"]["entry"]]
    merged = swath_cmr.dedupe(compact)
    assert [g[0] for g in merged] == ["2022-08-01T02:15:00.000Z", "2022-08-01T14:40:00.000Z"]
    # The two collection versions differ by metres; both rings are kept (union = conservative coverage).
    assert all(len(g[3]) == 2 for g in merged)
    assert swath_cmr.dedupe(compact[::-1]) == merged


def test_fetch_pages_with_search_after_and_validates_hits(tmp_path):
    entries = {"MOD03": [entry(f"2022-08-01T{h:02d}:00:00.000Z", WHOLE_EQ) for h in range(5)]}
    calls = []
    with paging_client(entries, calls) as client:
        path, requests = swath_cmr.fetch_chunk(client, "Terra", "eq", (9.9, -0.1, 10.5, 0.5), 2022, tmp_path,
                                               D1, D1, sleep=0, page_size=2)
    assert requests == 3 and len(calls) == 3
    assert [c["search_after"] for c in calls] == [None, "[2, 1]", "[4, 1]"]
    assert all(c["params"]["short_name"] == "MOD03" and c["params"]["version"] == "6.1" for c in calls)
    assert all(c["params"]["sort_key"] == "start_date" for c in calls)
    assert calls[0]["params"]["temporal"] == "2022-08-01T00:00:00Z,2022-08-02T00:00:00Z"
    assert calls[0]["user_agent"] == swath_cmr.HEADERS["User-Agent"]
    record = json.loads(path.read_text())
    assert record["hits"] == 5 and len(record["granules"]) == 5
    assert record["collection_concept_ids"] == ["C1379767668-LAADS"]
    with paging_client(entries, calls) as client:          # cached: no request
        assert swath_cmr.fetch_chunk(client, "Terra", "eq", (9.9, -0.1, 10.5, 0.5), 2022, tmp_path,
                                     D1, D1, sleep=0, page_size=2)[1] == 0
    waits = []
    with paging_client(entries, [], hits_offset=1) as client, pytest.raises(RuntimeError, match="CMR-Hits"):
        swath_cmr.fetch_chunk(client, "Terra", "eq", (9.9, -0.1, 10.5, 0.5), 2022, tmp_path / "bad",
                              D1, D1, sleep=0, page_size=2, retries=2, backoff=waits.append)
    assert waits == [1] and not (tmp_path / "bad").exists()


def test_fetch_retries_transient_errors(tmp_path):
    calls, waits = [], []
    entries = {"MOD03": [entry("2022-08-01T10:00:00.000Z", WHOLE_EQ)]}
    with paging_client(entries, calls, fail_first=2) as client:
        path, requests = swath_cmr.fetch_chunk(client, "Terra", "eq", (9.9, -0.1, 10.5, 0.5), 2022, tmp_path,
                                               D1, D1, sleep=0, backoff=waits.append)
    assert waits == [1, 2] and requests == 3 and len(json.loads(path.read_text())["granules"]) == 1


def test_chunks_split_the_record_by_calendar_year():
    chunks = swath_cmr.year_windows(date(2000, 11, 1), date(2002, 3, 1))
    assert chunks == [(2000, "2000-11-01T00:00:00Z", "2001-01-01T00:00:00Z"),
                      (2001, "2001-01-01T00:00:00Z", "2002-01-01T00:00:00Z"),
                      (2002, "2002-01-01T00:00:00Z", "2002-03-02T00:00:00Z")]


def test_region_cells_cover_every_possible_staged_parent():
    west, south, east, north = REGIONS["eq"]["bounds"]
    cells = set(swath_cmr.region_r4_cells(REGIONS["eq"]["bounds"]))
    for lat in np.linspace(south, north, 9):
        for lon in np.linspace(west, east, 9):
            for r7 in h3.grid_disk(h3.latlng_to_cell(lat, lon, 7), 1):       # footprint spread = 1-ring
                assert int(h3.cell_to_parent(r7, 4), 16) in cells
    bbox = swath_cmr.query_bbox(sorted(cells))
    for cell in cells:
        for lat, lon in cell_points_lonlat(format(cell, "x")):
            assert bbox[0] < lon < bbox[2] and bbox[1] < lat < bbox[3]


def test_ring_contains_centre_or_any_vertex():
    cell = h3.latlng_to_cell(0.2, 10.2, 4)
    points = swath_cmr.cell_points([int(cell, 16)])
    centre_lat, centre_lon = h3.cell_to_latlng(cell)
    vertex_lat, vertex_lon = h3.cell_to_boundary(cell)[1]
    tiny = lambda lat, lon: box(lon - 0.002, lat - 0.002, lon + 0.002, lat + 0.002)
    assert swath_cmr.covered_cells(tiny(centre_lat, centre_lon), points).tolist() == [True]
    assert swath_cmr.covered_cells(tiny(vertex_lat, vertex_lon), points).tolist() == [True]   # vertex only
    away = h3.cell_to_latlng(h3.grid_ring(cell, 2)[0])
    assert swath_cmr.covered_cells(tiny(*away), points).tolist() == [False]
    # Antipodal points never count as inside the gnomonic projection.
    assert swath_cmr.covered_cells(tiny(-centre_lat, centre_lon - 180.0), points).tolist() == [False]


def test_great_circle_edges_not_lat_lon_chords():
    # A long ring edge between (10 N, 0) and (10 N, 60 E) bows poleward (to ~11.5 N at 30 E) on the sphere:
    # 11.2 N is inside the spherical ring although a planar lat/lon test would put it outside.
    ring = [(10.0, 0.0), (10.0, 60.0), (-10.0, 60.0), (-10.0, 0.0)]
    inside = swath_cmr.unit_vectors(np.array([[11.2, 30.0]]))
    outside = swath_cmr.unit_vectors(np.array([[11.8, 30.0]]))
    assert swath_cmr.ring_contains(ring, inside).tolist() == [True]
    assert swath_cmr.ring_contains(ring, outside).tolist() == [False]


def test_granule_days_include_both_dates_of_a_midnight_granule():
    assert swath_cmr.granule_days("2022-08-01T23:55:00.000Z", "2022-08-02T00:00:00.000Z") == [D1, D2]
    assert swath_cmr.granule_days("2022-08-01T10:00:00.000Z", "2022-08-01T10:05:00.000Z") == [D1]


def gap_scenario():
    terra = [entry("2022-08-01T10:00:00.000Z", WHOLE_EQ), entry("2022-08-01T11:00:00.000Z", WHOLE_FAR),
             entry("2022-08-02T10:00:00.000Z", WEST_EQ),
             entry("2022-08-02T10:00:00.000Z", WEST_EQ, concept="C3860159104-LAADS"),   # duplicate listing
             entry("2022-08-02T11:00:00.000Z", WHOLE_FAR),
             entry("2022-08-03T11:00:00.000Z", WHOLE_FAR, day_night="NIGHT")]           # eq not covered
    aqua = [entry("2022-08-03T12:00:00.000Z", WHOLE_FAR, concept="C1379841358-LAADS")]  # Aqua's first granule
    return {"MOD03": terra, "MYD03": aqua}


def rows(path):
    return {(r["satellite"], format(r["h3_r4"], "x"), r["acq_date"]) for r in pq.read_table(path).to_pylist()}


def test_gap_table_declares_only_uncovered_cells_on_acquiring_days(tmp_path):
    out, calls, requests = fetch_and_build(tmp_path, gap_scenario())
    got = rows(out)
    cells = eq_cells()
    west_covered = {c for c in cells if any(lon < EAST_EDGE for _, lon in cell_points_lonlat(c))}
    assert 0 < len(west_covered) < len(cells)
    expected = {("Terra", c, D2) for c in cells if c not in west_covered}
    expected |= {("Terra", c, D3) for c in cells} | {("Aqua", c, D3) for c in cells}
    eq_got = {r for r in got if r[1] in set(cells)}
    assert eq_got == expected
    # Aqua had no granule on D1 and D2 (before its first granule): never a gap.
    assert not any(sat == "Aqua" and day < D3 for sat, _, day in got)
    # Terra covered every eq cell on D1 and the far region every day.
    assert not any(day == D1 for _, _, day in got)
    far = {format(c, "x") for c in swath_cmr.region_r4_cells(REGIONS["far"]["bounds"])}
    assert not any(cell in far for _, cell, _ in got)
    assert requests == len(calls)


def test_outage_days_and_missing_footprints_are_never_swath_gaps(tmp_path):
    entries = gap_scenario()
    entries["MOD03"].append(entry("2022-08-02T15:00:00.000Z", None))          # granule without a footprint
    out, _, _ = fetch_and_build(tmp_path, entries, outages=[
        dict(acq_date=D3, satellite="Aqua", evidence="known_outage")])
    got = rows(out)
    assert not any(day == D2 and sat == "Terra" for sat, _, day in got)        # unknown footprint that day
    assert not any(sat == "Aqua" for sat, _, _ in got)                          # outage day is bit 1, not 4
    assert any(sat == "Terra" and day == D3 for sat, _, day in got)
    meta = json.loads(pq.read_schema(out).metadata[b"modis_swath_gaps"])
    assert meta["excluded_days"]["Terra"]["missing_footprint"] == 1
    assert meta["excluded_days"]["Aqua"]["outage"] == 1


def test_gap_table_schema_order_metadata_and_determinism(tmp_path):
    out, _, _ = fetch_and_build(tmp_path, gap_scenario())
    table = pq.read_table(out)
    assert [(f.name, f.type) for f in table.schema] == [
        ("satellite", pa.string()), ("h3_r4", pa.uint64()), ("acq_date", pa.date32())]
    keys = list(zip(table["satellite"].to_pylist(), table["h3_r4"].to_pylist(), table["acq_date"].to_pylist()))
    assert keys == sorted(keys) and len(keys) == len(set(keys))
    assert pq.ParquetFile(out).metadata.row_group(0).column(0).compression == "ZSTD"
    meta = json.loads(pq.read_schema(out).metadata[b"modis_swath_gaps"])
    assert meta["collections"]["Terra"]["short_name"] == "MOD03" and meta["collections"]["Aqua"]["version"] == "6.1"
    assert meta["collections"]["Terra"]["concept_ids"] == ["C1379767668-LAADS", "C3860159104-LAADS"]
    assert meta["start"] == D1.isoformat() and meta["end"] == D3.isoformat()
    assert "vertex" in meta["coverage_rule"] and "acquir" in meta["acquiring_rule"]
    assert meta["rows"] == table.num_rows and meta["fetch_date_utc"]
    assert meta["outages_sha256"] == hashlib.sha256((tmp_path / "sensor_outages.parquet").read_bytes()).hexdigest()
    assert meta["first_granule_day"] == {"Aqua": D3.isoformat(), "Terra": D1.isoformat()}
    first = out.read_bytes()
    swath_cmr.build_gap_table(REGIONS, tmp_path / "cache", out, tmp_path / "sensor_outages.parquet", D1, D3)
    assert out.read_bytes() == first


def test_build_refuses_an_incomplete_cache(tmp_path):
    with pytest.raises(FileNotFoundError, match="CMR cache"):
        swath_cmr.build_gap_table(REGIONS, tmp_path / "empty", tmp_path / "gaps.parquet",
                                  write_outages(tmp_path / "o.parquet", []), D1, D3)


def test_run_cli_dispatches_the_swath_step(monkeypatch):
    from pipeline import run
    seen = []
    monkeypatch.setattr(swath_cmr, "main", lambda argv: seen.append(argv) or 0)
    assert run.main(["--swath-cmr"]) == 0 and run.main(["--swath-build-only"]) == 0
    assert seen == [[], ["--build-only"]]
    with pytest.raises(SystemExit):
        run.main(["--swath-cmr", "--region", "amazonas_manaus"])
