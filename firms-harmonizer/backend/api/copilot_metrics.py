"""Server-owned quantitative answers using the dashboard's scientific calculation."""
from __future__ import annotations

import json
import math

from fastapi import HTTPException

from backend.api.schemas import AnalyzeRequest, ExplainSpikeRequest, GeoJSONPolygon
from backend.db import duckdb_engine


def retrieve_energy(scope, req: ExplainSpikeRequest) -> dict:
    """Integrate the same full-history daily FRE series shown in the dashboard.

    Lazy import keeps route registration independent of the copilot. No client value,
    model-generated SQL, or instantaneous FRP sample enters this calculation.
    """
    if not scope.coordinates or not scope.start or not scope.end:
        return {"status": "missing_scope", "message": "Select an area and a date range to calculate energy in GJ."}
    if scope.start < "2000-01-01" or scope.end > "2026-12-31":
        return {"status": "unsupported_period", "message": "The scientific energy cube supports 2001–2026. Choose dates within that period."}
    missing = set(duckdb_engine.missing_columns())
    if missing.intersection({"obs_terra_fre", "obs_aqua_fre", "obs_viirs_fre"}):
        return {"status": "unavailable", "message": "Calibrated sensor energy columns are unavailable; instantaneous MW cannot be converted into GJ without time integration."}
    from backend.api.routes import analyze

    try:
        response = analyze(AnalyzeRequest(aoi=GeoJSONPolygon(coordinates=scope.coordinates),
            start_year=2000, end_year=2026, forecast_days=14,
            exclude_industrial_flaring=req.exclude_industrial_flaring,
            enable_kalman_gap_filling=req.enable_kalman_gap_filling,
            confidence_level=req.confidence_level))
    except (HTTPException, duckdb_engine.CubeNotAvailableError) as exc:
        if isinstance(exc, HTTPException) and exc.status_code == 422:
            raise ValueError(str(exc.detail)) from exc
        return {"status": "unavailable", "message": "The scientific energy calculation is unavailable. No GJ total has been estimated from raw MW."}
    data = json.loads(response.body)
    cells = [c for c in data["calendar_series"] if scope.start <= c["date"] <= scope.end and not c["is_forecast"]]
    if not cells or data["aoi_area_km2"] <= 0:
        return {"status": "empty", "message": "No scientific cube series is available for this area and period; this does not establish zero fire energy."}
    area = data["aoi_area_km2"]
    total = math.fsum(c["harmonized_fre_mj_km2"] for c in cells) * area / 1000.0
    by_year = {}
    for cell in cells:
        by_year.setdefault(cell["year"], []).append(cell["harmonized_fre_mj_km2"])
    peak = max(cells, key=lambda c: c["harmonized_fre_mj_km2"])
    return {"status": "ok", "data_source": data["data_source"], "energy_gj": total,
            "area_km2": area, "days": len(cells), "gap_filled_days": sum(c["is_gap_filled"] for c in cells),
            "biomass_tonnes": math.fsum(c["biomass_burned_tonnes"] for c in cells),
            "peak_day": peak["date"], "peak_day_gj": peak["harmonized_fre_mj_km2"] * area / 1000.0,
            "annual_gj": {year: math.fsum(values) * area / 1000.0 for year, values in by_year.items()}}


def energy_answer(scope, evidence: dict, req: ExplainSpikeRequest) -> str:
    if evidence["status"] != "ok":
        return evidence["message"]
    method = "per-cell observed energy with reconstruction limited to evidenced gaps" if req.enable_kalman_gap_filling else "available calibrated observations without gap filling"
    industrial = "excluded" if req.exclude_industrial_flaring else "included"
    lines = [f"### Energy result\n\nFor **{scope.label}**, **{scope.start} to {scope.end}**, the scientific cube gives "
             f"**{evidence['energy_gj']:,.3f} GJ** of integrated fire radiative energy. [6]",
             f"### Scope and method\n\nThis uses {method}, with industrial heat sources {industrial}. "
             f"The calculation covers **{evidence['area_km2']:,.3f} km²** of requested polygon area and "
             f"**{evidence['days']:,} days**, including **{evidence['gap_filled_days']:,} reconstructed days**. "
             "It uses the dashboard's 2001–2026 analysis history, then selects the requested inclusive dates.",
             f"### Derived estimates\n\n- Estimated dry biomass consumed: **{evidence['biomass_tonnes']:,.3f} tonnes** "
             "(0.368 kg/MJ). This is a model-derived estimate, not measured burned area or emissions. [1]",
             f"- The highest-energy day in this period is **{evidence['peak_day']}** "
             f"with **{evidence['peak_day_gj']:,.3f} GJ**. [6]",
             "### Interpretation\n\nGJ = Σ daily FRE (MJ/km²) × represented area (km²) / 1,000. "
             "This integrates calibrated daily energy; it does not convert a sum of instantaneous FRP samples into energy. "
             "Raw detection counts below use accepted centers before the scientific industrial-source filter."]
    if len(evidence["annual_gj"]) > 1:
        lines.append("### Yearly energy\n\nRequested dates only:\n\n| Year | FRE (GJ) |\n| --- | ---: |\n" +
            "\n".join(f"| {year} | {value:,.3f} |" for year, value in sorted(evidence["annual_gj"].items())))
    return "\n\n".join(lines)
