"""Hierarchical H3 filtering and DuckDB aggregation for an AOI.

Filtering: R7 polyfill inside the polygon -> unique R4 parents -> ``h3_r4`` filter (zone-map
pruning) followed by ``h3_r7`` filter. Cell lists are registered Arrow tables and scalar
values are bound parameters: no user value is ever placed in SQL text.
"""

from __future__ import annotations

from typing import NamedTuple

import h3
import numpy as np
import pyarrow as pa
from scipy.stats import theilslopes

from backend.api.schemas import H3MapSummaryHex
from backend.db import duckdb_engine

MAX_R7_CELLS = 250_000
INDUSTRIAL_THRESHOLD = 0.75
EPOCH = np.datetime64("2000-01-01", "D")
OBS_COLUMNS = ("obs_terra_fre", "obs_aqua_fre", "obs_viirs_fre")
MASK_COLUMNS = ("gap_status_mask", "sensor_obs_mask")
DAILY_KEYS = ("epoch_day", "year", "doy", "raw_modis_cnt", "raw_viirs_cnt", "raw_frp_mw", "obs_terra_fre",
              "obs_aqua_fre", "obs_viirs_fre", "neighbor_fre_lag1", "cloud_cover_pct", "gap_status_mask",
              "sensor_obs_mask", "burned_area_ha_mcd64")

# (expression when the column exists, expression when it is missing) — constant SQL fragments only.
_DAILY_EXPRESSIONS = {
    "raw_modis_cnt": ("SUM(raw_modis_cnt::BIGINT) AS raw_modis_cnt", None),
    "raw_viirs_cnt": ("SUM(raw_viirs_cnt::BIGINT) AS raw_viirs_cnt", None),
    "raw_frp_mw": ("SUM(raw_frp_mw::DOUBLE) AS raw_frp_mw", None),
    "obs_terra_fre": ("AVG(obs_terra_fre)::DOUBLE AS obs_terra_fre", "NULL::DOUBLE AS obs_terra_fre"),
    "obs_aqua_fre": ("AVG(obs_aqua_fre)::DOUBLE AS obs_aqua_fre", "NULL::DOUBLE AS obs_aqua_fre"),
    "obs_viirs_fre": ("AVG(obs_viirs_fre)::DOUBLE AS obs_viirs_fre", "NULL::DOUBLE AS obs_viirs_fre"),
    "neighbor_fre_lag1": ("AVG(neighbor_fre_lag1)::DOUBLE AS neighbor_fre_lag1",
                          "NULL::DOUBLE AS neighbor_fre_lag1"),
    "cloud_cover_pct": ("AVG(cloud_cover_pct)::DOUBLE AS cloud_cover_pct", "NULL::DOUBLE AS cloud_cover_pct"),
    "gap_status_mask": ("BIT_OR(gap_status_mask)::INTEGER AS gap_status_mask",
                        "NULL::INTEGER AS gap_status_mask"),
    "sensor_obs_mask": ("BIT_OR(sensor_obs_mask)::INTEGER AS sensor_obs_mask",
                        "NULL::INTEGER AS sensor_obs_mask"),
    "burned_area_ha_mcd64": ("SUM(burned_area_ha_mcd64::DOUBLE) AS burned_area_ha_mcd64",
                             "NULL::DOUBLE AS burned_area_ha_mcd64"),
}
_SPATIAL_FILTER = (" FROM fire_cube"
                   " WHERE h3_r4 IN (SELECT h3_r4 FROM aoi_r4)"
                   " AND h3_r7 IN (SELECT h3_r7 FROM aoi_r7)"
                   " AND year BETWEEN ? AND ?")
_INDUSTRIAL_FILTER = " AND industrial_prob < ?"
_OBS_VALUE = {c: "COALESCE(" + c + ", 0)::DOUBLE" for c in OBS_COLUMNS}
_OBS_PRESENT = {c: "(" + c + " IS NOT NULL)::INT" for c in OBS_COLUMNS}


class AoiAggregate(NamedTuple):
    daily: dict[str, np.ndarray]
    hexagons: list[H3MapSummaryHex]
    industrial_false_positives_removed: int
    n_cells_used: int
    used_cells: list[str] = []


# ---------------------------------------------------------------- geometry

def _orientation(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a, b, c) -> bool:
    return min(a[0], b[0]) <= c[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= c[1] <= max(a[1], b[1])


def _segments_intersect(p1, p2, q1, q2) -> bool:
    d1, d2 = _orientation(q1, q2, p1), _orientation(q1, q2, p2)
    d3, d4 = _orientation(p1, p2, q1), _orientation(p1, p2, q2)
    if ((d1 > 0) != (d2 > 0)) and d1 != 0 and d2 != 0 and ((d3 > 0) != (d4 > 0)) and d3 != 0 and d4 != 0:
        return True
    return ((d1 == 0 and _on_segment(q1, q2, p1)) or (d2 == 0 and _on_segment(q1, q2, p2))
            or (d3 == 0 and _on_segment(p1, p2, q1)) or (d4 == 0 and _on_segment(p1, p2, q2)))


def validate_polygon_topology(coords: list) -> None:
    """Raise ValueError for rings with zero area or self-intersecting edges."""
    for ring in coords:
        points = [(float(p[0]), float(p[1])) for p in ring]
        area2 = sum(points[i][0] * points[i + 1][1] - points[i + 1][0] * points[i][1]
                    for i in range(len(points) - 1))
        if abs(area2) < 1e-12:
            raise ValueError("Polygon ring has zero area.")
        n_seg = len(points) - 1
        for i in range(n_seg):
            for j in range(i + 1, n_seg):
                adjacent = j == i + 1 or (i == 0 and j == n_seg - 1)
                if not adjacent and _segments_intersect(points[i], points[i + 1], points[j], points[j + 1]):
                    raise ValueError("Polygon ring is self-intersecting.")


def _to_latlng_ring(ring: list) -> list[tuple[float, float]]:
    """GeoJSON positions are [lon, lat]; H3 expects (lat, lng). Drop the closing duplicate."""
    positions = ring[:-1] if len(ring) > 1 and list(ring[0]) == list(ring[-1]) else ring
    return [(float(lat), float(lng)) for lng, lat in positions]


def get_hierarchical_h3_filter(geojson_coords: list) -> tuple[list[int], list[int], float]:
    """Return (sorted unique R4 parents, sorted R7 cells inside the polygon, R7 area in km²)."""
    outer, *holes = (_to_latlng_ring(r) for r in geojson_coords)
    poly = h3.LatLngPoly(outer, *holes)
    r7_str = h3.polygon_to_cells(poly, 7)
    if len(r7_str) > MAX_R7_CELLS:
        raise ValueError(f"AOI too large: {len(r7_str)} R7 cells exceed the limit of {MAX_R7_CELLS}.")
    if not r7_str:
        return [], [], 0.0
    r7 = sorted(h3.str_to_int(c) for c in r7_str)
    r4 = sorted({h3.str_to_int(h3.cell_to_parent(c, 4)) for c in r7_str})
    area = float(sum(h3.cell_area(c, unit="km^2") for c in r7_str))
    return r4, r7, area


# ---------------------------------------------------------------- SQL

def _register_cells(cur, cells_r4: list[int], cells_r7: list[int]) -> None:
    cur.register("aoi_r4", pa.table({"h3_r4": pa.array(cells_r4, type=pa.uint64())}))
    cur.register("aoi_r7", pa.table({"h3_r7": pa.array(cells_r7, type=pa.uint64())}))


def _unregister_cells(cur) -> None:
    cur.unregister("aoi_r4")
    cur.unregister("aoi_r7")


def _daily_sql(missing: set[str], exclude_industrial: bool) -> str:
    parts = ["epoch_day"]
    for name, (present, absent) in _DAILY_EXPRESSIONS.items():
        if name in missing:
            if absent is None:
                raise duckdb_engine.CubeNotAvailableError("Required column missing: " + name)
            parts.append(absent)
        else:
            parts.append(present)
    sql = "SELECT " + ", ".join(parts) + _SPATIAL_FILTER
    if exclude_industrial:
        sql += _INDUSTRIAL_FILTER
    return sql + " GROUP BY epoch_day ORDER BY epoch_day"


def _hex_sql(missing: set[str]) -> str:
    obs = [c for c in OBS_COLUMNS if c not in missing]
    if obs:
        energy = ("COALESCE((" + " + ".join(_OBS_VALUE[c] for c in obs) + ") / NULLIF("
                  + " + ".join(_OBS_PRESENT[c] for c in obs) + ", 0), 0)")
    else:
        energy = "NULL::DOUBLE"
    return ("SELECT h3_r7, printf('%x', h3_r7) AS h3_index, year,"
            " month(DATE '2000-01-01' + CAST(epoch_day AS INTEGER)) AS month,"
            " SUM(raw_modis_cnt::BIGINT + raw_viirs_cnt::BIGINT) AS raw_cnt,"
            " SUM(" + energy + ")::DOUBLE AS energy,"
            " MAX(industrial_prob)::DOUBLE AS max_prob, MIN(industrial_prob)::DOUBLE AS min_prob,"
            " SUM(CASE WHEN industrial_prob >= ? THEN raw_modis_cnt::BIGINT + raw_viirs_cnt::BIGINT"
            " ELSE 0 END) AS industrial_cnt"
            + _SPATIAL_FILTER
            + " GROUP BY h3_r7, year, month ORDER BY h3_r7, year, month")


def query_daily_rows(cur, cells_r4: list[int], cells_r7: list[int], start_year: int, end_year: int,
                     exclude_industrial: bool) -> pa.Table:
    """Daily AOI aggregation as an Arrow table (one row per epoch_day with data)."""
    missing = set(duckdb_engine.missing_columns())
    params: list = [int(start_year), int(end_year)]
    if exclude_industrial:
        params.append(INDUSTRIAL_THRESHOLD)
    _register_cells(cur, cells_r4, cells_r7)
    try:
        return cur.sql(_daily_sql(missing, exclude_industrial), params=params).to_arrow_table()
    finally:
        _unregister_cells(cur)


def _query_hex_rows(cur, cells_r4, cells_r7, start_year, end_year) -> pa.Table:
    missing = set(duckdb_engine.missing_columns())
    _register_cells(cur, cells_r4, cells_r7)
    try:
        return cur.sql(_hex_sql(missing), params=[INDUSTRIAL_THRESHOLD, int(start_year), int(end_year)]
                           ).to_arrow_table()
    finally:
        _unregister_cells(cur)


# ---------------------------------------------------------------- aggregation

def _empty_daily() -> dict[str, np.ndarray]:
    ints = {"epoch_day", "year", "doy", "raw_modis_cnt", "raw_viirs_cnt", "gap_status_mask", "sensor_obs_mask"}
    return {k: np.empty(0, dtype=np.int64 if k in ints else np.float64) for k in DAILY_KEYS}


def _dense_daily(table: pa.Table, start_year: int, end_year: int, missing: set[str]) -> dict[str, np.ndarray]:
    lo = int((np.datetime64(f"{start_year}-01-01") - EPOCH).astype(int))
    hi = int((np.datetime64(f"{end_year}-12-31") - EPOCH).astype(int))
    epoch_day = np.arange(lo, hi + 1, dtype=np.int64)
    dates = EPOCH + epoch_day.astype("timedelta64[D]")
    year = dates.astype("datetime64[Y]").astype(np.int64) + 1970
    doy = (dates - dates.astype("datetime64[Y]")).astype(np.int64) + 1
    idx = table.column("epoch_day").to_numpy().astype(np.int64) - lo
    n = len(epoch_day)
    out: dict[str, np.ndarray] = {"epoch_day": epoch_day, "year": year, "doy": doy}
    for name in ("raw_modis_cnt", "raw_viirs_cnt"):
        arr = np.zeros(n, dtype=np.int64)
        arr[idx] = table.column(name).to_numpy().astype(np.int64)
        out[name] = arr
    arr = np.zeros(n, dtype=np.float64)
    arr[idx] = table.column("raw_frp_mw").to_numpy(zero_copy_only=False).astype(np.float64)
    out["raw_frp_mw"] = arr
    for name in OBS_COLUMNS + ("neighbor_fre_lag1", "cloud_cover_pct", "burned_area_ha_mcd64"):
        arr = np.full(n, np.nan, dtype=np.float64)
        if name not in missing:
            arr[idx] = table.column(name).to_numpy(zero_copy_only=False).astype(np.float64)
        out[name] = arr
    for name in MASK_COLUMNS:
        if name in missing:
            out[name] = np.full(n, -1, dtype=np.int64)
        else:
            arr = np.zeros(n, dtype=np.int64)
            arr[idx] = table.column(name).to_numpy().astype(np.int64)
            out[name] = arr
    return {k: out[k] for k in DAILY_KEYS}


def _summarize_hexagons(table: pa.Table, start_year: int, end_year: int
                        ) -> tuple[list[H3MapSummaryHex], int, list[float]]:
    """Per-cell map summaries, industrial detection total and per-cell min industrial_prob."""
    if table.num_rows == 0:
        return [], 0, []
    cols = {name: table.column(name).to_numpy(zero_copy_only=False) for name in
            ("h3_r7", "year", "month", "raw_cnt", "energy", "max_prob", "min_prob", "industrial_cnt")}
    h3_index = table.column("h3_index").to_pylist()
    years = np.arange(start_year, end_year + 1)
    energy_raw = cols["energy"].astype(np.float64)
    energy_all = np.where(np.isfinite(energy_raw), energy_raw, 0.0)  # NULL only if no obs columns exist
    hexagons, min_probs, industrial_total = [], [], 0
    for cell in np.unique(cols["h3_r7"]):
        sel = cols["h3_r7"] == cell
        energy = energy_all[sel]
        annual = np.zeros(len(years))
        np.add.at(annual, cols["year"][sel].astype(np.int64) - start_year, energy)
        monthly = np.zeros(12)
        np.add.at(monthly, cols["month"][sel].astype(np.int64) - 1, energy)
        total = monthly.sum()
        if total > 0:
            p = monthly / total
            entropy = float(np.clip(-np.sum(p * np.log(p + 1e-12)) / np.log(12), 0.0, 1.0))
        else:
            entropy = 0.0
        if len(years) >= 2 and np.ptp(annual) > 0:
            slope = float(theilslopes(annual, years).slope)
        else:
            slope = 0.0
        first = int(np.argmax(sel))
        hexagons.append(H3MapSummaryHex(
            h3_index=h3_index[first],
            mean_annual_fre=float(annual.mean()),
            raw_pixel_count=int(cols["raw_cnt"][sel].astype(np.int64).sum()),
            trend_slope=slope,
            is_industrial_site=bool(cols["max_prob"][sel].max() >= INDUSTRIAL_THRESHOLD),
            shannon_entropy=entropy,
        ))
        min_probs.append(float(cols["min_prob"][sel].min()))
        industrial_total += int(cols["industrial_cnt"][sel].astype(np.int64).sum())
    order = np.argsort([h.h3_index for h in hexagons])
    return [hexagons[i] for i in order], industrial_total, [min_probs[i] for i in order]


def fetch_aoi_aggregated_data(cells_r4: list[int], cells_r7: list[int], start_year: int, end_year: int,
                              exclude_industrial: bool) -> AoiAggregate:
    """Dense daily arrays, map hexagons and industrial removal count for an AOI."""
    if not cells_r4 or not cells_r7:
        return AoiAggregate(_empty_daily(), [], 0, 0)
    missing = set(duckdb_engine.missing_columns())
    with duckdb_engine.get_db_cursor() as cur:
        daily_tbl = query_daily_rows(cur, cells_r4, cells_r7, start_year, end_year, exclude_industrial)
        hex_tbl = _query_hex_rows(cur, cells_r4, cells_r7, start_year, end_year)
    hexagons, industrial_total, min_probs = _summarize_hexagons(hex_tbl, start_year, end_year)
    daily = _empty_daily() if daily_tbl.num_rows == 0 else _dense_daily(daily_tbl, start_year, end_year, missing)
    if exclude_industrial:
        removed = industrial_total
        used = [h.h3_index for h, p in zip(hexagons, min_probs) if p < INDUSTRIAL_THRESHOLD]
    else:
        removed = 0
        used = [h.h3_index for h in hexagons]
    return AoiAggregate(daily, hexagons, removed, len(used), used)

