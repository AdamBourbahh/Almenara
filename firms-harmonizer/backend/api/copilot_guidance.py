"""Deterministic scope and scientific definitions that require no network services."""
import re
from backend.api.copilot_research import normalize


def guidance(question: str):
    q = normalize(question).strip(' ¿?!.')
    if re.fullmatch(r'hi|hello|hey|hola|buenas|ola|help|ayuda|what can you do|que puedes hacer', q):
        return ('COPILOT_HELP', 'I can explain a reported fire, query local detections and energy in GJ, compare years within one area, and explain MODIS/VIIRS, uncertainty and reconstruction. Select an area and date or name a place and period. For ignition causes I distinguish sourced reports from satellite measurements.', [])
    if re.search(r'\b(pizza|horoscope|bitcoin|football|capital of france|write a python program)\b', q):
        return ('OUT_OF_SCOPE', 'I focus on fire observations, reported incidents and the science behind this dashboard. Ask about a fire, a selected area/date, energy, detections or satellite methods.', [])
    if re.search(r'co2|pm2[.,]?5|hectares|hectareas|burned area|area quemada', q) and re.search(r'how (many|much)|cuant|quant|total', q) and not re.search(r'\b(gj|energy|energia|fre)\b', q):
        return ('DATA_NOT_AVAILABLE', 'This chat endpoint does not compute a verified total of burned hectares, CO2 or PM2.5 emissions. Detections and instantaneous MW cannot substitute for those measurements. I can query integrated energy and model-derived biomass, or explain the additional burned-area and emission-factor data needed. [1] [6]', ['[1]', '[6]'])
    if not re.search(r'what (?:is|are|does)|que (?:es|son|significa)|meaning|difference|diferencia|explain|explica|define', q):
        return None
    if re.search(r'\b(gj|gigajoule|gigajulios)\b', q):
        return ('SCIENTIFIC_EXPLANATION', 'A gigajoule (GJ) is 1,000 megajoules (MJ), or one billion joules. Here total energy is daily FRE density (MJ/km²) integrated over represented H3 area and the selected days, divided by 1,000. Summing instantaneous FRP values in MW does not produce GJ. [1] [6]', ['[1]', '[6]'])
    if re.search(r'\b(frp|fre|mw)\b', q):
        return ('SCIENTIFIC_EXPLANATION', 'FRP is instantaneous fire radiative power in MW (one MJ per second). FRE is time-integrated energy in MJ; the dashboard reports daily density in MJ/km². Satellite power samples need a documented integration method before energy or biomass can be estimated. [1]', ['[1]'])
    if re.search(r'pm2[.,]?5|co2|emissions|emisiones|burned area|hectareas|area quemada', q):
        return ('SCIENTIFIC_EXPLANATION', 'Satellite detection counts do not measure burned hectares or smoke emissions. Biomass estimates use integrated energy and a combustion factor; emissions also require documented emission factors. PM2.5 totals and burned-area validation can be unavailable (null) in this application; I will not invent them from FRP or detection counts. [1] [6]', ['[1]', '[6]'])
    if re.search(r'\bh3\b|hexagon|hexagono', q):
        return ('SCIENTIFIC_EXPLANATION', 'H3 indexes locations with hierarchical hexagonal cells. This application queries resolution 7 cells and their unique resolution 4 parents. A selected hexagon is a spatial query unit, not an individual fire or its perimeter. Cell areas vary; energy totals use represented cell area. [6]', ['[6]'])
    if re.search(r'confidence|uncertainty|incertidumbre|intervalo', q):
        return ('SCIENTIFIC_EXPLANATION', 'The 95% interval describes model uncertainty around reconstructed daily energy. It does not mean a 95% probability that a named fire occurred, and it does not identify ignition cause. Wider intervals indicate less certainty in the estimated state. [4]', ['[4]'])
    return None
