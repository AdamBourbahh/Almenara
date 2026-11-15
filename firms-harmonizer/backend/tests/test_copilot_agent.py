"""Tool orchestration independent of question keywords and provider availability."""
import json
import pytest
from backend.api import copilot_agent as a,copilot_rag
from backend.api.schemas import ExplainSpikeRequest


@pytest.fixture
def online(monkeypatch):
    monkeypatch.setenv('COPILOT_PROVIDER','groq')
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


@pytest.mark.parametrize('question', [
    'How many satellite detections and what summed FRP in MW are recorded here? Are these separate fires?',
    'What is the total FRP in MW for the selected period?',
    '¿Cuántas detecciones y qué FRP total en MW hubo en el periodo seleccionado?',
    'Dame la suma de potencia radiativa en MW de estas fechas.',
])
@pytest.mark.parametrize('model_answer', [
    'The daily peak was 2147.06 MW. [5]',
    'There were 119 detections. These are not separate incidents. [5]',
])
def test_requested_frp_total_is_not_replaced_by_model_peak_or_omission(online, monkeypatch, question, model_answer):
    turns = iter([call('query_observations', {}), {'content': model_answer}])
    monkeypatch.setattr(a, 'turn', lambda *args, **kwargs: next(turns))
    scopes = []

    def observations(scope):
        scopes.append(scope)
        return {'status': 'ok', 'detections': 119, 'summed_frp_mw': 3328.57,
                'busiest_days': [{'date': '2021-08-16', 'summed_frp_mw': 2147.06}]}

    monkeypatch.setattr(a.local, 'retrieve_observations', observations)
    response = a.answer(ExplainSpikeRequest(user_question=question,
        period_start='2021-08-14', period_end='2021-08-22'))
    text = response.explanation_markdown
    assert response.model_used.startswith('groq-agent/')
    assert '**119 satellite detections**' in text
    assert 'Total summed FRP for the selected period: 3,328.57 MW' in text
    assert '2147.06' not in text and '2,147.06' not in text
    assert 'not a daily peak' in text and 'time-integrated energy' in text
    assert (scopes[0].start, scopes[0].end) == ('2021-08-14', '2021-08-22')
    assert {citation.id for citation in response.citations} == {'[5]'}


def test_zero_observations_render_zero_frp_without_claiming_no_fire(online, monkeypatch):
    turns = iter([call('query_observations', {}), {'content': 'No detections were recorded. [5]'}])
    monkeypatch.setattr(a, 'turn', lambda *args, **kwargs: next(turns))
    monkeypatch.setattr(a.local, 'retrieve_observations', lambda scope:
        {'status': 'ok', 'detections': 0, 'summed_frp_mw': 0.0})
    response = a.answer(ExplainSpikeRequest(user_question='What is the total FRP in MW?',
        period_start='2021-08-14', period_end='2021-08-22'))
    assert 'Total summed FRP for the selected period: 0.00 MW' in response.explanation_markdown
    assert 'do not prove that no fire occurred' in response.explanation_markdown


def test_energy_tool_cannot_overwrite_requested_frp_total(online, monkeypatch):
    turns = iter([call('query_observations', {}), call('query_energy', {}),
                  {'content': 'Thermal observations and estimated energy describe different quantities. [5] [6]'}])
    monkeypatch.setattr(a, 'turn', lambda *args, **kwargs: next(turns))
    monkeypatch.setattr(a.local, 'retrieve_observations', lambda scope:
        {'status': 'ok', 'detections': 119, 'summed_frp_mw': 3328.57})
    monkeypatch.setattr(a, 'retrieve_energy', lambda scope, req: {'status': 'ok', 'energy_gj': 12.5})
    monkeypatch.setattr(a, 'energy_answer', lambda *args: '**12.5 GJ** [6]')
    response = a.answer(ExplainSpikeRequest(user_question='Give me total FRP in MW and energy in GJ.',
        period_start='2021-08-14', period_end='2021-08-22'))
    text = response.explanation_markdown
    assert 'Total summed FRP for the selected period: 3,328.57 MW' in text
    assert '**12.5 GJ**' in text


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


def test_online_failure_does_not_run_local_fallback(online,monkeypatch):
    import httpx
    monkeypatch.setattr(a,'turn',lambda *args,**kwargs: (_ for _ in ()).throw(httpx.ReadTimeout('slow provider')))
    monkeypatch.setattr(a.researcher,'answer',lambda req:pytest.fail('Online failure invoked local fallback'))
    result=a.answer(ExplainSpikeRequest(user_question='Explain the selected satellite observations.'))
    assert result.model_used.startswith('groq-error/')
    assert result.physical_classification=='INSUFFICIENT_CONTEXT'
    assert result.verified_calculations is None


def test_pilot_envelope_cannot_replace_selected_location_label(online,monkeypatch):
    seen=[]
    def model(messages,**kwargs):
        seen.append(json.loads(messages[1]['content']))
        return {'content':'FRP is instantaneous power. [K1]'}
    monkeypatch.setattr(a,'turn',model)
    a.answer(ExplainSpikeRequest(region_name='Northern Africa selection',prefer_map_context=True,
        aoi={'coordinates':[[[3.05,36.72],[3.10,36.72],[3.10,36.77],[3.05,36.77],[3.05,36.72]]]},
        period_start='2023-01-01',period_end='2023-12-31',user_question='Explain FRP.'))
    assert seen[0]['scope']['location']=='Northern Africa selection'


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


def test_energy_tool_keeps_observed_and_regional_totals_separate(online,monkeypatch):
    sample=dict(status='ok',energy_gj=12.,biomass_tonnes=4.416,annual_gj={2026:12},gap_filled_days=2,days=3,
        peak_day='2026-07-24',peak_day_gj=6,area_km2=100,mapped_energy_gj=10.,mapped_biomass_tonnes=3.68,
        mapped_footprint_km2=20,mapped_detections=5,available_through='2026-07-24',comparison_note='Different estimators')
    monkeypatch.setattr(a,'retrieve_energy',lambda *args:sample)
    monkeypatch.setattr(a,'energy_answer',lambda *args:'Map: 10 GJ. Regional: 12 GJ. [6]')
    calls=[]
    def turn(messages,**kwargs):
        calls.append(messages)
        if len(calls)==1:
            return call('query_energy',{})
        result=json.loads(messages[-1]['content'])
        assert result['visible_map']['mapped_energy_gj']==10
        assert result['regional_model']['energy_gj']==12
        return {'content':'Map energy is 10 GJ; the regional model gives 12 GJ. [6]'}
    monkeypatch.setattr(a,'turn',turn)
    r=a.answer(ExplainSpikeRequest(user_question='Compare the GJ totals'))
    assert r.model_used.startswith('groq-agent/')


def test_unsupported_rounding_is_repaired_before_discarding_answer(online, monkeypatch):
    turns = iter([
        call('query_energy', {}),
        call('submit_answer', {'answer': 'The energy is about 13 GJ. [6]', 'citation_ids': ['[6]']}),
        call('submit_answer', {'answer': 'The energy is 12.5 GJ. [6]', 'citation_ids': ['[6]']})
    ])
    messages = []
    def model(history, **kwargs):
        messages.append(list(history))
        return next(turns)
    monkeypatch.setattr(a, 'turn', model)
    monkeypatch.setattr(a, 'retrieve_energy', lambda *args: {'energy_gj': 12.5, 'status': 'ok'})
    monkeypatch.setattr(a, 'energy_answer', lambda *args: '**12.5 GJ** [6]')
    result = a.answer(ExplainSpikeRequest(user_question='How much energy was released?',
        period_start='2026-07-23', period_end='2026-07-23'))
    assert result.model_used.startswith('groq-agent/')
    assert '12.5 GJ' in result.explanation_markdown
    assert '13 GJ' not in result.explanation_markdown
    assert 'unsupported' in messages[-1][-1]['content']


def test_citation_digits_are_not_checked_as_physical_measurements(online, monkeypatch):
    turns = iter([
        call('query_energy', {}),
        call('submit_answer', {'answer': 'The energy is 12.5 GJ. [6]', 'citation_ids': ['[6]']})
    ])
    monkeypatch.setattr(a, 'turn', lambda *args, **kwargs: next(turns))
    monkeypatch.setattr(a, 'retrieve_energy', lambda *args: {'energy_gj': 12.5, 'status': 'ok'})
    monkeypatch.setattr(a, 'energy_answer', lambda *args: '**12.5 GJ** [6]')
    result = a.answer(ExplainSpikeRequest(user_question='Energy?'))
    assert result.model_used.startswith('groq-agent/')


def test_unknown_ignition_does_not_erase_sourced_incident_explanation(online, monkeypatch):
    from backend.api.schemas import CitationReference
    source = CitationReference(id='[W1]', source_type='WEB_NEWS_REPORT', title='Madrid wildfire report',
        authors_or_agency='Madrid', year=2026, dataset_or_doi='Official report; article text retrieved',
        url='https://comunidad.madrid/noticias/2026/07/24/fire',
        relevance_note='Retrieved article text:\nMadrid. Strong wind intensified the fire.')
    monkeypatch.setattr(a.researcher, 'investigate_fire_literature_and_web', lambda *args: ([source], 'query'))
    monkeypatch.setattr(a.local.research, 'incident_passages', lambda *args: ['Strong wind intensified the fire.'])
    monkeypatch.setattr(a.local.research, 'supported_report_excerpt', lambda *args: True)
    monkeypatch.setattr(a.local.research, 'supported_ignition_excerpt', lambda *args: False)
    turns = iter([call('search_incident_reports', {}), {'content':
        'The report describes a wildfire in this region. Its ignition cause is unknown. Strong wind intensified the fire. [W1]'}])
    monkeypatch.setattr(a, 'turn', lambda *args, **kwargs: next(turns))
    result = a.answer(ExplainSpikeRequest(user_question='Why did this happen?'))
    assert 'report describes a wildfire' in result.explanation_markdown
    assert 'ignition cause is unknown' in result.explanation_markdown


# ---------------------------------------------------------------- calculation tools and provenance

PERIODS = {'start': '2021-01-01', 'end': '2021-12-31', 'compare_start': '2025-01-01', 'compare_end': '2025-12-31'}
FORMULA = {'items': [{'label': 'Energy change', 'formula': '(125.000 GJ − 100.000 GJ) ÷ 100.000 GJ × 100 = +25.00%', 'value': 25.0, 'unit': '%'}], 'note': None}


@pytest.fixture
def comparison(online, monkeypatch):
    periods = []
    def compare(scope, req, first, second):
        periods.append((first, second))
        return {'status': 'ok', 'energy_change_pct': 25.0}
    monkeypatch.setattr(a.metrics, 'retrieve_comparison', compare)
    monkeypatch.setattr(a.metrics, 'comparison_answer', lambda *args: '### Period comparison\n\n**+25.00%** [6]')
    monkeypatch.setattr(a.metrics, 'comparison_calculations', lambda evidence: FORMULA)
    return periods


def test_comparison_tool_supplies_the_percentage_and_its_formula(comparison, monkeypatch):
    turns = iter([call('compare_periods', PERIODS), {'content': 'Fire energy rose by 25% between the two years. [6]'}])
    monkeypatch.setattr(a, 'turn', lambda *args, **kwargs: next(turns))
    result = a.answer(ExplainSpikeRequest(user_question='Did this area burn more in 2025 than in 2021?'))
    assert comparison == [(('2021-01-01', '2021-12-31'), ('2025-01-01', '2025-12-31'))]
    assert result.model_used.startswith('groq-agent/')
    assert result.verified_calculations == FORMULA
    assert '**+25.00%**' in result.explanation_markdown
    assert result.evidence_sources[:2] == ['local_cube', 'verified_calculation']


def test_unsupported_figures_are_stripped_and_the_verified_table_is_kept(comparison, monkeypatch):
    wrong = {'content': 'Fire energy rose by 31%, which equals 4 football fields. The second period burned more. [6]'}
    turns = iter([call('compare_periods', PERIODS), wrong, wrong])
    monkeypatch.setattr(a, 'turn', lambda *args, **kwargs: next(turns))
    result = a.answer(ExplainSpikeRequest(user_question='Did this area burn more in 2025 than in 2021?'))
    assert result.model_used.startswith('groq-agent/')
    assert '31' not in result.explanation_markdown and 'football' not in result.explanation_markdown
    assert 'The second period burned more.' in result.explanation_markdown
    assert '**+25.00%**' in result.explanation_markdown and result.verified_calculations == FORMULA


def test_comparison_without_two_complete_periods_reports_model_error(comparison, monkeypatch):
    monkeypatch.setattr(a, 'turn', lambda *args, **kwargs: call('compare_periods', {'start': '2021-01-01', 'end': '2021-12-31'}))
    result = a.answer(ExplainSpikeRequest(user_question='Explain FRP and FRE'))
    assert comparison == [] and result.model_used.startswith('groq-error/')


@pytest.mark.parametrize('tool', ['estimate_emissions', 'query_fire_season', 'query_risk_outlook', 'query_data_quality',
    'query_burned_area', 'find_quiet_burn_windows', 'rank_thermal_events', 'query_sensor_breakdown'])
def test_every_calculation_tool_is_advertised_and_renders_server_text(online, monkeypatch, tool):
    assert tool in [t['function']['name'] for t in a.TOOLS] and tool in a.CALCULATION_TOOLS
    names = {'estimate_emissions': ('retrieve_emissions', 'emissions_answer'), 'query_fire_season': ('retrieve_phenology', 'phenology_answer'),
        'query_risk_outlook': ('retrieve_risk', 'risk_answer'), 'query_data_quality': ('retrieve_data_quality', 'quality_answer'),
        'query_burned_area': ('retrieve_burned_area', 'burned_area_answer'), 'find_quiet_burn_windows': ('retrieve_low_activity_windows', 'windows_answer'),
        'rank_thermal_events': ('retrieve_top_events', 'events_answer'),
        'query_sensor_breakdown': ('retrieve_sensor_breakdown', 'sensors_answer')}[tool]
    monkeypatch.setattr(a.metrics, names[0], lambda *args, **kwargs: {'status': 'ok', 'value': 42.5})
    monkeypatch.setattr(a.metrics, names[1], lambda *args, **kwargs: 'Server result: **42.5** [6]')
    for name in ('emissions_calculations', 'phenology_calculations', 'burned_area_calculations', 'events_calculations'):
        monkeypatch.setattr(a.metrics, name, lambda evidence: None)
    turns = iter([call(tool, {}), {'content': 'The local record gives 42.5 for this area. [6]'}])
    monkeypatch.setattr(a, 'turn', lambda *args, **kwargs: next(turns))
    result = a.answer(ExplainSpikeRequest(user_question='Summarise the local record for this area'))
    assert result.model_used.startswith('groq-agent/')
    assert 'Server result: **42.5**' in result.explanation_markdown
    assert 'local_cube' in result.evidence_sources and result.web_search_used is False


def test_web_search_runs_only_for_event_reports_and_regulations(online, monkeypatch):
    assert a.wants_reports('Which regulations apply to agricultural burning here?')
    assert a.wants_reports('What happened in this area on 2026-07-24?')
    assert not a.wants_reports('How much energy was released in this area?')
    def forbidden(*args, **kwargs):
        raise AssertionError('A numeric question must not reach the web')
    monkeypatch.setattr(a.researcher, 'investigate_fire_literature_and_web', forbidden)
    monkeypatch.setattr(a.local.research, 'google_search_reports', forbidden)
    seen = []
    def model(messages, **kwargs):
        seen.append(messages[-1])
        return [call('search_knowledge', {'query': 'FRP FRE energy'}), call('search_incident_reports', {}),
                {'content': 'FRP is instantaneous power; FRE integrates energy. [K1]'}][len(seen) - 1]
    monkeypatch.setattr(a, 'turn', model)
    result = a.answer(ExplainSpikeRequest(user_question='How much energy was released in this area?'))
    assert json.loads(seen[-1]['content'])['status'] == 'not_investigative'
    assert result.web_search_used is False and result.search_query_executed is None


def test_provider_outage_is_reported_without_local_substitution(online, monkeypatch):
    import httpx
    def outage(*args, **kwargs):
        raise httpx.ReadTimeout('search provider exceeded its deadline')
    monkeypatch.setattr(a, 'turn', outage)
    result = a.answer(ExplainSpikeRequest(user_question='Explain FRP and FRE'))
    assert result.model_used == result.provider_used
    assert result.model_used.startswith('groq-error/')
    assert result.data_source == 'real' and result.web_search_used is False
