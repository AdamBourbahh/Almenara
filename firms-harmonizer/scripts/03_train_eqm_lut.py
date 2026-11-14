"""Train the censor-aware EQM/GPD lookup with the core RadiometricHarmonizer (SPECS.md §3.3)."""

import argparse
import json
from pathlib import Path
import sys

import duckdb
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.core.eqm_harmonizer import RadiometricHarmonizer  # noqa: E402

STAGED = ROOT / "data/processed/staged_firms.parquet"
THRESHOLD = 8.0
MIN_SAMPLES = 20
METHOD = ("backend.core.eqm_harmonizer.RadiometricHarmonizer: 101-knot EQM of every VIIRS cell-day onto "
          "Aqua; delta_e_sub = pi_sub * truncated-GPD mean over [0.5, 8) MW, added to VIIRS and MODIS")


def fit(samples, biome_id=None):
    """Fit one stratum from matched (Aqua, SNPP) daily MW sums; None when the stratum is too sparse."""
    samples = np.asarray(samples, dtype=float)
    if len(samples) < MIN_SAMPLES or not (samples[:, 0] > 0).any() or not (samples[:, 1] > 0).any():
        return None
    model = RadiometricHarmonizer().fit_biome_eqm_gpd(samples[:, 0], samples[:, 1], biome_id=biome_id or 1)
    model["biome_id"] = biome_id
    model["matched_days"] = len(samples)
    return model


def generate_eqm_gpd_lut(output_path="data/lookup/eqm_gpd_lut.json", staged=STAGED):
    models = {}
    if (ROOT / staged).exists():
        # Single-threaded so floating-point aggregation order, and therefore the LUT, is reproducible.
        with duckdb.connect(config={"threads": 1}) as con:
            rows = con.execute("""WITH daytime AS (
                SELECT * FROM read_parquet(?)
                WHERE acq_date BETWEEN DATE '2012-01-01' AND DATE '2025-12-31'
                    AND daynight = 'D' AND satellite IN ('Aqua', 'SNPP')
            ), aqua AS (
                SELECT h3_r7, acq_date, sum(corrected_frp) AS frp
                FROM daytime WHERE satellite = 'Aqua' GROUP BY ALL
            ), viirs_counts AS (
                SELECT h3_r7, acq_date, igbp_biome, scan_bin,
                       count(*) AS n, sum(corrected_frp) AS frp
                FROM daytime WHERE satellite = 'SNPP'
                GROUP BY h3_r7, acq_date, igbp_biome, scan_bin
            ), viirs AS (
                SELECT h3_r7, acq_date, min(igbp_biome) AS biome,
                       arg_max(scan_bin, n * 10 - scan_bin)::INTEGER AS angle,
                       sum(frp) AS frp
                FROM viirs_counts GROUP BY h3_r7, acq_date
            )
            SELECT biome, angle, aqua.frp, viirs.frp
            FROM aqua JOIN viirs USING (h3_r7, acq_date)
            ORDER BY biome, angle, acq_date, h3_r7
            """, [str(ROOT / staged)]).fetchall()
        if rows:
            strata = np.asarray([row[:2] for row in rows], dtype=float)
            values = np.asarray([row[2:] for row in rows], dtype=float)
            for biome in ("all", *range(1, 18)):
                in_biome = np.ones(len(rows), bool) if biome == "all" else strata[:, 0] == biome
                for angle in ("all", *range(10)):
                    if biome == "all" and angle != "all":
                        continue
                    selected = in_biome if angle == "all" else in_biome & (strata[:, 1] == angle)
                    result = fit(values[selected], None if biome == "all" else biome)
                    if result:
                        models[f"{biome}:{angle}"] = result
    lut = {"reference": "Matched daytime Aqua and SNPP cell-days, 2012-2025", "method": METHOD,
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
