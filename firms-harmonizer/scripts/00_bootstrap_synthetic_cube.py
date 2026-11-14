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
REGIONS = {
    "cerrado_brazil": (-16.9, -56.2, 220.0, 9),
    "california_usa": (39.1, -120.35, 220.0, 8),
    "iberia_med": (38.5, -4.85, 205.0, 8),
    "niger_delta_flaring": (5.2, 6.4, 220.0, 12),
}
REGION_BOUNDS = {
    "cerrado_brazil": (-57.2, -17.8, -55.2, -16.0),
    "california_usa": (-121.2, 38.0, -119.5, 40.2),
    "iberia_med": (-6.5, 37.2, -3.2, 39.8),
    "niger_delta_flaring": (5.6, 4.6, 7.2, 5.8),
}

CUBE_SCHEMA = pa.schema([
    pa.field(name, dtype, nullable=name.startswith("obs_"))
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


def _write_mock(table: pa.Table, dates: np.ndarray, truth: np.ndarray,
                years: np.ndarray, doy: np.ndarray, elapsed_ms: float) -> None:
    """Complete bounded Cerrado response using explicit synthetic oracle truth."""
    import orjson
    from scipy.ndimage import gaussian_filter1d
    from scipy.stats import kendalltau, theilslopes, wasserstein_distance
    from backend.api.schemas import AnalyzeResponse

    count = len(dates)
    region = region_cells(*REGIONS["cerrado_brazil"][:2])
    area = len(region) * 5.161
    latent = truth[:len(region)].mean(axis=0)
    data = table.filter(pa.compute.is_in(table["h3_r7"], value_set=pa.array([
        int(c, 16) for c in region
    ], type=pa.uint64()))).to_pydict()
    epoch = np.asarray(data["epoch_day"])
    day_index = epoch - int((dates[0] - np.datetime64("1970-01-01")).astype(int))
    raw = np.bincount(day_index, weights=np.asarray(data["raw_modis_cnt"]) + np.asarray(data["raw_viirs_cnt"]), minlength=count)
    raw_frp = np.bincount(day_index, weights=data["raw_frp_mw"], minlength=count)
    biome_proxy = np.bincount(day_index, weights=data["burned_area_ha_mcd64"], minlength=count)
    masks = np.zeros(count, dtype=np.uint8)
    gaps = np.zeros(count, dtype=np.uint8)
    np.bitwise_or.at(masks, day_index, data["sensor_obs_mask"])
    np.bitwise_or.at(gaps, day_index, data["gap_status_mask"])
    prior = np.bincount(doy - 1, weights=latent, minlength=366) / np.maximum(1, np.bincount(doy - 1, minlength=366))
    prior = gaussian_filter1d(prior, sigma=5, mode="wrap")
    cells = []
    def cell(date: str, year: int, ordinal: int, value: float, cross: float,
             raw_count: int, power: float, mask: int, gap: int, forecast: bool) -> dict:
        biomass = 0.368 * value * area / 1000
        margin = value * (0.25 if forecast else 0.12)
        return dict(date=date, year=year, doy=ordinal, raw_hotspot_count=raw_count,
                    raw_frp_mw=power, harmonized_fre_mj_km2=value,
                    historical_cross_prior_fre=cross, ci_95_lower=max(0, value-margin),
                    ci_95_upper=value+margin, uncertainty_pct=100*margin/max(value, 1e-8),
                    biomass_burned_tonnes=biomass, pm25_emitted_kg=biomass*9.5,
                    z_score_anomaly=(value-cross)/max(float(latent.std()), 1e-8),
                    is_gap_filled=bool(gap), is_forecast=forecast,
                    gap_reason="Cloud blackout" if gap == 8 else "Aqua outage" if gap else None,
                    active_sensors=[s for bit, s in [(1,"Terra"),(2,"Aqua"),(4,"VIIRS")] if mask & bit],
                    tooltip_narrative="Synthetic forecast from circular climatology." if forecast else
                    "Synthetic latent-energy fixture; uncertainty is illustrative, not a Kalman estimate.")
    for i, date in enumerate(dates):
        cells.append(cell(str(date), int(years[i]), int(doy[i]), float(latent[i]), float(prior[doy[i]-1]),
                          int(raw[i]), float(raw_frp[i]), int(masks[i]), int(gaps[i]), False))
    future = np.arange(np.datetime64("2027-01-01"), np.datetime64("2027-01-15"))
    forecasts = [cell(str(d), 2027, i+1, float(prior[i]), float(prior[i]), 0, 0., 0, 0, True)
                 for i, d in enumerate(future)]
    phenology = []
    for year in range(2001, 2027):
        selected = years == year
        angles = 2*np.pi*(doy[selected]-1)/365.25
        weights = latent[selected]
        c, s = np.sum(weights*np.cos(angles))/weights.sum(), np.sum(weights*np.sin(angles))/weights.sum()
        r = min(float(np.hypot(c, s)), 1-1e-8)
        kappa = (2*r+r**3+5*r**5/6 if r < .53 else
                 -.4+1.39*r+.43/(1-r) if r < .85 else 1/(r**3-4*r*r+3*r))
        peak = 1+(np.arctan2(s,c) % (2*np.pi))*365.25/(2*np.pi)
        label = str(np.datetime64(f"{year}-01-01") + np.timedelta64(round(peak)-1,"D"))
        phenology.append(dict(year=year, peak_doy_mu=float(peak), peak_date_label=label,
                              concentration_kappa=kappa, season_width_days=365.25/np.sqrt(kappa),
                              total_annual_fre_gj=float(weights.sum()*area/1000)))
    raw_f, raw_p = _chow(raw, years, doy)
    harm_f, harm_p = _chow(latent, years, doy)
    before = years < 2012
    # Within-period raw vs calibrated proxy diagnostics, in the same FRE units.
    raw_density = raw / len(region) * 18
    w_raw = wasserstein_distance(raw_density[before], raw_density[~before])
    w_harm = wasserstein_distance(latent[before], latent[~before])
    peaks = np.asarray([p["peak_doy_mu"] for p in phenology])
    slope = float(theilslopes(peaks, np.arange(2001,2027)).slope*10)
    audit = dict(chow_test_f_stat_raw=raw_f, chow_test_p_val_raw=raw_p,
                 chow_test_f_stat_harm=harm_f, chow_test_p_val_harm=harm_p,
                 wasserstein_w1_raw=w_raw, wasserstein_w1_harm=w_harm,
                 burned_area_r2_raw=float(np.corrcoef(raw, biome_proxy)[0,1]**2),
                 burned_area_r2_harm=float(np.corrcoef(latent, biome_proxy)[0,1]**2),
                 phenology_shift_days_per_decade=slope, mann_kendall_p_value=float(kendalltau(np.arange(26),peaks).pvalue),
                 industrial_false_positives_removed=0,
                 total_biomass_burned_kt=float(latent.sum()*area*.368/1e6),
                 total_pm25_emitted_tonnes=float(latent.sum()*area*.368*.0095/1000),
                 executive_verdict_en=("Synthetic integration fixture. Harmonized Chow gate: "
                     + ("PASS" if harm_p > .10 else "FAIL")
                     + ". Chow and Wasserstein are simulated diagnostics; burned-area R² is squared proxy correlation, not independent validation. No production Kalman results are claimed."))
    response = dict(data_source="synthetic", query_hash=hashlib.sha256(b"synthetic-cerrado-2001-2026-v1").hexdigest(),
                    execution_time_ms=elapsed_ms, aoi_area_km2=area, total_h3_cells=len(region),
                    calendar_series=cells, forecast_series=forecasts, phenology_by_year=phenology,
                    audit_metrics=audit, map_hexagons=[])
    for h in sorted(set(data["h3_r7"])):
        selected = np.asarray(data["h3_r7"]) == h
        cell_index = region.index(f"{h:x}")
        cell_energy = truth[cell_index]
        annual = np.asarray([cell_energy[years == year].sum() for year in range(2001, 2027)])
        months = dates.astype("datetime64[M]").astype(int) % 12
        monthly = np.bincount(months, weights=cell_energy, minlength=12)
        fractions = monthly / monthly.sum()
        entropy = float(np.clip(-np.sum(fractions*np.log(fractions+1e-12))/np.log(12),0,1))
        response["map_hexagons"].append(dict(h3_index=f"{h:x}", mean_annual_fre=float(annual.mean()),
            raw_pixel_count=int((np.asarray(data["raw_modis_cnt"])[selected]+np.asarray(data["raw_viirs_cnt"])[selected]).sum()),
            trend_slope=float(theilslopes(annual, np.arange(2001,2027)).slope),
            is_industrial_site=bool(data["industrial_prob"][np.flatnonzero(selected)[0]] > .75), shannon_entropy=entropy))
    validated = AnalyzeResponse.model_validate(response)
    mock = ROOT / "data/mock/mock_analyze_response.json"
    mock.write_bytes(orjson.dumps(validated.model_dump(), option=orjson.OPT_APPEND_NEWLINE))


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
    if write_mock:
        _write_mock(table, dates, truth, years, doy, (perf_counter() - started) * 1000)
    return str(path)


if __name__ == "__main__":
    start = perf_counter()
    output = generate_bootstrap_cube()
    print(f"Synthetic cube: {output} ({perf_counter() - start:.3f}s)")
