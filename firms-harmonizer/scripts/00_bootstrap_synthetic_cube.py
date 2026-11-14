"""Deterministic offline integration fixture, not NASA observations or calibration."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
from time import perf_counter

import h3
import numpy as np
import orjson
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.ndimage import gaussian_filter1d
from scipy.stats import f as f_distribution, kendalltau, theilslopes, wasserstein_distance

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.api.schemas import AnalyzeResponse

REGIONS = {
    "cerrado_brazil": (-16.0, -48.0, 250.0, 9),
    "california_usa": (39.0, -121.0, 220.0, 8),
    "iberia_med": (39.0, -5.0, 205.0, 8),
    "niger_delta_flaring": (5.0, 6.0, 180.0, 12),
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


def region_cells(lat: float, lon: float) -> list[str]:
    """Use public string-index APIs under both h3-py v4 and v3."""
    if hasattr(h3, "latlng_to_cell"):
        return sorted(h3.grid_disk(h3.latlng_to_cell(lat, lon, 7), 1))
    return sorted(h3.k_ring(h3.geo_to_h3(lat, lon, 7), 1))


def parent_r4(cell: str) -> str:
    if hasattr(h3, "cell_to_parent"):
        return h3.cell_to_parent(cell, 4)
    return h3.h3_to_parent(cell, 4)


def _chow(values: np.ndarray, years: np.ndarray, doy: np.ndarray) -> tuple[float, float]:
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
    count = len(dates)
    # First region has seven equally weighted sample cells.
    area = 7 * 5.161
    latent = truth[:7].mean(axis=0)
    data = table.filter(pa.compute.is_in(table["h3_r7"], value_set=pa.array([
        int(c, 16) for c in region_cells(-16, -48)
    ], type=pa.uint64()))).to_pydict()
    epoch = np.asarray(data["epoch_day"])
    day_index = epoch - int((dates[0] - np.datetime64("2000-01-01")).astype(int))
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
    raw_density = raw / 7 * 18
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
                    execution_time_ms=elapsed_ms, aoi_area_km2=area, total_h3_cells=7,
                    calendar_series=cells, forecast_series=forecasts, phenology_by_year=phenology,
                    audit_metrics=audit, map_hexagons=[])
    for h in sorted(set(data["h3_r7"])):
        selected = np.asarray(data["h3_r7"]) == h
        cell_index = region_cells(-16, -48).index(f"{h:x}")
        cell_energy = truth[cell_index]
        annual = np.asarray([cell_energy[years == year].sum() for year in range(2001, 2027)])
        months = dates.astype("datetime64[M]").astype(int) % 12
        monthly = np.bincount(months, weights=cell_energy, minlength=12)
        fractions = monthly / monthly.sum()
        entropy = float(np.clip(-np.sum(fractions*np.log(fractions+1e-12))/np.log(12),0,1))
        response["map_hexagons"].append(dict(h3_index=f"{h:x}", mean_annual_fre=float(annual.mean()),
            raw_pixel_count=int((np.asarray(data["raw_modis_cnt"])[selected]+np.asarray(data["raw_viirs_cnt"])[selected]).sum()),
            trend_slope=float(theilslopes(annual, np.arange(2001,2027)).slope),
            is_industrial_site=False, shannon_entropy=entropy))
    validated = AnalyzeResponse.model_validate(response)
    mock = ROOT / "data/mock/mock_analyze_response.json"
    mock.write_bytes(orjson.dumps(validated.model_dump(), option=orjson.OPT_APPEND_NEWLINE))


def generate_bootstrap_cube(output_path="data/processed/fire_cube.parquet") -> Path:
    """Generate 28 R7 cells × 9496 days, sorted, ZSTD-compressed and reproducible."""
    started = perf_counter()
    rng = np.random.default_rng(42)
    dates = np.arange(np.datetime64("2001-01-01"), np.datetime64("2027-01-01"))
    years = dates.astype("datetime64[Y]").astype(int)+1970
    doy = (dates-dates.astype("datetime64[Y]")).astype(int)+1
    epoch = (dates-np.datetime64("2000-01-01")).astype(int)
    blocks, truths = [], []
    for name, (lat,lon,peak,biome) in REGIONS.items():
        for index, h in enumerate(region_cells(lat,lon)):
            phase = 2*np.pi*(doy-peak-.75*(years-2001))/365.25
            physical = (10+650*np.exp(4*(np.cos(phase)-1))) * (1+.035*index)
            if name == "niger_delta_flaring":
                physical = np.full(len(dates), 140.+index*3)
            truths.append(physical)
            observations = np.maximum(0, physical[:,None]*(1+rng.normal(0,.035,(len(dates),3))))
            observations[dates < np.datetime64("2002-07-04"),1] = np.nan
            observations[years < 2012,2] = np.nan
            outage = (dates >= np.datetime64("2022-07-31")) & (dates <= np.datetime64("2022-08-16"))
            blackout = (dates >= np.datetime64("2022-08-22")) & (dates <= np.datetime64("2022-08-26"))
            observations[outage,1] = np.nan
            observations[blackout,:] = np.nan
            mask = np.sum(np.isfinite(observations)*[1,2,4],axis=1).astype(np.uint8)
            modis = np.rint(physical/18).astype(np.uint16)
            modis[blackout] = 0
            viirs = np.where(years >= 2012,np.rint(modis*5.2),0).astype(np.uint16)
            cloud = rng.uniform(0,65,len(dates)).astype(np.float32)
            cloud[blackout] = 100
            # Each sample is the center or a ring neighbor; average other regional
            # cells sharing its first ring to obtain a genuinely spatial lag.
            region = region_cells(lat,lon)
            neighbors = (set(h3.grid_disk(h,1)) if hasattr(h3,"grid_disk") else set(h3.k_ring(h,1))) - {h}
            neighbor_indices = [j for j,c in enumerate(region) if c in neighbors]
            if name == "niger_delta_flaring":
                neighbor_energy = np.full(len(dates), np.mean([140.+j*3 for j in neighbor_indices]))
                initial_neighbor = neighbor_energy[0]
            else:
                neighbor_energy = (10+650*np.exp(4*(np.cos(phase)-1))) * np.mean([1+.035*j for j in neighbor_indices])
                # The day before the fixture starts is 2000-12-31, DOY 366.
                initial_phase = 2*np.pi*(366-peak+.75)/365.25
                initial_neighbor = (10+650*np.exp(4*(np.cos(initial_phase)-1))) * np.mean([1+.035*j for j in neighbor_indices])
            values = [np.full(len(dates),int(parent_r4(h),16),dtype=np.uint64),
                      np.full(len(dates),int(h,16),dtype=np.uint64), epoch,years,doy,
                      np.full(len(dates),biome),mask,np.where(blackout,8,np.where(outage,1,0)),cloud,
                      modis,viirs,(modis+viirs)*4.0,observations[:,0],observations[:,1],observations[:,2],
                      np.r_[initial_neighbor,neighbor_energy[:-1]],
                      np.full(len(dates),.92 if name=="niger_delta_flaring" else .08),
                      physical*.035*(1+rng.normal(0,.04,len(dates)))]
            arrays = [pa.array(v,type=field.type,mask=np.isnan(v) if field.nullable else None)
                      for field,v in zip(CUBE_SCHEMA,values)]
            blocks.append(pa.Table.from_arrays(arrays,schema=CUBE_SCHEMA))
    table = pa.concat_tables(blocks).sort_by([("h3_r4","ascending"),("epoch_day","ascending"),("h3_r7","ascending")])
    path = Path(output_path)
    if not path.is_absolute():
        path = ROOT/path
    path.parent.mkdir(parents=True,exist_ok=True)
    pq.write_table(table,path,compression="zstd",row_group_size=32768,write_statistics=True)
    _write_mock(table,dates,np.asarray(truths),years,doy,(perf_counter()-started)*1000)
    return path


if __name__ == "__main__":
    start = perf_counter()
    output = generate_bootstrap_cube()
    print(f"Synthetic cube: {output} ({perf_counter()-start:.3f}s)")
