"""DuckDB engine: one master in-memory connection over the Parquet cube, one cursor per request.

The synthetic fixture cube is used ONLY when ``USE_SYNTHETIC_CUBE=1``. Without it the engine
refuses to start unless a real (non-synthetic) cube exists at ``REAL_CUBE_PATH``.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Literal

import duckdb
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
REAL_CUBE_PATH = Path(os.environ.get("FIRE_CUBE_PATH", ROOT / "data/processed/fire_cube.parquet"))
SYNTHETIC_CUBE_PATH = ROOT / "data/processed/fire_cube_synthetic.parquet"
GENERATOR_PATH = ROOT / "scripts/00_bootstrap_synthetic_cube.py"

REQUIRED_COLUMNS = ("h3_r4", "h3_r7", "epoch_day", "year", "doy", "raw_modis_cnt", "raw_viirs_cnt",
                    "raw_frp_mw", "industrial_prob")
OPTIONAL_COLUMNS = ("igbp_biome", "sensor_obs_mask", "gap_status_mask", "cloud_cover_pct", "obs_terra_fre",
                    "obs_aqua_fre", "obs_viirs_fre", "neighbor_fre_lag1", "burned_area_ha_mcd64")

DataSource = Literal["real", "synthetic"]

_MASTER_CONN: duckdb.DuckDBPyConnection | None = None
_INIT_LOCK = threading.Lock()
_DATA_SOURCE: DataSource | None = None
_CUBE_PATH: Path | None = None
_MISSING: list[str] = []


class CubeNotAvailableError(RuntimeError):
    """The cube cannot be served (missing, synthetic without opt-in, or missing required columns)."""


def _is_synthetic_file(path: Path) -> bool:
    metadata = pq.read_schema(path).metadata or {}
    return b"SYNTHETIC" in metadata.get(b"source", b"")


def _generate_synthetic(path: Path) -> None:
    spec = importlib.util.spec_from_file_location("bootstrap_synthetic_cube", GENERATOR_PATH)
    if spec is None or spec.loader is None:
        raise CubeNotAvailableError(f"Cannot load the synthetic cube generator at {GENERATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.generate_bootstrap_cube(path)


def resolve_cube(real_path: Path | str, synthetic_path: Path | str,
                 use_synthetic: bool) -> tuple[Path, DataSource]:
    """Decide which cube to open. Never falls back to synthetic data implicitly."""
    real_path, synthetic_path = Path(real_path), Path(synthetic_path)
    if use_synthetic:
        if not synthetic_path.is_file():
            _generate_synthetic(synthetic_path)
        return synthetic_path, "synthetic"
    if not real_path.is_file():
        raise CubeNotAvailableError(
            f"Real cube not found at {real_path}. Run the ETL or set USE_SYNTHETIC_CUBE=1 "
            "to use the synthetic fixture.")
    if _is_synthetic_file(real_path):
        raise CubeNotAvailableError(
            f"{real_path} contains a SYNTHETIC cube; set USE_SYNTHETIC_CUBE=1 explicitly to serve it.")
    return real_path, "real"


def missing_optional_columns(names) -> list[str]:
    """Return the optional spec columns absent from ``names``; raise if a required one is absent."""
    present = set(names)
    missing_required = [c for c in REQUIRED_COLUMNS if c not in present]
    if missing_required:
        raise CubeNotAvailableError(f"Cube is missing required columns: {', '.join(missing_required)}")
    return sorted(set(OPTIONAL_COLUMNS) - present)


def init_engine() -> duckdb.DuckDBPyConnection:
    """Open the master connection once (thread-safe) and expose the cube as view ``fire_cube``."""
    global _MASTER_CONN, _DATA_SOURCE, _CUBE_PATH, _MISSING
    if _MASTER_CONN is not None:
        return _MASTER_CONN
    with _INIT_LOCK:
        if _MASTER_CONN is not None:
            return _MASTER_CONN
        use_synthetic = os.environ.get("USE_SYNTHETIC_CUBE") == "1"
        path, source = resolve_cube(REAL_CUBE_PATH, SYNTHETIC_CUBE_PATH, use_synthetic)
        conn = duckdb.connect(":memory:")
        conn.execute("SET parquet_metadata_cache = true")
        # DuckDB cannot bind a prepared parameter inside CREATE VIEW, so the view is created
        # through the relation API (no SQL text is built from the path).
        conn.read_parquet(str(path)).create_view("fire_cube")
        columns = [row[0] for row in conn.execute("DESCRIBE fire_cube").fetchall()]
        missing = missing_optional_columns(columns)
        if missing:
            logger.warning("Cube %s lacks optional columns (served as NULL): %s", path, ", ".join(missing))
        _DATA_SOURCE, _CUBE_PATH, _MISSING = source, path, missing
        _MASTER_CONN = conn
        return conn


@contextmanager
def get_db_cursor() -> Iterator[duckdb.DuckDBPyConnection]:
    """Isolated cursor per request; always closed."""
    cur = init_engine().cursor()
    try:
        yield cur
    finally:
        cur.close()


def data_source() -> DataSource:
    init_engine()
    assert _DATA_SOURCE is not None
    return _DATA_SOURCE


def cube_path() -> Path:
    init_engine()
    assert _CUBE_PATH is not None
    return _CUBE_PATH


def missing_columns() -> list[str]:
    init_engine()
    return list(_MISSING)


def get_row_count() -> int:
    with get_db_cursor() as cur:
        return int(cur.execute("SELECT COUNT(*) FROM fire_cube").fetchone()[0])
