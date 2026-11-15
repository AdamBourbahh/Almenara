"""Episode physics, provider failover and research integration regressions."""
from datetime import date,timedelta
import json
import math

import duckdb
import h3
import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from contextlib import contextmanager
from fastapi.testclient import TestClient

from backend.api import copilot_researcher as c, copilot_providers as providers, routes
from backend.api.cache import ANALYZE_CACHE
from backend.api.main import app
from backend.api.schemas import ExplainSpikeRequest, ExplainSpikeResponse, GeoJSONPolygon


@pytest.fixture
def cube(tmp_path,monkeypatch):
    cell=h3.latlng_to_cell(40.4,-4.2,7)
    industrial=h3.latlng_to_cell(40.42,-4.18,7)
    rows=[]
    def append(day,value,index=cell,prob=0.0,count=1):
        d=date.fromisoformat(day)
        rows.append(dict(h3_r7=int(index,16),h3_r4=int(h3.cell_to_parent(index,4),16),
            epoch_day=(d-date(1970,1,1)).days,year=d.year,doy=d.timetuple().tm_yday,
            raw_modis_cnt=count,raw_viirs_cnt=0,raw_frp_mw=value,industrial_prob=prob,
            obs_terra_fre=value,obs_aqua_fre=None,obs_viirs_fre=None,
            neighbor_fre_lag1=0.,cloud_cover_pct=0.,sensor_obs_mask=1,gap_status_mask=0,
            burned_area_ha_mcd64=None))
    for year in (2011,2013):
        append(f'{year}-07-01',1)
    for day,value in enumerate([1,1,40,70,100,80,50,1,1],20):
        append(f'2026-07-{day}',value)
    append('2026-07-27',999999,index=industrial,prob=.95,count=7)
    path=tmp_path/'cube.parquet'
    pq.write_table(pa.Table.from_pylist(rows),path)
    conn=duckdb.connect(':memory:')
    conn.read_parquet(str(path)).create_view('fire_cube')
    @contextmanager
    def cursor():
        cur=conn.cursor()
        try:
            yield cur
        finally:
            cur.close()
    monkeypatch.setattr(c.duckdb_engine,'get_db_cursor',cursor)
    monkeypatch.setattr(c.duckdb_engine,'data_source',lambda:'real')
    monkeypatch.setattr(c.duckdb_engine,'missing_columns',lambda:[])
    monkeypatch.setattr(c.duckdb_engine,'cube_path',lambda:path)
    monkeypatch.setattr(c.duckdb_engine,'ROOT',tmp_path)
    monkeypatch.setenv('COPILOT_OFFLINE','1')
    ANALYZE_CACHE.clear()
    aoi=GeoJSONPolygon(coordinates=[[[-4.25,40.35],[-4.1,40.35],[-4.1,40.48],[-4.25,40.48],[-4.25,40.35]]])
    yield aoi,cell,rows
    ANALYZE_CACHE.clear()
    conn.close()


def test_auto_discovery_excludes_industrial_and_integrates_units(cube):
    aoi,cell,rows=cube
    p=c.profile_fire_episode_from_duckdb(aoi,'Test region',enable_kalman_gap_filling=False)
    assert p['peak_date']=='2026-07-24'
    assert p['episode_start_date']=='2026-07-22'
    assert p['episode_end_date']=='2026-07-26'
    assert p['duration_days']==5
    assert p['peak_daily_fre_mj_km2']==100
    expected=sum([40,70,100,80,50])*h3.cell_area(cell,unit='km^2')/1000
    assert p['total_episode_fre_gj']==pytest.approx(expected)
    assert p['estimated_biomass_burned_tonnes']==pytest.approx(expected*.368)
    assert p['estimated_pm25_tonnes']==pytest.approx(expected*.368*.0095)
    assert p['estimated_co2_tonnes']==pytest.approx(expected*.368*1.58)
    assert p['industrial_candidate_cells']==1 and p['industrial_candidate_detections']==7
    assert p['dominant_sensors']==['Terra'] and p['gap_filling_occurred'] is False
    assert p['raw_count_inflation_factor']==pytest.approx(1)
    assert all(isinstance(h,str) for h in p['sample_h3_indices'])


def test_target_window_and_empty_period_do_not_substitute_another_year(cube):
    aoi,cell,rows=cube
    p=c.profile_fire_episode_from_duckdb(aoi,'Test',target_date='2011-07-01',enable_kalman_gap_filling=False)
    assert p['peak_date']=='2011-07-01' and p['auto_discovered'] is False
    p=c.profile_fire_episode_from_duckdb(aoi,'Test',period_start='2020-01-01',period_end='2020-12-31')
    assert p['status']=='empty'
    assert c.profile_fire_episode_from_duckdb(aoi,'Test','1842-01-01')['status']=='unsupported_period'


def test_small_empty_polygon_does_not_fallback_to_nearby_cell(cube):
    aoi,cell,rows=cube
    lat,lon=h3.cell_to_latlng(cell)
    p=GeoJSONPolygon(coordinates=[[[lon,lat],[lon+.000001,lat],[lon+.000001,lat+.000001],[lon,lat+.000001],[lon,lat]]])
    assert c.profile_fire_episode_from_duckdb(p,'Tiny')['status']=='empty'


def test_profile_invalid_hex_and_topology_are_explicit(cube):
    aoi,cell,rows=cube
    with pytest.raises(ValueError,match='valid H3'):
        c.profile_fire_episode_from_duckdb(aoi,'Test',target_h3_index='bad')
    with pytest.raises(ValueError,match='resolution 7'):
        c.profile_fire_episode_from_duckdb(aoi,'Test',target_h3_index=h3.cell_to_parent(cell,4))
    with pytest.raises(ValueError):
        c.profile_fire_episode_from_duckdb(GeoJSONPolygon(coordinates=[[[0,0],[1,1],[0,1],[1,0],[0,0]]]),'Test')


def test_full_dossier_endpoint_and_compatible_contract(cube):
    aoi,cell,rows=cube
    with TestClient(app) as client:
        response=client.post('/api/explain-spike',json={'aoi':aoi.model_dump(),'enable_kalman_gap_filling':False,
            'user_question':'Tell me everything about the main wildfire: cause, progression, duration and consequences.'})
    assert response.status_code==200,response.text
    r=ExplainSpikeResponse.model_validate(response.json())
    assert r.episode_summary['duration_days']==5
    assert r.provider_used=='offline-physics-engine'
    assert r.answer_markdown==r.explanation_markdown
    assert r.explanation_markdown.count('### Temporal Progression')==1
    assert 'not measured emissions' in r.explanation_markdown
    assert 'not verified' in r.explanation_markdown
    req=ExplainSpikeRequest(chat_history=[{'role':'user','content':'Madrid 2026-07-24'}])
    assert req.conversation==req.chat_history


@pytest.mark.parametrize('status',[401,403,429,500])
def test_cascade_uses_supported_endpoints_and_bounds_prompt_and_output(monkeypatch,status):
    monkeypatch.setenv('COPILOT_OFFLINE','0')
    for variable in ('GROQ_API_KEY','GITHUB_TOKEN','GEMINI_API_KEY'):
        monkeypatch.setenv(variable,'test-secret')
    monkeypatch.delenv('GROQ_MODEL',raising=False)
    monkeypatch.setenv('GITHUB_MODELS_ENDPOINT','https://models-gateway.example.org/v1/chat/completions')
    calls=[]
    def transport(request):
        calls.append(request)
        body=json.loads(request.content)
        assert sum(len(m['content']) for m in body['messages'])<=4500
        assert body['max_tokens']==900
        if request.url.host=='generativelanguage.googleapis.com':
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"claims":[]}'}}]})
        return httpx.Response(status,json={'error':'unavailable'})
    factory=httpx.Client
    monkeypatch.setattr(providers.httpx,'Client',lambda **kwargs:factory(transport=httpx.MockTransport(transport),**kwargs))
    result,provider=providers.complete([{'role':'system','content':'x'*6000},{'role':'user','content':'a'*10000}],structured=True)
    assert result=='{"claims":[]}' and provider=='gemini/gemini-2.5-flash'
    assert len(calls)==3
    assert calls[0].url.host=='api.groq.com'
    assert calls[1].url.host=='models-gateway.example.org'
    assert json.loads(calls[0].content)['model']=='llama-3.3-70b-versatile'


def test_all_provider_network_failures_and_malformed_json(monkeypatch):
    monkeypatch.setenv('COPILOT_OFFLINE','0')
    monkeypatch.setenv('GROQ_API_KEY','test')
    monkeypatch.delenv('GITHUB_TOKEN',raising=False)
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    factory=httpx.Client
    for mode in ('network','json','truncated','empty'):
        def transport(request):
            if mode=='network':
                raise httpx.ConnectError('offline',request=request)
            if mode=='json':
                return httpx.Response(200,text='invalid')
            return httpx.Response(200,json={'choices':[{'finish_reason':'length' if mode=='truncated' else 'stop','message':{'content':'bad' if mode=='truncated' else ''}}]})
        monkeypatch.setattr(providers.httpx,'Client',lambda **kwargs:factory(transport=httpx.MockTransport(transport),**kwargs))
        assert providers.complete([{'role':'user','content':'test'}])[0] is None


def test_offline_skips_every_provider(monkeypatch):
    monkeypatch.setenv('COPILOT_OFFLINE','1')
    monkeypatch.setattr(providers.httpx,'Client',lambda **kwargs:pytest.fail('Offline attempted HTTP'))
    assert providers.complete([{'role':'user','content':'test'}])[0] is None


def test_three_queries_and_wikipedia_are_clean_and_deduplicated(cube,monkeypatch):
    aoi,cell,rows=cube
    monkeypatch.setenv('COPILOT_OFFLINE','0')
    monkeypatch.delenv('TAVILY_API_KEY',raising=False)
    c.RESEARCH_CACHE.clear()
    calls=[]
    class Search:
        def __init__(self,timeout):
            assert timeout==4.0
        def text(self,query,**kwargs):
            assert kwargs['max_results']==2
            calls.append(query)
            return [{'title':'Sierra Oeste wildfire July 2026','href':'https://rtve.es/madrid-2026-fire','body':'Sierra Oeste fire July 2026.'}]
    monkeypatch.setattr(c.legacy,'DDGS',Search)
    monkeypatch.setattr(c.legacy,'search_reports',lambda scope:([],''))
    monkeypatch.setattr(c.research,'enrich_official_reports',lambda reports:reports)
    factory=httpx.Client
    wiki_calls=[]
    def transport(request):
        wiki_calls.append(request)
        assert request.headers['User-Agent']=='FIRMS-Harmonizer-NASA-SpaceApps/1.0'
        return httpx.Response(200,json={'query':{'search':[{'title':'Sierra Oeste wildfire','snippet':'Sierra Oeste fire historical context'}]}})
    monkeypatch.setattr(c.httpx,'Client',lambda **kwargs:factory(transport=httpx.MockTransport(transport),**kwargs))
    scope=c.legacy.resolve_scope(ExplainSpikeRequest(aoi=aoi,user_question='Madrid on 2026-07-24'))
    citations,query=c.investigate_fire_literature_and_web(scope)
    assert len(calls)==3 and len(wiki_calls)==1
    assert any('ignition' in q for q in calls) and any('duration' in q for q in calls) and any('ecological' in q for q in calls)
    assert len({x.url for x in citations})==len(citations)==2
    assert [x.id for x in citations]==['[W1]','[W2]']
    assert c.geographic_context(scope)[1] is not None


def test_missing_groq_model_uses_bounded_compatible_model(monkeypatch):
    monkeypatch.setenv('COPILOT_OFFLINE','0')
    monkeypatch.setenv('GROQ_API_KEY','test')
    monkeypatch.delenv('GROQ_MODEL',raising=False)
    calls=[]
    factory=httpx.Client
    def transport(request):
        body=json.loads(request.content)
        calls.append(body)
        if len(calls)==1:
            return httpx.Response(404,json={'error':{'code':'model_not_found'}})
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"claims":[]}'}}]})
    monkeypatch.setattr(providers.httpx,'Client',lambda **kwargs:factory(transport=httpx.MockTransport(transport),**kwargs))
    result,model=providers.complete([{'role':'user','content':'Extract facts in JSON.'}],structured=True)
    assert model=='groq/openai/gpt-oss-120b' and result=='{"claims":[]}'
    assert len(calls)==2 and all(c['max_tokens']==900 for c in calls)


@pytest.mark.parametrize('field,classification',[('is_forecast','FORECAST_PROJECTION'),('is_gap_filled','KALMAN_GAP_RECONSTRUCTION')])
def test_reconstruction_and_forecast_gates_never_search_incident_news(cube,monkeypatch,field,classification):
    aoi,cell,rows=cube
    data=json.loads(routes.analyze(c.AnalyzeRequest(aoi=aoi,start_year=2001,end_year=2026,forecast_days=0)).body)
    day=next(c for c in data['calendar_series'] if c['date']=='2026-07-24')
    day={**day,'is_gap_filled':False,field:True}
    if field=='is_gap_filled':
        day.update(raw_hotspot_count=0,active_sensors=[])
    monkeypatch.setattr(c,'investigate_fire_literature_and_web',lambda *a,**k:pytest.fail('Physics gate searched news'))
    r=c.answer(ExplainSpikeRequest(selected_day=day,aoi=aoi,user_question='Explain the progression and cause of this point.'))
    assert r.physical_classification==classification and r.web_search_used is False


def test_censored_profile_does_not_claim_extinction_at_window_edge(cube):
    aoi,cell,rows=cube
    p=c.profile_fire_episode_from_duckdb(aoi,'Test','2011-07-01',enable_kalman_gap_filling=False)
    assert p['left_censored'] is True
    assert p['coverage_start']=='2011-07-01'


def test_generic_first_question_and_remembered_context_are_supported(cube):
    aoi,cell,rows=cube
    r=c.answer(ExplainSpikeRequest(aoi=aoi,period_start='2026-01-01',period_end='2026-12-31',
        enable_kalman_gap_filling=False,user_question='What can you tell me about this area?'))
    assert r.episode_summary['auto_discovered'] is True
    assert r.episode_summary['peak_date']=='2026-07-24'


def test_summary_cannot_introduce_numbers_or_erase_investigation_status():
    from backend.api.copilot_answers import summary_matches_excerpt
    assert not summary_matches_excerpt('The fire killed 999 people.','A regional fire was reported.')
    assert not summary_matches_excerpt('The fire was caused by lightning.','The ignition cause remains unknown and under investigation.')
    assert summary_matches_excerpt('The ignition cause is under investigation.','The ignition cause remains unknown and under investigation.')


def test_dossier_model_input_is_complete_json_under_budget(cube,monkeypatch):
    from backend.api.schemas import CitationReference
    aoi,cell,rows=cube
    req=ExplainSpikeRequest(aoi=aoi,user_question='Investigate the main fire, its progression and consequences.'+' untrusted'*800)
    scope=c.legacy.resolve_scope(req)
    scope.start=scope.end='2026-07-24'
    p=c.profile_fire_episode_from_duckdb(aoi,'Test',enable_kalman_gap_filling=False)
    excerpt='Sierra Oeste experienced strong wind and high temperatures during the fire.'
    report=CitationReference(id='[W1]',source_type='WEB_NEWS_REPORT',title='Sierra Oeste fire 2026-07-24',
        url='https://www.comunidad.madrid/noticias/2026/07/24/fire',authors_or_agency='Comunidad de Madrid',
        year=2026,dataset_or_doi='Official report; article text retrieved',relevance_note='Retrieved article text:\n'+excerpt+'\n'+'irrelevant '*9000)
    seen=[]
    def complete(messages,**kwargs):
        seen.append(messages)
        assert sum(len(m['content']) for m in messages)<=4500
        payload=json.loads(messages[-1]['content'])
        assert payload['articles'][0]['passages'][0]==excerpt
        return json.dumps({'claims':[{'source_id':'[W999]','kind':'ignition','quote':excerpt,'summary':'Invented arson.'}]}),'fake'
    monkeypatch.setattr(c.providers,'complete',complete)
    r=c.synthesize_scientific_dossier(req,scope,p,[report],'test query')
    assert seen and 'Invented arson' not in r.explanation_markdown
    assert '[W999]' not in r.explanation_markdown


def test_partial_reconstruction_does_not_hide_observed_fire_evidence(cube):
    aoi,cell,rows=cube
    data=json.loads(routes.analyze(c.AnalyzeRequest(aoi=aoi,start_year=2001,end_year=2026,forecast_days=0)).body)
    day=next(v for v in data['calendar_series'] if v['date']=='2026-07-24')
    day={**day,'is_gap_filled':True,'raw_hotspot_count':1,'active_sensors':['Terra']}
    r=c.answer(ExplainSpikeRequest(selected_day=day,aoi=aoi,user_question='Investigate this fire: duration and consequences.'))
    assert r.episode_summary is not None and r.episode_summary['status']=='ok'
    assert r.physical_classification!='KALMAN_GAP_RECONSTRUCTION'


def test_search_cache_retries_article_fetch_after_network_recovers(cube,monkeypatch):
    from backend.api.schemas import CitationReference
    from time import monotonic
    aoi,cell,rows=cube
    monkeypatch.setenv('COPILOT_OFFLINE','0')
    scope=c.legacy.resolve_scope(ExplainSpikeRequest(aoi=aoi,user_question='Madrid on 2026-07-24'))
    source=CitationReference(id='[W1]',source_type='WEB_NEWS_REPORT',title='Madrid fire',
        authors_or_agency='Comunidad de Madrid',year=2026,url='https://www.comunidad.madrid/noticias/2026/07/24/fire',
        dataset_or_doi='Official report; curated URL; content must be retrieved',relevance_note='A lead cached during an outage.')
    key=json.dumps([scope.label,scope.start,scope.end,scope.search_query])
    c.legacy.SEARCH_CACHE.put(key,(monotonic(),[source],'cached search'))
    full=source.model_copy(update={'dataset_or_doi':'Official report; article text retrieved','relevance_note':'Recovered body.'})
    monkeypatch.setattr(c.research,'enrich_official_reports',lambda sources:[full])
    citations,query=c.legacy.search_reports(scope)
    assert citations[0].relevance_note=='Recovered body.' and query=='cached search'
    c.legacy.SEARCH_CACHE.clear()
