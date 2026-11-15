"""32 distinct integration checks against CSVs, staging, cube and HTTP.

The oracle scans actual H3 centers with Shapely, independently of the production
polyfill and SQL helpers. Energy uses per-row available-sensor means and H3 areas.
"""
from datetime import date
import json
import math
from pathlib import Path

import duckdb
from fastapi.testclient import TestClient
import h3
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from shapely.geometry import Point, shape

from backend.api import fire_copilot as local
from backend.api.copilot_metrics import retrieve_energy
from backend.api.schemas import ExplainSpikeRequest
from backend.db import duckdb_engine

ROOT = Path(__file__).resolve().parents[1]
AOI = {'type': 'Polygon', 'coordinates': [[[-4.8,40.2],[-4.15,40.2],[-4.15,40.58],[-4.8,40.58],[-4.8,40.2]]]}
EPOCH = date(1970, 1, 1)


@pytest.fixture(scope='module')
def oracle():
    con = duckdb.connect()
    con.read_parquet(str(ROOT/'data/processed/staged_firms.parquet')).create_view('staged')
    con.read_parquet(str(ROOT/'data/processed/fire_cube.parquet')).create_view('cube')
    polygon = shape(AOI)
    ids = [row[0] for row in con.sql('select distinct h3_r7 from staged union select distinct h3_r7 from cube').fetchall()
           if polygon.contains(Point(*reversed(h3.cell_to_latlng(format(row[0], 'x')))))]
    con.register('selected', pa.table({'cell': pa.array(ids, type=pa.uint64())}))
    assert ids and duckdb_engine.data_source() == 'real'
    yield con
    con.close()


def request(start, end=None, **kwargs):
    return ExplainSpikeRequest(aoi=AOI, region_name='Selected Sierra Oeste area', period_start=start,
        period_end=end or start, user_question='How many detections here?', **kwargs)


def audit(node, req, expected, actual, tools, method):
    node.audit = {'question': req.user_question, 'context': req.model_dump(mode='json'),
                  'files':['data/processed/staged_firms.parquet','data/processed/fire_cube.parquet'],
                  'tools_executed': tools, 'expected': expected, 'expected_method': method,
                  'response': actual, 'external_sources': [], 'criterion': 'independent numerical equality and scientific interpretation'}


@pytest.mark.parametrize('start,end,options', [
    ('2026-07-23', None, {}),
    ('2026-07-24', None, {}),
    ('2026-07-23', '2026-07-24', {}),
    ('2026-07-28', None, {}),
    ('2026-07-31', None, {}),
    ('2026-08-01', None, {}),
    ('2026-07-28', '2026-08-07', {}),
    ('2025-12-31', '2026-01-02', {}),
    ('2024-02-29', None, {}),
    ('2026-07-24', None, {'confidence_level': 'high'}),
    ('2026-07-24', None, {'confidence_level': 'low'}),
    ('2026-07-24', None, {'exclude_industrial_flaring': False}),
], ids=['first-day', 'diffusion-centers-only', 'inclusive-range', 'after-cutoff', 'reactivation',
        'august', 'later-window', 'year-boundary', 'leap-day', 'high-confidence', 'all-confidence', 'industrial-included'])
def test_observations_equal_independent_center_scan(oracle, start, end, options, request):
    req = globals()['request'](start, end, **options)
    levels = {'low': ['low','nominal','high'], 'nominal': ['nominal','high'], 'high': ['high']}[req.confidence_level]
    expected = oracle.execute('''select count(*), coalesce(sum(frp),0), min(acq_date)::varchar, max(acq_date)::varchar
        from staged where is_center and h3_r7 in (select cell from selected)
        and acq_date between ?::date and ?::date and confidence_norm in (select unnest(?))
        and (not ? or industrial_prob <= 0.75)''', [start, end or start, levels, req.exclude_industrial_flaring]).fetchall()[0]
    actual = local.retrieve_observations(local.resolve_scope(req))
    audit(request.node, req, expected, actual, ['retrieve_observations'], 'Direct staging SQL; independently selected Shapely H3 centers; accepted confidence and industrial settings')
    assert actual['detections'] == expected[0]
    assert actual['summed_frp_mw'] == pytest.approx(expected[1], rel=1e-12, abs=1e-8)
    assert (actual['first_detection'], actual['last_detection']) == expected[2:]
    assert 'not distinct fires' in actual['limits']


@pytest.mark.parametrize('start,end,exclude', [
    ('2026-07-23','2026-07-23',True), ('2026-07-24','2026-07-24',True),
    ('2026-07-23','2026-07-24',True), ('2026-07-28','2026-08-07',True),
    ('2025-12-31','2026-01-02',True), ('2024-02-29','2024-02-29',True),
    ('2026-07-24','2026-07-24',False), ('2026-11-13','2026-11-15',True),
], ids=['first-day-energy','peak-day-energy','two-day-integral','small-later-signals',
        'cross-year-integral','leap-day-energy','industrial-energy','archive-truncation'])
def test_energy_equals_independent_per_cell_integration(oracle, start, end, exclude, request):
    req = globals()['request'](start, end, enable_kalman_gap_filling=False, exclude_industrial_flaring=exclude)
    req.user_question = 'How much energy in GJ was released here?'
    rows = oracle.execute('''select h3_r7, obs_terra_fre, obs_aqua_fre, obs_viirs_fre from cube
        where h3_r7 in (select cell from selected) and epoch_day between ? and ?
        and (not ? or industrial_prob <= 0.75)''', [(date.fromisoformat(start)-EPOCH).days,
            (date.fromisoformat(end)-EPOCH).days, exclude]).fetchall()
    terms = []
    for cell, *sensors in rows:
        valid = [value for value in sensors if value is not None and math.isfinite(value)]
        if valid:
            terms.append(math.fsum(valid)/len(valid)*h3.cell_area(format(cell,'x'),unit='km^2')/1000)
    expected = math.fsum(terms)
    actual = retrieve_energy(local.resolve_scope(req), req)
    audit(request.node, req, {'energy_gj': expected}, actual, ['retrieve_energy'], 'Independent cube scan; available-sensor mean per cell times exact H3 area /1000; no RTS')
    if actual['status'] == 'empty':
        assert not rows
        assert expected == 0
        return
    assert actual['status'] == 'ok'
    assert actual['data_source'] == 'real'
    assert actual['mapped_energy_gj'] == pytest.approx(expected, rel=1e-10, abs=1e-8)
    assert actual['energy_gj'] == pytest.approx(expected, rel=1e-10, abs=1e-8)
    assert actual['biomass_tonnes'] == pytest.approx(expected*.368, rel=1e-10, abs=1e-8)
    assert actual['available_through'] <= '2026-11-14'


@pytest.mark.parametrize('check', ['source-sample','deduplication','diffusion-conservation','cube-counts','cube-confidence','null-ancillary'])
def test_pipeline_provenance_and_transforms(oracle, check, request):
    req = globals()['request']('2026-07-24')
    if check == 'source-sample':
        rows = oracle.sql("select source_file,acq_date,acq_time,latitude,longitude,frp from staged where is_center and h3_r7 in (select cell from selected) order by frp desc limit 5").fetchall()
        actual = []
        for filename, day, time, lat, lon, frp in rows:
            found = oracle.execute('''select count(*) from read_csv_auto(?,all_varchar=true)
                where acq_date=? and cast(acq_time as integer)=? and cast(latitude as double)=?
                and cast(longitude as double)=? and cast(frp as double)=?''', [str(ROOT/'data/raw'/filename), str(day), int(time), lat, lon, frp]).fetchall()[0][0]
            actual.append({'source_file':filename,'date':str(day),'acq_time':time,'latitude':lat,'longitude':lon,'frp_mw':frp,'raw_matches':found})
        expected = 'Each of five actual staged centers must exist with identical FRP and acquisition identity in its source CSV'
        ok = len(actual) == 5 and min(row['raw_matches'] for row in actual) >= 1
    elif check == 'deduplication':
        actual = oracle.sql('''select count(*) from (select satellite,acq_date,acq_time,round(latitude,5),round(longitude,5)
            from staged where is_center group by all having count(*)>1)''').fetchall()[0][0]
        expected, ok = 0, actual == 0
    elif check == 'diffusion-conservation':
        actual = oracle.sql('''select max(abs(fractions-1)) from (select satellite,acq_date,acq_time,latitude,longitude,
            sum(footprint_weight) fractions from staged group by all)''').fetchall()[0][0]
        expected, ok = 'PSF fractions sum to one per detection before bow-tie weighting', actual < 1e-10
    elif check == 'cube-counts':
        actual = oracle.sql('select sum(raw_modis_cnt+raw_viirs_cnt) from cube').fetchall()[0][0]
        expected = oracle.sql("select count(*) from staged where is_center and confidence_norm in ('nominal','high')").fetchall()[0][0]
        ok = actual == expected
    elif check == 'cube-confidence':
        actual = oracle.sql('select count(*) from cube').fetchall()[0][0]
        expected = oracle.sql("select count(*) from (select distinct h3_r7,acq_date from staged where confidence_norm in ('nominal','high'))").fetchall()[0][0]
        ok = actual == expected and pq.read_schema(ROOT/'data/processed/fire_cube.parquet').metadata[b'confidence_level'] == b'nominal'
    else:
        # Auxiliary products can be available on a real workstation. Missing
        # joins must stay NULL; measured values must equal the published input.
        actual = oracle.execute('''select count(*) from cube c
            left join read_parquet(?) a on c.h3_r7=a.h3_r7
                and DATE '1970-01-01' + c.epoch_day::INTEGER=a.acq_date::DATE
            where c.burned_area_ha_mcd64 is distinct from a.burned_area_ha_mcd64
               or c.cloud_cover_pct is distinct from a.cloud_cover_pct''',
            [str(ROOT/'data/lookup/cell_day_ancillary.parquet')]).fetchone()[0]
        expected, ok = 0, actual == 0
    audit(request.node, req, expected, actual, ['independent CSV/staging/cube scan'], check)
    if check=='source-sample':
        request.node.audit['files'] += ['data/raw/'+row['source_file'] for row in actual]
    assert ok


@pytest.mark.parametrize('question,period', [
    ('How many detections on July 23–24, 2026?', ('2026-07-23','2026-07-24')),
    ('¿Cuántas detecciones hubo el 23 y 24 de julio de 2026?', ('2026-07-23','2026-07-24')),
    ('and the next day?', ('2026-07-25','2026-07-25')),
    ('¿y el día siguiente?', ('2026-07-25','2026-07-25')),
    ('How many fires were there?', ('2026-07-24','2026-07-24')),
    ('How much energy in GJ was released here?', ('2026-07-24','2026-07-24')),
], ids=['english-range-http','spanish-range-http','english-relative-http','spanish-relative-http','fires-not-detections-http','energy-http'])
def test_offline_http_uses_real_context_and_evidence(oracle, question, period, request):
    from backend.api.main import app
    req = globals()['request']('2026-07-24')
    req.user_question = question
    with TestClient(app) as client:
        response = client.post('/api/explain-spike', json=req.model_dump(mode='json'))
    body = response.json()
    audit(request.node, req, {'resolved_period': period, 'data_source': 'real'}, body,
          ['POST /api/explain-spike', 'local DuckDB tools'], 'Literal calendar expectation; actual offline API over real archive')
    assert response.status_code == 200
    assert body['data_source'] == 'real'
    assert (body['map_context']['period_start'],body['map_context']['period_end']) == period
    assert not body['web_search_used']
    if 'fires were' in question:
        assert 'distinct fire' in body['explanation_markdown'].lower() or 'number of fires' in body['explanation_markdown'].lower()


def test_timeline_reports_actual_later_observations_without_changing_selection(oracle, request):
    from backend.api.copilot_timeline import observation_timeline
    req=globals()['request']('2026-07-24')
    req.user_question='Does local observation history actually end on July 27?'
    scope=local.resolve_scope(req)
    actual=observation_timeline(scope)
    rows=oracle.execute('''select acq_date::varchar,count(*) from staged where is_center
        and h3_r7 in (select cell from selected) and confidence_norm in ('nominal','high')
        and industrial_prob<=0.75 and acq_date between '2026-07-17' and '2026-08-08'
        group by acq_date order by acq_date''').fetchall()
    expected=[{'date':day,'detections':count} for day,count in rows]
    audit(request.node,req,expected,actual,['observation_timeline','retrieve_observations'],
          'Independent staging scan over explicitly labeled July 17–August 8 comparison window')
    assert actual['daily_detections']==expected
    assert any(day['date']>'2026-07-27' for day in expected)
    assert actual['selected_start']==actual['selected_end']==scope.start=='2026-07-24'


def test_offline_historical_questions_cannot_open_a_network_socket(oracle, monkeypatch, request):
    import socket
    from backend.api.main import app
    attempts=[]
    def deny_network(*args,**kwargs):
        attempts.append(str(args[1:]))
        raise AssertionError('Offline answer attempted network access')
    questions=['is this a fire?','why did this happen?','the reason of the fire is known?',
               'how much energy in GJ was released here?','how many fires were there?',
               'why does the map seem to stop on July 27 if the Madrid fire lasted fourteen days?']
    received=[]
    req=globals()['request']('2026-07-24')
    with TestClient(app) as client:
        # Windows initializes its event-loop self-pipe using a loopback socket
        # pair. Block connections after TestClient has created that loop.
        monkeypatch.setattr(socket.socket,'connect',deny_network)
        monkeypatch.setattr(socket,'getaddrinfo',deny_network)
        for question in questions:
            req.user_question=question
            response=client.post('/api/explain-spike',json=req.model_dump(mode='json'))
            received.append(response.json())
            assert response.status_code==200
            assert response.json()['data_source']=='real'
            assert not response.json()['web_search_used']
    audit(request.node,req,{'network_attempts':0},received,['actual offline HTTP routes and local tools'],
          'Block DNS resolution and socket connection; run all six historical prompts over real local data')
    assert not attempts
    assert '2026-07-28' in received[-1]['explanation_markdown']
    assert 'unverified' in received[-1]['explanation_markdown'].lower()


@pytest.mark.parametrize('level',['low','high'])
def test_energy_uses_same_confidence_cube_as_map_and_temporal_model(oracle, level, request):
    req=globals()['request']('2026-07-24',confidence_level=level,enable_kalman_gap_filling=False)
    req.user_question=f'How much energy in GJ with {level} detection confidence?'
    rows=oracle.execute('''select h3_r7,obs_terra_fre,obs_aqua_fre,obs_viirs_fre
        from read_parquet(?) where h3_r7 in (select cell from selected) and epoch_day=? and industrial_prob<=0.75''',
        [str(ROOT/f'data/processed/fire_cube_{level}.parquet'),(date(2026,7,24)-EPOCH).days]).fetchall()
    terms=[]
    for cell,*sensors in rows:
        valid=[value for value in sensors if value is not None and math.isfinite(value)]
        if valid:
            terms.append(math.fsum(valid)/len(valid)*h3.cell_area(format(cell,'x'),unit='km^2')/1000)
    expected=math.fsum(terms)
    actual=retrieve_energy(local.resolve_scope(req),req)
    audit(request.node,req,{'energy_gj':expected},actual,['retrieve_energy'],
          'Independent scan of the separately published confidence cube, per-cell available sensor fusion')
    request.node.audit['files'].append(f'data/processed/fire_cube_{level}.parquet')
    assert actual['mapped_energy_gj']==pytest.approx(expected,rel=1e-10,abs=1e-8)
    assert actual['energy_gj']==pytest.approx(expected,rel=1e-10,abs=1e-8)
