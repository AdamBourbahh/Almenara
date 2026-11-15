"""Hierarchical H3 filtering and DuckDB aggregation for an AOI.

Filtering: R7 polyfill inside the polygon -> unique R4 parents -> ``h3_r4`` filter (zone-map
pruning) followed by ``h3_r7`` filter. Cell lists are registered Arrow tables and scalar
values are bound parameters: no user value is ever placed in SQL text.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import NamedTuple

import h3.api.basic_int as h3i
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from pyproj import Geod
from shapely.geometry import Polygon

from backend.api.schemas import H3MapSummaryHex
from backend.db import duckdb_engine

MAX_R7_CELLS = 250_000
MAX_POLYGON_VERTICES = 512
INDUSTRIAL_THRESHOLD = 0.75
EPOCH = np.datetime64("1970-01-01", "D")  # epoch_day = days since 1970-01-01 (SPECS.md §5.1)
OBS_COLUMNS = ("obs_terra_fre", "obs_aqua_fre", "obs_viirs_fre")
MASK_COLUMNS = ("gap_status_mask", "sensor_obs_mask")
DAILY_KEYS = ("epoch_day", "year", "doy", "raw_modis_cnt", "raw_viirs_cnt", "raw_frp_mw", "obs_terra_fre",
              "obs_aqua_fre", "obs_viirs_fre", "neighbor_fre_lag1", "cloud_cover_pct", "gap_status_mask",
              "sensor_obs_mask", "burned_area_ha_mcd64", "observed_energy_mj", "observation_known", "observed_zero", "pm25_emitted_kg", "coverage_complete", "pm25_factor_sd_kg")

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
    # km² of the kept cube cells present on each day of ``daily`` (aligned with daily["epoch_day"]).
    # Daily AOI energy in MJ is the cell-mean density times this area, never times the area of every
    # cell that burned at some point of the record.
    daily_area_km2: np.ndarray | None = None


# ---------------------------------------------------------------- geometry

def polygon_area_km2(coords: list) -> float:
    """WGS84 geodesic exterior area minus hole areas, independent of winding."""
    geod = Geod(ellps="WGS84")
    areas = [abs(geod.polygon_area_perimeter(*zip(*ring))[0]) / 1e6 for ring in coords]
    return max(0.0, areas[0] - sum(areas[1:]))


def validate_polygon_topology(coords: list) -> None:
    """Raise ValueError for rings with zero area or self-intersecting edges."""
    if len(coords) > 16 or sum(map(len, coords)) > 512:
        raise ValueError("A polygon supports at most 16 rings and 512 positions.")
    polygon = Polygon(coords[0], coords[1:])
    if not polygon.is_valid or polygon.is_empty or polygon.area <= 0:
        raise ValueError("Polygon rings must form a valid non-empty polygon.")
    if any(abs(a[0] - b[0]) > 180 for ring in coords for a, b in zip(ring, ring[1:])):
        raise ValueError("Split antimeridian-crossing polygons before analysis.")
    if polygon_area_km2(coords) > 1_250_000:
        raise ValueError("AOI too large: exceeds the 1,250,000 km² preflight area limit.")

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
    validate_polygon_topology(geojson_coords)
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


def query_aoi_rows(cur, cells_r4: list[int], cells_r7: list[int], start_year: int, end_year: int,
                   epoch_range: tuple[int, int] | None = None, confidence_level: str = 'nominal') -> pa.Table:
    """Single scan: every cube row of the AOI and year range (no grouping), as Arrow."""
    missing = set(duckdb_engine.missing_columns())
    _register_cells(cur, cells_r4, cells_r7)
    try:
        sql = _scan_sql(missing)
        params = [int(start_year), int(end_year)]
        if confidence_level != 'nominal' and duckdb_engine.data_source() == 'real':
            if confidence_level not in ('low', 'high'):
                raise ValueError('Unsupported confidence threshold.')
            path = duckdb_engine.cube_path().with_name('fire_cube_' + confidence_level + '.parquet')
            if not path.is_file():
                raise ValueError('Confidence cube unavailable. Run scripts/run_pipeline.py etl.')
            sql = sql.replace(' FROM fire_cube', ' FROM read_parquet(?)')
            params.insert(0, str(path))
        if epoch_range is not None:
            sql += " AND epoch_day BETWEEN ? AND ?"
            params.extend(epoch_range)
        from datetime import datetime, timezone
        sql += ' AND epoch_day <= ?'
        params.append(int((np.datetime64(datetime.now(timezone.utc).date()) - EPOCH).astype(int)))
        return cur.sql(sql, params=params).to_arrow_table()
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
                     missing: set[str], area_km2: float | None = None) -> dict[str, np.ndarray]:
    """Dense daily AOI series from the kept rows (same semantics as the GROUP BY in query_daily_rows)."""
    lo = int((np.datetime64(f"{start_year}-01-01") - EPOCH).astype(int))
    hi = int((np.datetime64(f"{end_year}-12-31") - EPOCH).astype(int))
    # Clip to the archive's actual publication window; never manufacture future history.
    from datetime import datetime, timezone
    today = int((np.datetime64(datetime.now(timezone.utc).date()) - EPOCH).astype(int))
    with duckdb_engine.get_db_cursor() as cur:
        first, last = cur.execute('SELECT min(epoch_day), max(epoch_day) FROM fire_cube').fetchone()
    lo, hi = max(lo, first), min(hi, last, today)
    epoch_day = np.arange(lo, max(lo, hi + 1), dtype=np.int64)
    dates = EPOCH + epoch_day.astype("timedelta64[D]")
    n = len(epoch_day)
    keep = keep & (cols['epoch_day'] >= lo) & (cols['epoch_day'] <= hi)
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
    cells = cols['h3_r7'][keep]
    unique, inverse = np.unique(cells, return_inverse=True)
    areas = np.array([h3i.cell_area(int(c), unit='km^2') for c in unique])[inverse]
    denominator = area_km2 or sum(h3i.cell_area(int(c), unit='km^2') for c in unique)
    denominator = max(denominator, 1e-12)
    observations = np.column_stack([cols[c][keep] for c in OBS_COLUMNS])
    valid = np.isfinite(observations)
    fused = np.nansum(observations, axis=1) / np.maximum(valid.sum(axis=1), 1)
    out['observed_energy_mj'] = np.bincount(idx, weights=fused * areas, minlength=n)
    out['observation_known'] = np.bincount(idx, weights=valid.any(axis=1), minlength=n) > 0
    out['observed_zero'] = np.zeros(n, dtype=bool)
    out['coverage_complete'] = (out['observation_known'].copy() if duckdb_engine.data_source() == 'synthetic'
                                else np.zeros(n, dtype=bool))
    from backend.db.emission_inputs import estimate
    if duckdb_engine.data_source() == 'real':
        out['pm25_emitted_kg'], out['pm25_factor_sd_kg'] = estimate(duckdb_engine.ROOT, cells, cols['year'][keep], fused * areas, idx, n)
    else:
        out['pm25_emitted_kg'], out['pm25_factor_sd_kg'] = np.full(n, np.nan), np.full(n, np.nan)
    for name in OBS_COLUMNS + ('neighbor_fre_lag1',):
        values = cols[name][keep]
        present = np.isfinite(values)
        total = np.bincount(idx, weights=np.where(present, values * areas, 0), minlength=n)
        counts = np.bincount(idx, weights=present, minlength=n)
        out[name] = np.where(counts > 0, total / denominator, np.nan)
    for name in ("cloud_cover_pct",):
        out[name] = np.full(n, np.nan) if name in missing else _finite_mean(idx, cols[name][keep], n)
    burned = "burned_area_ha_mcd64"
    out[burned] = np.full(n, np.nan) if burned in missing else _finite_sum(idx, cols[burned][keep], n)
    for name in MASK_COLUMNS:
        out[name] = np.full(n, -1, dtype=np.int64) if name in missing else _bit_or(idx, cols[name][keep], n)
    return {k: out[k] for k in DAILY_KEYS}


@lru_cache(maxsize=1 << 19)
def _cell_area_km2(cell: int) -> float:
    """Exact km² of one H3 cell; cached because the same cube cells recur across requests."""
    return h3i.cell_area(cell, unit="km^2")


def _row_cell_areas(cells: np.ndarray) -> np.ndarray:
    """Exact km² area of the H3 cell of every row (one lookup per distinct cell)."""
    unique, inverse = np.unique(cells, return_inverse=True)
    areas = np.fromiter((_cell_area_km2(c) for c in unique.tolist()), dtype=np.float64, count=len(unique))
    return areas[inverse]


def _daily_area(cols: dict[str, np.ndarray], keep: np.ndarray, row_area: np.ndarray,
                start_year: int, end_year: int) -> np.ndarray:
    """Per-day km² of the kept cube cells, on the same dense calendar as _aggregate_daily."""
    lo = int((np.datetime64(f"{start_year}-01-01") - EPOCH).astype(int))
    hi = int((np.datetime64(f"{end_year}-12-31") - EPOCH).astype(int))
    return np.bincount(cols["epoch_day"][keep] - lo, weights=row_area[keep], minlength=hi - lo + 1)


# Small blocks keep the pairwise-slope temporary cache-resident (64 × 325 doubles for 26 years);
# measured ~2x faster than one full-size median and without a multi-hundred-MB allocation.
THEIL_SEN_CHUNK_ROWS = 64


def _theil_sen_rows(values: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Row-wise Theil-Sen slope (median of pairwise slopes), equal to scipy.stats.theilslopes.

    Constant rows have slope 0 and are skipped; the rest are processed in fixed-size chunks so a
    large AOI never materializes every pairwise slope at once.
    """
    out = np.zeros(values.shape[0])
    if values.shape[1] < 2:
        return out
    i, j = np.triu_indices(values.shape[1], 1)
    dx = x[j] - x[i]
    rows = np.flatnonzero(np.ptp(values, axis=1) > 0)
    varying = values[rows]
    slopes = np.empty(len(rows))
    for start in range(0, len(rows), THEIL_SEN_CHUNK_ROWS):
        block = varying[start:start + THEIL_SEN_CHUNK_ROWS]
        slopes[start:start + THEIL_SEN_CHUNK_ROWS] = np.median((block[:, j] - block[:, i]) / dx, axis=1)
    out[rows] = slopes
    return out


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
                              exclude_industrial: bool, area_km2: float | None = None,
                              confidence_level: str = 'nominal') -> AoiAggregate:
    """Dense daily arrays, map hexagons and industrial removal count for an AOI (one cube scan)."""
    if not cells_r4 or not cells_r7:
        return AoiAggregate(_empty_daily(), [], 0, 0, [], np.empty(0))
    missing = set(duckdb_engine.missing_columns())
    r7_sorted = np.asarray(sorted(cells_r7), dtype=np.uint64)
    with duckdb_engine.get_db_cursor() as cur:
        table = query_aoi_rows(cur, cells_r4, cells_r7, start_year, end_year, confidence_level=confidence_level)
        if table.num_rows == 0:
            if duckdb_engine.data_source() == 'real':
                empty = {name: np.empty(0, dtype=np.float64) for name in _SCAN_COLUMNS}
                for name in ('h3_r7', 'epoch_day', 'year', 'raw_modis_cnt', 'raw_viirs_cnt') + MASK_COLUMNS:
                    empty[name] = np.empty(0, dtype=np.int64)
                daily = _aggregate_daily(empty, np.empty(0, dtype=bool), start_year, end_year, missing, area_km2)
                from backend.db.observation_coverage import apply_coverage
                zero, sensor_codes, complete = apply_coverage(cur, duckdb_engine.ROOT, cells_r7, daily, area_km2 or 0, True)
                if zero.any():
                    daily['observed_zero'], daily['observation_known'], daily['coverage_complete'] = zero, zero.copy(), complete
                    daily['sensor_obs_mask'][zero] = sensor_codes[zero]
                    daily['pm25_emitted_kg'][zero] = 0
                    daily['pm25_factor_sd_kg'][zero] = 0
                    for name, bits in zip(OBS_COLUMNS, (1, 2, 28)):
                        daily[name][zero & ((sensor_codes & bits) > 0)] = 0.0
                    return AoiAggregate(daily, [], 0, 0)
            return AoiAggregate(_empty_daily(), [], 0, 0)
        cols = {"h3_r7": table.column("h3_r7").to_numpy()}
        for name in ("epoch_day", "year", "raw_modis_cnt", "raw_viirs_cnt") + MASK_COLUMNS:
            cols[name] = np.zeros(table.num_rows, dtype=np.int64) if name in missing else _int_col(table, name)
        for name in ("raw_frp_mw", "industrial_prob") + OBS_COLUMNS + (
                "neighbor_fre_lag1", "cloud_cover_pct", "burned_area_ha_mcd64"):
            cols[name] = _float_col(table, name)
        hexagons, industrial_total, min_probs = _summarize_hexagons(cur, cols, r7_sorted, start_year, end_year)
    keep = cols["industrial_prob"] < INDUSTRIAL_THRESHOLD if exclude_industrial else np.ones(table.num_rows, bool)
    daily = _aggregate_daily(cols, keep, start_year, end_year, missing, area_km2) if keep.any() else _empty_daily()
    area = _daily_area(cols, keep, _row_cell_areas(cols["h3_r7"]), start_year, end_year) if keep.any() else np.empty(0)
    if len(daily['epoch_day']) and duckdb_engine.data_source() == 'real':
        from backend.db.observation_coverage import apply_coverage
        with duckdb_engine.get_db_cursor() as cur:
            zero, sensor_codes, complete = apply_coverage(cur, duckdb_engine.ROOT, cells_r7, daily, area_km2 or 0, True)
        zero &= (daily['raw_modis_cnt'] + daily['raw_viirs_cnt']) == 0
        zero &= daily['observed_energy_mj'] == 0
        daily['observed_zero'] = zero
        daily['pm25_emitted_kg'][zero] = 0.0
        daily['pm25_factor_sd_kg'][zero] = 0.0
        daily['observation_known'] |= zero
        daily['coverage_complete'] = complete
        daily['sensor_obs_mask'][zero] |= sensor_codes[zero]
        for name, bits in zip(OBS_COLUMNS, (1, 2, 28)):
            daily[name][zero & ((sensor_codes & bits) > 0)] = 0.0
    if exclude_industrial:
        removed = industrial_total
        used = [h.h3_index for h, p in zip(hexagons, min_probs.tolist()) if p < INDUSTRIAL_THRESHOLD]
    else:
        removed = 0
        used = [h.h3_index for h in hexagons]
    return AoiAggregate(daily, hexagons, removed, len(used), used, area)


def fetch_map_period(cells_r4: list[int], cells_r7: list[int], year: int,
                     epoch_range: tuple[int, int], exclude_industrial: bool, confidence_level: str = "nominal") -> list[H3MapSummaryHex]:
    """Observed per-cell energy and counts for an inclusive period within one year.

    The legacy ``mean_annual_fre`` field contains the selected period's integrated
    density here; no annual extrapolation or regional gap filling is applied.
    """
    if not cells_r4 or not cells_r7:
        return []
    with duckdb_engine.get_db_cursor() as cur:
        table = query_aoi_rows(cur, cells_r4, cells_r7, year, year, epoch_range, confidence_level)
        if exclude_industrial:
            table = table.filter(pc.less(table["industrial_prob"], INDUSTRIAL_THRESHOLD))
        if table.num_rows == 0:
            return []
        cols = {"h3_r7": table.column("h3_r7").to_numpy()}
        for name in ("epoch_day", "year", "raw_modis_cnt", "raw_viirs_cnt"):
            cols[name] = _int_col(table, name)
        for name in ("industrial_prob",) + OBS_COLUMNS:
            cols[name] = _float_col(table, name)
        hexagons, _, _ = _summarize_hexagons(
            cur, cols, np.asarray(sorted(cells_r7), dtype=np.uint64), year, year)
    return [h for h in hexagons if h.raw_pixel_count > 0 or h.mean_annual_fre > 0]

def fetch_observed_detections(cells_r4: list[int], cells_r7: list[int], start_year: int, end_year: int) -> dict:
    """Aggregate accepted FIRMS detection centers, without calibration or imputation."""
    path = duckdb_engine.ROOT / 'data/processed/staged_firms.parquet'
    if not path.is_file():
        raise FileNotFoundError('Raw observations are unavailable. Run scripts/01_ingest_firms.py.')
    if duckdb_engine.data_source() != 'real':
        raise ValueError('The observations viewer requires a real cube; disable USE_SYNTHETIC_CUBE.')
    if not cells_r7:
        return {'daily': [], 'map_hexagons': []}
    with duckdb_engine.get_db_cursor() as cur:
        _register_cells(cur, cells_r4, cells_r7)
        try:
            rows = cur.sql("""SELECT acq_date, h3_r7, satellite, frp FROM read_parquet(?)
                WHERE is_center AND h3_r4 IN (SELECT h3_r4 FROM aoi_r4)
                AND h3_r7 IN (SELECT h3_r7 FROM aoi_r7)
                AND acq_date BETWEEN make_date(?,1,1) AND make_date(?,12,31)""",
                params=[str(path), start_year, end_year]).to_arrow_table()
            cur.register('selected_observations', rows)
            daily = cur.sql("""SELECT acq_date::VARCHAR AS date,
                year(acq_date)::INTEGER AS year, dayofyear(acq_date)::INTEGER AS doy,
                count(*) AS detection_count, sum(frp) AS raw_frp_mw,
                list_sort(list(DISTINCT satellite)) AS sensors
                FROM selected_observations GROUP BY acq_date ORDER BY acq_date""").to_arrow_table().to_pylist()
            hexagons = cur.sql("""SELECT printf('%x', h3_r7) AS h3_index,
                count(*) AS detection_count, sum(frp) AS raw_frp_mw
                FROM selected_observations GROUP BY h3_r7 ORDER BY h3_r7""").to_arrow_table().to_pylist()
            return {'daily': daily, 'map_hexagons': hexagons}
        finally:
            _unregister_cells(cur)


def fetch_risk_daily(cells_r4: list[int], cells_r7: list[int], start_year: int,
                     end_year: int, cutoff_epoch: int) -> dict[str, np.ndarray]:
    """Aggregate causal FRP features without reusing retrospective ETL classifications."""
    if not cells_r7:
        return {}
    missing = set(duckdb_engine.missing_columns())
    metadata = pq.read_schema(duckdb_engine.cube_path()).metadata or {}
    coverage = json.loads(metadata.get(b"ancillary_coverage", b"{}"))
    cloud_coverage = coverage.get("cloud_cover_pct", {})
    # The current cube has a zero sentinel. Use cloud only when zero can be trusted.
    has_cloud = ("cloud_cover_pct" not in missing and cloud_coverage.get("observed_rows", 0) > 0
                 and cloud_coverage.get("missing_rows", 1) == 0)
    cloud = "cloud_cover_pct" if has_cloud else "NULL::DOUBLE"
    gap = "gap_status_mask" if "gap_status_mask" not in missing else "0"
    query_sql = (
        "WITH source AS ("
        "    SELECT h3_r7, epoch_day, greatest(raw_frp_mw, 0)::DOUBLE AS frp, "
        + cloud + " AS cloud, " + gap + " AS gap, "
        "           month(DATE '1970-01-01' + epoch_day::INTEGER) AS month_idx "
        + _SPATIAL_FILTER + " AND epoch_day <= ?"
        "), history AS ("
        "    SELECT *, count(*) FILTER (WHERE frp > 0) OVER prior AS past_days, "
        "           bit_count(bit_or(1 << month_idx) FILTER (WHERE frp > 0) OVER prior) AS past_months, "
        "           avg(ln(1 + frp)) FILTER (WHERE frp > 0) OVER prior AS baseline, "
        "           stddev_pop(ln(1 + frp)) FILTER (WHERE frp > 0) OVER prior AS spread "
        "    FROM source WINDOW prior AS ("
        "        PARTITION BY h3_r7 ORDER BY epoch_day RANGE BETWEEN 365 PRECEDING AND 1 PRECEDING"
        "    )"
        ") "
        "SELECT h3_r7, epoch_day, frp, cloud, gap, "
        "       coalesce(past_days >= 12 AND past_months >= 9 AND spread <= 0.8, false) AS persistent, "
        "       greatest(0, (ln(1 + frp) - baseline) / greatest(0.25, spread)) AS excursion "
        "FROM history"
    )
    with duckdb_engine.get_db_cursor() as cur:
        _register_cells(cur, cells_r4, cells_r7)
        try:
            classified = cur.sql(query_sql, params=[start_year, end_year, cutoff_epoch]).to_arrow_table()
        finally:
            _unregister_cells(cur)
        if not classified.num_rows:
            return {}

        cur.register("risk_rows", classified)
        try:
            by_day = cur.sql("""
                SELECT epoch_day, sum(frp) FILTER (WHERE NOT persistent) AS vegetation_frp,
                       sum(frp) FILTER (WHERE persistent) / nullif(sum(frp), 0) AS persistent_share,
                       max(excursion) FILTER (WHERE persistent AND frp > 0) AS industrial_z,
                       avg(cloud) AS cloud, bit_or(gap) AS gap
                FROM risk_rows GROUP BY epoch_day ORDER BY epoch_day
            """).to_arrow_table()
            cells = cur.sql("SELECT DISTINCT h3_r7 FROM risk_rows WHERE NOT persistent AND frp > 0").fetchnumpy()["h3_r7"]
            origins, neighbors = [], []
            cell_set = set(cells.tolist())
            for cell in cell_set:
                for neighbor in h3i.grid_disk(cell, 1):
                    if neighbor != cell and neighbor in cell_set:
                        origins.append(cell)
                        neighbors.append(neighbor)
            cur.register("risk_neighbors", pa.table({
                "origin": pa.array(origins, type=pa.uint64()),
                "neighbor": pa.array(neighbors, type=pa.uint64()),
            }))
            try:
                spatial = cur.sql("""
                    SELECT a.epoch_day, avg(b.frp) AS neighbor_frp
                    FROM risk_rows a JOIN risk_neighbors n ON n.origin = a.h3_r7
                    JOIN risk_rows b ON b.h3_r7 = n.neighbor
                      AND b.epoch_day::INTEGER = a.epoch_day::INTEGER - 1
                    WHERE NOT a.persistent AND NOT b.persistent AND b.frp > 0
                    GROUP BY a.epoch_day
                """).to_arrow_table()
            finally:
                cur.unregister("risk_neighbors")
        finally:
            cur.unregister("risk_rows")

    days = _int_col(by_day, "epoch_day")
    epoch = np.arange(days[0], days[-1] + 1, dtype=np.int64)
    result = {"epoch_day": epoch}
    for name in ("vegetation_frp", "persistent_share", "industrial_z", "cloud", "gap"):
        values = np.full(len(epoch), np.nan if name == "cloud" else 0.0)
        rows = _float_col(by_day, name)
        values[days - epoch[0]] = rows if name == "cloud" else np.nan_to_num(rows)
        result[name] = values
    result["neighbor_frp"] = np.zeros(len(epoch))
    result["neighbor_frp"][_int_col(spatial, "epoch_day") - epoch[0]] = _float_col(spatial, "neighbor_frp")
    return result
