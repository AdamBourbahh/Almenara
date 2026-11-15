"""JavaScript cell unions must select exactly the same cells in the API adapter."""
import json
from pathlib import Path

import h3
import pytest

from backend.api.schemas import GeoJSONPolygon
from backend.db import queries


FIXTURES = json.loads((Path(__file__).parent / 'fixtures/hex_selection.json').read_text())


@pytest.mark.parametrize('case', FIXTURES, ids=lambda case: case['name'])
def test_browser_hex_union_preserves_exact_selection_and_holes(case):
    polygon = GeoJSONPolygon.model_validate(case['aoi'])
    queries.validate_polygon_topology(polygon.coordinates)
    parents, cells, area = queries.get_hierarchical_h3_filter(polygon.coordinates)
    assert {h3.int_to_str(cell) for cell in cells} == set(case['cells'])
    assert h3.str_to_int(case['hole']) not in cells
    assert set(parents) == {h3.str_to_int(h3.cell_to_parent(cell, 4)) for cell in case['cells']}
    assert len(parents) == len(set(parents))
    assert area > 0
