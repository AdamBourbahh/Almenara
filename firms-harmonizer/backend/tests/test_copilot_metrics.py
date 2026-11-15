"""Database-grounded energy, context precedence and graceful missing-data regressions."""
import math

import h3
import pytest
from fastapi.testclient import TestClient

from backend.api import fire_copilot as copilot
from backend.api.main import app
from backend.api.schemas import ExplainSpikeRequest
from backend.db import duckdb_engine


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("COPILOT_OFFLINE", "1")
    with TestClient(app) as client:
        yield client


def selected_cell_request():
    with duckdb_engine.get_db_cursor() as cursor:
        index = cursor.execute("SELECT printf('%x', h3_r7) FROM fire_cube WHERE year=2022 AND raw_modis_cnt>0 AND industrial_prob<0.75 LIMIT 1").fetchone()[0]
    ring = [[lon, lat] for lat, lon in h3.cell_to_boundary(index)]
    return {"region_name": "Selected test cell", "aoi": {"type": "Polygon", "coordinates": [ring + [ring[0]]]},
            "period_start": "2022-07-01", "period_end": "2022-08-31",
            "user_question": "How much energy in GJ and how many fires in this area?"}


@pytest.mark.parametrize("kalman,industrial", [(True, True), (False, False)])
def test_gj_matches_dashboard_inclusive_dates_and_filters(client, monkeypatch, kalman, industrial):
    def forbidden(*args, **kwargs):
        raise AssertionError("Local metrics must never call a language model or web search")
    monkeypatch.setattr(copilot, "complete", forbidden)
    monkeypatch.setattr(copilot, "search_reports", forbidden)
    payload = selected_cell_request()
    payload.update(enable_kalman_gap_filling=kalman, exclude_industrial_flaring=industrial)
    analysis = client.post("/api/analyze", json={"aoi": payload["aoi"], "start_year": 2000, "end_year": 2026,
        "enable_kalman_gap_filling": kalman, "exclude_industrial_flaring": industrial}).json()
    days = [c for c in analysis["calendar_series"] if payload["period_start"] <= c["date"] <= payload["period_end"]]
    expected_gj = math.fsum(c["biomass_burned_tonnes"] for c in days) / 0.368
    response = client.post("/api/explain-spike", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["physical_classification"] == "LOCAL_ENERGY_SUMMARY"
    assert f"**{expected_gj:,.3f} GJ**" in body["explanation_markdown"]
    assert f"**{len(days)} days**" in body["explanation_markdown"]
    assert body["data_source"] == "synthetic"
    assert "Synthetic demo mode" in body["explanation_markdown"]
    assert body["web_search_used"] is False
    assert {c["id"] for c in body["citations"]} == {"[1]", "[6]"}
    assert body["map_context"]["aoi"] == payload["aoi"]
    assert body["map_context"]["period_end"] == "2022-08-31"


def test_energy_does_not_trust_client_hex_totals(client):
    payload = selected_cell_request()
    ring = payload["aoi"]["coordinates"][0]
    lat = sum(p[1] for p in ring[:-1]) / len(ring[:-1])
    lon = sum(p[0] for p in ring[:-1]) / len(ring[:-1])
    index = h3.latlng_to_cell(lat, lon, 7)
    payload["selected_hex"] = {"h3_index": index, "mean_annual_fre": 987654321,
        "raw_pixel_count": 987654321, "trend_slope": 0, "is_industrial_site": True, "shannon_entropy": 1}
    result = client.post("/api/explain-spike", json=payload).json()
    assert "987654321" not in result["explanation_markdown"]
    assert result["physical_classification"] == "LOCAL_ENERGY_SUMMARY"
    assert result["map_context"]["h3_index"] == index


def test_missing_energy_columns_never_convert_raw_mw(client, monkeypatch):
    payload = selected_cell_request()
    monkeypatch.setattr(duckdb_engine, "missing_columns", lambda: ["obs_viirs_fre"])
    body = client.post("/api/explain-spike", json=payload).json()
    assert "energy columns are unavailable" in body["explanation_markdown"]
    assert "instantaneous MW cannot be converted" in body["explanation_markdown"]
    assert "[6]" not in body["explanation_markdown"]


def test_empty_cube_scope_is_missing_evidence_not_zero_energy(client):
    payload = selected_cell_request()
    payload["aoi"]["coordinates"] = [[[0, 0], [.05, 0], [.05, .05], [0, .05], [0, 0]]]
    body = client.post("/api/explain-spike", json=payload).json()
    assert "does not establish zero fire energy" in body["explanation_markdown"]


def test_context_override_discards_old_place_and_date_but_explicit_question_wins():
    coords = [[[-60.1,-3.9],[-59.9,-3.9],[-59.9,-3.7],[-60.1,-3.7],[-60.1,-3.9]]]
    req = ExplainSpikeRequest(aoi={"coordinates": coords}, region_name="New drawn area",
        period_start="2024-09-01", period_end="2024-09-30", prefer_map_context=True,
        user_question="How many detections?", conversation=[{"role":"user", "content":"Madrid July 2026"}])
    scope = copilot.resolve_scope(req)
    assert scope.coordinates == coords
    assert scope.start == "2024-09-01" and scope.end == "2024-09-30"
    req.user_question = "How many detections in Madrid on 24 July 2026?"
    scope = copilot.resolve_scope(req)
    assert scope.label.startswith("Madrid")
    assert scope.start == scope.end == "2026-07-24"


def test_unknown_explicit_location_never_returns_selected_region_metrics():
    req = ExplainSpikeRequest(region_name="Madrid", period_start="2026-01-01", period_end="2026-12-31",
        user_question="How many fires in Paris in 2026?")
    scope = copilot.resolve_scope(req)
    assert scope.coordinates is None
    assert copilot.retrieve_observations(scope)["status"] == "missing_scope"


def test_structured_previous_scope_survives_history_truncation_and_relative_dates():
    req = ExplainSpikeRequest(region_name="Chilecito", period_start="2022-01-01", period_end="2022-12-31",
        user_question="And on the next day?", previous_context={
            "label": "A previously queried custom area",
            "aoi": {"coordinates": [[[-4.3,40.3],[-4.1,40.3],[-4.1,40.5],[-4.3,40.3]]]},
            "period_start": "2026-07-24", "period_end": "2026-07-24"},
        conversation=[{"role": "user", "content": "And the observations?"}] * 10)
    scope = copilot.resolve_scope(req)
    assert scope.label == "A previously queried custom area"
    assert scope.coordinates == req.previous_context.aoi.coordinates
    assert scope.start == scope.end == "2026-07-25"
    req.prefer_map_context = True
    scope = copilot.resolve_scope(req)
    assert scope.label.startswith("Chilecito")
    assert scope.start == "2022-01-01"


@pytest.mark.parametrize("question,expected", [
    ("How many GJ in this area?", (True, True)),
    ("¿Cuánta energía en GJ hubo?", (True, True)),
    ("número de fuegos", (True, False)),
    ("And in GJ?", (True, True)),
    ("total FRP in MW", (True, False)),
    ("What is FRE?", (False, False)),
    ("Why did raw counts jump in January 2012?", (False, False)),
])
def test_quantitative_routing_preserves_method_questions(question, expected):
    assert copilot.quantitative_intent(question) == expected


def test_month_range_and_explicit_hex_scope():
    assert copilot.question_period("July to August 2026") == ("2026-07-01", "2026-08-31")
    index = h3.latlng_to_cell(40.4, -4.2, 7)
    scope = copilot.resolve_scope(ExplainSpikeRequest(user_question=f"How many detections in {index} in 2026?"))
    assert scope.h3_index == index
    assert copilot.queries.get_hierarchical_h3_filter(scope.coordinates)[1] == [int(index, 16)]


def test_chat_map_comparison_matches_independent_sparse_cell_sum(sparse_cube):
    from types import SimpleNamespace
    from backend.tests.test_api_accounting import square,CENTRE
    from backend.api.copilot_metrics import retrieve_energy
    client,expected=sparse_cube
    coordinates=square(*CENTRE,.05)
    scope=SimpleNamespace(coordinates=coordinates,start='2020-03-01',end='2020-03-03',label='Test area')
    req=ExplainSpikeRequest(enable_kalman_gap_filling=False)
    evidence=retrieve_energy(scope,req)
    total=sum(density*h3.cell_area(format(cell,'x'),unit='km^2')/1000 for density,cell in expected.values())
    assert evidence['mapped_energy_gj']==pytest.approx(total)
    assert evidence['mapped_biomass_tonnes']==pytest.approx(total*.368)
    assert evidence['available_through']=='2020-03-03'
    r=client.post('/api/map-period?start_date=2020-03-01&end_date=2020-03-03',json={
        'aoi':{'coordinates':coordinates},'start_year':2020,'end_year':2020})
    assert r.status_code==200
    mapped=sum(c['mean_annual_fre']*h3.cell_area(c['h3_index'],unit='km^2')/1000 for c in r.json()['map_hexagons'])
    assert evidence['mapped_energy_gj']==pytest.approx(mapped)

from backend.tests.test_api_accounting import sparse_cube


# ---------------------------------------------------------------- deterministic calculation engine

def region_payload(question, **extra):
    import json
    west, south, east, north = json.loads((duckdb_engine.ROOT / 'data/regions.json').read_text(encoding='utf-8'))['chilecito_la_rioja']['bounds']
    return {'region_name': 'Chilecito test region', 'user_question': question, 'period_start': '2022-01-01', 'period_end': '2022-12-31',
            'aoi': {'type': 'Polygon', 'coordinates': [[[west, south], [east, south], [east, north], [west, north], [west, south]]]}, **extra}


@pytest.fixture
def local_only(client, monkeypatch):
    """The calculation engine must answer without a language model or a web search."""
    def forbidden(*args, **kwargs):
        raise AssertionError('Deterministic calculations must never call a language model or web search')
    monkeypatch.setattr(copilot, 'complete', forbidden)
    monkeypatch.setattr(copilot, 'search_reports', forbidden)
    def ask(question, **extra):
        payload = region_payload(question, **extra)
        response = client.post('/api/explain-spike', json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['web_search_used'] is False and body['data_source'] == 'synthetic'
        return body, payload
    ask.analysis = lambda payload: client.post('/api/analyze', json={'aoi': payload['aoi'], 'start_year': 2000, 'end_year': 2026}).json()
    ask.client = client
    return ask


def gj(cells):
    return math.fsum(c['biomass_burned_tonnes'] for c in cells) / 0.368


def test_period_comparison_matches_dashboard_series_and_exposes_formulas(local_only):
    body, payload = local_only('Compare biomass consumed in this area between 2021 and 2025')
    series = local_only.analysis(payload)['calendar_series']
    first, second = (gj([c for c in series if c['year'] == year]) for year in (2021, 2025))
    change = (second - first) / first * 100
    assert body['physical_classification'] == 'LOCAL_CALCULATION'
    assert body['model_used'] == 'deterministic-offline-science'
    assert f'| Total energy (GJ) | {first:,.3f} | {second:,.3f} |' in body['explanation_markdown']
    assert f'| Dry biomass consumed (t) | {first * .368:,.3f} | {second * .368:,.3f} |' in body['explanation_markdown']
    items = {item['label']: item for item in body['verified_calculations']['items']}
    assert items['Energy change']['value'] == pytest.approx(change)
    assert items['Biomass difference']['value'] == pytest.approx((second - first) * .368)
    assert f'{second * .368:,.3f} t − {first * .368:,.3f} t' in items['Biomass difference']['formula']
    assert {'local_cube', 'verified_calculation'} <= set(body['evidence_sources'])


def test_selected_period_is_compared_with_the_previous_year_when_no_years_are_named(local_only):
    body, payload = local_only('Compare this period with the year before', period_start='2022-07-01', period_end='2022-08-31')
    series = local_only.analysis(payload)['calendar_series']
    first = gj([c for c in series if '2021-07-01' <= c['date'] <= '2021-08-31'])
    second = gj([c for c in series if '2022-07-01' <= c['date'] <= '2022-08-31'])
    assert f'| Total energy (GJ) | {first:,.3f} | {second:,.3f} |' in body['explanation_markdown']


def test_smoke_scenario_applies_declared_factors_and_keeps_its_disclaimer(local_only):
    body, payload = local_only('How much smoke (PM2.5) and CO2 was emitted here?')
    energy = gj([c for c in local_only.analysis(payload)['calendar_series'] if c['year'] == 2022])
    biomass = energy * .368
    items = {item['label']: item for item in body['verified_calculations']['items']}
    assert items['Consumed dry biomass']['value'] == pytest.approx(biomass)
    assert items['PM2.5 scenario']['value'] == pytest.approx(biomass * 9.5)
    assert items['CO2 scenario']['value'] == pytest.approx(biomass * 1580)
    assert f'**{biomass * 9.5 / 1000:,.3f} tonnes**' in body['explanation_markdown']
    assert 'not a measured emission' in body['explanation_markdown']
    assert 'not a measured emission' in body['verified_calculations']['note']


def test_fire_season_timing_uses_the_dashboard_trend_and_honours_recent_years(local_only):
    body, payload = local_only('How much has the annual fire season peak shifted here?')
    audit = local_only.analysis(payload)['audit_metrics']
    drift = audit['phenology_shift_days_per_decade']
    assert f'**{abs(drift):,.2f} days {"later" if drift > 0 else "earlier"} per decade**' in body['explanation_markdown']
    item = body['verified_calculations']['items'][0]
    assert item['unit'] == 'days' and f'{drift:+,.2f} days/decade' in item['formula']
    recent, _ = local_only('How much has the fire season peak shifted here over the last 10 years?')
    assert 'based on 10 complete years' in recent['explanation_markdown']
    assert 'As a land manager' not in recent['explanation_markdown']


def test_reconstruction_and_industrial_counts_match_the_analysis(local_only):
    body, payload = local_only('Are the persistent heat detections here vegetative fires or industrial gas flaring?')
    analysis = local_only.analysis(payload)
    days = [c for c in analysis['calendar_series'] if c['year'] == 2022]
    industrial = [h for h in analysis['map_hexagons'] if h['is_industrial_site']]
    text = body['explanation_markdown']
    assert text.index('Industrial versus vegetation heat') < text.index('Reconstructed activity')
    assert f"**{len(industrial):,} of {len(analysis['map_hexagons']):,} cells**" in text
    assert f"**{sum(c['is_gap_filled'] for c in days):,} days** were reconstructed" in text
    assert 'does not identify a facility' in text
    gaps, _ = local_only('How many days were reconstructed because of cloud cover or sensor outages?')
    assert gaps['explanation_markdown'].index('Reconstructed activity') < gaps['explanation_markdown'].index('Industrial versus')


def test_largest_events_are_ranked_by_energy_and_separated(local_only):
    from datetime import date
    body, payload = local_only('What were the largest thermal events recorded in this area?')
    series = local_only.analysis(payload)['calendar_series']
    peak = max((c for c in series if c['raw_hotspot_count'] > 0 and not c['is_gap_filled']), key=lambda c: c['biomass_burned_tonnes'])
    rows = [line.split('|') for line in body['explanation_markdown'].splitlines() if line.startswith('| ') and line[2].isdigit()]
    assert [row[1].strip() for row in rows] == [str(rank) for rank in range(1, len(rows) + 1)]
    assert peak['date'] in [row[2].strip() for row in rows]
    peaks = [date.fromisoformat(row[2].strip()) for row in rows]
    assert 1 < len(peaks) <= 5
    assert all(abs((a - b).days) >= 15 for i, a in enumerate(peaks) for b in peaks[:i])
    energies = [float(row[6].replace(',', '')) for row in rows]
    assert energies == sorted(energies, reverse=True)
    assert f'**{energies[0]:,.3f} GJ**' in body['explanation_markdown']
    assert body['verified_calculations']['items'][0]['value'] == pytest.approx(energies[0] * .368, abs=1e-3)
    assert 'not official ignition or containment dates' in body['explanation_markdown']


def test_quiet_windows_are_disjoint_and_never_presented_as_authorisation(local_only):
    from types import SimpleNamespace
    from backend.api.copilot_metrics import retrieve_low_activity_windows
    body, payload = local_only('When is the quietest window for a prescribed burn here?')
    assert 'not a burn authorisation' in body['explanation_markdown']
    evidence = retrieve_low_activity_windows(SimpleNamespace(coordinates=payload['aoi']['coordinates'], label='x'), ExplainSpikeRequest())
    quiet, active = evidence['quietest_windows'], evidence['most_active_window']
    assert len(quiet) == 3 and len({w['start'] for w in quiet}) == 3
    assert quiet[0]['mean_daily_energy_density_mj_km2'] <= quiet[1]['mean_daily_energy_density_mj_km2'] <= active['mean_daily_energy_density_mj_km2']


def test_risk_outlook_repeats_the_predictor_without_recomputing(local_only):
    body, payload = local_only('What is the fire risk outlook for the next 7 days?')
    risk = local_only.client.post('/api/predict-risk', json={'aoi': payload['aoi'], 'as_of_date': '2022-12-31'}).json()['assessment']
    for horizon in risk['horizons']:
        assert f"{horizon['combined_risk_pct']:,.1f}%" in body['explanation_markdown']
    assert f"**{risk['overall_hazard_level']}**" in body['explanation_markdown']
    assert 'not a forecast of a confirmed ignition' in body['explanation_markdown']


def test_burned_area_is_never_invented_and_definitions_are_untouched(local_only):
    body, _ = local_only('How many hectares of burned area were validated here?')
    assert body['physical_classification'] == 'DATA_NOT_AVAILABLE'
    assert body['verified_calculations'] is None and ' ha' not in body['explanation_markdown']
    definition, _ = local_only('What is burned area?')
    assert 'hectares' in definition['explanation_markdown'] and definition['physical_classification'] == 'SCIENTIFIC_EXPLANATION'


def test_sensor_breakdown_lists_each_sensor_and_matches_dashboard_counts(local_only):
    body, payload = local_only('Show energy and detections by sensor for this area', period_start='2010-01-01', period_end='2014-12-31')
    assert body['physical_classification'] == 'LOCAL_CALCULATION'
    rows = {int(cells[1]): cells for cells in (line.split('|') for line in body['explanation_markdown'].splitlines())
            if len(cells) > 3 and cells[1].strip().isdigit()}
    assert sorted(rows) == [2010, 2011, 2012, 2013, 2014]
    series = local_only.analysis(payload)['calendar_series']
    for year, cells in rows.items():
        counted = int(cells[2].replace(',', '')) + int(cells[3].replace(',', ''))
        assert counted == sum(c['raw_hotspot_count'] for c in series if c['year'] == year)
    header = next(line for line in body['explanation_markdown'].splitlines() if line.startswith('| Year'))
    assert all(name in header for name in ('MODIS detections', 'VIIRS detections', 'Terra', 'Aqua', 'VIIRS energy'))
    assert 'not a count of distinct fires' in body['explanation_markdown']
    definition, _ = local_only('What is the difference between MODIS and VIIRS by sensor?')
    assert definition['physical_classification'] != 'LOCAL_CALCULATION'


def test_energy_summary_carries_the_biomass_formula(local_only):
    body, payload = local_only('How much energy in GJ and biomass was consumed in this area?')
    energy = gj([c for c in local_only.analysis(payload)['calendar_series'] if c['year'] == 2022])
    items = body['verified_calculations']['items']
    assert items[0]['value'] == pytest.approx(energy) and items[1]['value'] == pytest.approx(energy * .368)
    assert f'{energy:,.3f} GJ × 0.368 t/GJ = {energy * .368:,.3f} t' == items[1]['formula']
