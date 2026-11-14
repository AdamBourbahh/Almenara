"""Stage 5: real master cube (18-field contract of ``scripts/00`` ``CUBE_SCHEMA``), atomic publication.

Vectorized port of ``scripts/04_build_master_cube.py`` ``real_rows()``:
* groups per (R7 cell, UTC day, sensor) over footprint contributions;
* FRP calibrated with the EQM/GPD lookup (``estimate_vec`` == Germán's ``estimate`` row by row),
  then FRE density = calibrated FRP · 3600 s / cell area (one-hour integration proxy);
* Terra scaled by the Aqua/Terra diurnal ratio of its R4 block and month (>= 3 matched days);
* VIIRS = mean of the VIIRS sensors; sensors in an outage keep their counts but give no observation;
* ``neighbor_fre_lag1`` = mean previous-day energy of the 6 neighbouring cells present in the cube, else 0.
Columns FIRMS cannot provide use declared sentinels: ``cloud_cover_pct = 0``, ``burned_area_ha_mcd64 = 0``,
``igbp_biome`` = region nominal class, or 255 (MCD12Q1 fill) outside every region.
Bits written in ``gap_status_mask``: 1 (an outage on that day), 8 (a MODIS and a VIIRS outage the same day).
Bits 2 (cloud) and 4 (swath gap) need data FIRMS does not have and stay 0.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from pipeline import config, german, industrial, lookups, pairs

MODIS = np.array(config.MODIS_SENSORS)


def cube_schema() -> pa.Schema:
    return german.load("00_bootstrap_synthetic_cube").CUBE_SCHEMA


def _model(models: dict, biome, angle):
    return models.get(f"{biome}:{angle}") or models.get(f"{biome}:all") or models.get("all:all")


def estimate_vec(is_modis: np.ndarray, mw: np.ndarray, biome: np.ndarray, angle: np.ndarray,
                 models: dict, threshold: float = config.EQM_THRESHOLD_MW) -> np.ndarray:
    """Vectorized ``scripts/04_build_master_cube.estimate``."""
    mw = np.asarray(mw, dtype=np.float64)
    out = mw.copy()
    biome, angle, is_modis = np.asarray(biome), np.asarray(angle), np.asarray(is_modis, dtype=bool)
    for b, a in set(zip(biome.tolist(), angle.tolist())):
        model = _model(models, b, a)
        if model is None:
            continue
        sel = (biome == b) & (angle == a)
        tail = model["gpd"]
        m_sel = sel & is_modis
        if tail:
            hit = m_sel & (mw >= threshold)
            out[hit] = mw[hit] + tail["mean_mw"] * tail["fraction"] / (1 - tail["fraction"])
        v_sel = sel & ~is_modis & (mw >= threshold)
        x, y = np.asarray(model["viirs_quantiles"]), np.asarray(model["aqua_quantiles"])
        inside = v_sel & (mw >= x[0]) & (mw <= x[-1])
        out[inside] = np.interp(mw[inside], x, y)
        low = v_sel & (mw < x[0])
        out[low] = mw[low] * (y[0] / x[0])
        high = v_sel & (mw > x[-1])
        out[high] = mw[high] * (y[-1] / x[-1])
    return out


GROUPS_SQL = """
    WITH f AS ({fp}),
    g AS (
        SELECT h3_r4, h3_r7, acq_date, satellite, sensor_bit, mode(igbp_biome) AS biome, mode(scan_bin) AS angle,
               sum(corrected_frp) AS power, count(*) FILTER (WHERE is_center) AS n,
               coalesce(sum(frp) FILTER (WHERE is_center), 0) AS raw_power, max(industrial_prob) AS industrial
        FROM f GROUP BY h3_r4, h3_r7, acq_date, satellite, sensor_bit)
    SELECT g.*, (g.acq_date - DATE '1970-01-01')::INTEGER AS epoch_day, month(g.acq_date) AS month,
           h3_cell_area(g.h3_r7, 'km^2') AS area_km2,
           EXISTS (SELECT 1 FROM read_parquet(?) o WHERE o.acq_date = g.acq_date AND o.satellite = g.satellite) AS is_out,
           coalesce(r.ratio, 1.0) AS ratio
    FROM g LEFT JOIN (SELECT h3_r4, month, ratio FROM read_parquet(?) WHERE matched_days >= ?) r
        ON r.h3_r4 = g.h3_r4 AND r.month = month(g.acq_date)
"""


def _groups(con, detections: str, where: str, where_params: list, work: Path, lut: dict, industrial_path: Path,
            outages: Path, ratios: Path) -> Path:
    sql = GROUPS_SQL.replace("{fp}", industrial.footprint_sql(where))
    params = industrial.footprint_params(detections, industrial_path, where_params) + [str(outages), str(ratios),
                                                                         config.DIURNAL_MIN_MATCHED_DAYS]
    reader = con.sql(sql, params=params).to_arrow_reader(1_000_000)
    path = work / "groups.parquet"
    writer = None
    for batch in reader:
        t = pa.Table.from_batches([batch])
        sat = t["satellite"].to_numpy(zero_copy_only=False)
        is_modis = np.isin(sat, MODIS)
        est = estimate_vec(is_modis, t["power"].to_numpy(), t["biome"].to_numpy(), t["angle"].to_numpy(), lut)
        value = est * config.FRP_INTEGRATION_S / t["area_km2"].to_numpy()
        value = np.where(sat == "Terra", value * t["ratio"].to_numpy(), value)
        obs = pa.array(value, mask=t["is_out"].to_numpy(zero_copy_only=False))
        t = t.append_column("obs", obs).append_column("is_modis", pa.array(is_modis))
        if writer is None:
            writer = pq.ParquetWriter(path, t.schema, compression="zstd")
        writer.write_table(t)
    if writer is None:
        raise ValueError("No staged detections match the cube selection; refusing to publish an empty cube.")
    writer.close()
    return path


DAILY_SQL = """
    WITH g AS (SELECT * FROM read_parquet(?)),
    outday AS (
        SELECT acq_date, bool_or(list_contains(?, satellite)) AS modis_out,
               bool_or(NOT list_contains(?, satellite)) AS viirs_out
        FROM read_parquet(?) GROUP BY acq_date),
    d AS (
        SELECT h3_r7, epoch_day, any_value(h3_r4) AS h3_r4, any_value(acq_date) AS acq_date,
               arg_min(biome, satellite) AS igbp_biome,
               coalesce(bit_or(sensor_bit) FILTER (WHERE NOT is_out), 0) AS sensor_obs_mask,
               sum(n) FILTER (WHERE is_modis) AS modis_n, sum(n) FILTER (WHERE NOT is_modis) AS viirs_n,
               sum(raw_power) AS raw_frp_mw, max(industrial) AS industrial_prob,
               max(obs) FILTER (WHERE satellite = 'Terra') AS obs_terra_fre,
               max(obs) FILTER (WHERE satellite = 'Aqua') AS obs_aqua_fre,
               avg(obs) FILTER (WHERE NOT is_modis) AS obs_viirs_fre
        FROM g GROUP BY h3_r7, epoch_day),
    e AS (
        SELECT *, (coalesce(obs_terra_fre, 0) + coalesce(obs_aqua_fre, 0) + coalesce(obs_viirs_fre, 0))
                  / nullif((obs_terra_fre IS NOT NULL)::INT + (obs_aqua_fre IS NOT NULL)::INT
                           + (obs_viirs_fre IS NOT NULL)::INT, 0) AS energy
        FROM d),
    nb AS (SELECT h3_r7, epoch_day, unnest(h3_grid_disk(h3_r7, 1)) AS nbr FROM e),
    lag AS (
        SELECT nb.h3_r7, nb.epoch_day, avg(x.energy) AS lag
        FROM nb JOIN e x ON x.h3_r7 = nb.nbr AND x.epoch_day = nb.epoch_day - 1
        WHERE nb.nbr <> nb.h3_r7 AND x.energy IS NOT NULL GROUP BY ALL)
    SELECT e.h3_r4::UBIGINT AS h3_r4, e.h3_r7::UBIGINT AS h3_r7, e.epoch_day::USMALLINT AS epoch_day,
           year(e.acq_date)::USMALLINT AS year, dayofyear(e.acq_date)::USMALLINT AS doy,
           e.igbp_biome::UTINYINT AS igbp_biome, e.sensor_obs_mask::UTINYINT AS sensor_obs_mask,
           (CASE WHEN o.acq_date IS NULL THEN 0 ELSE 1 END
            + CASE WHEN o.modis_out AND o.viirs_out THEN 8 ELSE 0 END)::UTINYINT AS gap_status_mask,
           ?::FLOAT AS cloud_cover_pct,
           coalesce(e.modis_n, 0)::USMALLINT AS raw_modis_cnt, coalesce(e.viirs_n, 0)::USMALLINT AS raw_viirs_cnt,
           e.raw_frp_mw::FLOAT AS raw_frp_mw, e.obs_terra_fre::FLOAT AS obs_terra_fre,
           e.obs_aqua_fre::FLOAT AS obs_aqua_fre, e.obs_viirs_fre::FLOAT AS obs_viirs_fre,
           coalesce(lag.lag, 0)::FLOAT AS neighbor_fre_lag1, e.industrial_prob::FLOAT AS industrial_prob,
           ?::FLOAT AS burned_area_ha_mcd64
    FROM e LEFT JOIN lag USING (h3_r7, epoch_day) LEFT JOIN outday o ON o.acq_date = e.acq_date
    ORDER BY h3_r4, epoch_day, h3_r7
"""


def metadata(selection: str, rows: int, coverage: dict) -> dict[bytes, bytes]:
    return {
        b"source": b"REAL FIRMS detections (pipeline/; FIRMS yearly global archives)",
        b"sort_order": b"h3_r4,epoch_day,h3_r7",
        b"epoch": config.EPOCH.isoformat().encode(),
        b"selection": selection.encode(),
        b"real_rows": str(rows).encode(),
        b"synthetic_rows": b"0",
        b"coverage": json.dumps(coverage).encode(),
        b"sparsity": b"one row per cell-day with at least one FIRMS detection; a missing day means no detection",
        b"ancillary_sentinels": json.dumps({
            "cloud_cover_pct": config.CLOUD_SENTINEL, "burned_area_ha_mcd64": config.BURNED_SENTINEL,
            "igbp_biome": f"regions.json nominal_biome inside a region, {config.IGBP_FILL} (MCD12Q1 fill) outside",
            "gap_status_mask_bits_not_computed": [2, 4]}).encode(),
        b"fre_method": b"EQM/GPD calibrated FRP x 3600 s / cell area (one-hour integration proxy)",
    }


def build_cube(con, detections: str, region: str | None = None, output: Path = config.CUBE,
               industrial_path: Path = industrial.INDUSTRIAL, lut_path: Path = pairs.LUT,
               outages: Path = lookups.OUTAGES, ratios: Path = lookups.RATIOS,
               coverage: dict | None = None) -> Path:
    if output.resolve() == (config.ROOT / "data/processed/fire_cube_synthetic.parquet").resolve():
        raise ValueError("The synthetic cube path is reserved for the generated fixture.")
    lut = json.loads(Path(lut_path).read_text())["models"]
    where, where_params = "true", []
    if region is not None:
        if region not in config.load_regions():
            raise ValueError(f"Unknown region {region!r} (see data/regions.json)")
        where, where_params = "region = ?", [region]
    output.parent.mkdir(parents=True, exist_ok=True)
    work = config.TMP / f"cube_{output.stem}"
    work.mkdir(parents=True, exist_ok=True)
    groups = _groups(con, detections, where, where_params, work, lut, industrial_path, outages, ratios)
    rows = con.execute("SELECT count(*) FROM (SELECT DISTINCT h3_r7, epoch_day FROM read_parquet(?))",
                       [str(groups)]).fetchall()[0][0]
    schema = cube_schema().with_metadata(metadata(region or "global", rows, coverage or {}))
    modis = list(config.MODIS_SENSORS)
    reader = con.sql(DAILY_SQL, params=[str(groups), modis, modis, str(outages), config.CLOUD_SENTINEL,
                                        config.BURNED_SENTINEL]).to_arrow_reader(config.ROW_GROUP_SIZE)
    tmp = output.with_suffix(".parquet.tmp")
    written = 0
    writer = pq.ParquetWriter(tmp, schema, compression="zstd", write_statistics=True)
    try:
        for batch in reader:
            table = pa.Table.from_batches([batch]).cast(schema)
            writer.write_table(table, row_group_size=config.ROW_GROUP_SIZE)
            written += len(table)
    finally:
        writer.close()
    if written != rows:
        tmp.unlink()
        raise RuntimeError(f"Cube writer produced {written} rows, expected {rows} unique cell-days.")
    tmp.replace(output)
    for f in work.glob("*"):
        f.unlink()
    work.rmdir()
    return output

