"""Tool orchestration independent of question keywords and provider availability."""
import json
import pytest
from backend.api import copilot_agent as a,copilot_rag
from backend.api.schemas import ExplainSpikeRequest


@pytest.fixture
def online(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY','test')
    monkeypatch.setenv('COPILOT_OFFLINE','0')
    monkeypatch.setattr(a.duckdb_engine,'data_source',lambda:'real')


def call(name,args):
    return {'tool_calls':[{'id':'call1','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}


def test_rag_retrieves_units_and_method_without_fts_injection():
    assert copilot_rag.search('FRP GJ')[0]['id']=='K1'
    assert copilot_rag.search('" OR *; DROP TABLE notes; --') is not None
    assert any(x['id']=='K7' for x in copilot_rag.search('industrial entropy flaring'))


def test_model_selects_tools_for_unanticipated_paraphrase(online,monkeypatch):
    turns=iter([call('search_knowledge',{'query':'FRP FRE energy'}),call('submit_answer',{'answer':'FRP is instantaneous power; FRE integrates energy. [K1]','citation_ids':['[K1]']})])
    monkeypatch.setattr(a,'turn',lambda *args,**kwargs:next(turns))
    result=a.answer(ExplainSpikeRequest(user_question='Help me understand these two measures.'))
    assert result.model_used.startswith('groq-agent/')
    assert result.citations[0].id=='[K1]'


def test_database_tool_returns_server_numbers_and_preserves_scope(online,monkeypatch):
    turns=iter([call('query_energy',{}),call('submit_answer',{'answer':'The selected period contains 12.5 GJ. [6]','citation_ids':['[6]']})])
    monkeypatch.setattr(a,'turn',lambda *args,**kwargs:next(turns))
    scopes=[]
    def energy(scope,req):
        scopes.append(scope)
        return {'energy_gj':12.5,'status':'ok'}
    monkeypatch.setattr(a,'retrieve_energy',energy)
    monkeypatch.setattr(a,'energy_answer',lambda *args:'### Calculation\n\n**12.5 GJ** [6]')
    result=a.answer(ExplainSpikeRequest(user_question='Tell me the integrated output here',aoi={'coordinates':[[[-4.8,40.2],[-4.15,40.2],[-4.15,40.58],[-4.8,40.58],[-4.8,40.2]]]},period_start='2026-07-24',period_end='2026-07-24'))
    assert scopes[0].start==scopes[0].end=='2026-07-24'
    assert result.model_used.startswith('groq-agent/') and '**12.5 GJ**' in result.explanation_markdown


@pytest.mark.parametrize('bad',[
 call('submit_answer',{'answer':'Fake cause [W999]','citation_ids':['[W999]']}),
 call('submit_answer',{'answer':'It burned 999999999 GJ [K1]','citation_ids':['[K1]']}),
 {'tool_calls':[]}, {'tool_calls':[{'id':'bad','function':{'name':'query_energy','arguments':'not json'}}]}])
def test_malformed_and_unsupported_answers_fall_back_without_inventing(online,monkeypatch,bad):
    monkeypatch.setattr(a,'turn',lambda *args,**kwargs:bad)
    r=a.answer(ExplainSpikeRequest(user_question='Explain FRP and FRE'))
    assert not r.model_used.startswith('groq-agent/')
    assert 'Fake cause' not in r.explanation_markdown and '999999999' not in r.explanation_markdown


def test_tool_arguments_cannot_supply_sql_or_geometry(online,monkeypatch):
    monkeypatch.setattr(a,'turn',lambda *args,**kwargs:call('query_observations',{'sql':'DROP TABLE fire_cube'}))
    r=a.answer(ExplainSpikeRequest(user_question='Explain FRP'))
    assert not r.model_used.startswith('groq-agent/')


def test_offline_bypasses_provider(online,monkeypatch):
    monkeypatch.setenv('COPILOT_OFFLINE','1')
    monkeypatch.setattr(a,'turn',lambda *args,**kwargs:pytest.fail('offline attempted provider'))
    monkeypatch.setattr(a.researcher,'answer',lambda req:'local fallback')
    assert a.answer(ExplainSpikeRequest())=='local fallback'


def test_natural_completion_after_tool_is_accepted(online,monkeypatch):
    turns=iter([call('search_knowledge',{'query':'FRP FRE'}),{'content':'FRP is power, FRE is integrated energy. [K1]'}])
    monkeypatch.setattr(a,'turn',lambda *args,**kwargs:next(turns))
    r=a.answer(ExplainSpikeRequest(user_question='Please clarify these measures'))
    assert r.model_used.startswith('groq-agent/')


def test_live_protocol_uses_auto_and_never_repeats_completed_tool(online,monkeypatch):
    import httpx
    seen=[]
    factory=httpx.Client
    def transport(request):
        data=json.loads(request.content);seen.append(data)
        assert data['tool_choice']=='auto'
        assert 'query_energy' not in [t['function']['name'] for t in data['tools']]
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'FRP is power. [K1]'}}]})
    monkeypatch.setattr(a.httpx,'Client',lambda **kwargs:factory(transport=httpx.MockTransport(transport),**kwargs))
    assert a.turn([{'role':'user','content':'Define FRP'}],used=['query_energy'])['content']


def test_provider_unicode_citations_are_normalized(online,monkeypatch):
    monkeypatch.setattr(a,'turn',lambda *args,**kwargs:{'content':'FRP is instantaneous power.【K1】'})
    r=a.answer(ExplainSpikeRequest(user_question='Explain FRP'))
    assert r.model_used.startswith('groq-agent/') and '[K1]' in r.explanation_markdown


def test_missing_inline_markers_are_attached_from_actual_tool_sources(online,monkeypatch):
    turns=iter([call('search_knowledge',{'query':'FRP FRE'}),{'content':'FRP is instantaneous power; FRE integrates energy.'}])
    monkeypatch.setattr(a,'turn',lambda *args,**kwargs:next(turns))
    r=a.answer(ExplainSpikeRequest(user_question='Explain the difference'))
    assert r.model_used.startswith('groq-agent/') and '[K1]' in r.explanation_markdown


def test_forced_offline_is_request_local():
    from backend.api.copilot_network import offline_context,is_forced_offline
    from concurrent.futures import ThreadPoolExecutor
    assert not is_forced_offline()
    with offline_context():
        assert is_forced_offline()
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(is_forced_offline).result() is False
    assert not is_forced_offline()


def test_weather_cannot_be_promoted_to_ignition(online,monkeypatch):
    from backend.api.schemas import CitationReference
    source=CitationReference(id='[W1]',source_type='WEB_NEWS_REPORT',title='Madrid fire',authors_or_agency='Madrid',year=2026,
        dataset_or_doi='Official report; article text retrieved',url='https://comunidad.madrid/noticias/2026/07/24/fire',
        relevance_note='Retrieved article text:\nMadrid. Strong wind intensified the fire.')
    monkeypatch.setattr(a.researcher,'investigate_fire_literature_and_web',lambda *args:([source],'query'))
    monkeypatch.setattr(a.local.research,'incident_passages',lambda *args:['Strong wind intensified the fire.'])
    monkeypatch.setattr(a.local.research,'supported_report_excerpt',lambda *args:True)
    monkeypatch.setattr(a.local.research,'supported_ignition_excerpt',lambda *args:False)
    turns=iter([call('search_incident_reports',{}),{'content':'Strong wind caused the fire to ignite. [W1]'}])
    monkeypatch.setattr(a,'turn',lambda *args,**kwargs:next(turns))
    r=a.answer(ExplainSpikeRequest(user_question='What led to this?'))
    assert 'do not establish what ignited' in r.explanation_markdown
    assert 'caused the fire to ignite' not in r.explanation_markdown
