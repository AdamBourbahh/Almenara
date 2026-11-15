"""Google transport selection, tool continuity and bounded failure behavior."""
import json

import httpx
import pytest

from backend.api import copilot_agent as agent, copilot_providers as providers
from backend.api.schemas import ExplainSpikeRequest


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setenv('COPILOT_PROVIDER', 'gemini')
    monkeypatch.setenv('GEMINI_API_KEY', 'google-test-secret')
    monkeypatch.setenv('GEMINI_MODEL', 'gemini-3.8-flash')
    monkeypatch.setenv('GROQ_API_KEY', 'other-provider-secret')
    monkeypatch.setenv('COPILOT_OFFLINE', '0')


def intercept(monkeypatch, transport):
    factory = httpx.Client
    monkeypatch.setattr(providers.httpx, 'Client', lambda **kwargs: factory(transport=httpx.MockTransport(transport), **kwargs))


def test_agent_executes_google_function_call_and_reports_actual_provider(gemini, monkeypatch):
    calls = []
    def transport(request):
        assert request.url.host == 'generativelanguage.googleapis.com'
        assert request.headers['Authorization'] == 'Bearer google-test-secret'
        body = json.loads(request.content)
        assert body['model'] == 'gemini-3.8-flash'
        calls.append(body)
        if len(calls) == 1:
            message = {'content': None, 'tool_calls': [{'id': 'google-call', 'type': 'function', 'function': {
                'name': 'query_observations', 'arguments': '{}'}, 'extra_content': {'google': {'thought_signature': 'opaque'}}}]}
        else:
            assert body['messages'][-1]['role'] == 'tool'
            assert body['messages'][-1]['tool_call_id'] == 'google-call'
            assert body['messages'][-2]['tool_calls'][0]['extra_content']['google']['thought_signature'] == 'opaque'
            message = {'content': 'The observations are consistent with active burning. [5]'}
        return httpx.Response(200, json={'choices': [{'finish_reason': 'tool_calls' if len(calls) == 1 else 'stop', 'message': message}]})
    intercept(monkeypatch, transport)
    monkeypatch.setattr(agent.duckdb_engine, 'data_source', lambda: 'real')
    monkeypatch.setattr(agent.local, 'retrieve_observations', lambda scope: {'status': 'ok', 'detections': 2})
    monkeypatch.setattr(agent.local, 'local_answer', lambda *args: 'Verified observations: 2 detections. [5]')
    result = agent.answer(ExplainSpikeRequest(user_question='is this a fire?', period_start='2026-07-23', period_end='2026-07-23'))
    assert result.model_used == 'gemini-agent/gemini-3.8-flash'
    assert 'active burning' in result.explanation_markdown
    assert '2 detections' in result.explanation_markdown
    assert len(calls) == 2


@pytest.mark.parametrize('status', [401, 403, 404, 429, 503])
def test_selected_google_failure_never_silently_uses_groq(gemini, monkeypatch, status):
    hosts = []
    def transport(request):
        hosts.append(request.url.host)
        return httpx.Response(status, json={'error': {'message': 'unavailable'}})
    intercept(monkeypatch, transport)
    result, model = providers.complete([{'role': 'user', 'content': 'Explain fire energy.'}])
    assert result is None and model == 'deterministic-offline-science'
    assert hosts == ['generativelanguage.googleapis.com']


def test_google_offline_mode_never_contacts_network(gemini, monkeypatch):
    monkeypatch.setenv('COPILOT_OFFLINE', '1')
    monkeypatch.setattr(providers.httpx, 'Client', lambda **kwargs: pytest.fail('Offline network request'))
    monkeypatch.setattr(agent.researcher, 'answer', lambda request: 'local evidence')
    assert agent.answer(ExplainSpikeRequest(user_question='What happened here?')) == 'local evidence'
    assert providers.complete([{'role': 'user', 'content': 'Fire energy'}])[0] is None


def test_generic_google_completion_uses_same_selected_model(gemini, monkeypatch):
    def transport(request):
        assert request.url.host == 'generativelanguage.googleapis.com'
        body = json.loads(request.content)
        assert body['model'] == 'gemini-3.8-flash'
        assert body['response_format'] == {'type': 'json_object'}
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{"claims": []}'}}]})
    intercept(monkeypatch, transport)
    text, model = providers.complete([{'role': 'user', 'content': 'Extract fire claims.'}], structured=True)
    assert text == '{"claims": []}' and model == 'gemini/gemini-3.8-flash'


def test_google_discovery_uses_grounding_metadata_not_model_invented_links(gemini, monkeypatch):
    from backend.api import copilot_research as research
    seen = []
    def transport(request):
        seen.append(request)
        if request.method == 'POST':
            assert request.url.host == 'generativelanguage.googleapis.com'
            body = json.loads(request.content)
            assert body['tools'] == [{'google_search': {}}]
            assert request.extensions['timeout']['read'] <= 12
            assert body['generationConfig']['thinkingConfig'] == {'thinkingLevel': 'low'}
            return httpx.Response(200, json={'candidates': [{'finishReason': 'STOP',
                'content': {'parts': [{'text': 'Fabricated link https://evil.example/fake'}]},
                'groundingMetadata': {'groundingChunks': [
                    {'web': {'uri': 'https://www.comunidad.madrid/report', 'title': 'Official incident report'}},
                    {'web': {'uri': 'https://vertexaisearch.cloud.google.com/grounding-api-redirect/trusted', 'title': 'News report'}},
                    {'web': {'uri': 'http://127.0.0.1/admin', 'title': 'Unsafe'}},
                    {'web': {'uri': 'https://evil.example/fake', 'title': 'Unapproved'}}]}}]})
        assert str(request.url) == 'https://vertexaisearch.cloud.google.com/grounding-api-redirect/trusted'
        assert 'x-goog-api-key' not in request.headers
        return httpx.Response(302, headers={'location': 'https://elpais.com/espana/report.html'})
    intercept(monkeypatch, transport)
    reports = research.google_search_reports('Madrid fire July 2026')
    assert [r.url for r in reports] == ['https://www.comunidad.madrid/report', 'https://elpais.com/espana/report.html']
    assert len(seen) == 2
    assert all('Fabricated' not in r.relevance_note for r in reports)


def test_google_redirect_never_fetches_unapproved_target(gemini, monkeypatch):
    from backend.api import copilot_research as research
    seen = []
    def transport(request):
        seen.append(str(request.url))
        if request.method == 'POST':
            return httpx.Response(200, json={'candidates': [{'groundingMetadata': {'groundingChunks': [
                {'web': {'uri': 'https://vertexaisearch.cloud.google.com/grounding-api-redirect/unsafe', 'title': 'Unsafe'}}]}}]})
        return httpx.Response(302, headers={'location': 'http://169.254.169.254/latest/meta-data/'})
    intercept(monkeypatch, transport)
    assert research.google_search_reports('Madrid fire') == []
    assert len(seen) == 2


def test_google_discovery_outage_and_offline_are_empty_not_fabricated(gemini, monkeypatch):
    from backend.api import copilot_research as research
    def unavailable(request):
        raise httpx.ReadTimeout('Search unavailable', request=request)
    intercept(monkeypatch, unavailable)
    assert research.google_search_reports('Madrid fire') == []
    monkeypatch.setenv('COPILOT_OFFLINE', '1')
    monkeypatch.setattr(providers.httpx, 'Client', lambda **kwargs: pytest.fail('Offline Google request'))
    assert research.google_search_reports('Madrid fire') == []


@pytest.mark.parametrize('markup', ['[K1, K2]', '[[K1], [K2]]', '[[K1, K2]]'])
def test_google_grouped_citations_become_individual_verified_source_links(gemini, monkeypatch, markup):
    turns = iter([
        {'tool_calls': [{'id': 'units', 'type': 'function', 'function': {'name': 'search_knowledge', 'arguments': '{"query":"FRP FRE"}'}}]},
        {'content': 'FRP is power; FRE integrates energy. '+markup}
    ])
    monkeypatch.setattr(agent, 'turn', lambda *args, **kwargs: next(turns))
    monkeypatch.setattr(agent.duckdb_engine, 'data_source', lambda: 'real')
    monkeypatch.setattr(agent.copilot_rag, 'search', lambda query: [
        {'id': 'K1', 'title': 'FRP units', 'url': None, 'text': 'FRP is instantaneous power.'},
        {'id': 'K2', 'title': 'FRE units', 'url': None, 'text': 'FRE integrates energy over time.'}])
    result = agent.answer(ExplainSpikeRequest(user_question='Explain the units'))
    assert result.model_used == 'gemini-agent/gemini-3.8-flash'
    assert '[K1, K2]' not in result.explanation_markdown
    assert '[[' not in result.explanation_markdown
    assert '[K1] [K2]' in result.explanation_markdown
    assert {c.id for c in result.citations} == {'[K1]', '[K2]'}


@pytest.mark.parametrize('large', [False, True])
def test_google_parallel_read_only_calls_receive_all_results_before_final_answer(gemini, monkeypatch, large):
    turns = []
    def transport(request):
        body = json.loads(request.content)
        turns.append(body)
        if len(turns) == 1:
            calls = [{'id': 'observations', 'type': 'function', 'function': {'name': 'query_observations', 'arguments': '{}'}},
                     {'id': 'methods', 'type': 'function', 'function': {'name': 'search_knowledge', 'arguments': '{"query":"FRP FRE"}'}}]
            return httpx.Response(200, json={'choices': [{'finish_reason': 'tool_calls', 'message': {'content': None, 'tool_calls': calls}}]})
        outputs = body['messages'][-2:]
        assert [m['role'] for m in outputs] == ['tool', 'tool']
        assert [m['tool_call_id'] for m in outputs] == ['observations', 'methods']
        assert len(body['messages'][-3]['tool_calls']) == 2
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {
            'content': 'The observations are consistent with burning; FRP measures power. [5] [K1]'}}]})
    intercept(monkeypatch, transport)
    monkeypatch.setattr(agent.duckdb_engine, 'data_source', lambda: 'real')
    monkeypatch.setattr(agent.local, 'retrieve_observations', lambda scope: {'status': 'ok', 'detections': 2, 'details': 'x'*5900 if large else ''})
    if large:
        monkeypatch.setattr(agent.copilot_rag, 'search', lambda query: [
            {'id': 'K1', 'title': 'Power', 'url': None, 'text': 'x'*2800},
            {'id': 'K2', 'title': 'Energy', 'url': None, 'text': 'y'*2800}])
    monkeypatch.setattr(agent.local, 'local_answer', lambda *args: 'Verified observations: 2 detections. [5]')
    result = agent.answer(ExplainSpikeRequest(user_question='is this a fire?'))
    assert result.model_used == 'gemini-agent/gemini-3.8-flash'
    assert 'consistent with burning' in result.explanation_markdown
    assert len(turns) == 2


def test_default_agent_is_gemini_even_with_groq_credentials(monkeypatch):
    monkeypatch.delenv('COPILOT_PROVIDER', raising=False)
    monkeypatch.setenv('GROQ_API_KEY', 'groq-secret')
    monkeypatch.setenv('GEMINI_API_KEY', 'gemini-secret')
    assert providers.agent_config()[:2] == ('gemini', 'gemini-secret')


def test_county_named_english_article_reaches_gemini_without_keyword_match(gemini, monkeypatch):
    from backend.api.schemas import CitationReference
    from backend.api import copilot_research as research
    source = CitationReference(id='[W1]', source_type='WEB_NEWS_REPORT', title='Regional wildfires',
        authors_or_agency='NASA', year=2011, url='https://science.nasa.gov/regional-report/',
        dataset_or_doi='Official report; article text retrieved; incident match unconfirmed',
        relevance_note='Retrieved article text (location/date match must still be checked):\n'
        'March 1, 2011\nAqua detected fires in eastern Florida on February 28, 2011.\n'
        'The largest was the Example Fire in northern Brevard County. Smoke forced road closures.\n'
        'The ignition cause was not reported.\nYou may also be interested in:\nUnrelated modern fire.')
    searches = []
    def search(query):
        searches.append(query)
        return [source]
    monkeypatch.setattr(research, 'google_search_reports', search)
    monkeypatch.setattr(research, 'enrich_official_reports', lambda reports: reports)
    monkeypatch.setattr(agent.duckdb_engine, 'data_source', lambda: 'real')
    calls = []
    def turn(messages, **kwargs):
        calls.append(list(messages))
        if len(calls) == 1:
            return {'tool_calls': [{'id': 'research', 'function': {'name': 'search_incident_reports', 'arguments': '{}'}}]}
        tool_result = next(m for m in reversed(messages) if m['role'] == 'tool')
        result = json.loads(tool_result['content'])
        article = result['reports'][0]['article_text']
        assert 'Example Fire' in article and 'Brevard' in article
        assert 'Unrelated modern' not in article
        assert 'assess location/date' in result['reports'][0]['status']
        return {'content': 'For February 28, 2011, NASA reports the Example Fire in northern Brevard County, '
                'a regional candidate for this activity. Its ignition cause was not reported; '
                'a match to the selected cells is unconfirmed. [W1]'}
    monkeypatch.setattr(agent, 'turn', turn)
    result = agent.answer(ExplainSpikeRequest(user_question='Why did this happen?',
        region_name='Selected map area', period_start='2011-02-28', period_end='2011-02-28',
        aoi={'coordinates': [[[-81.03,28.68],[-80.88,28.68],[-80.88,28.82],[-81.03,28.82],[-81.03,28.68]]]}))
    assert result.model_used.startswith('gemini-agent/')
    assert 'Example Fire' in result.explanation_markdown
    assert result.web_search_used
    assert 'latitude 28.7500, longitude -80.9550' in searches[0]
    assert result.map_context.period_start == '2011-02-28'
    assert len(calls) == 3
    assert 'Review and correct' in calls[-1][-1]['content']


def test_selected_dates_are_supported_without_requerying_observations(gemini, monkeypatch):
    monkeypatch.setattr(agent.duckdb_engine, 'data_source', lambda: 'real')
    monkeypatch.setattr(agent, 'turn', lambda *args, **kwargs: {
        'content': 'For February 28, 2011, the selected date alone does not establish ignition. [K5]'})
    result = agent.answer(ExplainSpikeRequest(user_question='What ignited it?',
        period_start='2011-02-28', period_end='2011-02-28'))
    assert result.model_used.startswith('gemini-agent/')


def test_gemini_can_refine_weak_incident_search_without_losing_initial_evidence(gemini, monkeypatch):
    from backend.api.schemas import CitationReference
    from backend.api import copilot_research as research
    queries = []
    source = CitationReference(id='[W1]', source_type='WEB_NEWS_REPORT', title='Regional report',
        authors_or_agency='NASA', year=2011, url='https://science.nasa.gov/report/',
        dataset_or_doi='Official report; article text retrieved',
        relevance_note='Retrieved article text:\nThe Example Fire was reported in this region.')
    def search(query):
        queries.append(query)
        return [] if len(queries) == 1 else [source]
    monkeypatch.setattr(research, 'google_search_reports', search)
    monkeypatch.setattr(research, 'enrich_official_reports', lambda reports: reports)
    monkeypatch.setattr(agent.duckdb_engine, 'data_source', lambda: 'real')
    turns = []
    def turn(messages, **kwargs):
        turns.append(list(messages))
        if len(turns) <= 2:
            assert 'search_incident_reports' not in kwargs['used']
            args = {} if len(turns) == 1 else {'query': 'Brevard county incident reports'}
            return {'tool_calls': [{'id': 'search'+str(len(turns)), 'function': {
                'name': 'search_incident_reports', 'arguments': json.dumps(args)}}]}
        assert 'search_incident_reports' in kwargs['used']
        assert sum(m['role'] == 'tool' for m in messages) == 2
        return {'content': 'The retrieved report describes the Example Fire as a regional candidate; '
                'the selected footprint match and cause remain unconfirmed. [W1]'}
    monkeypatch.setattr(agent, 'turn', turn)
    result = agent.answer(ExplainSpikeRequest(user_question='Which incident was this?',
        region_name='Orlando', period_start='2011-02-28', period_end='2011-02-28'))
    assert result.model_used.startswith('gemini-agent/')
    assert 'Brevard county incident reports' in queries[-1]
    assert len(queries) == 2


@pytest.mark.parametrize('batched', [False, True])
def test_provider_cannot_execute_a_third_incident_search(gemini, monkeypatch, batched):
    from backend.api import copilot_research as research
    searches = []
    monkeypatch.setattr(agent.duckdb_engine, 'data_source', lambda: 'real')
    monkeypatch.setattr(research, 'google_search_reports', lambda query: searches.append(query) or [])
    monkeypatch.setattr(research, 'indexed_sources', lambda scope: [])
    monkeypatch.setattr(research, 'enrich_official_reports', lambda reports: reports)
    monkeypatch.setattr(agent.copilot_rag, 'search', lambda question: [
        {'id': 'K2', 'title': 'Incident identity', 'url': None,
         'text': 'Thermal observations alone do not identify a named incident.'}])
    calls = []

    def turn(messages, **kwargs):
        calls.append(kwargs)
        def search(index):
            return {'id': f'search-{index}', 'function': {'name': 'search_incident_reports',
                'arguments': json.dumps({'query': f'official incident search {index}'})}}
        if batched and len(calls) == 1:
            return {'tool_calls': [search(index) for index in range(3)]}
        if not batched and len(calls) <= 3:
            if len(calls) == 3:
                assert 'search_incident_reports' in kwargs['used']
            return {'tool_calls': [search(len(calls))]}
        results = [json.loads(message['content']) for message in messages if message['role'] == 'tool']
        assert len(results) == 3
        assert results[-1]['status'] == 'search_limit_reached'
        return {'content': 'No independent incident reports were retrieved. The incident identity and cause remain unverified. [K2]'}

    monkeypatch.setattr(agent, 'turn', turn)
    response = agent.answer(ExplainSpikeRequest(user_question='what has happened here?',
        period_start='2026-07-24', period_end='2026-07-24'))
    assert len(searches) == 2
    assert response.model_used.startswith('gemini-agent/')
    assert 'unverified' in response.explanation_markdown
    assert response.map_context is None


@pytest.mark.parametrize('question', [
    'what has happened here?', 'What is happening here?', "What's happened here?",
    '¿Qué ha pasado aquí?', '¿Qué está pasando aquí?',
])
def test_event_question_variants_allow_report_research(question):
    assert agent.wants_reports(question)


def test_article_evidence_is_bounded_without_replacing_reports_with_size_error():
    from backend.api import copilot_research as research
    from backend.api.schemas import CitationReference
    sources = [CitationReference(id=f'[W{i}]', source_type='WEB_NEWS_REPORT', title='Report '+str(i),
        authors_or_agency='NASA', year=2011, url=f'https://science.nasa.gov/report/{i}',
        dataset_or_doi='Official report; article text retrieved',
        relevance_note='Retrieved article text:\nThe fire was reported near the selected region. '*100)
        for i in range(1, 5)]
    result = research.investigator_reports(sources)
    assert len(json.dumps(result, ensure_ascii=False)) <= 5500
    assert all('The fire was reported' in r['article_text'] for r in result)
    assert len(result) == 4


def test_gemini_reviews_incident_draft_using_actual_article_not_local_fallback(gemini, monkeypatch):
    from backend.api import copilot_research as research
    from backend.api.schemas import CitationReference
    source = CitationReference(id='[W1]', source_type='WEB_NEWS_REPORT', title='Regional report',
        authors_or_agency='NASA', year=2011, url='https://science.nasa.gov/report/',
        dataset_or_doi='Official report; article text retrieved',
        relevance_note='Retrieved article text:\nThe Example Fire produced smoke and threatened homes.')
    monkeypatch.setattr(research, 'google_search_reports', lambda query: [source])
    monkeypatch.setattr(research, 'enrich_official_reports', lambda reports: reports)
    monkeypatch.setattr(agent.duckdb_engine, 'data_source', lambda: 'real')
    monkeypatch.setattr(agent.researcher, 'answer', lambda req: pytest.fail('Successful research replaced with local fallback'))
    turns = []
    def turn(messages, **kwargs):
        turns.append(list(messages))
        if len(turns) == 1:
            return {'tool_calls': [{'id': 'search', 'function': {'name': 'search_incident_reports', 'arguments': '{}'}}]}
        if len(turns) == 2:
            return {'content': 'This is confirmed as the Example Fire, driven by high fuel loading. [W1]'}
        assert kwargs['finish'] is True
        assert 'fuel loading' in messages[-1]['content']
        article = json.loads(next(m for m in messages if m['role'] == 'tool')['content'])['reports'][0]['article_text']
        assert 'threatened homes' in article
        return {'content': 'The Example Fire is a regional candidate. The report documents smoke and threats '
                'to homes; its ignition cause and a match to these cells remain unverified. [W1]'}
    monkeypatch.setattr(agent, 'turn', turn)
    result = agent.answer(ExplainSpikeRequest(user_question='Which fire was this?',
        region_name='Orlando', period_start='2011-02-28', period_end='2011-02-28'))
    assert result.model_used.startswith('gemini-agent/')
    assert 'high fuel loading' not in result.explanation_markdown
    assert 'regional candidate' in result.explanation_markdown


def test_episode_profile_does_not_replace_explicit_map_period_in_followups(gemini, monkeypatch):
    monkeypatch.setattr(agent.duckdb_engine, 'data_source', lambda: 'real')
    monkeypatch.setattr(agent.researcher, 'profile_fire_episode_from_duckdb', lambda *args, **kwargs: {
        'status': 'ok', 'window_start': '2011-02-13', 'window_end': '2011-03-15', 'peak_date': '2011-02-28'})
    turns = iter([
        {'tool_calls': [{'id': 'profile', 'function': {'name': 'profile_episode', 'arguments': '{"target_date":"2011-02-28"}'}}]},
        {'content': 'The profile describes a thermal activity window around the selected day, not official incident duration. [6]'}])
    monkeypatch.setattr(agent, 'turn', lambda *args, **kwargs: next(turns))
    result = agent.answer(ExplainSpikeRequest(user_question='Describe progression around this day',
        region_name='Orlando', period_start='2011-02-28', period_end='2011-02-28'))
    assert result.model_used.startswith('gemini-agent/')
    assert result.map_context.period_start == result.map_context.period_end == '2011-02-28'
