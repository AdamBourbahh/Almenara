"""Regressions for seasons, time phrases and yearly questions in the FIRMS Copilot.

These run without the cube: they check period parsing, intent routing and scope
resolution, which decide whether a question reaches the right calculation at all.
"""
import re

import pytest

from backend.api import copilot_researcher as researcher
from backend.api import fire_copilot as local
from backend.api.schemas import ExplainSpikeRequest

IBERIA = [[[-9.5, 36.0], [4.0, 36.0], [4.0, 44.0], [-9.5, 44.0], [-9.5, 36.0]]]
CHILECITO = [[[-69.5, -31.0], [-65.5, -31.0], [-65.5, -27.5], [-69.5, -27.5], [-69.5, -31.0]]]


@pytest.mark.parametrize('question,southern,want', [
    ('What happened in summer 2022?', False, ('2022-06-01', '2022-08-31')),
    ('verano de 2022', False, ('2022-06-01', '2022-08-31')),
    ('summer 2023', True, ('2022-12-01', '2023-02-28')),
    ('winter of 2021', False, ('2020-12-01', '2021-02-28')),
    ('2019 autumn', True, ('2019-03-01', '2019-05-31')),
    ('spring 2024', False, ('2024-03-01', '2024-05-31')),
], ids=['north-summer', 'es-summer', 'south-summer', 'north-winter', 'south-autumn', 'north-spring'])
def test_seasons_follow_the_hemisphere(question, southern, want):
    assert local.question_period(question, southern=southern) == want


def test_fall_as_a_verb_is_not_a_season():
    assert local.question_period('did detections fall in 2022') == ('2022-01-01', '2022-12-31')


@pytest.mark.parametrize('question', ['What happened in summer 2022?', 'Which country burned most?', 'It was totally quiet'])
def test_substrings_do_not_trigger_numeric_routing(question):
    assert local.quantitative_intent(question) == (False, False)


@pytest.mark.parametrize('question', ['How many detections in total?', 'Give me the sum of FRP', 'peak day count'])
def test_numeric_words_still_trigger_numeric_routing(question):
    assert local.quantitative_intent(question)[0]


@pytest.mark.parametrize('coords,question,want', [
    (IBERIA, 'What happened here in summer 2022?', ('2022-06-01', '2022-08-31')),
    (CHILECITO, 'How many detections in summer 2023?', ('2022-12-01', '2023-02-28')),
    (CHILECITO, 'What was the quietest year in the last 10 years?', (None, None)),
], ids=['north-season', 'south-season', 'recent-years'])
def test_time_phrases_keep_the_selected_area(coords, question, want):
    """'in summer' / 'in the last' are times, not unknown places that drop the selected area."""
    scope = local.resolve_scope(ExplainSpikeRequest(region_name='Selected area', aoi={'type': 'Polygon', 'coordinates': coords},
                                                    user_question=question, prefer_map_context=True))
    assert scope.coordinates == coords
    assert (scope.start, scope.end) == want


def _intent(question):
    q = local.normalized(question)
    return next((name for name, pattern in researcher.LOCAL_INTENTS if re.search(pattern, q)), None)


@pytest.mark.parametrize('question', [
    'Which was the worst fire year?', 'What was the quietest year in the last 10 years?',
    'Is fire activity increasing over time?', 'What is the long-term trend?', '¿Cuál fue el peor año?',
    '¿Están aumentando los incendios?',
])
def test_yearly_questions_reach_the_annual_calculation(question):
    assert _intent(question) == 'annual'


@pytest.mark.parametrize('question,want', [
    ('What is the fire risk for the next two weeks?', 'risk'),
    ('When does the fire season peak?', 'season'),
    ('What were the largest fires?', 'events'),
    ('Compare 2022 and 2023', 'comparison'),
])
def test_existing_intents_are_not_captured_by_the_annual_route(question, want):
    assert _intent(question) == want
