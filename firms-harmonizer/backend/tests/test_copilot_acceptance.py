"""Behavioral acceptance matrix: language variants, dates, evidence and provider outages."""
import pytest
from backend.api import fire_copilot as c
from backend.api.schemas import ExplainSpikeRequest
from backend.tests.test_explain_spike import real_archive


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv('COPILOT_OFFLINE', '1')


@pytest.mark.parametrize('place', ['Madrid', 'madrid', 'MADRID'])
@pytest.mark.parametrize('phrase', ['How many detections in {p} on 2026-07-24?',
    '¿Cuántas detecciones hubo en {p} el 24 de julio de 2026?',
    'Quantas deteccoes em {p} em 24 julho 2026?',
    'Number of fires in {p} on July 24, 2026',
    'Total FRP in {p} on 24/07/2026',
    'Which detections were strongest in {p} on 2026-07-24?'])
def test_numeric_paraphrases_match_accepted_centers_not_fire_events(real_archive, monkeypatch, place, phrase):
    def forbidden(*a, **k):
        raise AssertionError('Numerical evidence must not depend on a model or web search')
    monkeypatch.setattr(c, 'complete', forbidden)
    monkeypatch.setattr(c, 'search_reports', forbidden)
    result=c.answer(ExplainSpikeRequest(user_question=phrase.format(p=place)))
    assert '**2 satellite detections**' in result.explanation_markdown
    assert '**30.00 MW**' in result.explanation_markdown
    assert 'number of fires' in result.explanation_markdown
    assert result.map_context.period_start == result.map_context.period_end == '2026-07-24'


@pytest.mark.parametrize('q,expected', [
    ('What is GJ?', '1,000'), ('¿Qué significa GJ?', '1,000'), ('Define gigajoule', '1,000'),
    ('What is FRP?', 'instantaneous'), ('What is FRE?', 'integrated'), ('Explain MW', 'second'),
    ('What is H3?', 'resolution 7'), ('¿Qué es un hexágono?', 'not an individual fire'),
    ('Explain uncertainty', '95%'), ('¿Qué significa incertidumbre?', 'estimated state'),
    ('Explain PM2.5 emissions', 'unavailable'), ('¿Qué son las emisiones?', 'not invent'),
    ('What is burned area?', 'hectares'), ('Hola', 'Select an area'),
    ('What can you do?', 'explain a reported fire'), ('help', 'MODIS'),
    ('Write a python program', 'focus on fire'), ('bitcoin', 'focus on fire')])
def test_help_and_scientific_definitions_are_useful_without_any_providers(monkeypatch,q,expected):
    monkeypatch.setattr(c.duckdb_engine,'data_source',lambda:'real')
    result=c.answer(ExplainSpikeRequest(user_question=q))
    assert expected.lower() in result.explanation_markdown.lower()
    assert result.web_search_used is False


@pytest.mark.parametrize('q', ['Why did the Madrid fire happen on 2026-07-24?',
    '¿Por qué sucedió ese incendio en Madrid el 24 de julio de 2026?',
    'Qual a causa do incendio em Madrid em 24 julho 2026?'])
def test_causal_outage_does_not_become_invented_cause_or_numeric_dump(real_archive,q):
    result=c.answer(ExplainSpikeRequest(user_question=q))
    assert 'not verified' in result.explanation_markdown
    assert 'What the local data show' in result.explanation_markdown
    assert '| Date' not in result.explanation_markdown
    assert 'Summed instantaneous' not in result.explanation_markdown


@pytest.mark.parametrize('day', ['2026-02-30','2026-13-01','31 February 2026','2026-00-01'])
def test_invalid_dates_do_not_trigger_evidence_search(real_archive,monkeypatch,day):
    def forbidden(*a,**k):
        raise AssertionError('Invalid scope must not query external evidence')
    monkeypatch.setattr(c,'search_reports',forbidden)
    result=c.answer(ExplainSpikeRequest(user_question=f'How many detections in Madrid on {day}?'))
    assert 'invalid' in result.explanation_markdown
    assert result.map_context is None


@pytest.mark.parametrize('q',['How much PM2.5 in Madrid in 2026?','Total CO2 emissions?','¿Cuántas hectáreas quemadas?'])
def test_unavailable_metrics_are_not_answered_with_unrelated_counts(monkeypatch,q):
    monkeypatch.setattr(c.duckdb_engine,'data_source',lambda:'real')
    result=c.answer(ExplainSpikeRequest(user_question=q))
    assert result.physical_classification=='DATA_NOT_AVAILABLE'
    assert 'satellite detections**' not in result.explanation_markdown
