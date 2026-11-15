"""Deterministic domain relevance gate, evaluated before any model, database or web call.

The gate is a lexical screen, not a classifier: it refuses on positive evidence of an
unrelated or instruction-override request and on longer questions carrying no fire, land,
satellite or map-context signal. Short follow-ups stay answerable.
"""
from __future__ import annotations

import re
import unicodedata

from backend.api.schemas import ExplainSpikeRequest, ExplainSpikeResponse

MODEL_NAME = 'deterministic-domain-guardrail'
INJECTION = re.compile(
    r'\b(ignore|disregard|forget|override|bypass|ignora|olvida|omite)\b.{0,40}\b(instruction|instruccion|instrucoes|rule|regla|prompt|guideline|restriction)'
    r'|system prompt|developer mode|jailbreak|\bdan mode\b|you are now\b|from now on you|pretend (to be|you are)'
    r'|\b(reveal|show|print|repeat|leak)\b.{0,30}\b(prompt|instructions|system message)|new instructions:')
TASK = re.compile(
    r'\b(write|generate|create|compose|code|program|implement|debug|fix|refactor|escribe|genera|crea|programa)\b.{0,40}'
    r'\b(script|code|codigo|program|programa|function|funcion|class|app|website|essay|ensayo|poem|poema|song|cancion|story|cuento|email|letter|carta|homework|deberes|joke|chiste)\b'
    r'|\b(python|javascript|typescript|java|rust|golang|html|css|regex)\b.{0,25}\b(script|code|program|function|snippet|tutorial)\b')
UNRELATED = re.compile(
    r'\b(bitcoin|crypto\w*|ethereum|dogecoin|stock market|stock price|share price|forex|mortgage|hipoteca|lottery|loteria'
    r'|football|soccer|futbol|basketball|baloncesto|nba|nfl|tennis|tenis|world cup|mundial|champions league|olympic\w*'
    r'|celebrit\w*|famos[oa]s?|actor|actress|actriz|singer|cantante|movie|pelicula|netflix|lyrics|horoscope|horoscopo|zodiac'
    r'|recipe|receta|pizza|lasagna|cocktail|dating|joke|chiste|riddle|adivinanza|trivia|homework|deberes'
    r'|election|elecciones|president|presidente|prime minister|parliament|parlamento'
    r'|medicine|medicina|medication|symptom\w*|sintoma\w*|diagnos\w*|dosage|headache|pregnan\w*'
    r'|capital of|translate|traduce|traducir)\b')
STRONG = re.compile(
    r'fire|incend|burn|quema|queimad|blaze|smoke|humo|fumaca|biomass|biomasa|fuel|combust|emission|emision|pm2|\bco2\b|carbon'
    r'|forest|bosque|floresta|woodland|vegetat|vegetac|biome|bioma|igbp|drought|sequia|\bseca\b|modis|viirs|firms|mcd64|mcd12'
    r'|satellite|satelite|sensor|hotspot|thermal|termic|\bfrp\b|\bfre\b|flaring|\bflare|kalman|phenolog|fenolog|hectare|hectarea'
    r'|land (management|use|cover)|grassland|savanna|sabana|peat|crop|agricultur|agricol|pasture|deforest|ignition|ignicion'
    r'|prescribed|suppression|evacuat|heat ?wave|ola de calor|\bwind|viento|humidity|humedad|temperatur|climat|\bclima\b'
    r'|season|temporada|\bestacion\b')
WEAK = re.compile(
    r'\b(gj|mj|mw|gigajoules?|megajoules?|energy|energia|detections?|deteccion\w*|deteccoes|heat|calor|industrial|entropy|entropia'
    r'|peak|pico|risk|riesgo|hazard|forecast|pronostico|gaps?|outages?|clouds?|nubes?|uncertainty|incertidumbre|confidence'
    r'|h3|hexagons?|hexagono|area|zona|region|map|mapa|aoi|cells?|celda|dashboard|data|datos|dataset|cube|cubo|measures?|metrics?'
    r'|trend|tendencia|years?|months?|days?|period|periodo|date|fecha|happen\w*|caus\w*|spread\w*|start\w*|began|events?|evento'
    r'|incident\w*|this|that|these|those|here|there|selected|current|esta|este|esto|estos|estas|aqui|ese|esa|eso'
    r'|hi|hello|hey|hola|buenas|ola|help|ayuda|thanks|thank|gracias)\b|what can you do|que puedes hacer|\b(19|20)\d{2}\b')
GENERIC_REGIONS = {'unknown region', 'no attached location', ''}


def _normalized(text: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', text.lower()) if not unicodedata.combining(c))


def assess(question: str) -> str | None:
    """Return the refusal reason, or None when the question may proceed."""
    q = _normalized(question).strip()
    if not q:
        return None
    if INJECTION.search(q):
        return 'instruction_override'
    if TASK.search(q):
        return 'unrelated_task'
    strong = bool(STRONG.search(q))
    if UNRELATED.search(q) and not strong:
        return 'unrelated_topic'
    if strong or WEAK.search(q):
        return None
    # A short question without any signal is treated as a follow-up to the conversation.
    return 'no_domain_signal' if len(re.findall(r'[^\W_]+', q)) > 4 else None


def suggestions(req: ExplainSpikeRequest) -> list[str]:
    """Starter questions for the attached region; no database or network access."""
    label = (req.region_name or '').strip()
    place = 'this area' if label.lower() in GENERIC_REGIONS or label.lower().startswith('selected area at') else label[:80]
    year = req.period_end[:4] if req.period_end else '2025'
    return [f'How much fire energy and dry biomass was consumed in {place} during {year}?',
            f'How has the peak of the fire season shifted in {place} over the satellite record?',
            f'Are the persistent heat detections in {place} vegetation fires or industrial gas flaring?']


def refusal(req: ExplainSpikeRequest, data_source: str) -> ExplainSpikeResponse:
    prompts = suggestions(req)
    text = ('I am a specialized Wildfire & Land Management Copilot. I focus on fire activity, burning seasons, '
            'biomass and smoke estimates, land and forestry questions, and the satellite record behind this dashboard, '
            'so I cannot help with that request.\n\nQuestions I can answer here:\n\n' + '\n'.join(f'- {p}' for p in prompts))
    return ExplainSpikeResponse(physical_classification='OFF_TOPIC_REFUSAL', explanation_markdown=text,
        model_used=MODEL_NAME, data_source=data_source, guardrail_triggered=True,
        suggested_prompts=prompts, evidence_sources=['guardrail'])


def check(req: ExplainSpikeRequest, data_source: str) -> ExplainSpikeResponse | None:
    return refusal(req, data_source) if assess(req.user_question) else None
