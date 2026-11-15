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
    if scope.start < "2000-01-01" or scope.end > "2026-12-31":
        return {"status": "unsupported_period", "message": "The scientific energy cube supports November 2000–2026. Choose dates within that period."}
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
    method = "per-cell observed energy with reconstruction limited to evidenced gaps" if req.enable_kalman_gap_filling else "available calibrated observations without gap filling"
    industrial = "excluded" if req.exclude_industrial_flaring else "included"
    lines = [f"### Regional model energy\n\nFor **{scope.label}**, **{scope.start} to {scope.end}**, the scientific cube gives "
             f"**{evidence['energy_gj']:,.3f} GJ** of integrated fire radiative energy. [6]",
             f"### Scope and method\n\nThis uses {method}, with industrial heat sources {industrial}. "
             f"The calculation covers **{evidence['area_km2']:,.3f} km²** of requested polygon area and "
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
        lines.insert(0, f"### Visible map energy\n\nFor the same area and requested dates, the mapped observation-based proxy is **{evidence['mapped_energy_gj']:,.3f} GJ**, with **{evidence['mapped_biomass_tonnes']:,.3f} tonnes** of derived biomass. This matches the Explore panel's map calculation. [6]\n\nBoth calculations fuse available sensor observations within each cell and integrate against exact cell areas. The temporal estimate can additionally include reconstruction across explicitly evidenced gaps; the map contains observed energy only. Neither is a continuous physical energy measurement.")
        lines.append(f"### Available dates\n\nThe requested period is {scope.start}–{scope.end}; the model series available for this query ends on **{evidence['available_through']}**. Dates after archive coverage are not forecasts. Selected polygon area and observed cell footprint also differ: the mapped footprint is **{evidence['mapped_footprint_km2']:,.3f} km²**, not burned area.")
    if len(evidence["annual_gj"]) > 1:
        lines.append("### Yearly energy\n\nRequested dates only:\n\n| Year | FRE (GJ) |\n| --- | ---: |\n" +
            "\n".join(f"| {year} | {value:,.3f} |" for year, value in sorted(evidence["annual_gj"].items())))
    return "\n\n".join(lines)


# ---------------------------------------------------------------- deterministic calculation engine
#
# Every figure below is computed here from the dashboard's own analysis series. The language
# model receives these results as tool output and may only repeat them; it never does arithmetic.

WOOSTER_T_PER_GJ = 0.368          # 0.368 kg dry matter per MJ (Wooster et al. 2005) = 0.368 t per GJ
SCENARIO_PM25_KG_PER_T = 9.5      # assumed generic factor, g PM2.5 per kg dry matter
SCENARIO_CO2_KG_PER_T = 1580.0    # assumed generic factor, g CO2 per kg dry matter
SCENARIO_NOTE = ("Scenario estimate from assumed generic emission factors (9.5 kg PM2.5 and 1,580 kg CO2 per tonne of "
                 "dry biomass). It is not a measured emission, an air-quality concentration, or the dashboard's "
                 "fuel-specific PM2.5 value, which stays unavailable without measured annual land-cover classes.")
ENERGY_NOTE = ("Energy is a model-derived estimate from sampled satellite observations, not a continuous physical "
               "measurement. Biomass uses the Wooster combustion factor of 0.368 t per GJ.")


def _item(label: str, formula: str, value: float | None, unit: str) -> dict:
    return {"label": label, "formula": formula, "value": value, "unit": unit}


def verified(items: list[dict], note: str | None = None) -> dict | None:
    """The ``verified_calculations`` payload: formulas with their exact server results."""
    return {"items": items, "note": note} if items else None


def merge_verified(*groups: dict | None) -> dict | None:
    items = [item for group in groups if group for item in group["items"]]
    notes = list(dict.fromkeys(group["note"] for group in groups if group and group.get("note")))
    return verified(items[:12], " ".join(notes) or None)


def _gj(cell: dict) -> float:
    return cell["biomass_burned_tonnes"] / WOOSTER_T_PER_GJ


def _analysis(scope, req: ExplainSpikeRequest) -> tuple[dict | None, dict | None]:
    """The dashboard analysis for this polygon, or an explicit unavailable status."""
    if not scope.coordinates:
        return None, {"status": "missing_scope", "message": "Select an area to run this calculation."}
    if set(duckdb_engine.missing_columns()).intersection({"obs_terra_fre", "obs_aqua_fre", "obs_viirs_fre"}):
        return None, {"status": "unavailable", "message": "Calibrated sensor energy columns are unavailable; instantaneous MW cannot be converted into energy without time integration."}
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
        return None, {"status": "unavailable", "message": "The scientific calculation is unavailable. No value has been estimated from raw MW."}
    data = json.loads(response.body)
    data["series"] = [c for c in data["calendar_series"] if not c["is_forecast"]]
    if not data["series"] or data["aoi_area_km2"] <= 0:
        return None, {"status": "empty", "message": "No scientific cube series is available for this area; this does not establish zero fire activity."}
    return data, None


def _period_summary(series: list[dict], start: str, end: str) -> dict | None:
    cells = [c for c in series if start <= c["date"] <= end]
    if not cells:
        return None
    total = math.fsum(_gj(c) for c in cells)
    peak = max(cells, key=_gj)
    return {"start": start, "end": end, "first_available_day": cells[0]["date"], "last_available_day": cells[-1]["date"],
            "days": len(cells), "energy_gj": total, "mean_daily_gj": total / len(cells),
            "biomass_tonnes": total * WOOSTER_T_PER_GJ, "peak_day": peak["date"], "peak_day_gj": _gj(peak),
            "reconstructed_days": sum(c["is_gap_filled"] for c in cells)}


def _pct(before: float, after: float) -> float | None:
    return None if before == 0 else (after - before) / before * 100


def _signed(value: float | None, unit: str = "%", digits: int = 2) -> str:
    return "not defined (the first period is zero)" if value is None else f"{value:+,.{digits}f}{unit}"


def energy_calculations(evidence: dict) -> dict | None:
    if evidence.get("status") != "ok":
        return None
    energy = evidence["energy_gj"]
    return verified([
        _item("Total radiative energy", f"Σ daily FRE (MJ/km²) × represented cell area (km²) ÷ 1,000 over {evidence['days']:,} days = {energy:,.3f} GJ", energy, "GJ"),
        _item("Consumed dry biomass", f"{energy:,.3f} GJ × 0.368 t/GJ = {energy * WOOSTER_T_PER_GJ:,.3f} t", energy * WOOSTER_T_PER_GJ, "t"),
    ], ENERGY_NOTE)


# ---- smoke scenario

def retrieve_emissions(scope, req: ExplainSpikeRequest) -> dict:
    energy = retrieve_energy(scope, req)
    if energy["status"] != "ok":
        return energy
    biomass = energy["energy_gj"] * WOOSTER_T_PER_GJ
    return {"status": "ok", "data_source": energy["data_source"], "start": scope.start, "end": scope.end,
            "energy_gj": energy["energy_gj"], "biomass_tonnes": biomass,
            "scenario_pm25_kg": biomass * SCENARIO_PM25_KG_PER_T, "scenario_pm25_tonnes": biomass * SCENARIO_PM25_KG_PER_T / 1000,
            "scenario_co2_kg": biomass * SCENARIO_CO2_KG_PER_T, "scenario_co2_tonnes": biomass * SCENARIO_CO2_KG_PER_T / 1000,
            "reconstructed_days": energy["gap_filled_days"], "days": energy["days"], "disclaimer": SCENARIO_NOTE}


def emissions_calculations(evidence: dict) -> dict | None:
    if evidence.get("status") != "ok":
        return None
    energy, biomass = evidence["energy_gj"], evidence["biomass_tonnes"]
    return verified([
        _item("Consumed dry biomass", f"{energy:,.3f} GJ × 0.368 t/GJ = {biomass:,.3f} t", biomass, "t"),
        _item("PM2.5 scenario", f"{biomass:,.3f} t × 9.5 kg/t = {evidence['scenario_pm25_kg']:,.3f} kg", evidence["scenario_pm25_kg"], "kg"),
        _item("CO2 scenario", f"{biomass:,.3f} t × 1,580 kg/t = {evidence['scenario_co2_kg']:,.3f} kg", evidence["scenario_co2_kg"], "kg"),
    ], SCENARIO_NOTE)


def emissions_answer(scope, evidence: dict) -> str:
    if evidence["status"] != "ok":
        return evidence["message"]
    return (f"### Smoke and carbon scenario\n\nFor **{scope.label}**, **{scope.start} to {scope.end}**, the integrated fire energy is "
            f"**{evidence['energy_gj']:,.3f} GJ**, equivalent to **{evidence['biomass_tonnes']:,.3f} tonnes** of dry biomass consumed. [1] [6]\n\n"
            f"- PM2.5 (fine smoke particles): **{evidence['scenario_pm25_tonnes']:,.3f} tonnes** ({evidence['scenario_pm25_kg']:,.3f} kg).\n"
            f"- CO2: **{evidence['scenario_co2_tonnes']:,.3f} tonnes** ({evidence['scenario_co2_kg']:,.3f} kg).\n\n"
            f"{SCENARIO_NOTE} Real factors vary with fuel type and how completely it burns. [11]")


# ---- period-over-period comparison

def retrieve_comparison(scope, req: ExplainSpikeRequest, first: tuple[str, str], second: tuple[str, str]) -> dict:
    data, error = _analysis(scope, req)
    if error:
        return error
    a, b = _period_summary(data["series"], *first), _period_summary(data["series"], *second)
    if not a or not b:
        return {"status": "empty", "message": "One of the two periods lies outside the local archive, so no comparison was made."}
    return {"status": "ok", "data_source": data["data_source"], "area_km2": data["aoi_area_km2"],
            "first": a, "second": b,
            "energy_change_gj": b["energy_gj"] - a["energy_gj"], "energy_change_pct": _pct(a["energy_gj"], b["energy_gj"]),
            "biomass_change_tonnes": b["biomass_tonnes"] - a["biomass_tonnes"],
            "mean_daily_change_pct": _pct(a["mean_daily_gj"], b["mean_daily_gj"]),
            "peak_day_change_gj": b["peak_day_gj"] - a["peak_day_gj"], "peak_day_change_pct": _pct(a["peak_day_gj"], b["peak_day_gj"]),
            "available_through": data["series"][-1]["date"]}


def comparison_calculations(evidence: dict) -> dict | None:
    if evidence.get("status") != "ok":
        return None
    a, b = evidence["first"], evidence["second"]
    change = evidence["energy_change_pct"]
    return verified([
        _item("Energy change", f"({b['energy_gj']:,.3f} GJ − {a['energy_gj']:,.3f} GJ) ÷ {a['energy_gj']:,.3f} GJ × 100 = {_signed(change, '%', 2)}", change, "%"),
        _item("Biomass, first period", f"{a['energy_gj']:,.3f} GJ × 0.368 t/GJ = {a['biomass_tonnes']:,.3f} t", a["biomass_tonnes"], "t"),
        _item("Biomass, second period", f"{b['energy_gj']:,.3f} GJ × 0.368 t/GJ = {b['biomass_tonnes']:,.3f} t", b["biomass_tonnes"], "t"),
        _item("Biomass difference", f"{b['biomass_tonnes']:,.3f} t − {a['biomass_tonnes']:,.3f} t = {evidence['biomass_change_tonnes']:+,.3f} t", evidence["biomass_change_tonnes"], "t"),
    ], ENERGY_NOTE)


def comparison_answer(scope, evidence: dict) -> str:
    if evidence["status"] != "ok":
        return evidence["message"]
    a, b = evidence["first"], evidence["second"]
    def row(label, key, digits=3):
        return f"| {label} | {a[key]:,.{digits}f} | {b[key]:,.{digits}f} |"
    lines = [f"### Period comparison\n\nIn **{scope.label}**, fire energy changed by **{_signed(evidence['energy_change_pct'])}** from the first "
             f"period to the second, and dry biomass consumed by **{evidence['biomass_change_tonnes']:+,.3f} tonnes**. [6]",
             f"| Measure | {a['start']} to {a['end']} | {b['start']} to {b['end']} |\n| --- | ---: | ---: |\n"
             + row("Total energy (GJ)", "energy_gj") + "\n" + row("Dry biomass consumed (t)", "biomass_tonnes") + "\n"
             + row("Mean daily energy (GJ/day)", "mean_daily_gj") + "\n" + row("Highest single day (GJ)", "peak_day_gj") + "\n"
             + f"| Highest day (date) | {a['peak_day']} | {b['peak_day']} |\n"
             + f"| Days in archive | {a['days']:,} | {b['days']:,} |\n"
             + f"| Reconstructed days | {a['reconstructed_days']:,} | {b['reconstructed_days']:,} |",
             f"Mean daily energy changed by **{_signed(evidence['mean_daily_change_pct'])}** and the highest single day by "
             f"**{_signed(evidence['peak_day_change_pct'])}**. Biomass uses 0.368 t per GJ. [1] The archive for this area ends on "
             f"{evidence['available_through']}; a period that runs past it is compared on its available days only. "
             "Differences in satellite coverage between periods can contribute to the change."]
    return "\n\n".join(lines)


# ---- fire season timing

def retrieve_phenology(scope, req: ExplainSpikeRequest, recent_years: int | None = None) -> dict:
    import numpy as np
    from backend.api import core_contract
    from backend.core.von_mises import doy_to_date_label

    data, error = _analysis(scope, req)
    if error:
        return error
    days = {}
    for cell in data["series"]:
        days[cell["year"]] = days.get(cell["year"], 0) + 1
    rows = [p for p in data["phenology_by_year"]
            if p["total_annual_fre_gj"] > 0 and p["concentration_kappa"] > 1e-12
            and days.get(p["year"], 0) == (date(p["year"], 12, 31) - date(p["year"], 1, 1)).days + 1]
    if recent_years and rows:
        rows = [p for p in rows if p["year"] > rows[-1]["year"] - max(3, recent_years)]
    if len(rows) < 3:
        return {"status": "insufficient", "message": "Fewer than three complete years with fire energy are available here, so the timing of the fire season cannot be summarised."}
    years = np.asarray([p["year"] for p in rows])
    peaks = np.asarray([p["peak_doy_mu"] for p in rows])
    try:
        (slope, p_value), _ = core_contract.call("phenology_trend", years, peaks)
    except (core_contract.CoreMissingError, core_contract.CoreContractViolation):
        return {"status": "unavailable", "message": "The fire-season trend calculation is unavailable."}
    angles = peaks * 2 * math.pi / 365.25
    resultant = complex(float(np.cos(angles).mean()), float(np.sin(angles).mean()))
    mean_peak = (math.atan2(resultant.imag, resultant.real) % (2 * math.pi)) * 365.25 / (2 * math.pi)
    span = int(years[-1] - years[0])
    return {"status": "ok", "data_source": data["data_source"], "years_used": len(rows),
            "first_year": int(years[0]), "last_year": int(years[-1]),
            "mean_peak_day_of_year": mean_peak, "mean_peak_date": doy_to_date_label(min(max(mean_peak, 1.0), 366.0)),
            "peak_consistency": abs(resultant),
            "mean_season_duration_days": float(np.mean([p["season_width_days"] for p in rows])),
            "drift_days_per_decade": slope, "trend_p_value": p_value, "span_years": span,
            "total_shift_days": slope * span / 10,
            "drift_direction": "later" if slope > 0.05 else "earlier" if slope < -0.05 else "no measurable shift",
            "recent_years": [{"year": p["year"], "peak_date": p["peak_date_label"],
                              "season_duration_days": p["season_width_days"], "energy_gj": p["total_annual_fre_gj"]}
                             for p in rows[-5:]]}


def phenology_calculations(evidence: dict) -> dict | None:
    if evidence.get("status") != "ok":
        return None
    return verified([_item("Shift of the season peak over the record",
        f"{evidence['drift_days_per_decade']:+,.2f} days/decade × {evidence['span_years']} years ÷ 10 = {evidence['total_shift_days']:+,.2f} days",
        evidence["total_shift_days"], "days")],
        "Theil-Sen slope of the yearly energy-weighted peak date. The p-value is a rank test without correction for year-to-year correlation.")


def phenology_answer(scope, evidence: dict) -> str:
    if evidence["status"] != "ok":
        return evidence["message"]
    direction = evidence["drift_direction"]
    shift = (f"The peak has moved **{abs(evidence['drift_days_per_decade']):,.2f} days {direction} per decade** "
             f"(about **{abs(evidence['total_shift_days']):,.2f} days** across {evidence['first_year']}–{evidence['last_year']})."
             if direction != "no measurable shift" else "The peak date shows **no measurable shift** across the record.")
    significance = ("This trend is statistically distinguishable from no change" if evidence["trend_p_value"] < 0.05
                    else "This trend is not statistically distinguishable from year-to-year variability")
    p_value = "p < 0.001" if evidence["trend_p_value"] < 0.001 else f"p = {evidence['trend_p_value']:.3f}"
    return "\n\n".join([
        f"### Fire season timing\n\nIn **{scope.label}**, the burning season typically peaks around **{evidence['mean_peak_date']}** "
        f"and lasts about **{evidence['mean_season_duration_days']:,.1f} days**, based on {evidence['years_used']} complete years "
        f"({evidence['first_year']}–{evidence['last_year']}). [6]",
        f"### Decadal drift\n\n{shift} {significance} ({p_value}).",
        "| Year | Peak burning date | Season duration (days) | Energy (GJ) |\n| --- | --- | ---: | ---: |\n"
        + "\n".join(f"| {r['year']} | {r['peak_date']} | {r['season_duration_days']:,.1f} | {r['energy_gj']:,.3f} |" for r in evidence["recent_years"]),
        "The peak date is the energy-weighted centre of each year's fire activity, and duration is its effective seasonal width. "
        "A weakly seasonal year gives a long duration and an unstable peak. Only complete calendar years are used."])


# ---- reconstruction and persistent industrial heat

def retrieve_data_quality(scope, req: ExplainSpikeRequest) -> dict:
    data, error = _analysis(scope, req)
    if error:
        return error
    series = data["series"]
    start, end = scope.start or series[0]["date"], scope.end or series[-1]["date"]
    cells = [c for c in series if start <= c["date"] <= end]
    if not cells:
        return {"status": "empty", "message": "The requested dates lie outside the local archive for this area."}
    status = {}
    reasons = {}
    for cell in cells:
        key = cell.get("observation_status", "unknown")
        status[key] = status.get(key, 0) + 1
        if cell["is_gap_filled"]:
            reasons[cell["gap_reason"] or "Unspecified"] = reasons.get(cell["gap_reason"] or "Unspecified", 0) + 1
    hexagons = data["map_hexagons"]
    industrial = [h for h in hexagons if h["is_industrial_site"]]
    total = sum(h["raw_pixel_count"] for h in hexagons)
    flagged = sum(h["raw_pixel_count"] for h in industrial)
    return {"status": "ok", "data_source": data["data_source"], "start": cells[0]["date"], "end": cells[-1]["date"],
            "days": len(cells), "reconstructed_days": status.get("reconstructed", 0),
            "days_with_detections": status.get("detected", 0), "confirmed_clear_days": status.get("observed_zero", 0),
            "days_without_coverage_evidence": status.get("unknown", 0),
            "reconstruction_reasons": dict(sorted(reasons.items(), key=lambda entry: -entry[1])[:4]),
            "reconstruction_enabled": req.enable_kalman_gap_filling,
            "cells_with_activity": len(hexagons), "persistent_source_cells": len(industrial),
            "detections_all_cells": total, "detections_in_persistent_cells": flagged,
            "persistent_detection_share_pct": flagged / total * 100 if total else 0.0,
            "persistent_sources_excluded_from_energy": req.exclude_industrial_flaring,
            "strongest_persistent_cells": [{"h3_index": h["h3_index"], "seasonality_entropy": h["shannon_entropy"],
                                             "detections": h["raw_pixel_count"]}
                                            for h in sorted(industrial, key=lambda h: -h["raw_pixel_count"])[:3]]}


def quality_answer(scope, evidence: dict, sources_first: bool = False) -> str:
    if evidence["status"] != "ok":
        return evidence["message"]
    reasons = "; ".join(f"{name}: {count:,} days" for name, count in evidence["reconstruction_reasons"].items())
    if evidence["persistent_source_cells"]:
        sources = (f"**{evidence['persistent_source_cells']:,} of {evidence['cells_with_activity']:,} cells** with activity behave like "
                   f"stationary year-round heat sources (candidate industrial flaring). They account for "
                   f"**{evidence['persistent_detection_share_pct']:,.1f}%** of all detections in the full record "
                   f"({evidence['detections_in_persistent_cells']:,} of {evidence['detections_all_cells']:,}) and are "
                   f"{'excluded from' if evidence['persistent_sources_excluded_from_energy'] else 'included in'} the energy totals. "
                   "The remaining activity follows a seasonal pattern consistent with vegetation fire.")
    else:
        sources = (f"None of the **{evidence['cells_with_activity']:,} cells** with activity is flagged as a stationary year-round heat source, "
                   "so the detections here follow a seasonal pattern consistent with vegetation fire rather than industrial flaring.")
    sections = [
        f"### Reconstructed activity\n\nBetween **{evidence['start']}** and **{evidence['end']}** ({evidence['days']:,} days) in **{scope.label}**, "
        f"**{evidence['reconstructed_days']:,} days** were reconstructed across an evidenced satellite outage or cloud cover"
        + (f" ({reasons})" if reasons else "") + f". Satellites detected fire on **{evidence['days_with_detections']:,} days**, "
        f"**{evidence['confirmed_clear_days']:,} days** have a confirmed clear observation, and "
        f"**{evidence['days_without_coverage_evidence']:,} days** have no coverage evidence and are left unfilled. [4] [6]"
        + ("" if evidence["reconstruction_enabled"] else " Reconstruction is switched off for this request."),
        f"### Industrial versus vegetation heat\n\n{sources} [10]",
        "A persistent-source flag is a screening result from published flare sites and year-round persistence. "
        "It does not identify a facility, and an unflagged cell is not proof of vegetation fire."]
    return "\n\n".join([sections[1], sections[2], sections[0]] if sources_first else sections)


# ---- validated burned area

def retrieve_burned_area(scope, req: ExplainSpikeRequest) -> dict:
    import numpy as np

    if duckdb_engine.data_source() != "real":
        return {"status": "unavailable", "message": "MCD64A1 validated burned area is not part of the synthetic demo data."}
    data, error = _analysis(scope, req)
    if error:
        return error
    energy = {}
    for cell in data["series"]:
        energy.setdefault(cell["year"], []).append(_gj(cell))
    first = int(scope.start[:4]) if scope.start else min(energy)
    last = int(scope.end[:4]) if scope.end else max(energy)
    years = [year for year in sorted(energy) if first <= year <= last]
    if not years:
        return {"status": "empty", "message": "The requested years lie outside the local archive for this area."}
    _, r7, _ = queries.get_hierarchical_h3_filter(scope.coordinates)
    from backend.db.burned_area import annual_totals
    with duckdb_engine.get_db_cursor() as cursor:
        totals = annual_totals(duckdb_engine.ROOT, cursor, scope.coordinates, r7, np.asarray(years))
    rows = [{"year": year, "burned_area_ha": float(ha), "energy_gj": math.fsum(energy[year]),
             "energy_gj_per_ha": math.fsum(energy[year]) / float(ha) if ha > 0 else None}
            for year, ha in zip(years, totals.tolist()) if math.isfinite(ha)]
    if not rows:
        return {"status": "unavailable", "message": "MCD64A1 validated burned area is not published locally for this area and these years, so no hectares are reported. Detections and energy cannot substitute for burned area."}
    area, total = math.fsum(r["burned_area_ha"] for r in rows), math.fsum(r["energy_gj"] for r in rows)
    return {"status": "ok", "data_source": "real", "years": rows, "total_burned_area_ha": area, "total_energy_gj": total,
            "energy_gj_per_ha": total / area if area > 0 else None,
            "years_without_burned_area": [year for year in years if year not in {r["year"] for r in rows}]}


def burned_area_calculations(evidence: dict) -> dict | None:
    if evidence.get("status") != "ok" or evidence["energy_gj_per_ha"] is None:
        return None
    return verified([_item("Fire energy per burned hectare",
        f"{evidence['total_energy_gj']:,.3f} GJ ÷ {evidence['total_burned_area_ha']:,.3f} ha = {evidence['energy_gj_per_ha']:,.3f} GJ/ha",
        evidence["energy_gj_per_ha"], "GJ/ha")],
        "Burned area is the MCD64A1 500 m product; energy is the model-derived estimate for the same calendar years.")


def burned_area_answer(scope, evidence: dict) -> str:
    if evidence["status"] != "ok":
        return evidence["message"]
    density = (f" That is **{evidence['energy_gj_per_ha']:,.3f} GJ per burned hectare**." if evidence["energy_gj_per_ha"] is not None else "")
    missing = (f" Burned area is unavailable for: {', '.join(map(str, evidence['years_without_burned_area']))}."
               if evidence["years_without_burned_area"] else "")
    return "\n\n".join([
        f"### Validated burned area\n\nIn **{scope.label}**, MCD64A1 maps **{evidence['total_burned_area_ha']:,.3f} hectares** burned across "
        f"the years below, against **{evidence['total_energy_gj']:,.3f} GJ** of fire energy.{density} [6]",
        "| Year | Burned area (ha) | Energy (GJ) | Energy per hectare (GJ/ha) |\n| --- | ---: | ---: | ---: |\n"
        + "\n".join(f"| {r['year']} | {r['burned_area_ha']:,.3f} | {r['energy_gj']:,.3f} | "
                    + (f"{r['energy_gj_per_ha']:,.3f}" if r["energy_gj_per_ha"] is not None else "n/a") + " |" for r in evidence["years"]),
        "Burned area comes from the MCD64A1 500 m satellite product and includes burned cells without an active-fire detection. "
        "Small or low-intensity burns can be missed." + missing])


# ---- low-activity windows for planned burning

def retrieve_low_activity_windows(scope, req: ExplainSpikeRequest, window: int = 30, limit: int = 3) -> dict:
    import numpy as np

    if not scope.coordinates:
        return {"status": "missing_scope", "message": "Select an area to look for historically quiet burning windows."}
    r4, r7, _ = queries.get_hierarchical_h3_filter(scope.coordinates)
    area = queries.polygon_area_km2(scope.coordinates)
    daily = queries.fetch_aoi_aggregated_data(r4, r7, 2000, 2026, req.exclude_industrial_flaring, area, req.confidence_level).daily
    if len(daily["epoch_day"]) < 730 or area <= 0:
        return {"status": "insufficient", "message": "At least two years of local record are needed to identify historically quiet windows."}
    leap = (daily["year"] % 4 == 0) & ((daily["year"] % 100 != 0) | (daily["year"] % 400 == 0))
    slot = daily["doy"] - 1 - (leap & (daily["doy"] > 59))            # 365-day calendar; 29 Feb joins 28 Feb
    counts = np.maximum(np.bincount(slot, minlength=365), 1)
    def climatology(values):
        return np.bincount(slot, weights=values, minlength=365) / counts
    def rolling(values):
        return np.convolve(np.r_[values, values[:window - 1]], np.full(window, 1.0 / window), mode="valid")
    energy = rolling(climatology(daily["observed_energy_mj"] / area))
    neighbor = rolling(climatology(np.nan_to_num(daily["neighbor_fre_lag1"])))
    active = rolling(climatology((daily["raw_modis_cnt"] + daily["raw_viirs_cnt"]) > 0))
    def describe(start: int) -> dict:
        first = np.datetime64("2001-01-01") + int(start)
        last = np.datetime64("2001-01-01") + int((start + window - 1) % 365)
        label = lambda day: f"{int(str(day)[8:10])} {('Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec')[int(str(day)[5:7]) - 1]}"
        return {"start": label(first), "end": label(last), "mean_daily_energy_density_mj_km2": float(energy[start]),
                "mean_neighbor_energy_density_mj_km2": float(neighbor[start]), "days_with_detections_pct": float(active[start] * 100)}
    chosen: list[int] = []
    for start in np.lexsort((neighbor, energy)).tolist():
        if all(min(abs(start - other), 365 - abs(start - other)) >= window for other in chosen):
            chosen.append(start)
        if len(chosen) == limit:
            break
    return {"status": "ok", "data_source": duckdb_engine.data_source(), "window_days": window,
            "record_years": int(daily["year"][-1] - daily["year"][0] + 1),
            "quietest_windows": [describe(start) for start in chosen], "most_active_window": describe(int(np.argmax(energy)))}


def windows_answer(scope, evidence: dict) -> str:
    if evidence["status"] != "ok":
        return evidence["message"]
    best, peak = evidence["quietest_windows"][0], evidence["most_active_window"]
    return "\n\n".join([
        f"### Historically quiet {evidence['window_days']}-day windows\n\nIn **{scope.label}**, the quietest {evidence['window_days']}-day window in the "
        f"{evidence['record_years']}-year record runs from **{best['start']} to {best['end']}**. Fire was detected on "
        f"**{best['days_with_detections_pct']:,.1f}%** of those days, against **{peak['days_with_detections_pct']:,.1f}%** in the most active "
        f"window ({peak['start']} to {peak['end']}). [6]",
        "| Window | Mean fire energy density (MJ/km²/day) | Spread from adjacent cells (MJ/km²/day) | Days with detections (%) |\n| --- | ---: | ---: | ---: |\n"
        + "\n".join(f"| {w['start']} to {w['end']} | {w['mean_daily_energy_density_mj_km2']:,.4f} | "
                    f"{w['mean_neighbor_energy_density_mj_km2']:,.4f} | {w['days_with_detections_pct']:,.1f} |" for w in evidence["quietest_windows"]),
        "These windows show when satellites have historically recorded the least fire energy and the least spread between neighbouring cells. "
        "They are not a burn authorisation: weather, fuel moisture, staffing and local regulations decide whether a planned burn is safe. "
        "Days without a detection are counted as quiet, although cloud can hide activity."])


# ---- largest recorded thermal events

def retrieve_top_events(scope, req: ExplainSpikeRequest, start: str | None = None, end: str | None = None, limit: int = 5) -> dict:
    data, error = _analysis(scope, req)
    if error:
        return error
    series = data["series"]
    position = {c["date"]: i for i, c in enumerate(series)}
    candidates = sorted((c for c in series if (start or "") <= c["date"] <= (end or "9999") and c["raw_hotspot_count"] > 0
                         and not c["is_gap_filled"] and _gj(c) > 0), key=lambda c: (-_gj(c), c["date"]))
    peaks: list[dict] = []
    for cell in candidates:
        day = date.fromisoformat(cell["date"])
        if all(abs((day - date.fromisoformat(other["date"])).days) >= 15 for other in peaks):
            peaks.append(cell)
        if len(peaks) == limit:
            break
    if not peaks:
        return {"status": "empty", "message": "No observed thermal activity is recorded for this area and period. This does not prove that no fire occurred."}
    events = []
    for peak in peaks:
        index = position[peak["date"]]
        floor = 0.05 * _gj(peak)
        left = right = index
        while left > 0 and index - left < 15 and _gj(series[left - 1]) >= floor:
            left -= 1
        while right + 1 < len(series) and right - index < 15 and _gj(series[right + 1]) >= floor:
            right += 1
        episode = series[left:right + 1]
        total = math.fsum(_gj(c) for c in episode)
        events.append({"peak_date": peak["date"], "peak_day_gj": _gj(peak),
                       "peak_energy_density_mj_km2": peak["harmonized_fre_mj_km2"],
                       "start_date": episode[0]["date"], "end_date": episode[-1]["date"], "duration_days": len(episode),
                       "episode_energy_gj": total, "biomass_tonnes": total * WOOSTER_T_PER_GJ,
                       "detections": sum(c["raw_hotspot_count"] for c in episode)})
    # Candidates are the highest single days; the ranking is by the energy of the whole event.
    events.sort(key=lambda event: (-event["episode_energy_gj"], event["peak_date"]))
    events = [{"rank": rank, **event} for rank, event in enumerate(events, 1)]
    return {"status": "ok", "data_source": data["data_source"], "period_start": start or series[0]["date"],
            "period_end": end or series[-1]["date"], "events": events}


def events_calculations(evidence: dict) -> dict | None:
    if evidence.get("status") != "ok":
        return None
    top = evidence["events"][0]
    return verified([_item(f"Dry biomass, largest event ({top['peak_date']})",
        f"{top['episode_energy_gj']:,.3f} GJ × 0.368 t/GJ = {top['biomass_tonnes']:,.3f} t", top["biomass_tonnes"], "t")], ENERGY_NOTE)


def events_answer(scope, evidence: dict) -> str:
    if evidence["status"] != "ok":
        return evidence["message"]
    top = evidence["events"][0]
    return "\n\n".join([
        f"### Largest thermal events\n\nThe largest recorded event in **{scope.label}** between {evidence['period_start']} and "
        f"{evidence['period_end']} peaked on **{top['peak_date']}**: about **{top['episode_energy_gj']:,.3f} GJ** over "
        f"**{top['duration_days']} days**, or **{top['biomass_tonnes']:,.3f} tonnes** of dry biomass consumed. [1] [6]",
        "| Rank | Peak date | Active from | Active to | Days | Energy (GJ) | Dry biomass (t) | Detections |\n| ---: | --- | --- | --- | ---: | ---: | ---: | ---: |\n"
        + "\n".join(f"| {e['rank']} | {e['peak_date']} | {e['start_date']} | {e['end_date']} | {e['duration_days']} | "
                    f"{e['episode_energy_gj']:,.3f} | {e['biomass_tonnes']:,.3f} | {e['detections']:,} |" for e in evidence["events"]),
        "Each event is a run of consecutive days around one of the highest-energy days (at most 15 days either side) where daily energy stays above 5% of that peak. "
        "Peaks are at least 15 days apart and events are ranked by their total energy. An event can combine several fires inside the area, and its dates are not official ignition or containment dates."])


# ---- per-sensor record

def retrieve_sensor_breakdown(scope, req: ExplainSpikeRequest, max_years: int = 15) -> dict:
    """Yearly detections and calibrated energy density of each sensor channel in the cube."""
    import numpy as np

    if not scope.coordinates:
        return {"status": "missing_scope", "message": "Select an area to list its record by sensor."}
    r4, r7, _ = queries.get_hierarchical_h3_filter(scope.coordinates)
    area = queries.polygon_area_km2(scope.coordinates)
    first = max(2000, int(scope.start[:4])) if scope.start else 2000
    last = min(2026, int(scope.end[:4])) if scope.end else 2026
    daily = queries.fetch_aoi_aggregated_data(r4, r7, first, last, req.exclude_industrial_flaring, area, req.confidence_level).daily
    if not len(daily["epoch_day"]):
        return {"status": "empty", "message": "No satellite record is available for this area and these years. This does not prove that no fire occurred."}
    years = np.unique(daily["year"])
    rows = []
    for year in years[-max_years:].tolist():
        chosen = daily["year"] == year
        row = {"year": int(year), "modis_detections": int(daily["raw_modis_cnt"][chosen].sum()),
               "viirs_detections": int(daily["raw_viirs_cnt"][chosen].sum())}
        for name in ("terra", "aqua", "viirs"):
            values = daily[f"obs_{name}_fre"][chosen]
            burning = np.isfinite(values) & (values > 0)
            row[f"{name}_fire_days"] = int(burning.sum())
            row[f"{name}_mean_energy_density_mj_km2"] = float(values[burning].mean()) if burning.any() else None
        rows.append(row)
    return {"status": "ok", "data_source": duckdb_engine.data_source(), "years": rows,
            "years_omitted_before": int(years[0]) if len(years) > max_years else None,
            "modis_detections": sum(r["modis_detections"] for r in rows),
            "viirs_detections": sum(r["viirs_detections"] for r in rows),
            "first_viirs_year": next((r["year"] for r in rows if r["viirs_detections"] > 0), None),
            "industrial_sources_excluded": req.exclude_industrial_flaring}


def sensors_answer(scope, evidence: dict) -> str:
    if evidence["status"] != "ok":
        return evidence["message"]
    rows = evidence["years"]
    def cell(row, name):
        density = row[f"{name}_mean_energy_density_mj_km2"]
        return "n/a" if density is None else f"{density:,.4f} ({row[f'{name}_fire_days']} d)"
    viirs = (f" VIIRS detections begin in **{evidence['first_viirs_year']}** in this selection."
             if evidence["first_viirs_year"] else " No VIIRS detections fall in this selection.")
    return "\n\n".join([
        f"### Record by sensor\n\nBetween {rows[0]['year']} and {rows[-1]['year']}, **{scope.label}** has "
        f"**{evidence['modis_detections']:,} MODIS detections** (Terra and Aqua, 1 km) and "
        f"**{evidence['viirs_detections']:,} VIIRS detections** (375 m).{viirs} [5] [6]",
        "| Year | MODIS detections | VIIRS detections | Terra energy | Aqua energy | VIIRS energy |\n| --- | ---: | ---: | ---: | ---: | ---: |\n"
        + "\n".join(f"| {r['year']} | {r['modis_detections']:,} | {r['viirs_detections']:,} | {cell(r, 'terra')} | "
                    f"{cell(r, 'aqua')} | {cell(r, 'viirs')} |" for r in rows),
        "Energy columns give each sensor's calibrated mean daily energy density in MJ/km²/day over the days it recorded fire, "
        "with that number of days in brackets. A detection is a satellite thermal anomaly, not a count of distinct fires. "
        "VIIRS sees smaller and cooler fires than MODIS, so detection counts are not comparable between sensors or across the "
        "years before and after VIIRS; the calibrated energy columns are the comparable quantity. [2] [3]"
        + (f" Years before {rows[0]['year']} are omitted from this table." if evidence["years_omitted_before"] else "")])


# ---- thermal risk outlook

def retrieve_risk(scope, req: ExplainSpikeRequest) -> dict:
    from datetime import datetime, timezone
    from backend.api.routes import predict_risk
    from backend.api.schemas import RiskPredictionRequest

    if not scope.coordinates:
        return {"status": "missing_scope", "message": "Select an area to compute its thermal risk outlook."}
    origin = None
    if scope.end:
        origin = min(date.fromisoformat(scope.end), datetime.now(timezone.utc).date())
        origin = origin if 2001 <= origin.year <= 2026 else None
    try:
        response = predict_risk(RiskPredictionRequest(aoi=GeoJSONPolygon(coordinates=scope.coordinates), as_of_date=origin))
    except (HTTPException, duckdb_engine.CubeNotAvailableError, ValueError):
        return {"status": "unavailable", "message": "The thermal risk outlook could not be computed for this area."}
    body = json.loads(response.body)
    result = body.get("assessment")
    if not result:
        return {"status": "unavailable", "message": body.get("unavailable_reason") or "The thermal risk outlook is unavailable for this area."}
    intensity, observation = result.get("intensity") or {}, result.get("observation") or {}
    return {"status": "ok", "data_source": body["data_source"], "as_of_date": result["as_of_date"],
            "last_observation_date": result.get("last_observation_date"), "hazard_level": result["overall_hazard_level"],
            "horizons": [{"days": h["days"], "combined_risk_pct": h["combined_risk_pct"],
                          "vegetation_heat_pct": h["wildfire_prob_pct"], "persistent_source_pct": h["accident_prob_pct"]}
                         for h in result["horizons"]],
            "seasonal_baseline_pct": result.get("baseline_climatology_pct"),
            "multi_year_shift_pct": result.get("multi_year_trend_delta_pct"),
            "short_term_surge_pct": result.get("short_term_anomaly_delta_pct"),
            "times_seasonal_norm": result.get("anomaly_multiplier"),
            "intensity_regime": intensity.get("regime"), "intensity_guidance": intensity.get("guidance"),
            "intensity_mw": intensity.get("intensity_mw"), "spread_origin": intensity.get("contagion_origin"),
            "observation_status": observation.get("status"),
            "top_drivers": [{"driver": f["feature"], "effect_pct_points": f.get("signed_impact_pct"), "detail": f["description"]}
                            for f in result["top_risk_factors"][:4]],
            "meaning": "Probability that satellites record high non-persistent heat or a persistent-source excursion in the window. It is a thermal-event proxy, not a forecast of a confirmed ignition."}


def risk_answer(scope, evidence: dict) -> str:
    if evidence["status"] != "ok":
        return evidence["message"]
    def pct(value):
        return "n/a" if value is None else f"{value:,.1f}%"
    lines = [f"### Thermal risk outlook\n\nFrom **{evidence['as_of_date']}**, **{scope.label}** is rated **{evidence['hazard_level'] or 'unrated'}** "
             f"for the next 24 hours. [6]",
             "| Window | Combined risk | Vegetation heat | Persistent source |\n| --- | ---: | ---: | ---: |\n"
             + "\n".join(f"| {'24 hours' if h['days'] == 1 else str(h['days']) + ' days'} | {pct(h['combined_risk_pct'])} | "
                         f"{pct(h['vegetation_heat_pct'])} | {pct(h['persistent_source_pct'])} |" for h in evidence["horizons"])]
    if evidence["seasonal_baseline_pct"] is not None and evidence["short_term_surge_pct"] is not None:
        lines.append(f"The 24-hour figure combines a seasonal baseline of **{evidence['seasonal_baseline_pct']:,.2f}%**, a multi-year shift of "
                     f"**{evidence['multi_year_shift_pct']:+,.2f}** points and a short-term surge of **{evidence['short_term_surge_pct']:+,.2f}** points"
                     + (f" (**{evidence['times_seasonal_norm']:,.2f}×** the seasonal norm)." if evidence["times_seasonal_norm"] is not None else "."))
    if evidence["intensity_regime"]:
        lines.append(f"Current intensity regime: **{evidence['intensity_regime']}**"
                     + (f" ({evidence['intensity_mw']:,.1f} MW per detection)" if evidence["intensity_mw"] is not None else "")
                     + (f"; {evidence['spread_origin']}" if evidence["spread_origin"] else "") + "."
                     + (f" {evidence['intensity_guidance'].rstrip('.')}." if evidence["intensity_guidance"] else ""))
    if evidence["top_drivers"]:
        lines.append("Main drivers:\n\n" + "\n".join(f"- {d['detail']}" for d in evidence["top_drivers"]))
    lines.append(evidence["meaning"] + (f" Observation status: {evidence['observation_status']}." if evidence["observation_status"] else ""))
    return "\n\n".join(lines)
