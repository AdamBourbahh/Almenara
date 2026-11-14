"""Fit empirical Aqua/VIIRS quantiles and a bounded sub-threshold GPD model."""

import argparse
import json
from pathlib import Path

import duckdb
import numpy as np
from scipy.stats import genpareto

ROOT = Path(__file__).resolve().parents[1]
STAGED = ROOT / "data/processed/staged_firms.parquet"
THRESHOLD = 8.0
MIN_FRP = .5
MIN_SAMPLES = 20
QUANTILES = np.linspace(0, 1, 21)


def fit(samples):
    aqua = samples[(samples[:, 0] >= THRESHOLD), 0]
    viirs = samples[:, 1]
    above = viirs[viirs >= THRESHOLD]
    below = viirs[(viirs >= MIN_FRP) & (viirs < THRESHOLD)]
    if min(len(aqua), len(above)) < MIN_SAMPLES:
        return None
    bins = np.quantile(above, QUANTILES).round(5)
    x, indices = np.unique(bins, return_index=True)
    tail = None
    if len(below) >= MIN_SAMPLES and np.ptp(below) > 0:
        shape, _, scale = genpareto.fit(below - MIN_FRP, floc=0)
        distribution = genpareto(shape, loc=0, scale=scale)
        span = THRESHOLD - MIN_FRP
        probability_mass = distribution.cdf(span)
        if probability_mass > 0 and np.isfinite([shape, scale]).all():
            mean = distribution.expect(lambda value: value + MIN_FRP, lb=0, ub=span,
                                       conditional=True)
            if np.isfinite(mean):
                tail = {"shape": shape, "scale": scale, "lower_mw": MIN_FRP,
                        "upper_mw": THRESHOLD, "fraction": len(below) / len(viirs),
                        "mean_mw": float(np.clip(mean, MIN_FRP, THRESHOLD))}
    return {"aqua_quantiles": np.quantile(aqua, QUANTILES)[indices].round(5).tolist(),
            "viirs_quantiles": x.tolist(), "gpd": tail, "matched_days": len(samples)}


def generate_eqm_gpd_lut(output_path="data/lookup/eqm_gpd_lut.json", staged=STAGED):
    models = {}
    if (ROOT / staged).exists():
        with duckdb.connect() as con:
            rows = con.execute("""WITH daytime AS (
                SELECT * FROM read_parquet(?)
                WHERE acq_date BETWEEN DATE '2012-01-01' AND DATE '2025-12-31'
                    AND daynight = 'D' AND satellite IN ('Aqua', 'SNPP')
            ), aqua AS (
                SELECT h3_r7, acq_date, sum(corrected_frp) AS frp
                FROM daytime WHERE satellite = 'Aqua' GROUP BY ALL
            ), viirs AS (
                SELECT h3_r7, acq_date, any_value(igbp_biome) AS biome,
                       mode(scan_bin)::INTEGER AS angle, sum(corrected_frp) AS frp
                FROM daytime WHERE satellite = 'SNPP' GROUP BY h3_r7, acq_date
            )
            SELECT biome, angle, aqua.frp, viirs.frp
            FROM aqua JOIN viirs USING (h3_r7, acq_date)
            ORDER BY biome, angle, acq_date, h3_r7
            """, [str(ROOT / staged)]).fetchall()
        if rows:
            data = np.asarray(rows)
            for biome in ("all", *range(1, 18)):
                subset = data if biome == "all" else data[data[:, 0] == biome]
                for angle in ("all", *range(10)):
                    if biome == "all" and angle != "all":
                        continue
                    selected = subset if angle == "all" else subset[subset[:, 1] == angle]
                    result = fit(selected[:, 2:])
                    if result:
                        models[f"{biome}:{angle}"] = result
    lut = {"reference": "Matched daytime Aqua and SNPP cell-days, 2012-2025",
           "threshold_mw": THRESHOLD, "biomes": list(range(1, 18)),
           "angle_edges_degrees": np.linspace(0, 65, 11).tolist(), "models": models}
    path = ROOT / output_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lut, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(models)} supported EQM models to {path.name}.")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", default=STAGED)
    parser.add_argument("--output", default="data/lookup/eqm_gpd_lut.json")
    args = parser.parse_args()
    generate_eqm_gpd_lut(args.output, args.staged)
