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
