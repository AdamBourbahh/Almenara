"""Server-owned quantitative answers using the dashboard's scientific calculation."""
from __future__ import annotations

import json
import math
from datetime import date
import h3

from fastapi import HTTPException

from backend.api.schemas import AnalyzeRequest, ExplainSpikeRequest, GeoJSONPolygon
from backend.db import duckdb_engine, queries


def retrieve_mapped_energy(scope, req):
    """Exactly the observed cell-period calculation used by the visible map."""
    queries.validate_polygon_topology(scope.coordinates)
    r4,r7,_=queries.get_hierarchical_h3_filter(scope.coordinates)
    epoch=date(1970,1,1)
    totals=[]
    cells=set()
    detections=0
    for year in range(int(scope.start[:4]),int(scope.end[:4])+1):
        start=max(scope.start,f'{year}-01-01')
        end=min(scope.end,f'{year}-12-31')
        rows=queries.fetch_map_period(r4,r7,year,((date.fromisoformat(start)-epoch).days,(date.fromisoformat(end)-epoch).days),req.exclude_industrial_flaring)
        for cell in rows:
            if req.exclude_industrial_flaring and cell.is_industrial_site:
                continue
            cells.add(cell.h3_index)
            totals.append(cell.mean_annual_fre*h3.cell_area(cell.h3_index,unit='km^2')/1000)
            detections+=cell.raw_pixel_count
    total=math.fsum(totals)
    return {'mapped_energy_gj':total,'mapped_biomass_tonnes':total*.368,
            'mapped_footprint_km2':math.fsum(h3.cell_area(c,unit='km^2') for c in cells),
            'mapped_detections':detections}


def retrieve_energy(scope, req: ExplainSpikeRequest) -> dict:
    """Integrate the same full-history daily FRE series shown in the dashboard.

    Lazy import keeps route registration independent of the copilot. No client value,
    model-generated SQL, or instantaneous FRP sample enters this calculation.
    """
    if not scope.coordinates or not scope.start or not scope.end:
        return {"status": "missing_scope", "message": "Select an area and a date range to calculate energy in GJ."}
    if scope.start < "2001-01-01" or scope.end > "2026-12-31":
        return {"status": "unsupported_period", "message": "The scientific energy cube supports 2001–2026. Choose dates within that period."}
    missing = set(duckdb_engine.missing_columns())
    if missing.intersection({"obs_terra_fre", "obs_aqua_fre", "obs_viirs_fre"}):
        return {"status": "unavailable", "message": "Calibrated sensor energy columns are unavailable; instantaneous MW cannot be converted into GJ without time integration."}
    from backend.api.routes import analyze

    try:
        response = analyze(AnalyzeRequest(aoi=GeoJSONPolygon(coordinates=scope.coordinates),
            start_year=2001, end_year=2026, forecast_days=14,
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
    total = math.fsum(c["biomass_burned_tonnes"] for c in cells) / 0.368
    by_year = {}
    for cell in cells:
        by_year.setdefault(cell["year"], []).append(cell["biomass_burned_tonnes"] / 0.368)
    peak = max(cells, key=lambda c: c["biomass_burned_tonnes"])
    mapped = retrieve_mapped_energy(scope, req)
    return {**mapped, "comparison_note": "Mapped energy is the sum of per-cell calibrated observations. energy_gj is the regional model estimate using sensor aggregation and optional reconstruction; these are different estimators.", "available_through": cells[-1]["date"], "status": "ok", "data_source": data["data_source"], "energy_gj": total,
            "area_km2": area, "days": len(cells), "gap_filled_days": sum(c["is_gap_filled"] for c in cells),
            "biomass_tonnes": math.fsum(c["biomass_burned_tonnes"] for c in cells),
            "peak_day": peak["date"], "peak_day_gj": peak["biomass_burned_tonnes"] / 0.368,
            "annual_gj": {year: math.fsum(values) for year, values in by_year.items()}}


def energy_answer(scope, evidence: dict, req: ExplainSpikeRequest) -> str:
    if evidence["status"] != "ok":
        return evidence["message"]
    method = "RTS Kalman reconstruction" if req.enable_kalman_gap_filling else "available calibrated observations without gap filling"
    industrial = "excluded" if req.exclude_industrial_flaring else "included"
    lines = [f"### Regional model energy\n\nFor **{scope.label}**, **{scope.start} to {scope.end}**, the scientific cube gives "
             f"**{evidence['energy_gj']:,.3f} GJ** of integrated fire radiative energy. [6]",
             f"### Scope and method\n\nThis uses {method}, with industrial heat sources {industrial}. "
             f"The calculation covers **{evidence['area_km2']:,.3f} km²** of selected H3 cells and "
             f"**{evidence['days']:,} days**, including **{evidence['gap_filled_days']:,} reconstructed days**. "
             "It uses the dashboard's 2001–2026 analysis history, then selects the requested inclusive dates.",
             f"### Derived estimates\n\n- Estimated dry biomass consumed: **{evidence['biomass_tonnes']:,.3f} tonnes** "
             "(0.368 kg/MJ). This is a model-derived estimate, not measured burned area or emissions. [1]",
             f"- The highest-energy day in this period is **{evidence['peak_day']}** "
             f"with **{evidence['peak_day_gj']:,.3f} GJ**. [6]",
             "### Interpretation\n\nGJ = Σ daily FRE (MJ/km²) × the cube cell area represented on that day (km²) / 1,000. "
             "The full polygon area is not used for every day. Model density averages sensors with different spatial coverage; totals are derived estimates. This integrates calibrated daily energy; it does not convert a sum of instantaneous FRP samples into energy. "
             "Raw detection counts below use accepted centers before the scientific industrial-source filter."]
    if 'mapped_energy_gj' in evidence:
        lines.insert(0, f"### Visible map energy\n\nFor the same area and requested dates, the mapped observation-based proxy is **{evidence['mapped_energy_gj']:,.3f} GJ**, with **{evidence['mapped_biomass_tonnes']:,.3f} tonnes** of derived biomass. This matches the Explore panel's map calculation. [6]\n\nThe regional model estimate below uses a different calculation: it aggregates sensor densities before reconstruction, whereas the map integrates calibrated observations per cell. These are not two measurements of the same estimator. No regional reconstruction is included in the map total.")
        lines.append(f"### Available dates\n\nThe requested period is {scope.start}–{scope.end}; the model series available for this query ends on **{evidence['available_through']}**. Dates after archive coverage are not forecasts. Selected polygon area and observed cell footprint also differ: the mapped footprint is **{evidence['mapped_footprint_km2']:,.3f} km²**, not burned area.")
    if len(evidence["annual_gj"]) > 1:
        lines.append("### Yearly energy\n\nRequested dates only:\n\n| Year | FRE (GJ) |\n| --- | ---: |\n" +
            "\n".join(f"| {year} | {value:,.3f} |" for year, value in sorted(evidence["annual_gj"].items())))
    return "\n\n".join(lines)
