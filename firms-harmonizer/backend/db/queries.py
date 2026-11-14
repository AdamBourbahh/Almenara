"""Hierarchical H3 filtering and DuckDB aggregation for an AOI.

Filtering: R7 polyfill inside the polygon -> unique R4 parents -> ``h3_r4`` filter (zone-map
pruning) followed by ``h3_r7`` filter. Cell lists are registered Arrow tables and scalar
values are bound parameters: no user value is ever placed in SQL text.
"""

from __future__ import annotations

from typing import NamedTuple

import h3.api.basic_int as h3i
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

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
_SCAN_COLUMNS = ("h3_r7", "epoch_day", "year", "raw_modis_cnt", "raw_viirs_cnt", "raw_frp_mw", "obs_terra_fre",
                 "obs_aqua_fre", "obs_viirs_fre", "neighbor_fre_lag1", "cloud_cover_pct", "gap_status_mask",
                 "sensor_obs_mask", "burned_area_ha_mcd64", "industrial_prob")
_SCAN_ABSENT = {
    "obs_terra_fre": "NULL::DOUBLE AS obs_terra_fre", "obs_aqua_fre": "NULL::DOUBLE AS obs_aqua_fre",
    "obs_viirs_fre": "NULL::DOUBLE AS obs_viirs_fre", "neighbor_fre_lag1": "NULL::DOUBLE AS neighbor_fre_lag1",
    "cloud_cover_pct": "NULL::DOUBLE AS cloud_cover_pct", "burned_area_ha_mcd64": "NULL::DOUBLE AS burned_area_ha_mcd64",
    "gap_status_mask": "NULL::INTEGER AS gap_status_mask", "sensor_obs_mask": "NULL::INTEGER AS sensor_obs_mask",
}
_HEX_SQL = "SELECT printf('%x', h3_r7) AS h3_index FROM hex_cells ORDER BY h3_r7"


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


def _parents_r4(cells_r7: np.ndarray) -> np.ndarray:
    """Vectorized H3 cell_to_parent(c, 4) for R7 cells (bit layout of the H3 index).

    Resolution lives in bits 52-55; each resolution digit r occupies 3 bits at (15 - r) * 3 and unused
    digits are 7 (0b111). Parent at R4 = resolution field set to 4 and digits 5..15 set to 7.
    """
    res_mask = np.uint64(0xF) << np.uint64(52)
    low_digits = np.uint64((1 << (3 * (15 - 4))) - 1)
    return (cells_r7 & ~res_mask) | (np.uint64(4) << np.uint64(52)) | low_digits


def get_hierarchical_h3_filter(geojson_coords: list) -> tuple[list[int], list[int], float]:
    """Return (sorted unique R4 parents, sorted R7 cells inside the polygon, R7 area in km²)."""
    outer, *holes = (_to_latlng_ring(r) for r in geojson_coords)
    poly = h3i.LatLngPoly(outer, *holes)
    r7_int = h3i.polygon_to_cells(poly, 7)
    if len(r7_int) > MAX_R7_CELLS:
        raise ValueError(f"AOI too large: {len(r7_int)} R7 cells exceed the limit of {MAX_R7_CELLS}.")
    if not r7_int:
        return [], [], 0.0
    r7_arr = np.sort(np.asarray(r7_int, dtype=np.uint64))
    r4_arr = np.unique(_parents_r4(r7_arr))
    area = float(sum(h3i.cell_area(c, unit="km^2") for c in r7_int))
    return [int(c) for c in r4_arr.tolist()], [int(c) for c in r7_arr.tolist()], area


# ---------------------------------------------------------------- SQL

def _register_cells(cur, cells_r4: list[int], cells_r7: list[int]) -> None:
    cur.register("aoi_r4", pa.table({"h3_r4": pa.array(np.asarray(cells_r4, dtype=np.uint64))}))
    cur.register("aoi_r7", pa.table({"h3_r7": pa.array(np.asarray(cells_r7, dtype=np.uint64))}))


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


def _scan_sql(missing: set[str]) -> str:
    parts = []
    for name in _SCAN_COLUMNS:
        if name in missing:
            parts.append(_SCAN_ABSENT[name])
        else:
            parts.append(name)
    return "SELECT " + ", ".join(parts) + _SPATIAL_FILTER


def query_aoi_rows(cur, cells_r4: list[int], cells_r7: list[int], start_year: int, end_year: int) -> pa.Table:
    """Single scan: every cube row of the AOI and year range (no grouping), as Arrow."""
    missing = set(duckdb_engine.missing_columns())
    _register_cells(cur, cells_r4, cells_r7)
    try:
        return cur.sql(_scan_sql(missing), params=[int(start_year), int(end_year)]).to_arrow_table()
    finally:
        _unregister_cells(cur)


def _hex_strings(cur, cells: np.ndarray) -> list[str]:
    """15-character hex H3 indices, projected in SQL with printf('%x', h3_r7) (shield 1)."""
    cur.register("hex_cells", pa.table({"h3_r7": pa.array(cells, type=pa.uint64())}))
    try:
        return [row[0] for row in cur.sql(_HEX_SQL).fetchall()]
    finally:
        cur.unregister("hex_cells")


# ---------------------------------------------------------------- aggregation

def _empty_daily() -> dict[str, np.ndarray]:
    ints = {"epoch_day", "year", "doy", "raw_modis_cnt", "raw_viirs_cnt", "gap_status_mask", "sensor_obs_mask"}
    return {k: np.empty(0, dtype=np.int64 if k in ints else np.float64) for k in DAILY_KEYS}


def _float_col(table: pa.Table, name: str) -> np.ndarray:
    return pc.fill_null(table.column(name).cast(pa.float64()), np.nan).to_numpy()


def _int_col(table: pa.Table, name: str) -> np.ndarray:
    return table.column(name).to_numpy().astype(np.int64)


def _finite_mean(idx: np.ndarray, values: np.ndarray, n: int) -> np.ndarray:
    ok = np.isfinite(values)
    total = np.bincount(idx[ok], weights=values[ok], minlength=n)
    count = np.bincount(idx[ok], minlength=n)
    return np.where(count > 0, total / np.maximum(count, 1), np.nan)


def _finite_sum(idx: np.ndarray, values: np.ndarray, n: int) -> np.ndarray:
    ok = np.isfinite(values)
    total = np.bincount(idx[ok], weights=values[ok], minlength=n)
    count = np.bincount(idx[ok], minlength=n)
    return np.where(count > 0, total, np.nan)


def _bit_or(idx: np.ndarray, values: np.ndarray, n: int) -> np.ndarray:
    out = np.zeros(n, dtype=np.int64)
    present = int(np.bitwise_or.reduce(values)) if len(values) else 0
    for flag in (1 << b for b in range(8) if present & (1 << b)):
        hits = np.bincount(idx, weights=(values & flag) != 0, minlength=n)
        out |= np.where(hits > 0, flag, 0)
    return out


def _aggregate_daily(cols: dict[str, np.ndarray], keep: np.ndarray, start_year: int, end_year: int,
                     missing: set[str]) -> dict[str, np.ndarray]:
    """Dense daily AOI series from the kept rows (same semantics as the GROUP BY in query_daily_rows)."""
    lo = int((np.datetime64(f"{start_year}-01-01") - EPOCH).astype(int))
    hi = int((np.datetime64(f"{end_year}-12-31") - EPOCH).astype(int))
    epoch_day = np.arange(lo, hi + 1, dtype=np.int64)
    dates = EPOCH + epoch_day.astype("timedelta64[D]")
    n = len(epoch_day)
    idx = cols["epoch_day"][keep] - lo
    out: dict[str, np.ndarray] = {
        "epoch_day": epoch_day,
        "year": dates.astype("datetime64[Y]").astype(np.int64) + 1970,
        "doy": (dates - dates.astype("datetime64[Y]")).astype(np.int64) + 1,
    }
    for name in ("raw_modis_cnt", "raw_viirs_cnt"):
        out[name] = np.rint(np.bincount(idx, weights=cols[name][keep], minlength=n)).astype(np.int64)
    out["raw_frp_mw"] = np.bincount(idx, weights=np.where(np.isfinite(cols["raw_frp_mw"][keep]),
                                                          cols["raw_frp_mw"][keep], 0.0), minlength=n)
    for name in OBS_COLUMNS + ("neighbor_fre_lag1", "cloud_cover_pct"):
        out[name] = np.full(n, np.nan) if name in missing else _finite_mean(idx, cols[name][keep], n)
    burned = "burned_area_ha_mcd64"
    out[burned] = np.full(n, np.nan) if burned in missing else _finite_sum(idx, cols[burned][keep], n)
    for name in MASK_COLUMNS:
        out[name] = np.full(n, -1, dtype=np.int64) if name in missing else _bit_or(idx, cols[name][keep], n)
    return {k: out[k] for k in DAILY_KEYS}


def _theil_sen_rows(values: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Row-wise Theil-Sen slope (median of pairwise slopes), equal to scipy.stats.theilslopes."""
    if values.shape[1] < 2:
        return np.zeros(values.shape[0])
    i, j = np.triu_indices(values.shape[1], 1)
    slopes = np.median((values[:, j] - values[:, i]) / (x[j] - x[i]), axis=1)
    return np.where(np.ptp(values, axis=1) > 0, slopes, 0.0)


def _summarize_hexagons(cur, cols: dict[str, np.ndarray], cells_r7: np.ndarray, start_year: int, end_year: int
                        ) -> tuple[list[H3MapSummaryHex], int, np.ndarray]:
    """Per-cell map summaries over all rows (industrial included), industrial total, per-cell min prob."""
    cell_idx = np.searchsorted(cells_r7, cols["h3_r7"])
    n_cells = len(cells_r7)
    rows_per_cell = np.bincount(cell_idx, minlength=n_cells)
    present = np.flatnonzero(rows_per_cell)
    if len(present) == 0:
        return [], 0, np.empty(0)
    obs = np.column_stack([cols[c] for c in OBS_COLUMNS])
    count = np.isfinite(obs).sum(axis=1)
    density = np.where(count > 0, np.nansum(obs, axis=1) / np.maximum(count, 1), 0.0)
    n_years = end_year - start_year + 1
    year_idx = cols["year"] - start_year
    month_idx = (EPOCH + cols["epoch_day"].astype("timedelta64[D]")).astype("datetime64[M]").astype(np.int64) % 12
    annual = np.bincount(cell_idx * n_years + year_idx, weights=density,
                         minlength=n_cells * n_years).reshape(n_cells, n_years)[present]
    monthly = np.bincount(cell_idx * 12 + month_idx, weights=density,
                          minlength=n_cells * 12).reshape(n_cells, 12)[present]
    raw = cols["raw_modis_cnt"] + cols["raw_viirs_cnt"]
    raw_count = np.bincount(cell_idx, weights=raw, minlength=n_cells)[present]
    prob = cols["industrial_prob"]
    max_prob = np.full(n_cells, -np.inf)
    min_prob = np.full(n_cells, np.inf)
    np.maximum.at(max_prob, cell_idx, prob)
    np.minimum.at(min_prob, cell_idx, prob)
    industrial_total = int(raw[prob >= INDUSTRIAL_THRESHOLD].sum())
    totals = monthly.sum(axis=1)
    p = monthly / np.where(totals > 0, totals, 1.0)[:, None]
    entropy = np.where(totals > 0, np.clip(-np.sum(p * np.log(p + 1e-12), axis=1) / np.log(12), 0.0, 1.0), 0.0)
    slopes = _theil_sen_rows(annual, np.arange(start_year, end_year + 1, dtype=np.float64))
    hex_ids = _hex_strings(cur, cells_r7[present])
    hexagons = [H3MapSummaryHex(h3_index=h, mean_annual_fre=float(a), raw_pixel_count=int(round(rc)),
                                trend_slope=float(s), is_industrial_site=bool(mx >= INDUSTRIAL_THRESHOLD),
                                shannon_entropy=float(e))
                for h, a, rc, s, mx, e in zip(hex_ids, annual.mean(axis=1).tolist(), raw_count.tolist(),
                                              slopes.tolist(), max_prob[present].tolist(), entropy.tolist())]
    return hexagons, industrial_total, min_prob[present]


def fetch_aoi_aggregated_data(cells_r4: list[int], cells_r7: list[int], start_year: int, end_year: int,
                              exclude_industrial: bool) -> AoiAggregate:
    """Dense daily arrays, map hexagons and industrial removal count for an AOI (one cube scan)."""
    if not cells_r4 or not cells_r7:
        return AoiAggregate(_empty_daily(), [], 0, 0)
    missing = set(duckdb_engine.missing_columns())
    r7_sorted = np.asarray(sorted(cells_r7), dtype=np.uint64)
    with duckdb_engine.get_db_cursor() as cur:
        table = query_aoi_rows(cur, cells_r4, cells_r7, start_year, end_year)
        if table.num_rows == 0:
            return AoiAggregate(_empty_daily(), [], 0, 0)
        cols = {"h3_r7": table.column("h3_r7").to_numpy()}
        for name in ("epoch_day", "year", "raw_modis_cnt", "raw_viirs_cnt") + MASK_COLUMNS:
            cols[name] = np.zeros(table.num_rows, dtype=np.int64) if name in missing else _int_col(table, name)
        for name in ("raw_frp_mw", "industrial_prob") + OBS_COLUMNS + (
                "neighbor_fre_lag1", "cloud_cover_pct", "burned_area_ha_mcd64"):
            cols[name] = _float_col(table, name)
        hexagons, industrial_total, min_probs = _summarize_hexagons(cur, cols, r7_sorted, start_year, end_year)
    keep = cols["industrial_prob"] < INDUSTRIAL_THRESHOLD if exclude_industrial else np.ones(table.num_rows, bool)
    daily = _aggregate_daily(cols, keep, start_year, end_year, missing) if keep.any() else _empty_daily()
    if exclude_industrial:
        removed = industrial_total
        used = [h.h3_index for h, p in zip(hexagons, min_probs.tolist()) if p < INDUSTRIAL_THRESHOLD]
    else:
        removed = 0
        used = [h.h3_index for h in hexagons]
    return AoiAggregate(daily, hexagons, removed, len(used), used)
