"""Stage 6: data-quality report (``data/real/quality_report.md`` and ``.json``).

Everything in the report is measured from the pipeline outputs; nothing is asserted about science.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq

from pipeline import config, cube, german, pairs

STAGES = ("rows_read", "valid", "after_dedup", "sama_removed", "kept")

# Static provenance of every column of the scripts/04 cube (data/ETL_SPEC.md); the report adds measured counts.
COLUMNS = {
    "h3_r4": ("computed", "H3 v4 parent (res 4) of the target R7 cell"),
    "h3_r7": ("computed", "H3 v4 res 7 of the detection, or the MODIS footprint target cell"),
    "epoch_day": ("computed", "UTC acquisition day, days since 1970-01-01"),
    "year": ("computed", "UTC acquisition year"),
    "doy": ("computed", "UTC day of year"),
    "igbp_biome": ("partial", "data/lookup/igbp_cells.parquet class when present, else regions.json nominal_biome"),
    "sensor_obs_mask": ("computed", "bit per sensor with a usable observation after outage and cloud masking"),
    "gap_status_mask": ("partial", "bit 1 any instrument outage that day (scripts/02 evidence: known SNPP outage, "
                                   "global count drop, zero global count), bit 2 cloud > 0.80, bit 8 no observation "
                                   "channel left; bit 4 (swath gap) is not computed"),
    "cloud_cover_pct": ("partial", "cell_day_ancillary.parquet in the lookup folder when present, else 0.0"),
    "raw_modis_cnt": ("computed", "MODIS centre-pixel detections (Terra + Aqua)"),
    "raw_viirs_cnt": ("computed", "VIIRS centre-pixel detections (SNPP + NOAA-20)"),
    "raw_frp_mw": ("computed", "sum of raw centre-pixel FRP, all sensors"),
    "obs_terra_fre": ("computed", "core RadiometricHarmonizer daily MW x 3600 s / cell area x orbital weight x "
                                  "diurnal Aqua/Terra ratio; one-hour integration proxy; NULL on outage or cloud"),
    "obs_aqua_fre": ("computed", "same proxy, reference sensor; NULL on outage or cloud"),
    "obs_viirs_fre": ("computed", "EQM-harmonized VIIRS with the same proxy; mean of the surviving VIIRS sensors"),
    "neighbor_fre_lag1": ("computed", "mean previous-day energy of burning neighbouring cells, else 0"),
    "industrial_prob": ("computed", "max R10 Shannon temporal entropy score with the positional-variance gate"),
    "burned_area_ha_mcd64": ("partial", "cell_day_ancillary.parquet in the lookup folder when present, else 0.0"),
}


def _stats_by_chunk() -> list[dict]:
    out = []
    for path in sorted((config.STAGED / "detections").glob("product=*/year=*/_stats.json")):
        product = path.parent.parent.name.split("=", 1)[1]
        year = int(path.parent.name.split("=", 1)[1])
        out.append({"product": product, "year": year, **json.loads(path.read_text())})
    return out


def detections_table(chunks: list[dict]) -> tuple[list[dict], list[dict]]:
    per_sensor, per_region = [], defaultdict(int)
    for chunk in chunks:
        for sensor, stats in sorted(chunk["sensors"].items()):
            per_sensor.append({"year": chunk["year"], "satellite": sensor, **{k: stats[k] for k in STAGES}})
        for row in chunk["by_region"]:
            per_region[(chunk["year"], row["satellite"], row["region"], row.get("tier", "SP"))] += row["kept"]
    regions = [{"year": y, "satellite": s, "region": r, "tier": t, "kept": n}
               for (y, s, r, t), n in sorted(per_region.items())]
    return sorted(per_sensor, key=lambda r: (r["year"], r["satellite"])), regions


def _cube_stats(con, path: Path) -> dict:
    if not path.is_file():
        return {"present": False}
    f = pq.ParquetFile(path)
    meta = {k.decode(): v.decode() for k, v in (f.schema_arrow.metadata or {}).items()}
    expected = german.load("00_bootstrap_synthetic_cube").CUBE_SCHEMA
    schema_ok = [(x.name, x.type, x.nullable) for x in f.schema_arrow] == \
                [(x.name, x.type, x.nullable) for x in expected]
    p = [str(path)]
    rows, cells, lo, hi = con.execute("SELECT count(*), count(DISTINCT h3_r7), min(epoch_day), max(epoch_day) "
                                      "FROM read_parquet(?)", p).fetchall()[0]
    dup = con.execute("SELECT count(*) FROM (SELECT h3_r7, epoch_day FROM read_parquet(?) GROUP BY ALL "
                      "HAVING count(*) > 1)", p).fetchall()[0][0]
    unsorted = con.execute("SELECT count(*) FROM (SELECT h3_r4, epoch_day, h3_r7, "
                           "lag(h3_r4) OVER w AS a, lag(epoch_day) OVER w AS b, lag(h3_r7) OVER w AS c "
                           "FROM read_parquet(?, file_row_number = true) WINDOW w AS (ORDER BY file_row_number)) "
                           "WHERE a IS NOT NULL AND (h3_r4, epoch_day, h3_r7) < (a, b, c)", p).fetchall()[0][0]
    columns = []
    for name, (status, note) in COLUMNS.items():
        nulls = con.execute("SELECT count(*) FILTER (WHERE " + name + " IS NULL) FROM read_parquet(?)", p).fetchall()[0][0]
        entry = {"column": name, "status": status, "note": note, "null_rows": nulls}
        if name in ("cloud_cover_pct", "burned_area_ha_mcd64"):
            entry["nonzero_rows"] = con.execute("SELECT count(*) FILTER (WHERE " + name + " <> 0) FROM read_parquet(?)",
                                                p).fetchall()[0][0]
        if name == "gap_status_mask":
            entry["bit_rows"] = {str(b): con.execute("SELECT count(*) FILTER (WHERE gap_status_mask & ? <> 0) "
                                                     "FROM read_parquet(?)", [b] + p).fetchall()[0][0] for b in (1, 2, 4, 8)}
        columns.append(entry)
    by_year = con.execute("SELECT year, count(*), sum(raw_modis_cnt), sum(raw_viirs_cnt) FROM read_parquet(?) "
                          "GROUP BY year ORDER BY year", p).fetchall()
    return {"present": True, "path": str(path.relative_to(config.ROOT)) if path.is_relative_to(config.ROOT) else str(path), "rows": rows, "cells": cells,
            "first_day": str(date.fromordinal(config.EPOCH.toordinal() + lo)),
            "last_day": str(date.fromordinal(config.EPOCH.toordinal() + hi)),
            "schema_matches_contract": schema_ok, "duplicate_keys": dup, "unsorted_rows": unsorted,
            "metadata": meta, "columns": columns,
            "by_year": [{"year": y, "cell_days": n, "modis_detections": m, "viirs_detections": v}
                        for y, n, m, v in by_year]}


def _pairs_stats(con, work: Path | None) -> dict:
    path = None if work is None else work / pairs.PAIRS_NAME
    if path is None or not path.is_file():
        return {"present": False}
    p = [str(path)]
    by_year = con.execute("SELECT year, daynight, count(*), count(*) FILTER (WHERE aqua_count > 0) "
                          "FROM read_parquet(?) GROUP BY ALL ORDER BY ALL", p).fetchall()
    by_region = con.execute("SELECT coalesce(region, '<none>'), count(*) FROM read_parquet(?) GROUP BY 1 ORDER BY 1",
                            p).fetchall()
    lut_path = work / cube.LOOKUP_NAME / cube.LUT_NAME
    lut = json.loads(lut_path.read_text()) if lut_path.is_file() else {"models": {}}
    return {"present": True, "rows": sum(r[2] for r in by_year),
            "by_year": [{"year": y, "daynight": d, "pairs": n, "centre_to_centre": c} for y, d, n, c in by_year],
            "by_region": [{"region": r, "pairs": n} for r, n in by_region],
            "lut_models": sorted(lut["models"]),
            "lut_models_with_gpd_tail": sorted(k for k, m in lut["models"].items() if m.get("gpd"))}


def _counts_stats(con, global_counts: Path, work: Path | None) -> dict:
    if not global_counts.is_file():
        return {"present": False}
    span = con.execute("SELECT satellite, min(acq_date), max(acq_date), count(*), count(*) FILTER (WHERE detection_count = 0),"
                       " sum(detection_count) FROM read_parquet(?) GROUP BY 1 ORDER BY 1",
                       [str(global_counts)]).fetchall()
    outages = []
    outage_path = None if work is None else work / cube.LOOKUP_NAME / "sensor_outages.parquet"
    if outage_path is not None and outage_path.is_file():
        outages = con.execute("SELECT satellite, evidence, count(*), min(acq_date), max(acq_date) FROM read_parquet(?) "
                              "GROUP BY ALL ORDER BY ALL", [str(outage_path)]).fetchall()
    return {"present": True,
            "sensors": [{"satellite": s, "first_day": str(a), "last_day": str(b), "days": d, "zero_days": z,
                         "detections": n} for s, a, b, d, z, n in span],
            "outages": [{"satellite": s, "evidence": e, "days": n, "first_day": str(a), "last_day": str(b)}
                        for s, e, n, a, b in outages]}


def coverage() -> dict:
    downloaded = {p: sorted(int(z.stem) for z in (config.RAW / p).glob("*.zip")) for p in config.PRODUCTS}
    return {"archives": downloaded,
            "not_covered": ["2026 (no yearly archive yet; needs the FIRMS area API with a MAP_KEY)",
                            "NOAA-21 (no viirs-jpss2 yearly archive; needs the FIRMS area API)",
                            "detections not assigned to any country by FIRMS (yearly *_all_countries archives)",
                            "detections outside every data/regions.json box (counted globally, never cubed)"]}


def build_report(con, region: str | None = None, work: Path | None = None, cube_path: Path | None = None,
                 global_counts: Path = config.GLOBAL_COUNTS) -> dict:
    """Report on the global ingest and, when ``region`` is given, on its regional build in ``work``."""
    if region is not None:
        work = config.region_dir(region) if work is None else work
        cube_path = work / cube.CUBE_NAME if cube_path is None else cube_path
    chunks = _stats_by_chunk()
    sensors, regions = detections_table(chunks)
    report = {"coverage": coverage(), "region": region, "detections_by_year_satellite": sensors,
              "kept_by_year_satellite_region_tier": regions,
              "global_daily_counts": _counts_stats(con, Path(global_counts), work),
              "cube": _cube_stats(con, cube_path) if cube_path is not None else {"present": False},
              "pairs_aqua_snpp": _pairs_stats(con, work)}
    config.REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    config.REPORT_JSON.write_text(json.dumps(report, indent=1, default=str))
    config.REPORT_MD.write_text(render_markdown(report))
    return report


def _table(headers: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    plain = {i for i, h in enumerate(headers) if h == "year"}
    lines += ["| " + " | ".join(f"{v:,}" if isinstance(v, int) and not isinstance(v, bool) and i not in plain
                                else str(v) for i, v in enumerate(r)) + " |" for r in rows]
    return "\n".join(lines)


def render_markdown(r: dict) -> str:
    out = ["# FIRMS real-data quality report", "",
           "Generated by `python -m pipeline.run`. Every number is measured from the pipeline outputs.", ""]
    cov = r["coverage"]
    out += ["## 1. Coverage", "", _table(["product", "yearly archives"],
                                         [[p, f"{y[0]}–{y[-1]} ({len(y)})" if y else "none"]
                                          for p, y in cov["archives"].items()]), ""]
    out += ["Not covered:", ""] + [f"- {x}" for x in cov["not_covered"]] + [""]
    out += ["## 2. Detections per year and satellite (global)", "",
            "`rows_read` → `valid` (finite, in range, 2000-11-01..2026-12-31) → `after_dedup` (exact sensor/time/"
            "position) → `sama_removed` (South Atlantic Anomaly rule) → `kept`.", "",
            _table(["year", "satellite"] + list(STAGES),
                   [[s["year"], s["satellite"]] + [s[k] for k in STAGES] for s in r["detections_by_year_satellite"]]), ""]
    region_rows = [x for x in r["kept_by_year_satellite_region_tier"] if x["region"] != "<none>"]
    out += ["### Kept detections inside the configured regions", "",
            _table(["year", "satellite", "region", "tier", "kept"],
                   [[x["year"], x["satellite"], x["region"], x["tier"], x["kept"]] for x in region_rows]), ""]
    gc = r["global_daily_counts"]
    if gc["present"]:
        out += ["## 3. Global daily counts and outages", "",
                _table(["satellite", "first day", "last day", "days", "zero-count days", "detections"],
                       [[s["satellite"], s["first_day"], s["last_day"], s["days"], s["zero_days"], s["detections"]]
                        for s in gc["sensors"]]), "",
                _table(["satellite", "evidence", "days", "first", "last"],
                       [[o["satellite"], o["evidence"], o["days"], o["first_day"], o["last_day"]] for o in gc["outages"]]),
                "", "Outage evidence comes from `scripts/02_detect_outages_clouds.py` run on these counts for the "
                "region build; the table is empty when no region was built.", ""]
    c = r["cube"]
    out += ["## 4. Cube columns", ""]
    if c["present"]:
        out += [f"`{c['path']}` — {c['rows']:,} cell-days, {c['cells']:,} R7 cells, {c['first_day']} → {c['last_day']}. "
                f"Schema matches the 18-field contract: **{c['schema_matches_contract']}**; duplicate keys: "
                f"{c['duplicate_keys']}; unsorted rows: {c['unsorted_rows']}. Region: `{r['region']}`; built by "
                "`scripts/04_build_master_cube.py`.",
                "", "Real rows are sparse: a cell-day exists only when FIRMS detected a fire; a missing day is "
                "*no detection*, not an observed zero.", "",
                _table(["column", "status", "null rows", "detail", "how"],
                       [[x["column"], x["status"], x["null_rows"],
                         ", ".join(f"{k}={v}" for k, v in x.items() if k in ("nonzero_rows", "bit_rows")),
                         x["note"]] for x in c["columns"]]), "",
                _table(["year", "cell-days", "MODIS detections", "VIIRS detections"],
                       [[y["year"], y["cell_days"], y["modis_detections"], y["viirs_detections"]] for y in c["by_year"]]), ""]
    else:
        out += ["No cube built yet.", ""]
    p = r["pairs_aqua_snpp"]
    out += ["## 5. Aqua–Suomi-NPP pairs", ""]
    if p["present"]:
        out += [f"{p['rows']:,} pairs (same R7 cell, UTC day and day/night pass). `centre_to_centre` = Aqua centre pixel "
                "in the cell (`aqua_count > 0`).", "",
                _table(["year", "pass", "pairs", "centre_to_centre"],
                       [[y["year"], y["daynight"], y["pairs"], y["centre_to_centre"]] for y in p["by_year"]]), "",
                _table(["region", "pairs"], [[x["region"], x["pairs"]] for x in p["by_region"]]), "",
                f"EQM/GPD strata with a supported model: {len(p['lut_models'])} "
                f"({', '.join(p['lut_models']) or 'none'}); with a GPD tail: {len(p['lut_models_with_gpd_tail'])}.", ""]
    else:
        out += ["No pairs built yet.", ""]
    return "\n".join(out) + "\n"
