"""Deterministic offline integration fixture, not NASA observations or calibration."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

import duckdb
import h3
import numpy as np
import pyarrow as pa

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Centers are strictly inside the four bounding boxes in SPECS.md section 5.3.
# Keep the tuple interface used by the downstream ETL and benchmark scripts.
import json
REGISTRY = json.loads((ROOT / "data/regions.json").read_text(encoding="utf-8"))
REGIONS = {key: (*value["fixture_center"], 220.0, value["nominal_biome"])
           for key, value in REGISTRY.items()}
REGION_BOUNDS = {key: tuple(value["bounds"]) for key, value in REGISTRY.items()}

CUBE_SCHEMA = pa.schema([
    pa.field(name, dtype, nullable=name.startswith("obs_") or name in {"cloud_cover_pct", "burned_area_ha_mcd64"})
    for name, dtype in [
        ("h3_r4", pa.uint64()), ("h3_r7", pa.uint64()),
        ("epoch_day", pa.uint16()), ("year", pa.uint16()), ("doy", pa.uint16()),
        ("igbp_biome", pa.uint8()), ("sensor_obs_mask", pa.uint8()),
        ("gap_status_mask", pa.uint8()), ("cloud_cover_pct", pa.float32()),
        ("raw_modis_cnt", pa.uint16()), ("raw_viirs_cnt", pa.uint16()),
        ("raw_frp_mw", pa.float32()), ("obs_terra_fre", pa.float32()),
        ("obs_aqua_fre", pa.float32()), ("obs_viirs_fre", pa.float32()),
        ("neighbor_fre_lag1", pa.float32()), ("industrial_prob", pa.float32()),
        ("burned_area_ha_mcd64", pa.float32()),
    ]
], metadata={b"source": b"SYNTHETIC integration fixture; not NASA observations",
             b"sort_order": b"h3_r4,epoch_day,h3_r7", b"seed": b"42"})


def _latlng_to_h3_int(lat: float, lon: float, res: int) -> int:
    """Return a lossless unsigned H3 index with h3-py v3 or v4."""
    if hasattr(h3, "latlng_to_cell"):
        cell = h3.latlng_to_cell(lat, lon, res)
    else:
        cell = h3.geo_to_h3(lat, lon, res)
    return int(cell, 16) if isinstance(cell, str) else int(cell)


def _h3_to_parent_int(h_int: int, res: int) -> int:
    """Use string APIs for both versions, preserving all 64 index bits."""
    cell = format(h_int, "x")
    if hasattr(h3, "cell_to_parent"):
        parent = h3.cell_to_parent(cell, res)
    else:
        parent = h3.h3_to_parent(cell, res)
    return int(parent, 16) if isinstance(parent, str) else int(parent)


def _disk(cell: str, radius: int) -> list[str]:
    if hasattr(h3, "grid_disk"):
        return sorted(h3.grid_disk(cell, radius))
    return sorted(h3.k_ring(cell, radius))


def region_cells(lat: float, lon: float) -> list[str]:
    """Sample ten nearby R7 cells deterministically, with spatial neighbors."""
    center = format(_latlng_to_h3_int(lat, lon, 7), "x")
    inner = _disk(center, 1)
    outer = sorted(set(_disk(center, 2)) - set(inner))
    chosen = np.random.default_rng(42).choice(outer, size=10 - len(inner), replace=False)
    return sorted(inner + chosen.tolist())


def parent_r4(cell: str) -> str:
    """Retain the string helper consumed by existing ETL callers."""
    return format(_h3_to_parent_int(int(cell, 16), 4), "x")


def _chow(values: np.ndarray, years: np.ndarray, doy: np.ndarray) -> tuple[float, float]:
    from scipy.stats import f as f_distribution

    t = np.arange(len(values)) / 365.25
    angle = 2 * np.pi * (doy - 1) / 365.25
    design = np.column_stack([np.ones(len(t)), t, np.sin(angle), np.cos(angle)])
    def rss(x: np.ndarray, y: np.ndarray) -> float:
        residual = y - x @ np.linalg.lstsq(x, y, rcond=None)[0]
        return float(residual @ residual)
    before = years < 2012
    pooled = rss(design, values)
    separate = rss(design[before], values[before]) + rss(design[~before], values[~before])
    stat = max(0.0, (pooled - separate) / 4 / (separate / (len(t) - 8) + 1e-8))
    return stat, float(f_distribution.sf(stat, 4, len(t) - 8))


SYNTHETIC_PATH = ROOT / "data/processed/fire_cube_synthetic.parquet"


def generate_bootstrap_cube(
    output_path: str | Path = SYNTHETIC_PATH, *, write_mock: bool = False,
) -> str:
    """Write 40 cells × 9,496 days offline and return the absolute output path.

    All day/sensor arrays are vectorized. The optional legacy mock export is
    excluded from the fast cube path; existing ETL callers can pass write_mock=False.
    Seasonal width grows 30% over 25 year intervals, while the peak moves
    0.75 days per interval (18.75 days from 2001 to 2026).
    """
    started = perf_counter()
    rng = np.random.default_rng(42)
    dates = np.arange(np.datetime64("2001-01-01"), np.datetime64("2027-01-01"))
    years = dates.astype("datetime64[Y]").astype(int) + 1970
    doy = (dates - dates.astype("datetime64[Y]")).astype(int) + 1
    epoch = (dates - np.datetime64("1970-01-01")).astype(np.uint16)
    cell_groups = [region_cells(lat, lon) for lat, lon, _, _ in REGIONS.values()]
    cells = [cell for group in cell_groups for cell in group]
    cell_ids = np.array([int(cell, 16) for cell in cells], dtype=np.uint64)
    parents = np.array([_h3_to_parent_int(int(cell), 4) for cell in cell_ids], dtype=np.uint64)
    industrial = np.zeros(40, dtype=bool)
    industrial[np.r_[0:2, 10:12, 20:22, 30:36]] = True

    # A wrapped Gaussian represents seasonal vegetation energy. Dividing by
    # width keeps annual energy stable as the season broadens, avoiding a
    # spurious harmonized level shift across the 2012 instrument transition.
    peaks = np.repeat([r[2] for r in REGIONS.values()], 10)[:, None]
    width = 25.0 * (1.0 + 0.30 * (years - 2001) / 25.0)
    phase = (doy[None, :] - peaks - 0.75 * (years - 2001) + 182.625) % 365.25 - 182.625
    scale = rng.uniform(0.9, 1.1, (40, 1))
    truth = (10.0 + 650.0 * 25.0 / width * np.exp(-0.5 * (phase / width) ** 2)) * scale
    truth[industrial] = np.broadcast_to(140.0 * scale[industrial], truth[industrial].shape)
    observations = (truth[:, :, None] * (1.0 + rng.normal(0.0, 0.025, (40, len(dates), 3)))).astype(np.float32)
    viirs_active = dates >= np.datetime64("2012-01-20")
    observations[:, ~viirs_active, 2] = np.nan
    observations[:, dates < np.datetime64("2002-07-04"), 1] = np.nan
    outage = (dates >= np.datetime64("2022-07-31")) & (dates <= np.datetime64("2022-08-16"))
    blackout = (dates >= np.datetime64("2022-08-22")) & (dates <= np.datetime64("2022-08-26"))
    observations[:, outage, 1] = np.nan
    observations[:, blackout, :] = np.nan
    sensor_mask = np.sum(np.isfinite(observations) * [1, 2, 4], axis=2, dtype=np.uint8)
    gap = np.where(blackout, 8, np.where(outage, 1, 0)).astype(np.uint8)
    cloud = rng.uniform(0.0, 0.65, truth.shape).astype(np.float32)
    cloud[:, blackout] = 0.95

    modis = np.rint(truth / 18.0).astype(np.uint16)
    # VIIRS adds 3.5 times MODIS counts, yielding about 4.5 times total raw
    # detections without changing the calibrated FRE observations.
    viirs = np.where(viirs_active, np.rint(modis * 3.5), 0).astype(np.uint16)
    modis[:, blackout] = 0
    viirs[:, blackout] = 0

    # Mean true energy of sampled first-ring neighbors at t-1. Every sampled
    # cell has a first-ring neighbor because the sample includes the inner disk.
    neighborhoods = [set(_disk(cell, 1)) - {cell} for cell in cells]
    weights = np.array([[other in neighbors for other in cells]
                        for neighbors in neighborhoods], dtype=np.float64)
    weights /= weights.sum(axis=1, keepdims=True)
    # Einsum avoids multithreaded BLAS startup for this small sparse product.
    neighbor = np.einsum("ij,jt->it", weights, truth, optimize=False)
    lag = np.empty_like(neighbor)
    lag[:, 1:] = neighbor[:, :-1]
    initial_phase = (366.0 - peaks[:, 0] + 0.75 + 182.625) % 365.25 - 182.625
    initial_width = 25.0 * (1.0 - 0.30 / 25.0)
    initial = (10.0 + 650.0 * 25.0 / initial_width * np.exp(-0.5 * (initial_phase / initial_width) ** 2)) * scale[:, 0]
    initial[industrial] = 140.0 * scale[industrial, 0]
    lag[:, 0] = weights @ initial
    burned = truth * 0.035 * (1.0 + rng.normal(0.0, 0.035, truth.shape))
    burned[industrial] = 0.0

    n = len(dates)
    values = [
        np.repeat(parents, n), np.repeat(cell_ids, n), np.tile(epoch, 40),
        np.tile(years, 40), np.tile(doy, 40),
        np.repeat([r[3] for r in REGIONS.values()], 10 * n),
        sensor_mask.ravel(), np.tile(gap, 40), cloud.ravel(),
        modis.ravel(), viirs.ravel(), ((modis.astype(np.float32) + viirs) * 4.0).ravel(),
        observations[:, :, 0].ravel(), observations[:, :, 1].ravel(), observations[:, :, 2].ravel(),
        lag.ravel(), np.repeat(np.where(industrial, 0.92, 0.04), n), burned.ravel(),
    ]
    arrays = [pa.array(v, type=field.type, mask=np.isnan(v) if field.nullable else None)
              for field, v in zip(CUBE_SCHEMA, values)]
    table = pa.Table.from_arrays(arrays, schema=CUBE_SCHEMA)
    path = Path(output_path)
    if not path.is_absolute():
        path = ROOT / path
    if path.resolve() == (ROOT / "data/processed/fire_cube.parquet").resolve():
        raise ValueError("The master cube path is reserved for real FIRMS data.")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Publish atomically so readers never see a partially written Parquet file.
    # DuckDB propagates real table constraints to Parquet repetition types.
    sql_types = {pa.uint64(): "UBIGINT", pa.uint16(): "USMALLINT",
                 pa.uint8(): "UTINYINT", pa.float32(): "FLOAT"}
    columns = ", ".join(f"{f.name} {sql_types[f.type]}" + ("" if f.nullable else " NOT NULL")
                        for f in CUBE_SCHEMA)
    with TemporaryDirectory(prefix=".bootstrap-", dir=path.parent) as temp:
        staged = Path(temp) / "fire_cube.parquet"
        with duckdb.connect(config={"threads": 2}) as con:
            con.register("synthetic_cube", table)
            con.execute("CREATE TEMP TABLE cube (" + columns + ")")
            con.execute("INSERT INTO cube SELECT * FROM synthetic_cube")
            con.execute(
                "COPY (SELECT * FROM cube "
                "ORDER BY h3_r4 ASC, epoch_day ASC, h3_r7 ASC) TO ? "
                "(FORMAT PARQUET, CODEC 'ZSTD', COMPRESSION_LEVEL 1, ROW_GROUP_SIZE 32768, "
                "KV_METADATA {source: 'SYNTHETIC integration fixture; not NASA observations', "
                "sort_order: 'h3_r4,epoch_day,h3_r7', seed: '42'})",
                [str(staged)],
            )
        staged.replace(path)
    return str(path)


if __name__ == "__main__":
    start = perf_counter()
    output = generate_bootstrap_cube()
    print(f"Synthetic cube: {output} ({perf_counter() - start:.3f}s)")
