"""Regression checks for source-aware validation regions and frozen frontend fields."""
import re
from pathlib import Path
from typing import get_args, get_origin, Literal
import pytest
from backend import check_core
from backend.api import schemas


def test_validation_regions_follow_explicit_source(monkeypatch):
    for source in ('0', '1'):
        monkeypatch.setenv('USE_SYNTHETIC_CUBE', source)
        assert set(check_core.validation_regions()) == {'chilecito_la_rioja','iberia_med','orlando_florida','amazonas_manaus'}


def ts_type(annotation):
    origin=get_origin(annotation)
    if origin is Literal:
        return ' | '.join(f'"{x}"' for x in get_args(annotation))
    if origin is list:
        return f'Array<{ts_type(get_args(annotation)[0])}>'
    if origin is not None:
        return ' | '.join(ts_type(x) for x in get_args(annotation))
    return {str:'string',int:'number',float:'number',bool:'boolean',type(None):'null'}.get(annotation, getattr(annotation,'__name__',str(annotation)))


@pytest.mark.parametrize('name', ['DailyCalendarCell','VonMisesPhenologyYear','ScientificAuditMetrics','H3MapSummaryHex','AnalyzeResponse','ChaosMonkeyResponse'])
def test_frozen_response_types_match_typescript(name):
    source=(Path(__file__).resolve().parents[2]/'frontend/src/api/types.ts').read_text(encoding='utf-8')
    body=re.search(r'export interface '+name+r' \{([^}]+)\}',source).group(1)
    actual=dict(re.findall(r'^\s*(\w+): ([^;]+);',body,re.M))
    expected={key:ts_type(field.annotation) for key,field in getattr(schemas,name).model_fields.items()}
    assert actual==expected
