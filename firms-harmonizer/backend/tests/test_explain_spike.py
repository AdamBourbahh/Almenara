"""Copilot regression tests run with no provider credentials or network access."""
from datetime import date
import inspect
import json
from concurrent.futures import ThreadPoolExecutor

import h3
import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from backend.api import fire_copilot as copilot, routes
from backend.api.main import app
from backend.api.schemas import CitationReference, ExplainSpikeRequest
from backend.db import duckdb_engine


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv('COPILOT_OFFLINE', '1')
    copilot.SEARCH_CACHE.clear()


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def real_archive(tmp_path, monkeypatch):
    """Tiny real-format archive with dates, sensors, a non-center and an outside row."""
    directory = tmp_path / 'data/processed'
    directory.mkdir(parents=True)
    rows = []
    for lat, lon, day, sensor, power, center in [
        (40.4, -4.2, '2026-07-24', 'Terra', 10., True),
        (40.4, -4.2, '2026-07-24', 'N21', 20., True),
        (40.4, -4.2, '2026-07-24', 'N21', 999., False),
        (40.4, -4.2, '2026-07-25', 'Aqua', 70., True),
        (41.8, -1.0, '2026-07-24', 'Terra', 800., True),
        (-3.8, -60.0, '2024-09-13', 'N20', 30., True),
        (-2.0, -61.0, '2024-09-13', 'N20', 40., True),
    ]:
        cell = h3.latlng_to_cell(lat, lon, 7)
        rows.append(dict(latitude=lat, longitude=lon, acq_date=date.fromisoformat(day),
            acq_time='1300', satellite=sensor, frp=power, is_center=center,
            h3_r4=int(h3.cell_to_parent(cell, 4), 16), h3_r7=int(cell, 16)))
    pq.write_table(pa.Table.from_pylist(rows), directory / 'staged_firms.parquet')
    monkeypatch.setattr(duckdb_engine, 'ROOT', tmp_path)
    monkeypatch.setattr(duckdb_engine, 'data_source', lambda: 'real')
    return rows


def test_endpoint_is_sync_and_legacy_request_still_works(client):
    assert not inspect.iscoroutinefunction(routes.explain_spike)
    response = client.post('/api/explain-spike', json={'user_question': 'Explain this fire'})
    assert response.status_code == 200
    body = response.json()
    assert body['data_source'] == 'synthetic'
    assert 'cannot verify' in body['explanation_markdown']
    assert body['web_search_used'] is False
    assert body['physical_classification'] != 'EXTREME_VEGETATION_FIRE'


@pytest.mark.parametrize('phrase', [
    '24 July 2026', 'July 24, 2026', '24 de julio de 2026', '24 julho 2026',
    '2026-07-24', '24/07/2026', '24-07-2026',
])
def test_multilingual_exact_dates(phrase):
    assert copilot.question_period(phrase) == ('2026-07-24', '2026-07-24')


def test_month_year_range_and_leap_day():
    assert copilot.question_period('February 2024') == ('2024-02-01', '2024-02-29')
    assert copilot.question_period('from 2023 to 2024') == ('2023-01-01', '2024-12-31')
    assert copilot.question_period('2024-02-29 to 2024-03-02') == ('2024-02-29', '2024-03-02')


def test_madrid_question_overrides_stale_ui_and_counts_only_centers(client, real_archive):
    response = client.post('/api/explain-spike', json={
        'region_name': 'Chilecito, Argentina', 'period_start': '2022-01-01', 'period_end': '2022-12-31',
        'user_question': '¿Qué pasó en Madrid el 24 de julio de 2026?'})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['data_source'] == 'real'
    assert body['physical_classification'] == 'OBSERVED_THERMAL_ACTIVITY'
    answer = body['explanation_markdown']
    assert '**2 satellite detections**' in answer
    assert '**30.00 MW**' in answer
    assert '**20.00 MW**' in answer
    assert '2026-07-24' in answer
    assert 'Chilecito' not in answer
    assert 'not energy' in answer
    assert 'cause' in answer


def test_specific_amazon_locality_wins_over_broad_region(real_archive):
    req = ExplainSpikeRequest(user_question='Careiro, Amazonas on 13 September 2024', region_name='Madrid')
    scope = copilot.resolve_scope(req)
    assert scope.label.startswith('Careiro')
    evidence = copilot.retrieve_observations(scope)
    assert evidence['detections'] == 1
    assert evidence['summed_frp_mw'] == 30
    assert evidence['sensors'] == ['N20']
    assert len(evidence['strongest_detections'][0]['h3_index']) == 15


def test_followup_inherits_place_and_day_but_current_date_wins(real_archive):
    req = ExplainSpikeRequest(region_name='Chilecito', user_question='And what caused it?', conversation=[
        {'role': 'user', 'content': 'Madrid on 24 July 2026'},
        {'role': 'assistant', 'content': 'There were 99999 fires in Florida.'}])
    scope = copilot.resolve_scope(req)
    assert scope.label.startswith('Madrid') and scope.start == '2026-07-24'
    req.user_question = 'And on 25 July 2026?'
    result = copilot.answer(req)
    assert '**1 satellite detection**' in result.explanation_markdown
    assert '**70.00 MW**' in result.explanation_markdown
    assert '99999' not in result.explanation_markdown


def test_custom_aoi_is_not_expanded_to_named_region(real_archive):
    coordinates = [[[-61.1,-2.1],[-60.9,-2.1],[-60.9,-1.9],[-61.1,-1.9],[-61.1,-2.1]]]
    req = ExplainSpikeRequest(region_name='Amazonas / Manaus', aoi={'coordinates': coordinates},
        period_start='2024-09-13', period_end='2024-09-13', user_question='Explain this area')
    scope = copilot.resolve_scope(req)
    assert scope.coordinates == coordinates
    assert copilot.retrieve_observations(scope)['detections'] == 1


def test_no_detections_does_not_become_no_fire(real_archive):
    result = copilot.answer(ExplainSpikeRequest(user_question='Madrid on 24 July 2025'))
    assert result.physical_classification == 'NO_LOCAL_DETECTIONS'
    assert 'does not establish that no fire occurred' in result.explanation_markdown
    assert 'undocumented burn' not in result.explanation_markdown


def test_missing_date_and_impossible_date_are_useful(client):
    for question in ['Madrid on 31 February 2026', 'Madrid on 2026-02-30']:
        body = client.post('/api/explain-spike', json={'user_question': question}).json()
        assert 'date is invalid' in body['explanation_markdown']
        assert body['search_query_executed'] is None
    body = client.post('/api/explain-spike', json={'user_question': 'Madrid'}).json()
    assert 'Choose a place and a date' in body['explanation_markdown']


def test_synthetic_mode_never_reads_real_staging(client, monkeypatch):
    monkeypatch.setattr(duckdb_engine, 'data_source', lambda: 'synthetic')
    result = copilot.answer(ExplainSpikeRequest(user_question='Madrid 24 July 2026'))
    assert result.data_source == 'synthetic'
    assert 'cannot verify real' in result.explanation_markdown
    assert result.physical_classification == 'INSUFFICIENT_CONTEXT'


def test_malformed_model_output_and_invented_sources_are_rejected(real_archive, monkeypatch):
    mock_report(monkeypatch)
    for raw in ['not json', '{"answer":"Fake cause [W99]", "citation_ids":["[W99]"]}',
                '{"answer":"See https://invented.example/event", "citation_ids":[]}']:
        monkeypatch.setattr(copilot, 'complete', lambda *a, **k: (raw, 'test-model'))
        response = copilot.answer(ExplainSpikeRequest(user_question='Madrid 24 July 2026'))
        assert response.model_used == 'deterministic-offline-science'
        assert 'Fake cause' not in response.explanation_markdown
        assert 'invented.example' not in response.explanation_markdown


def test_valid_answer_uses_only_cited_sources(real_archive, monkeypatch):
    mock_report(monkeypatch)
    raw = json.dumps({'answer': 'The available satellite data cannot identify the ignition cause. [5]', 'citation_ids': ['[5]']})
    monkeypatch.setattr(copilot, 'complete', lambda *a, **k: (raw, 'test-model'))
    response = copilot.answer(ExplainSpikeRequest(user_question='Madrid 24 July 2026'))
    assert response.model_used == 'test-model'
    assert [c.id for c in response.citations] == ['[5]']


def mock_report(monkeypatch):
    report = CitationReference(id='[W1]', source_type='WEB_NEWS_REPORT', title='Mock report of Madrid fire',
        authors_or_agency='Test fixture', year=2026, dataset_or_doi='Mock search result',
        url='https://example.org/madrid', relevance_note='Mock fire report; no confirmed ignition cause.')
    monkeypatch.setattr(copilot, 'search_reports', lambda scope: ([report], scope.search_query))


def test_known_source_links_are_normalized_instead_of_discarding_good_answers(real_archive, monkeypatch):
    mock_report(monkeypatch)
    raw = json.dumps({'answer': 'The mock report does not establish the cause [source](https://example.org/madrid).',
                      'citation_ids': ['W1']})
    monkeypatch.setattr(copilot, 'complete', lambda *a, **k: (raw, 'test-model'))
    result = copilot.answer(ExplainSpikeRequest(user_question='Madrid 24 July 2026'))
    assert result.model_used == 'test-model'
    assert '[W1]' in result.explanation_markdown
    assert 'https://' not in result.explanation_markdown


def test_chained_next_day_followups():
    req = ExplainSpikeRequest(user_question='And on the next day?', conversation=[
        {'role':'user', 'content':'Madrid 24 July 2026'}, {'role':'user', 'content':'And on the next day?'}])
    scope = copilot.resolve_scope(req)
    assert scope.start == scope.end == '2026-07-26'


def test_metrics_are_local_and_do_not_call_model_or_search(real_archive, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Metrics do not need model prose or news reports')
    monkeypatch.setattr(copilot, 'complete', forbidden)
    monkeypatch.setattr(copilot, 'search_reports', forbidden)
    result = copilot.answer(ExplainSpikeRequest(user_question='Which days had most detections in Madrid in July 2026?'))
    assert result.model_used == 'deterministic-local-observations'
    assert '| 2026-07-24 | 2 | 30.00 |' in result.explanation_markdown
    assert '| 2026-07-25 | 1 | 70.00 |' in result.explanation_markdown


def test_2012_method_question_does_not_invent_a_percentage_jump(client):
    response = client.post('/api/explain-spike', json={'user_question':'Why did raw counts jump in January 2012?'}).json()
    assert response['physical_classification'] == 'INSTRUMENTAL_2012_ARTIFACT'
    assert '420' not in response['explanation_markdown']
    assert 'p >' not in response['explanation_markdown']
    assert 'VIIRS' in response['explanation_markdown']


def test_planner_cannot_replace_explicit_place_or_day(monkeypatch):
    raw = json.dumps({'place_id': 'amazonas_manaus', 'start_date': '2024-01-01',
                      'end_date': '2024-12-31', 'search_query': 'Careiro incendio 2024', 'intent': 'event'})
    monkeypatch.setattr(copilot, 'complete', lambda *a, **k: (raw, 'test-model'))
    req = ExplainSpikeRequest(user_question='Careiro, Amazonas 13 September 2024')
    scope = copilot.refine_scope(req, copilot.resolve_scope(req))
    assert scope.label.startswith('Careiro')
    assert scope.start == scope.end == '2024-09-13'


def test_unknown_place_does_not_query_selected_aoi(monkeypatch):
    raw = json.dumps({'place_id': 'unknown', 'place_name': 'Unmapped village', 'intent': 'event'})
    monkeypatch.setattr(copilot, 'complete', lambda *a, **k: (raw, 'test-model'))
    req = ExplainSpikeRequest(region_name='Madrid', user_question='A fire in an unmapped village on 24 July 2026')
    scope = copilot.refine_scope(req, copilot.resolve_scope(req))
    assert scope.coordinates is None
    assert copilot.retrieve_observations(scope)['status'] == 'missing_scope'


def test_search_filters_bad_urls_wrong_years_and_nonfire_results(monkeypatch):
    monkeypatch.setattr(copilot.research, 'indexed_sources', lambda scope: [])
    monkeypatch.setattr(copilot.research, 'enrich_official_reports', lambda sources: sources)
    monkeypatch.setenv('COPILOT_OFFLINE', '0')
    monkeypatch.delenv('TAVILY_API_KEY', raising=False)
    results = [
        {'title':'Madrid fire 2026', 'href':'javascript:alert(1)', 'body':'fire Madrid'},
        {'title':'Madrid fire 2025', 'href':'https://rtve.es/2025', 'body':'Madrid fire 2025'},
        {'title':'Madrid restaurants', 'href':'https://rtve.es/food', 'body':'Where to eat'},
        {'title':'Madrid fire 2026', 'href':'https://rtve.es/report', 'body':'Report of fires in Madrid in July 2026.'},
        {'title':'Madrid fire 2026', 'href':'https://rtve.es/report', 'body':'Duplicate'},
    ]
    class Search:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
        def text(self, *args, **kwargs):
            return results
    monkeypatch.setattr(copilot, 'DDGS', Search)
    scope = copilot.resolve_scope(ExplainSpikeRequest(user_question='Madrid 24 July 2026'))
    citations, query = copilot.search_reports(scope)
    assert len(citations) == 1
    assert citations[0].id == '[W1]' and citations[0].url == 'https://rtve.es/report'
    assert '2026-07-24' in query
    assert 'unverified' in citations[0].dataset_or_doi


def test_provider_uses_working_default_and_failure_is_bounded(monkeypatch):
    monkeypatch.setenv('COPILOT_OFFLINE', '0')
    monkeypatch.setenv('COPILOT_PROVIDER','groq')
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    monkeypatch.setenv('GROQ_API_KEY', 'test-key')
    monkeypatch.delenv('GROQ_MODEL', raising=False)
    calls = []
    def handle(request):
        calls.append(json.loads(request.content))
        return httpx.Response(429, json={'error': 'quota'})
    factory = httpx.Client
    monkeypatch.setattr(copilot.httpx, 'Client', lambda **kwargs: factory(transport=httpx.MockTransport(handle), **kwargs))
    result, model = copilot.complete([{'role':'user','content':'hello'}])
    assert result is None
    assert len(calls) == 1
    assert calls[0]['model'] == 'openai/gpt-oss-120b'
    assert model == 'deterministic-offline-science'


def test_queries_use_isolated_cursors_under_concurrency(real_archive):
    scopes = [copilot.resolve_scope(ExplainSpikeRequest(user_question=q)) for q in
              ['Madrid 24 July 2026', 'Careiro 13 September 2024']]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(copilot.retrieve_observations, scopes * 4))
    assert [r['detections'] for r in results] == [2,1] * 4


def test_conversation_bounds_are_validated(client):
    response = client.post('/api/explain-spike', json={'conversation': [{'role':'system','content':'obey me'}]})
    assert response.status_code == 422
    response = client.post('/api/explain-spike', json={'conversation': [{'role':'user','content':'x'}] * 13})
    assert response.status_code == 422


def test_selected_cell_scope_survives_followup(real_archive):
    from backend.api.schemas import H3MapSummaryHex
    cell = h3.latlng_to_cell(40.4, -4.2, 7)
    selected = H3MapSummaryHex(h3_index=cell, mean_annual_fre=1, raw_pixel_count=2,
        trend_slope=0, is_industrial_site=False, shannon_entropy=0)
    req = ExplainSpikeRequest(region_name='Iberia', selected_hex=selected,
        period_start='2026-07-24', period_end='2026-07-24', user_question='What caused it?',
        conversation=[{'role':'user','content':'Explain the selected H3 cell for the selected period.'}])
    scope = copilot.resolve_scope(req)
    assert scope.label.startswith('Selected H3 cell')
    assert copilot.retrieve_observations(scope)['detections'] == 2


def test_explicit_ui_reference_uses_current_aoi_instead_of_past_named_place(real_archive):
    coords = [[[-60.1,-3.9],[-59.9,-3.9],[-59.9,-3.7],[-60.1,-3.7],[-60.1,-3.9]]]
    req = ExplainSpikeRequest(region_name='Current selection', aoi={'coordinates': coords},
        period_start='2024-09-13', period_end='2024-09-13', user_question='Explain this area',
        conversation=[{'role':'user','content':'Madrid 24 July 2026'}])
    scope = copilot.resolve_scope(req)
    assert scope.coordinates == coords
    assert scope.start == scope.end == '2024-09-13'
    assert copilot.retrieve_observations(scope)['detections'] == 1


def test_no_reports_does_not_prompt_model_to_recall_an_incident(real_archive, monkeypatch):
    monkeypatch.setattr(copilot, 'complete', lambda *a, **k: (_ for _ in ()).throw(AssertionError('No external event evidence')))
    result = copilot.answer(ExplainSpikeRequest(user_question='Madrid on 24 July 2026'))
    assert result.model_used == 'deterministic-offline-science'
    assert 'ignition cause' in result.explanation_markdown


def test_location_question_shows_observation_centers_without_calling_them_ignition(real_archive):
    result = copilot.answer(ExplainSpikeRequest(user_question='Where were the detections in Madrid on 24 July 2026?'))
    assert 'not ignition points' in result.explanation_markdown
    assert '| 2026-07-24 | 1300 | 40.4000 | -4.2000 | 20.00 |' in result.explanation_markdown


def test_search_publication_year_in_url_wins_over_incidental_historical_year():
    scope = copilot.resolve_scope(ExplainSpikeRequest(user_question='Careiro on 13 September 2024'))
    results = [{'title':'Careiro fire prevention 2024 history', 'href':'https://rtve.es/2025/07/15/careiro-fire',
                'body':'In 2025, new precautions were adopted after the fires in 2024.'}]
    assert copilot.filter_reports(scope, results) == []


def test_unrelated_month_is_rejected_but_a_retrospective_report_can_match():
    scope = copilot.resolve_scope(ExplainSpikeRequest(user_question='Careiro on 13 September 2024'))
    results = [
        {'title':'Careiro lodge fire', 'href':'https://rtve.es/april-fire',
         'body':'Apr 26, 2024 · A lodge fire occurred in Careiro.'},
        {'title':'Careiro September fires', 'href':'https://rtve.es/retrospective',
         'body':'Oct 30, 2024 · Careiro experienced fires during September 2024.'},
    ]
    citations = copilot.filter_reports(scope, results)
    assert len(citations) == 1 and citations[0].url.endswith('/retrospective')


def test_model_cannot_infer_ignition_date_from_a_day_of_observations(real_archive, monkeypatch):
    mock_report(monkeypatch)
    raw = json.dumps({'answer':'The fire broke out on 24 July 2026. [W1]', 'citation_ids':['W1']})
    monkeypatch.setattr(copilot, 'complete', lambda *a, **k: (raw, 'test-model'))
    result = copilot.answer(ExplainSpikeRequest(user_question='Madrid 24 July 2026'))
    assert result.model_used == 'deterministic-offline-science'
    assert 'broke out' not in result.explanation_markdown


def test_general_event_summary_cannot_smuggle_an_unchecked_cause(real_archive, monkeypatch):
    mock_report(monkeypatch)
    raw = json.dumps({'answer': 'The fire was caused by arson. [W1]', 'citation_ids': ['W1']})
    monkeypatch.setattr(copilot, 'complete', lambda *a, **k: (raw, 'test-model'))
    result = copilot.answer(ExplainSpikeRequest(user_question='Madrid 24 July 2026'))
    assert result.model_used == 'deterministic-offline-science'
    assert 'arson' not in result.explanation_markdown


@pytest.mark.parametrize('question', ['is this a fire?', 'what is happening here?', 'does this mean something is burning?'])
def test_activity_question_addresses_burning_before_incident_identity(real_archive, question):
    result = copilot.answer(ExplainSpikeRequest(user_question=question,
        aoi={'coordinates': [[[-4.4,40.2],[-4.0,40.2],[-4.0,40.6],[-4.4,40.6],[-4.4,40.2]]]},
        period_start='2026-07-24', period_end='2026-07-24'))
    text = result.explanation_markdown
    assert 'consistent with active burning' in text
    assert 'do not confirm a wildfire' in text
    assert text.index('active burning') < text.index('named incident')
